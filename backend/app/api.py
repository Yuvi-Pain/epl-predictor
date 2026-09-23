"""Prediction endpoints: teams, live predictions, season backtest, model info."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.db import engine
from app.match_model import MODEL_LABEL, OUTCOMES
from app.predictor import Predictor
from app.repository import Repository, TeamRow
from app.schemas import (
    ErrorResponse,
    MatchFeatures,
    MatchList,
    MatchResult,
    MatchScore,
    Metrics,
    ModelInfo,
    Outcome,
    OutcomeProbabilities,
    Prediction,
    PredictResponse,
    SplitMetrics,
    Team,
    TeamList,
)

router = APIRouter()

# OUTCOMES is ["A", "D", "H"], the column order of every probability array.
OUTCOME_NAMES: dict[str, Outcome] = {"A": "away_win", "D": "draw", "H": "home_win"}
NO_MODEL_DETAIL = (
    "No trained model is loaded. Run `python -m scripts.train_model`, then restart the backend."
)
MODEL_UNAVAILABLE: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorResponse, "description": "No usable model file is loaded."}
}


async def get_repository() -> AsyncIterator[Repository]:
    """One database connection per request, returned to the pool afterwards."""
    async with engine.connect() as conn:
        yield Repository(conn)


def get_predictor(request: Request) -> Predictor:
    """The model loaded at startup. 503 if there is none."""
    predictor: Predictor | None = getattr(request.app.state, "predictor", None)
    if predictor is None:
        detail = getattr(request.app.state, "model_error", None) or NO_MODEL_DETAIL
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    return predictor


RepoDep = Annotated[Repository, Depends(get_repository)]
PredictorDep = Annotated[Predictor, Depends(get_predictor)]


def _team(row: TeamRow) -> Team:
    return Team(id=row.id, name=row.name)


def _prediction(proba: np.ndarray) -> Prediction:
    """One row of predict_proba output (A, D, H order) as a response model."""
    by_name = {OUTCOME_NAMES[o]: float(p) for o, p in zip(OUTCOMES, proba, strict=True)}
    return Prediction(
        probabilities=OutcomeProbabilities(**by_name),
        most_likely=OUTCOME_NAMES[OUTCOMES[int(np.argmax(proba))]],
    )


def _nan_to_none(values: pd.Series) -> dict[str, float | None]:
    return {k: None if pd.isna(v) else float(v) for k, v in values.items()}


@router.get("/teams", response_model=TeamList, tags=["teams"])
async def list_teams(repo: RepoDep) -> TeamList:
    """Every team in the database, alphabetically. Use the ids with /predict."""
    return TeamList(teams=[_team(t) for t in await repo.list_teams()])


@router.get(
    "/predict",
    response_model=PredictResponse,
    tags=["predictions"],
    responses={
        400: {"model": ErrorResponse, "description": "Home and away are the same team."},
        404: {"model": ErrorResponse, "description": "A team id does not exist."},
        **MODEL_UNAVAILABLE,
    },
)
async def predict(
    repo: RepoDep,
    predictor: PredictorDep,
    home: Annotated[int, Query(description="Home team id, from /teams.")],
    away: Annotated[int, Query(description="Away team id, from /teams.")],
    as_of: Annotated[
        date | None,
        Query(description="Predict as if the match were on this date. Defaults to today."),
    ] = None,
) -> PredictResponse:
    """Win/draw/loss probabilities for a match between two teams.

    Features are built from results before `as_of` only, with the same code
    used in training.
    """
    if home == away:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="home and away must be different teams")
    teams = await repo.get_teams([home, away])
    missing = [t for t in (home, away) if t not in teams]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"unknown team id(s): {', '.join(map(str, missing))}"
        )

    as_of = as_of or date.today()
    history = await repo.load_matches()
    # Feature building is CPU-bound pandas; run it off the event loop.
    features = await asyncio.to_thread(predictor.match_features, history, home, away, as_of)
    proba = predictor.predict_proba(features.to_frame().T)[0]
    return PredictResponse(
        home_team=_team(teams[home]),
        away_team=_team(teams[away]),
        as_of=as_of,
        prediction=_prediction(proba),
        features=MatchFeatures(**_nan_to_none(features)),
        model_version=predictor.version,
    )


@router.get(
    "/matches",
    response_model=MatchList,
    tags=["predictions"],
    responses={
        404: {"model": ErrorResponse, "description": "No matches for that season."},
        **MODEL_UNAVAILABLE,
    },
)
async def list_matches(
    repo: RepoDep,
    predictor: PredictorDep,
    season: Annotated[
        str | None,
        Query(pattern=r"^\d{4}-\d{2}$", description='e.g. "2026-27". Defaults to the latest season.'),
    ] = None,
) -> MatchList:
    """Played matches in a season, oldest first, each with the model's pre-match prediction.

    Each prediction uses only results from before that match's date, exactly as
    in training, so it is what the model would have said beforehand.
    """
    matches = await repo.load_matches()
    season = season or (str(matches["season"].iloc[-1]) if not matches.empty else None)
    if season is None or not (matches["season"] == season).any():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no matches for season {season}")

    features = await asyncio.to_thread(predictor.history_features, matches)
    rows = features.index[(features["season"] == season) & features["result"].notna()]
    proba = predictor.predict_proba(features.loc[rows]) if len(rows) else np.empty((0, 3))
    teams = {t.id: t for t in await repo.list_teams()}

    results = []
    for i, p in zip(rows, proba, strict=True):
        m = matches.loc[i]
        prediction = _prediction(p)
        actual = OUTCOME_NAMES[str(features.at[i, "result"])]
        results.append(
            MatchResult(
                match_id=int(m["id"]),
                match_date=m["match_date"],
                home_team=_team(teams[int(m["home_team_id"])]),
                away_team=_team(teams[int(m["away_team_id"])]),
                score=MatchScore(home_goals=int(m["home_goals"]), away_goals=int(m["away_goals"])),
                actual=actual,
                prediction=prediction,
                correct=prediction.most_likely == actual,
            )
        )
    return MatchList(
        season=season,
        model_version=predictor.version,
        model_split=predictor.split_of(season),
        matches=results,
    )


def _split_metrics(season: str, results: dict[str, dict[str, float]]) -> SplitMetrics:
    return SplitMetrics(
        season=season,
        model=Metrics(**results[MODEL_LABEL]),
        baselines={name: Metrics(**m) for name, m in results.items() if name != MODEL_LABEL},
    )


@router.get("/model", response_model=ModelInfo, tags=["model"], responses=MODEL_UNAVAILABLE)
async def model_info(predictor: PredictorDep) -> ModelInfo:
    """The loaded model's version, training date, and validation and test scores
    alongside the baselines it was compared with."""
    return ModelInfo(
        version=predictor.version,
        trained_at=predictor.trained_at,
        features=predictor.feature_columns,
        train_seasons=predictor.train_seasons,
        validation=_split_metrics(predictor.validation_season, predictor.metrics["validation"]),
        test=_split_metrics(predictor.test_season, predictor.metrics["test"]),
    )
