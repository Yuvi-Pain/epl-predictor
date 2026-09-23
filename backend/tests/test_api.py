"""Tests for /teams, /predict, /matches and /model.

The database is replaced by an in-memory FakeRepository and the model by
StubModel, which returns fixed probabilities and records what it was given.
Feature building runs for real on the fake matches. Fixtures are in conftest.py;
caching is tested in test_cache.py.
"""

from datetime import date
from pathlib import Path
from typing import Any

import joblib
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import get_repository
from app.features import FEATURE_COLUMNS
from fakes import FakeRepository, StubModel, make_bundle, make_matches, match, metrics


# --- /teams ------------------------------------------------------------------------


def test_teams_lists_every_team_alphabetically(client: TestClient) -> None:
    r = client.get("/teams")
    assert r.status_code == 200
    assert [t["name"] for t in r.json()["teams"]] == ["Arsenal", "Chelsea", "Everton", "Liverpool"]
    assert r.json()["teams"][0] == {"id": 1, "name": "Arsenal"}


def test_teams_works_without_a_model(client_without_model: TestClient) -> None:
    assert client_without_model.get("/teams").status_code == 200


# --- /predict ----------------------------------------------------------------------


def test_predict_returns_probabilities_and_features(client: TestClient, model: StubModel) -> None:
    r = client.get("/predict", params={"home": 1, "away": 3, "as_of": "2026-09-26"})
    assert r.status_code == 200
    body = r.json()
    assert body["home_team"] == {"id": 1, "name": "Arsenal"}
    assert body["away_team"] == {"id": 3, "name": "Liverpool"}
    assert body["as_of"] == "2026-09-26"
    assert body["model_version"] == "vtest"
    assert body["prediction"] == {
        "probabilities": {"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
        "most_likely": "home_win",
    }
    assert set(body["features"]) == set(FEATURE_COLUMNS)
    # Arsenal's last five (here: three) matches: W 2-0, D 2-2, W 3-1.
    assert body["features"]["home_form_points"] == pytest.approx(7 / 3)
    assert body["features"]["home_form_goals_for"] == pytest.approx(7 / 3)

    # The model got one row with exactly the training feature columns, in order.
    (X,) = model.calls
    assert list(X.columns) == FEATURE_COLUMNS and len(X) == 1


def test_predict_only_uses_results_before_as_of(client: TestClient) -> None:
    before_2026 = client.get("/predict", params={"home": 1, "away": 3, "as_of": "2026-08-15"}).json()
    # On 15 Aug 2026 Arsenal's 3-1 that day must not count yet: W 2-0, D 2-2 only.
    assert before_2026["features"]["home_form_points"] == pytest.approx(2.0)


def test_predict_defaults_as_of_to_today(client: TestClient) -> None:
    r = client.get("/predict", params={"home": 1, "away": 2})
    assert r.status_code == 200
    assert r.json()["as_of"] == date.today().isoformat()


def test_predict_reports_missing_form_as_null(client: TestClient, repo: FakeRepository) -> None:
    repo.matches = repo.matches.iloc[:0]
    r = client.get("/predict", params={"home": 1, "away": 2, "as_of": "2026-09-26"})
    assert r.status_code == 200
    assert r.json()["features"]["home_form_points"] is None
    assert r.json()["features"]["home_elo"] == 1500


def test_predict_same_team_is_400(client: TestClient) -> None:
    r = client.get("/predict", params={"home": 2, "away": 2})
    assert r.status_code == 400
    assert "different" in r.json()["detail"]


@pytest.mark.parametrize("home,away,missing", [(1, 99, "99"), (98, 2, "98"), (98, 99, "98, 99")])
def test_predict_unknown_team_is_404(client: TestClient, home: int, away: int, missing: str) -> None:
    r = client.get("/predict", params={"home": home, "away": away})
    assert r.status_code == 404
    assert r.json()["detail"] == f"unknown team id(s): {missing}"


@pytest.mark.parametrize(
    "params", [{"home": "arsenal", "away": 2}, {"home": 1}, {"home": 1, "away": 2, "as_of": "soon"}]
)
def test_predict_bad_parameters_are_422(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/predict", params=params).status_code == 422


# --- /matches ----------------------------------------------------------------------


def test_matches_lists_played_matches_with_predictions(client: TestClient) -> None:
    r = client.get("/matches", params={"season": "2026-27"})
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == "2026-27"
    assert body["model_version"] == "vtest"
    assert body["model_split"] == "unseen"
    assert [m["match_id"] for m in body["matches"]] == [5, 6, 7]

    first = body["matches"][0]
    assert first["match_date"] == "2026-08-15"
    assert first["home_team"]["name"] == "Arsenal" and first["away_team"]["name"] == "Liverpool"
    assert first["score"] == {"home_goals": 3, "away_goals": 1}
    assert first["prediction"]["most_likely"] == "home_win"
    # The stub always picks a home win, so only the home win is "correct".
    assert [(m["actual"], m["correct"]) for m in body["matches"]] == [
        ("home_win", True),
        ("away_win", False),
        ("draw", False),
    ]


def test_matches_skips_unplayed_fixtures(client: TestClient, repo: FakeRepository) -> None:
    repo.matches = make_matches(match(8, "2026-27", date(2026, 9, 30), 1, 2, None, None))
    ids = [m["match_id"] for m in client.get("/matches", params={"season": "2026-27"}).json()["matches"]]
    assert ids == [5, 6, 7]


def test_matches_predictions_use_only_earlier_results(client: TestClient, model: StubModel) -> None:
    client.get("/matches", params={"season": "2026-27"})
    (X,) = model.calls
    # Match 5 is Arsenal's first of the season: form from 2025-26 only (W 2-0, D 2-2).
    assert X.iloc[0]["home_form_points"] == pytest.approx(2.0)


def test_matches_defaults_to_latest_season(client: TestClient) -> None:
    assert client.get("/matches").json()["season"] == "2026-27"


def test_matches_reports_how_the_model_used_the_season(client: TestClient) -> None:
    assert client.get("/matches", params={"season": "2025-26"}).json()["model_split"] == "test"


def test_matches_unknown_season_is_404(client: TestClient) -> None:
    r = client.get("/matches", params={"season": "1999-00"})
    assert r.status_code == 404


def test_matches_bad_season_format_is_422(client: TestClient) -> None:
    assert client.get("/matches", params={"season": "2026"}).status_code == 422


# --- /model ------------------------------------------------------------------------


def test_model_info(client: TestClient) -> None:
    r = client.get("/model")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "vtest"
    assert body["trained_at"] == "2026-09-01T12:00:00+00:00"
    assert body["features"] == FEATURE_COLUMNS
    assert body["test"]["season"] == "2025-26"
    assert body["test"]["model"] == metrics(0.5)
    assert body["test"]["baselines"] == {"always home win": metrics(0.45)}


# --- no model ----------------------------------------------------------------------


@pytest.mark.parametrize("url", ["/predict?home=1&away=2", "/matches", "/model"])
def test_model_endpoints_are_503_without_a_model(client_without_model: TestClient, url: str) -> None:
    r = client_without_model.get(url)
    assert r.status_code == 503
    assert "train_model" in r.json()["detail"]


# --- loading the model at startup ----------------------------------------------------


def test_startup_loads_the_model_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: FakeRepository
) -> None:
    path = tmp_path / "model.joblib"
    joblib.dump(make_bundle(StubModel()), path)
    monkeypatch.setenv("MODEL_PATH", str(path))
    loads = []
    real_load = joblib.load
    monkeypatch.setattr("app.predictor.joblib.load", lambda p: loads.append(p) or real_load(p))
    main.app.dependency_overrides[get_repository] = lambda: repo
    with TestClient(main.app) as c:
        assert c.get("/model").json()["version"] == "vtest"
        for _ in range(3):
            assert c.get("/predict", params={"home": 1, "away": 2}).status_code == 200
    assert loads == [path]


def test_startup_without_a_model_file_serves_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "missing.joblib"))
    with TestClient(main.app) as c:
        assert c.get("/model").status_code == 503


def test_startup_with_an_incompatible_model_serves_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.joblib"
    joblib.dump({**make_bundle(StubModel()), "feature_columns": ["home_elo", "away_elo"]}, path)
    monkeypatch.setenv("MODEL_PATH", str(path))
    with TestClient(main.app) as c:
        r = c.get("/model")
    assert r.status_code == 503
    assert "incompatible" in r.json()["detail"] and "retrain" in r.json()["detail"]
