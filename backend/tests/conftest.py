"""Fixtures for the API tests: a fake database, a stub model and an in-memory Redis."""

from collections.abc import Iterator

import pytest
from fakeredis import FakeAsyncRedis, FakeRedis, FakeServer
from fastapi.testclient import TestClient

from app import main
from app.api import get_predictor, get_repository
from app.cache import ResponseCache, get_cache
from app.predictor import Predictor

from fakes import FakeRepository, StubModel, make_bundle, make_matches


@pytest.fixture
def redis_server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def fake_redis(redis_server: FakeServer) -> FakeAsyncRedis:
    """What the app talks to."""
    return FakeAsyncRedis(server=redis_server)


@pytest.fixture
def inspect_redis(redis_server: FakeServer) -> FakeRedis:
    """A synchronous view of the same data, for tests to look at keys and TTLs."""
    return FakeRedis(server=redis_server)


@pytest.fixture(autouse=True)
def cache(fake_redis: FakeAsyncRedis) -> Iterator[ResponseCache]:
    """Every test gets an empty in-memory cache, never the real Redis."""
    response_cache = ResponseCache(fake_redis)
    main.app.dependency_overrides[get_cache] = lambda: response_cache
    yield response_cache
    main.app.dependency_overrides.clear()


@pytest.fixture
def model() -> StubModel:
    return StubModel()


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(make_matches())


@pytest.fixture
def client(model: StubModel, repo: FakeRepository) -> TestClient:
    predictor = Predictor.from_bundle(make_bundle(model))
    main.app.dependency_overrides[get_repository] = lambda: repo
    main.app.dependency_overrides[get_predictor] = lambda: predictor
    return TestClient(main.app)  # no `with`: the startup model load is tested separately


@pytest.fixture
def client_without_model(repo: FakeRepository, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main.app.state, "predictor", None, raising=False)
    monkeypatch.setattr(main.app.state, "model_error", None, raising=False)
    main.app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(main.app)
