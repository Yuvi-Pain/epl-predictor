"""Health endpoint tests. Postgres/Redis checks are stubbed so no services are needed."""

import pytest
from fastapi.testclient import TestClient

from app import main


async def _ok() -> str:
    return "ok"


async def _down() -> str:
    return "error: connection refused"


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


def test_health_ok(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "check_postgres", _ok)
    monkeypatch.setattr(main, "check_redis", _ok)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


def test_health_503_when_a_dependency_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "check_postgres", _ok)
    monkeypatch.setattr(main, "check_redis", _down)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
