"""Tests for Redis caching of /teams, /predict and /matches.

Redis is an in-memory FakeAsyncRedis (see conftest.py), except in the
"Redis is down" tests, which point a real client at a port nothing listens on.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis, FakeRedis, FakeServer
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app import main
from app.api import get_predictor
from app.cache import (
    MATCHES_TTL,
    PREDICT_TTL,
    RETRY_AFTER,
    TEAMS_TTL,
    ResponseCache,
    get_cache,
)
from app.predictor import Predictor

from fakes import FakeRepository, StubModel, make_bundle, make_matches, match

PREDICT = ("/predict", {"home": 1, "away": 3, "as_of": "2026-09-26"})
MATCHES = ("/matches", {"season": "2026-27"})
TEAMS = ("/teams", {})
CACHED_ENDPOINTS = [PREDICT, MATCHES, TEAMS]


def keys(redis: FakeRedis) -> list[str]:
    return sorted(k.decode() for k in redis.keys("*"))


# --- hit / miss ---------------------------------------------------------------------


@pytest.mark.parametrize("url,params", CACHED_ENDPOINTS)
def test_first_request_misses_then_hits(
    client: TestClient, url: str, params: dict[str, Any]
) -> None:
    first = client.get(url, params=params)
    second = client.get(url, params=params)
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert second.headers["content-type"] == "application/json"


def test_a_hit_does_not_run_the_model(client: TestClient, model: StubModel) -> None:
    for _ in range(3):
        client.get(PREDICT[0], params=PREDICT[1])
    assert len(model.calls) == 1


def test_different_parameters_are_cached_separately(client: TestClient) -> None:
    assert client.get("/predict", params={"home": 1, "away": 3}).headers["X-Cache"] == "MISS"
    assert client.get("/predict", params={"home": 3, "away": 1}).headers["X-Cache"] == "MISS"
    r = client.get("/predict", params={"home": 1, "away": 3, "as_of": "2026-08-15"})
    assert r.headers["X-Cache"] == "MISS"


def test_default_as_of_is_cached_under_todays_date(client: TestClient) -> None:
    client.get("/predict", params={"home": 1, "away": 3})
    r = client.get("/predict", params={"home": 1, "away": 3, "as_of": date.today().isoformat()})
    assert r.headers["X-Cache"] == "HIT"


@pytest.mark.parametrize(
    "request_,prefix,ttl",
    [
        (PREDICT, "epl:v1:predict:", PREDICT_TTL),
        (MATCHES, "epl:v1:matches:", MATCHES_TTL),
        (TEAMS, "epl:v1:teams:", TEAMS_TTL),
    ],
)
def test_entries_are_stored_with_their_ttl(
    client: TestClient,
    inspect_redis: FakeRedis,
    request_: tuple[str, dict[str, Any]],
    prefix: str,
    ttl: timedelta,
) -> None:
    client.get(request_[0], params=request_[1])
    (key,) = keys(inspect_redis)
    assert key.startswith(prefix)
    assert 0 < inspect_redis.ttl(key) <= ttl.total_seconds()


def test_keys_contain_model_and_data_versions(client: TestClient, inspect_redis: FakeRedis) -> None:
    client.get(PREDICT[0], params=PREDICT[1])
    client.get(TEAMS[0])
    assert keys(inspect_redis) == [
        "epl:v1:predict:mvtest@2026-09-01T12:00:00+00:00:d1:1:3:2026-09-26",
        "epl:v1:teams:d1",
    ]


@pytest.mark.parametrize(
    "url,params,status",
    [
        ("/predict", {"home": 1, "away": 99}, 404),
        ("/predict", {"home": 1, "away": 1}, 400),
        ("/matches", {"season": "1999-00"}, 404),
    ],
)
def test_errors_are_not_cached(
    client: TestClient, inspect_redis: FakeRedis, url: str, params: dict[str, Any], status: int
) -> None:
    for _ in range(2):
        r = client.get(url, params=params)
        assert r.status_code == status
        assert "X-Cache" not in r.headers
    assert keys(inspect_redis) == []


# --- invalidation -------------------------------------------------------------------


def test_new_match_data_with_a_version_bump_is_served_immediately(
    client: TestClient, repo: FakeRepository
) -> None:
    before = client.get(PREDICT[0], params=PREDICT[1]).json()
    assert client.get(PREDICT[0], params=PREDICT[1]).headers["X-Cache"] == "HIT"

    # The loader adds Arsenal's 5-0 win on 1 Sep and bumps the data version.
    repo.matches = make_matches(match(8, "2026-27", date(2026, 9, 1), 1, 4, 5, 0))
    repo.version += 1

    r = client.get(PREDICT[0], params=PREDICT[1])
    assert r.headers["X-Cache"] == "MISS"
    assert r.json()["features"]["home_form_points"] > before["features"]["home_form_points"]
    assert client.get(PREDICT[0], params=PREDICT[1]).headers["X-Cache"] == "HIT"


@pytest.mark.parametrize("url,params", CACHED_ENDPOINTS)
def test_a_data_version_bump_misses_every_endpoint(
    client: TestClient, repo: FakeRepository, url: str, params: dict[str, Any]
) -> None:
    client.get(url, params=params)
    repo.version += 1
    assert client.get(url, params=params).headers["X-Cache"] == "MISS"


def test_the_data_version_is_what_invalidates(client: TestClient, repo: FakeRepository) -> None:
    """Without a bump, changed data is not noticed: the loader must bump the version."""
    before = client.get(PREDICT[0], params=PREDICT[1])
    repo.matches = make_matches(match(8, "2026-27", date(2026, 9, 1), 1, 4, 5, 0))
    after = client.get(PREDICT[0], params=PREDICT[1])
    assert after.headers["X-Cache"] == "HIT"
    assert after.json() == before.json()


@pytest.mark.parametrize("url,params", [PREDICT, MATCHES])
def test_a_new_model_misses(client: TestClient, url: str, params: dict[str, Any]) -> None:
    client.get(url, params=params)
    # Same version string, retrained later (train_model --force): still a new model.
    retrained = Predictor.from_bundle(
        {**make_bundle(StubModel()), "trained_at": "2026-09-20T09:00:00+00:00"}
    )
    main.app.dependency_overrides[get_predictor] = lambda: retrained
    assert client.get(url, params=params).headers["X-Cache"] == "MISS"


def test_teams_do_not_depend_on_the_model(client: TestClient) -> None:
    client.get("/teams")
    retrained = Predictor.from_bundle({**make_bundle(StubModel()), "version": "v2"})
    main.app.dependency_overrides[get_predictor] = lambda: retrained
    assert client.get("/teams").headers["X-Cache"] == "HIT"


# --- Redis unavailable --------------------------------------------------------------


@pytest.fixture
def redis_down() -> ResponseCache:
    """A cache whose Redis refuses connections (nothing listens on port 1)."""
    dead = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.5, socket_timeout=0.5)
    response_cache = ResponseCache(dead)
    main.app.dependency_overrides[get_cache] = lambda: response_cache
    return response_cache


@pytest.mark.parametrize("url,params", CACHED_ENDPOINTS)
def test_redis_down_still_serves_responses(
    client: TestClient, redis_down: ResponseCache, url: str, params: dict[str, Any]
) -> None:
    for _ in range(2):
        r = client.get(url, params=params)
        assert r.status_code == 200
        assert r.headers["X-Cache"] == "MISS"


def test_redis_down_gives_the_same_body_as_a_working_cache(
    client: TestClient, redis_down: ResponseCache, cache: ResponseCache
) -> None:
    without_redis = client.get(PREDICT[0], params=PREDICT[1]).json()
    main.app.dependency_overrides[get_cache] = lambda: cache
    assert client.get(PREDICT[0], params=PREDICT[1]).json() == without_redis


def test_redis_down_logs_one_warning_per_outage(
    client: TestClient, redis_down: ResponseCache, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.cache"):
        for _ in range(3):
            client.get(PREDICT[0], params=PREDICT[1])
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Redis unavailable" in warnings[0].getMessage()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_after_a_failure_redis_is_skipped_until_the_retry_time(
    fake_redis: FakeAsyncRedis, redis_server: FakeServer
) -> None:
    clock = FakeClock()
    response_cache = ResponseCache(fake_redis, retry_after=timedelta(seconds=30), clock=clock)

    async def scenario() -> list[bytes | None]:
        redis_server.connected = False
        await response_cache.get("k")  # fails: Redis marked unavailable
        redis_server.connected = True
        await fake_redis.set("k", b"v")
        results = [await response_cache.get("k")]  # still skipped, Redis not asked
        clock.now += 30
        results.append(await response_cache.get("k"))  # retry time reached: asks again
        return results

    assert asyncio.run(scenario()) == [None, b"v"]


def test_recovery_is_logged_and_caching_resumes(
    fake_redis: FakeAsyncRedis, redis_server: FakeServer, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    response_cache = ResponseCache(fake_redis, clock=clock)

    async def outage_then_recovery() -> bytes | None:
        redis_server.connected = False  # fakeredis raises ConnectionError while disconnected
        assert await response_cache.get("k") is None
        await response_cache.set("k", b"v", TEAMS_TTL)
        redis_server.connected = True
        clock.now += RETRY_AFTER.total_seconds()
        await response_cache.set("k", b"v", TEAMS_TTL)
        return await response_cache.get("k")

    with caplog.at_level(logging.INFO, logger="app.cache"):
        assert asyncio.run(outage_then_recovery()) == b"v"
    assert [r.levelname for r in caplog.records] == ["WARNING", "INFO"]
