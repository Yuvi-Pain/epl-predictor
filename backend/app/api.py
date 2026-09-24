"""Prediction endpoints: teams, live predictions, upcoming fixtures, season backtest, model info.

/teams, /predict, /matches and /fixtures/upcoming are cached in Redis (see
app/cache.py). Their keys include the data version from Postgres and, where
the model is used, the model's version and training time.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.cache import (
    FIXTURES_TTL,
    MATCHES_TTL,
    PREDICT_TTL,
    TEAMS_TTL,
    ResponseCache,
    cache_key,
    get_cache,
)
from app.db import engine
from app.fixtures import UK, UPCOMING_STATUSES
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
    UpcomingFixture,
    UpcomingFixtures,
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
CacheDep = Annotated[ResponseCache, Depends(get_cache)]
CACHE_HEADER_DOC = {
    "X-Cache": {"description": "HIT if served from Redis, MISS if built for this request."}
}


def _model_tag(predictor: Predictor) -> str:
    # The training time as well as the version: retraining with --force keeps
    # the version but produces a different model.
    return f"m{predictor.version}@{predictor.trained_at}"


def _team(row: TeamRow) -> Team:
    return Team(id=row.id, name=row.name)


def _prediction(proba: np.ndarray) -> Prediction:
    """One row of predict_proba output (A, D, H order) as a response model."""
    by_name = {OUTCOME_NAMES[o]: float(p) for o, p in zip(OUTCOMES, proba, strict=True)}
    return Prediction(
        probabilities=OutcomeProbabilities(**by_name),
        most_likely=OUTCOME_NAMES[OUTCOMES[int(np.argmax(proba))]],
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if pd.isna(value) else pd.Timestamp(value).to_pydatetime()  # type: ignore[arg-type]


def _nan_to_none(values: pd.Series) -> dict[str, float | None]:
    return {k: None if pd.isna(v) else float(v) for k, v in values.items()}


async def _build_predict(
    repo: Repository, predictor: Predictor, home: int, away: int, as_of: date
) -> PredictResponse:
    teams = await repo.get_teams([home, away])
    missing = [t for t in (home, away) if t not in teams]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"unknown team id(s): {', '.join(map(str, missing))}"
        )

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


async def _build_matches(repo: Repository, predictor: Predictor, season: str | None) -> MatchList:
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


# In every cached endpoint the data version is read before any data, so a
# response is never stored under a newer version than the data it was built
# from (at worst, newer data lands under an older key that nobody reads again).


@router.get(
    "/teams",
    response_model=TeamList,
    tags=["teams"],
    responses={200: {"headers": CACHE_HEADER_DOC}},
)
async def list_teams(repo: RepoDep, cache: CacheDep) -> Response:
    """Every team in the database, alphabetically. Use the ids with /predict."""

    async def build() -> TeamList:
        return TeamList(teams=[_team(t) for t in await repo.list_teams()])

    key = cache_key("teams", f"d{await repo.data_version()}")
    return await cache.get_or_build(key, TEAMS_TTL, build)


@router.get(
    "/predict",
    response_model=PredictResponse,
    tags=["predictions"],
    responses={
        200: {"headers": CACHE_HEADER_DOC},
        400: {"model": ErrorResponse, "description": "Home and away are the same team."},
        404: {"model": ErrorResponse, "description": "A team id does not exist."},
        **MODEL_UNAVAILABLE,
    },
)
async def predict(
    repo: RepoDep,
    predictor: PredictorDep,
    cache: CacheDep,
    home: Annotated[int, Query(description="Home team id, from /teams.")],
    away: Annotated[int, Query(description="Away team id, from /teams.")],
    as_of: Annotated[
        date | None,
        Query(description="Predict as if the match were on this date. Defaults to today."),
    ] = None,
) -> Response:
    """Win/draw/loss probabilities for a match between two teams.

    Features are built from results before `as_of` only, with the same code
    used in training.
    """
    if home == away:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="home and away must be different teams")
    # Resolve the default before building the key, so "today" is cached per day.
    as_of = as_of or date.today()
    data_version = await repo.data_version()
    key = cache_key(
        "predict", _model_tag(predictor), f"d{data_version}", home, away, as_of.isoformat()
    )
    return await cache.get_or_build(
        key, PREDICT_TTL, lambda: _build_predict(repo, predictor, home, away, as_of)
    )


@router.get(
    "/matches",
    response_model=MatchList,
    tags=["predictions"],
    responses={
        200: {"headers": CACHE_HEADER_DOC},
        404: {"model": ErrorResponse, "description": "No matches for that season."},
        **MODEL_UNAVAILABLE,
    },
)
async def list_matches(
    repo: RepoDep,
    predictor: PredictorDep,
    cache: CacheDep,
    season: Annotated[
        str | None,
        Query(pattern=r"^\d{4}-\d{2}$", description='e.g. "2026-27". Defaults to the latest season.'),
    ] = None,
) -> Response:
    """Played matches in a season, oldest first, each with the model's pre-match prediction.

    Each prediction uses only results from before that match's date, exactly as
    in training, so it is what the model would have said beforehand.
    """
    # "latest" is safe to cache: which season is latest can only change with the data version.
    data_version = await repo.data_version()
    key = cache_key("matches", _model_tag(predictor), f"d{data_version}", season or "latest")
    return await cache.get_or_build(
        key, MATCHES_TTL, lambda: _build_matches(repo, predictor, season)
    )


def uk_today() -> date:
    """Today in the UK, the timezone match dates are stored in. Tests override it."""
    return datetime.now(UK).date()


TodayDep = Annotated[date, Depends(uk_today)]


def next_matchweek(matches: pd.DataFrame, today: date) -> pd.DataFrame:
    """The next matchweek's unplayed fixtures, soonest first. Empty if there are none.

    Upcoming means no result yet, dated today or later, and not postponed or
    under way. The next matchweek is the matchday of the soonest of those; a
    match rescheduled from an earlier matchday shows up with its old matchday
    once it is the soonest. Fixtures without a matchday fall back to the seven
    days from the soonest one.
    """
    status = matches["status"]
    upcoming = matches[
        matches["home_goals"].isna()
        & (pd.to_datetime(matches["match_date"]) >= pd.Timestamp(today))
        & (status.isna() | status.isin(UPCOMING_STATUSES))
    ].sort_values(["match_date", "kickoff_at", "id"])
    if upcoming.empty:
        return upcoming
    first = upcoming.iloc[0]
    if pd.isna(first["matchday"]):
        week_end = pd.Timestamp(first["match_date"]) + pd.Timedelta(days=7)
        return upcoming[pd.to_datetime(upcoming["match_date"]) < week_end]
    same_week = upcoming["matchday"].eq(first["matchday"]).fillna(False) & (
        upcoming["season"] == first["season"]
    )
    return upcoming[same_week]


async def _build_upcoming(repo: Repository, predictor: Predictor, today: date) -> UpcomingFixtures:
    matches = await repo.load_matches()
    fixtures = next_matchweek(matches, today)
    if fixtures.empty:
        return UpcomingFixtures(
            season=None, matchday=None, model_version=predictor.version, fixtures=[]
        )

    # Pre-match features for every match, as in training; a future fixture's
    # features use every result so far, the same as /predict would today.
    features = await asyncio.to_thread(predictor.history_features, matches)
    proba = predictor.predict_proba(features.loc[fixtures.index])
    teams = {t.id: t for t in await repo.list_teams()}

    first = fixtures.iloc[0]
    return UpcomingFixtures(
        season=str(first["season"]),
        matchday=None if pd.isna(first["matchday"]) else int(first["matchday"]),
        model_version=predictor.version,
        fixtures=[
            UpcomingFixture(
                match_id=int(m["id"]),
                match_date=m["match_date"],
                kickoff=_optional_datetime(m["kickoff_at"]),
                home_team=_team(teams[int(m["home_team_id"])]),
                away_team=_team(teams[int(m["away_team_id"])]),
                prediction=_prediction(p),
            )
            for (_, m), p in zip(fixtures.iterrows(), proba, strict=True)
        ],
    )


@router.get(
    "/fixtures/upcoming",
    response_model=UpcomingFixtures,
    tags=["predictions"],
    responses={200: {"headers": CACHE_HEADER_DOC}, **MODEL_UNAVAILABLE},
)
async def upcoming_fixtures(
    repo: RepoDep, predictor: PredictorDep, cache: CacheDep, today: TodayDep
) -> Response:
    """The next matchweek's fixtures, soonest first, each with the model's prediction.

    Fixtures come from football-data.org via the worker. An empty list means
    none are stored yet (or the season is over).
    """
    # Today is in the key: a new day can drop fixtures already played.
    data_version = await repo.data_version()
    key = cache_key(
        "fixtures", "upcoming", _model_tag(predictor), f"d{data_version}", today.isoformat()
    )
    return await cache.get_or_build(
        key, FIXTURES_TTL, lambda: _build_upcoming(repo, predictor, today)
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
