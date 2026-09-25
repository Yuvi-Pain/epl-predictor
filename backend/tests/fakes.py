"""In-memory stand-ins for the database and the model, shared by the API tests."""

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.features import FEATURE_COLUMNS, EloConfig
from app.match_model import MODEL_LABEL, OUTCOMES
from app.repository import TeamRow

TEAMS = [
    TeamRow(1, "Arsenal"),
    TeamRow(2, "Chelsea"),
    TeamRow(3, "Liverpool"),
    TeamRow(4, "Everton"),
]
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
    id: int,
    season: str,
    day: date,
    home: int,
    away: int,
    hg: int | None,
    ag: int | None,
    *,
    matchday: int | None = None,
    kickoff_at: datetime | None = None,
    status: str | None = None,
    odds: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """One matches row. `odds` are decimal (home, draw, away) odds."""
    odds_home, odds_draw, odds_away = odds or (None, None, None)
    return {
        "odds_home": odds_home,
        "odds_draw": odds_draw,
        "odds_away": odds_away,
        "id": id,
        "season": season,
        "match_date": day,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_shots_on_target": None if hg is None else hg + 3,
        "away_shots_on_target": None if ag is None else ag + 2,
        "matchday": matchday,
        "kickoff_at": kickoff_at,
        "status": status,
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
    for col in (
        "home_goals",
        "away_goals",
        "home_shots_on_target",
        "away_shots_on_target",
        "matchday",
    ):
        df[col] = df[col].astype("Int16")
    for col in ("odds_home", "odds_draw", "odds_away"):
        df[col] = df[col].astype(float)
    return df


def saved(
    match_id: int, version: str, at: datetime, proba: tuple[float, float, float]
) -> dict[str, Any]:
    """One predictions row. `proba` is (home, draw, away)."""
    p_home, p_draw, p_away = proba
    return {
        "match_id": match_id,
        "model_version": version,
        "p_home": p_home,
        "p_draw": p_draw,
        "p_away": p_away,
        "predicted_at": at,
    }


PREDICTION_COLUMNS = ["match_id", "model_version", "p_home", "p_draw", "p_away", "predicted_at"]


def make_predictions(*rows: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=PREDICTION_COLUMNS)


class FakeRepository:
    def __init__(self, matches: pd.DataFrame, predictions: pd.DataFrame | None = None) -> None:
        self.matches = matches
        self.predictions = make_predictions() if predictions is None else predictions
        self.version = 1  # what data_version() returns; bump it when changing matches

    async def list_teams(self) -> list[TeamRow]:
        return sorted(TEAMS, key=lambda t: t.name)

    async def get_teams(self, team_ids: list[int]) -> dict[int, TeamRow]:
        return {t.id: t for t in TEAMS if t.id in team_ids}

    async def load_matches(self) -> pd.DataFrame:
        return self.matches.copy()

    async def load_predictions(self) -> pd.DataFrame:
        return self.predictions.copy()

    async def data_version(self) -> int:
        return self.version


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
