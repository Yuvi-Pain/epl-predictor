"""Tests for /teams, /predict, /matches and /model.

The database is replaced by an in-memory FakeRepository and the model by
StubModel, which returns fixed probabilities and records what it was given.
Feature building runs for real on the fake matches.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.api import get_predictor, get_repository
from app.features import FEATURE_COLUMNS, EloConfig
from app.match_model import MODEL_LABEL, OUTCOMES
from app.predictor import Predictor
from app.repository import TeamRow

TEAMS = [TeamRow(1, "Arsenal"), TeamRow(2, "Chelsea"), TeamRow(3, "Liverpool"), TeamRow(4, "Everton")]
# Away win, draw, home win: the stub always favours the home side.
STUB_PROBA = [0.2, 0.3, 0.5]


class StubModel:
    """Stands in for the scikit-learn pipeline. Module-level so it can be pickled."""

    def __init__(self) -> None:
        self.calls: list[pd.DataFrame] = []

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        self.calls.append(X)
        return np.tile(STUB_PROBA, (len(X), 1))


def match(
    id: int, season: str, day: date, home: int, away: int, hg: int | None, ag: int | None
) -> dict[str, Any]:
    return {
        "id": id,
        "season": season,
        "match_date": day,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_shots_on_target": None if hg is None else hg + 3,
        "away_shots_on_target": None if ag is None else ag + 2,
    }


def make_matches(*extra: dict[str, Any]) -> pd.DataFrame:
    rows = [
        match(1, "2025-26", date(2025, 8, 16), 1, 2, 2, 0),
        match(2, "2025-26", date(2025, 8, 16), 3, 4, 1, 1),
        match(3, "2025-26", date(2025, 8, 23), 2, 3, 0, 1),
        match(4, "2025-26", date(2025, 8, 23), 4, 1, 2, 2),
        match(5, "2026-27", date(2026, 8, 15), 1, 3, 3, 1),  # home win
        match(6, "2026-27", date(2026, 8, 15), 2, 4, 0, 2),  # away win
        match(7, "2026-27", date(2026, 8, 22), 3, 2, 1, 1),  # draw
        *extra,
    ]
    df = pd.DataFrame(rows)
    for col in ("home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target"):
        df[col] = df[col].astype("Int16")
    return df


class FakeRepository:
    def __init__(self, matches: pd.DataFrame) -> None:
        self.matches = matches

    async def list_teams(self) -> list[TeamRow]:
        return sorted(TEAMS, key=lambda t: t.name)

    async def get_teams(self, team_ids: list[int]) -> dict[int, TeamRow]:
        return {t.id: t for t in TEAMS if t.id in team_ids}

    async def load_matches(self) -> pd.DataFrame:
        return self.matches.copy()


def metrics(accuracy: float) -> dict[str, float]:
    return {"accuracy": accuracy, "log_loss": 1.0, "brier": 0.6}


def make_bundle(model: Any) -> dict[str, Any]:
    """Shaped like what scripts/train_model.py saves."""
    split = {MODEL_LABEL: metrics(0.5), "always home win": metrics(0.45)}
    return {
        "version": "vtest",
        "trained_at": "2026-09-01T12:00:00+00:00",
        "model": model,
        "feature_columns": list(FEATURE_COLUMNS),
        "classes": list(OUTCOMES),
        "elo_config": EloConfig(),
        "form_window": 5,
        "train_seasons": ["2023-24"],
        "validation_season": "2024-25",
        "test_season": "2025-26",
        "metrics": {"validation": split, "test": split},
    }


@pytest.fixture
def model() -> StubModel:
    return StubModel()


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(make_matches())


@pytest.fixture
def client(model: StubModel, repo: FakeRepository) -> Iterator[TestClient]:
    predictor = Predictor.from_bundle(make_bundle(model))
    main.app.dependency_overrides[get_repository] = lambda: repo
    main.app.dependency_overrides[get_predictor] = lambda: predictor
    yield TestClient(main.app)  # no `with`: the startup model load is tested separately
    main.app.dependency_overrides.clear()


@pytest.fixture
def client_without_model(repo: FakeRepository, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main.app.state, "predictor", None, raising=False)
    monkeypatch.setattr(main.app.state, "model_error", None, raising=False)
    main.app.dependency_overrides[get_repository] = lambda: repo
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


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
    try:
        with TestClient(main.app) as c:
            assert c.get("/model").json()["version"] == "vtest"
            for _ in range(3):
                assert c.get("/predict", params={"home": 1, "away": 2}).status_code == 200
    finally:
        main.app.dependency_overrides.clear()
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
