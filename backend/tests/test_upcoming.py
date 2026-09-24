"""Tests for GET /fixtures/upcoming, over the FakeRepository and StubModel from conftest.py.

"Today" is pinned to Thursday 24 September 2026 through the `uk_today`
dependency. The fake data has the 2026-27 results from fakes.make_matches plus
the unplayed fixtures below.
"""

from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fakeredis import FakeRedis
from fastapi.testclient import TestClient

from app import main
from app.api import uk_today
from app.cache import FIXTURES_TTL
from fakes import FakeRepository, StubModel, make_matches, match

TODAY = date(2026, 9, 24)
UPCOMING = "/fixtures/upcoming"


def kickoff(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def fixture(id: int, day: date, home: int, away: int, **kw: Any) -> dict[str, Any]:
    kw.setdefault("status", "TIMED")
    kw.setdefault("kickoff_at", kickoff(day, 14))
    return match(id, "2026-27", day, home, away, None, None, **kw)


SAT, SUN = date(2026, 9, 26), date(2026, 9, 27)
FIXTURES = [
    fixture(10, SUN, 3, 4, matchday=6, status="SCHEDULED", kickoff_at=None),
    fixture(8, SAT, 1, 2, matchday=6, kickoff_at=kickoff(SAT, 16)),
    fixture(9, SAT, 4, 3, matchday=6, kickoff_at=kickoff(SAT, 11)),
    fixture(11, date(2026, 10, 3), 2, 1, matchday=7),  # the matchweek after
    fixture(12, date(2026, 9, 25), 4, 1, matchday=6, status="POSTPONED"),
    fixture(13, date(2026, 9, 20), 1, 4, matchday=5),  # in the past, still no result
]


@pytest.fixture(autouse=True)
def pinned_today() -> None:
    main.app.dependency_overrides[uk_today] = lambda: TODAY  # cleared by conftest's `cache`


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(make_matches(*FIXTURES))


def test_returns_the_next_matchweek_soonest_first(client: TestClient) -> None:
    r = client.get(UPCOMING)
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == "2026-27"
    assert body["matchday"] == 6
    assert body["model_version"] == "vtest"
    # Postponed (12), past (13) and next week's (11) fixtures are left out.
    assert [f["match_id"] for f in body["fixtures"]] == [9, 8, 10]

    first = body["fixtures"][0]
    assert first["match_date"] == "2026-09-26"
    assert first["kickoff"] == "2026-09-26T11:00:00Z"
    assert first["home_team"] == {"id": 4, "name": "Everton"}
    assert first["away_team"] == {"id": 3, "name": "Liverpool"}
    assert first["prediction"] == {
        "probabilities": {"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
        "most_likely": "home_win",
    }
    assert body["fixtures"][2]["kickoff"] is None


def test_features_match_what_predict_would_use(
    client: TestClient, model: StubModel, repo: FakeRepository
) -> None:
    """The Predict page linked from each fixture must show the same numbers."""
    client.get(UPCOMING)
    (upcoming_X,) = model.calls
    arsenal_chelsea = upcoming_X.loc[repo.matches.index[repo.matches["id"] == 8]]

    client.get("/predict", params={"home": 1, "away": 2, "as_of": SAT.isoformat()})
    predict_X = model.calls[1]
    np.testing.assert_allclose(
        arsenal_chelsea.to_numpy(dtype=float), predict_X.to_numpy(dtype=float), equal_nan=True
    )


def test_a_fixture_with_a_result_is_no_longer_upcoming(
    client: TestClient, repo: FakeRepository
) -> None:
    repo.matches.loc[repo.matches["id"] == 9, ["home_goals", "away_goals"]] = [1, 0]
    repo.version += 1
    ids = [f["match_id"] for f in client.get(UPCOMING).json()["fixtures"]]
    assert ids == [8, 10]


def test_moves_on_when_the_matchweek_is_over(client: TestClient) -> None:
    main.app.dependency_overrides[uk_today] = lambda: date(2026, 9, 28)
    body = client.get(UPCOMING).json()
    assert body["matchday"] == 7
    assert [f["match_id"] for f in body["fixtures"]] == [11]


def test_without_matchdays_uses_the_next_seven_days(
    repo: FakeRepository, client: TestClient
) -> None:
    repo.matches["matchday"] = pd.array([pd.NA] * len(repo.matches), dtype="Int16")
    body = client.get(UPCOMING).json()
    assert body["matchday"] is None
    # 26 Sep + 7 days reaches 2 Oct, so the 3 Oct fixture is left out.
    assert [f["match_id"] for f in body["fixtures"]] == [9, 8, 10]


def test_no_fixtures_is_an_empty_list_not_an_error(
    client: TestClient, repo: FakeRepository
) -> None:
    repo.matches = make_matches()  # results only: the worker has not fetched fixtures yet
    r = client.get(UPCOMING)
    assert r.status_code == 200
    assert r.json() == {"season": None, "matchday": None, "model_version": "vtest", "fixtures": []}


def test_needs_a_model(client_without_model: TestClient) -> None:
    assert client_without_model.get(UPCOMING).status_code == 503


# --- caching -------------------------------------------------------------------------


def test_is_cached_under_the_data_version_and_the_day(
    client: TestClient, repo: FakeRepository, model: StubModel, inspect_redis: FakeRedis
) -> None:
    assert client.get(UPCOMING).headers["X-Cache"] == "MISS"
    assert client.get(UPCOMING).headers["X-Cache"] == "HIT"
    assert len(model.calls) == 1

    (key,) = [k.decode() for k in inspect_redis.keys("*")]
    assert key.startswith("epl:v1:fixtures:upcoming:mvtest@") and key.endswith(":d1:2026-09-24")
    ttl = inspect_redis.ttl(key)
    assert FIXTURES_TTL.total_seconds() - 5 < ttl <= FIXTURES_TTL.total_seconds()

    repo.version += 1  # the worker stored new fixtures or results
    assert client.get(UPCOMING).headers["X-Cache"] == "MISS"

    main.app.dependency_overrides[uk_today] = lambda: date(2026, 9, 25)  # a new day
    assert client.get(UPCOMING).headers["X-Cache"] == "MISS"
