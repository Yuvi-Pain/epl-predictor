"""Save each model's predictions before kickoff, and score them once results arrive.

Recording (run by the worker): for fixtures kicking off soon, every tracked
model predicts and the predictions are inserted into the predictions table.
The live model (the one users see) and any shadow models are treated alike.
Rows are never changed afterwards; see `app.models.Prediction`.

Scoring (used by GET /track-record) never writes anything. A prediction's
status is worked out from the match as it is now:

- late: saved at or after kickoff (or the kickoff time is unknown). Never
  counted, whatever happens. The insert refuses these, but kickoff can be
  moved earlier after a prediction was saved.
- scored: saved before kickoff and the result is in.
- postponed: the match is postponed or suspended. Not counted for now; once
  it is rescheduled and played, the frozen prediction is scored like any other.
- pending: waiting for kickoff or for the result.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy import Double, Integer, String, column, func, select, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.features import match_results
from app.fixtures import UPCOMING_STATUSES
from app.ingest import bump_data_version
from app.match_model import OUTCOMES, implied_proba, score
from app.models import Match, Prediction
from app.predictor import Predictor
from app.repository import TeamRow, load_matches
from app.schemas import (
    MatchScore,
    Metrics,
    OutcomeProbabilities,
    RunningLogLoss,
    SavedPrediction,
    Team,
    TrackedMatch,
    TrackedModel,
    TrackRecord,
    TrackRecordScore,
)
from app.schemas import Prediction as PredictionSchema

log = logging.getLogger(__name__)

# football-data.org states for a match that will not be played as listed for now.
POSTPONED_STATUSES = frozenset({"POSTPONED", "SUSPENDED"})
BOOKMAKER = "bookmaker"
# Probability columns in OUTCOMES order (away, draw, home), like predict_proba output.
PROBA_COLUMNS = ["p_away", "p_draw", "p_home"]
ODDS_COLUMNS = ["odds_away", "odds_draw", "odds_home"]
OUTCOME_NAMES = {"A": "away_win", "D": "draw", "H": "home_win"}
# Log loss of a probability of 0 on what happened would be infinite; clip like scikit-learn.
_EPS = np.finfo(float).eps


# --- recording -----------------------------------------------------------------------


def fixtures_to_predict(matches: pd.DataFrame, now: datetime, lead: timedelta) -> pd.DataFrame:
    """Unplayed, still-scheduled fixtures kicking off after `now` and within `lead` of it.

    Fixtures without a kickoff time are left out: without one there is no way
    to show the prediction came first.
    """
    kickoff = pd.to_datetime(matches["kickoff_at"], utc=True)
    start = pd.Timestamp(now)
    return matches[
        matches["home_goals"].isna()
        & matches["status"].isin(UPCOMING_STATUSES)
        & (kickoff > start)
        & (kickoff <= start + lead)
    ]


async def insert_predictions(conn: AsyncConnection, rows: Sequence[Mapping[str, object]]) -> int:
    """Insert predictions that are new and still before kickoff. Returns how many were saved.

    Both rules are applied by Postgres in the one statement, against its own
    clock (the same clock that stamps `predicted_at`):

    - a (match, model version) that already has a prediction keeps it: the new
      one is dropped (ON CONFLICT DO NOTHING), never merged in;
    - a row for a match that has kicked off, has a result or has no kickoff
      time is dropped.

    Args:
        rows: Dicts with match_id, model_version, p_home, p_draw, p_away.
    """
    if not rows:
        return 0
    new = values(
        column("match_id", Integer),
        column("model_version", String),
        column("p_home", Double),
        column("p_draw", Double),
        column("p_away", Double),
        name="new",
    ).data(
        [(r["match_id"], r["model_version"], r["p_home"], r["p_draw"], r["p_away"]) for r in rows]
    )
    before_kickoff = (
        select(new)
        .join(Match, Match.id == new.c.match_id)
        .where(Match.kickoff_at > func.now(), Match.home_goals.is_(None))
    )
    stmt = (
        insert(Prediction)
        .from_select(["match_id", "model_version", "p_home", "p_draw", "p_away"], before_kickoff)
        .on_conflict_do_nothing(index_elements=[Prediction.match_id, Prediction.model_version])
        .returning(Prediction.id)
    )
    return len((await conn.execute(stmt)).all())


async def record_predictions(
    conn: AsyncConnection, predictors: Sequence[Predictor], now: datetime, lead: timedelta
) -> int:
    """Save every model's prediction for fixtures kicking off within `lead` of `now`.

    Each model builds its features with its own settings from the results
    stored so far, as /fixtures/upcoming does. Bumps the data version if
    anything was saved, so the cached track record is rebuilt.

    Returns:
        How many predictions were saved.
    """
    matches = await load_matches(conn)
    due = fixtures_to_predict(matches, now, lead)
    if due.empty or not predictors:
        return 0

    rows: list[dict[str, object]] = []
    for predictor in predictors:
        features = await asyncio.to_thread(predictor.history_features, matches)
        proba = predictor.predict_proba(features.loc[due.index])
        for match_id, (p_away, p_draw, p_home) in zip(due["id"], proba, strict=True):
            rows.append(
                {
                    "match_id": int(match_id),
                    "model_version": predictor.version,
                    "p_home": float(p_home),
                    "p_draw": float(p_draw),
                    "p_away": float(p_away),
                }
            )

    saved = await insert_predictions(conn, rows)
    log.info(
        "predictions: %d fixtures due, %d new predictions saved (%s)",
        len(due),
        saved,
        ", ".join(p.version for p in predictors),
    )
    if saved:
        await bump_data_version(conn)
    return saved


# --- scoring -------------------------------------------------------------------------


def prediction_status(tracked: pd.DataFrame) -> pd.Series:
    """Each prediction's status (see the module docstring), from predictions joined to matches."""
    kickoff = pd.to_datetime(tracked["kickoff_at"], utc=True)
    predicted = pd.to_datetime(tracked["predicted_at"], utc=True)
    late = kickoff.isna() | (predicted >= kickoff)
    played = tracked["home_goals"].notna() & tracked["away_goals"].notna()
    postponed = tracked["status"].isin(POSTPONED_STATUSES)
    status = np.select(
        [late.to_numpy(bool), played.to_numpy(bool), postponed.to_numpy(bool)],
        ["late", "scored", "postponed"],
        default="pending",
    )
    return pd.Series(status, index=tracked.index, dtype="object")


def _probabilities(p_home: float, p_draw: float, p_away: float) -> OutcomeProbabilities:
    return OutcomeProbabilities(home_win=p_home, draw=p_draw, away_win=p_away)


def _prediction(row: pd.Series) -> PredictionSchema:
    proba = row[PROBA_COLUMNS].to_numpy(dtype=float)
    return PredictionSchema(
        probabilities=_probabilities(row["p_home"], row["p_draw"], row["p_away"]),
        most_likely=OUTCOME_NAMES[OUTCOMES[int(np.argmax(proba))]],  # type: ignore[arg-type]
    )


def _version_order(versions: Sequence[str], live_version: str | None) -> list[str]:
    """The live model first, then the others by name, newest version first."""
    newest_first = sorted(set(versions), reverse=True)
    return sorted(newest_first, key=lambda v: v != live_version)


def _compared(tracked: pd.DataFrame, versions: Sequence[str]) -> pd.DataFrame:
    """Scored matches that every model predicted before kickoff and that have odds.

    Returns one row per match, oldest kickoff first, with the result, the odds
    and each model's probabilities (columns like "v2:p_home").
    """
    scored = tracked[tracked["status"] == "scored"]
    wide = scored.pivot(index="match_id", columns="model_version", values=PROBA_COLUMNS)
    wide.columns = [f"{c[1]}:{c[0]}" for c in wide.columns]  # "v2:p_home"
    wide = wide.dropna()  # every model has a scored prediction for the match
    if not all(f"{v}:p_home" in wide.columns for v in versions):
        return wide.iloc[0:0]
    info = scored.drop_duplicates("match_id").set_index("match_id")[
        ["match_date", "kickoff_at", "result", *ODDS_COLUMNS]
    ]
    compared = info.join(wide, how="inner").dropna(subset=ODDS_COLUMNS)
    return compared.sort_values(["kickoff_at", "match_date"]).reset_index()


def _series_proba(compared: pd.DataFrame, versions: Sequence[str]) -> dict[str, np.ndarray]:
    """(n, 3) probabilities in OUTCOMES order for every model and the bookmaker."""
    proba = {
        v: compared[[f"{v}:{c}" for c in PROBA_COLUMNS]].to_numpy(dtype=float) for v in versions
    }
    proba[BOOKMAKER] = implied_proba(compared[ODDS_COLUMNS])
    return proba


def _running_log_loss(
    compared: pd.DataFrame, proba: Mapping[str, np.ndarray]
) -> list[RunningLogLoss]:
    actual = compared["result"].map(OUTCOMES.index).to_numpy(dtype=int)
    rows = np.arange(len(compared))
    per_match = pd.DataFrame(
        {name: -np.log(np.clip(p[rows, actual], _EPS, 1.0)) for name, p in proba.items()}
    )
    running = per_match.expanding().mean()
    running["matches"] = rows + 1
    running["match_date"] = compared["match_date"].to_numpy()
    # After the last match of each day.
    by_day = running.groupby("match_date", sort=True).last()
    return [
        RunningLogLoss(
            match_date=cast(date, day),  # the groupby key: a match_date
            matches=int(point["matches"]),
            log_loss={name: float(point[name]) for name in proba},
        )
        for day, point in by_day.iterrows()
    ]


def _tracked_match(group: pd.DataFrame, teams: Mapping[int, TeamRow]) -> TrackedMatch:
    first = group.iloc[0]
    match_id = int(first["match_id"])
    played = not pd.isna(first["result"])
    has_odds = bool(first[ODDS_COLUMNS].notna().all())
    bookmaker = None
    if has_odds:
        p_away, p_draw, p_home = implied_proba(first[ODDS_COLUMNS].to_frame().T)[0]
        bookmaker = _probabilities(float(p_home), float(p_draw), float(p_away))
    actual = OUTCOME_NAMES[str(first["result"])] if played else None
    predictions = []
    for _, row in group.iterrows():
        prediction = _prediction(row)
        scored = row["status"] == "scored"
        predictions.append(
            SavedPrediction(
                model_version=row["model_version"],
                predicted_at=pd.Timestamp(row["predicted_at"]).to_pydatetime(),
                status=row["status"],
                prediction=prediction,
                correct=prediction.most_likely == actual if scored else None,
            )
        )
    home, away = teams[int(first["home_team_id"])], teams[int(first["away_team_id"])]
    kickoff = first["kickoff_at"]
    return TrackedMatch(
        match_id=match_id,
        match_date=first["match_date"],
        kickoff=None if pd.isna(kickoff) else pd.Timestamp(kickoff).to_pydatetime(),
        home_team=Team(id=home.id, name=home.name),
        away_team=Team(id=away.id, name=away.name),
        score=(
            MatchScore(home_goals=int(first["home_goals"]), away_goals=int(first["away_goals"]))
            if played
            else None
        ),
        actual=actual,  # type: ignore[arg-type]
        bookmaker=bookmaker,
        predictions=predictions,
    )


def track_record(
    predictions: pd.DataFrame,
    matches: pd.DataFrame,
    teams: Mapping[int, TeamRow],
    live_version: str | None,
    season: str | None = None,
) -> TrackRecord:
    """Score the saved predictions for one season against the results so far.

    Every model and the bookmaker are scored on the same matches: those every
    model predicted before kickoff, that have been played, and that have
    bookmaker odds. Otherwise one model could look better just by having
    skipped a hard match.

    Args:
        predictions: Rows of the predictions table.
        matches: Every match, as from `load_matches`.
        teams: Team id -> team, for names.
        live_version: The model users see, listed first; None if none is loaded.
        season: e.g. "2026-27". Defaults to the latest season with predictions.
    """
    tracked = (
        predictions.astype({"match_id": "int64"}).merge(
            matches.rename(columns={"id": "match_id"}), on="match_id", validate="many_to_one"
        )
        if not predictions.empty
        else pd.DataFrame()
    )
    if season is None and not tracked.empty:
        season = str(tracked.sort_values("match_date")["season"].iloc[-1])
    if not tracked.empty:
        tracked = tracked[tracked["season"] == season].copy()
    if tracked.empty:
        return TrackRecord(
            season=season,
            live_version=live_version,
            models=[],
            compared_matches=0,
            scores=[],
            running=[],
            matches=[],
        )

    tracked["status"] = prediction_status(tracked)
    tracked["result"] = match_results(tracked)
    versions = _version_order(tracked["model_version"].tolist(), live_version)

    counts = tracked.groupby(["model_version", "status"]).size()
    models = [
        TrackedModel(
            version=v,
            role="live" if v == live_version else "shadow",
            **{s: int(counts.get((v, s), 0)) for s in ("scored", "pending", "postponed", "late")},
        )
        for v in versions
    ]

    compared = _compared(tracked, versions)
    scores: list[TrackRecordScore] = []
    running: list[RunningLogLoss] = []
    if not compared.empty:
        proba = _series_proba(compared, versions)
        scores = [
            TrackRecordScore(
                name=name,
                kind="bookmaker" if name == BOOKMAKER else "model",
                metrics=Metrics(**score(compared["result"].astype(str), p)),
            )
            for name, p in proba.items()
        ]
        running = _running_log_loss(compared, proba)

    rank = {v: i for i, v in enumerate(versions)}
    tracked["_rank"] = tracked["model_version"].map(rank)
    tracked["_kickoff"] = pd.to_datetime(tracked["kickoff_at"], utc=True)
    newest_first = tracked.sort_values(
        ["_kickoff", "match_date", "match_id", "_rank"], ascending=[False, False, False, True]
    )
    return TrackRecord(
        season=season,
        live_version=live_version,
        models=models,
        compared_matches=len(compared),
        scores=scores,
        running=running,
        matches=[
            _tracked_match(group, teams)
            for _, group in newest_first.groupby("match_id", sort=False)
        ],
    )
