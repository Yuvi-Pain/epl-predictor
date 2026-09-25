"""Tests for saving predictions before kickoff and scoring them afterwards.

Scoring (`track_record`) and choosing fixtures (`fixtures_to_predict`) are pure
and tested on small DataFrames. GET /track-record runs over the FakeRepository.
The rules that must hold in the database itself (a saved prediction never
changes, nothing is saved after kickoff) run against the real Postgres in a
transaction that is always rolled back, and are skipped without one.
"""

import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fakeredis import FakeRedis
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app import main
from app.api import live_model_version
from app.models import DataVersion, Match, Prediction, Team
from app.predictor import Predictor
from app.tracking import fixtures_to_predict, insert_predictions, record_predictions, track_record
from fakes import (
    TEAMS,
    FakeRepository,
    StubModel,
    make_bundle,
    make_matches,
    make_predictions,
    match,
    saved,
)
from test_fixtures import run_in_rollback

TEAM_MAP = {t.id: t for t in TEAMS}
V2 = (0.5, 0.3, 0.2)  # home, draw, away
V1 = (0.4, 0.3, 0.3)


def at(day: int, hour: int, month: int = 9) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def played(
    id: int, day: int, home: int, away: int, hg: int, ag: int, odds: Any, hour: int = 14
) -> dict[str, Any]:
    return match(
        id, "2026-27", date(2026, 9, day), home, away, hg, ag,
        kickoff_at=at(day, hour), status="FINISHED", odds=odds,
    )  # fmt: skip


def unplayed(id: int, day: int, home: int, away: int, status: str = "TIMED") -> dict[str, Any]:
    return match(
        id, "2026-27", date(2026, 9, day), home, away, None, None,
        kickoff_at=at(day, 14), status=status,
    )  # fmt: skip


MATCHES = [
    played(20, 19, 1, 2, 2, 0, odds=(2.0, 3.5, 4.0)),  # home win
    played(21, 20, 3, 4, 0, 1, odds=(2.5, 3.4, 3.0), hour=15),  # away win
    unplayed(22, 21, 2, 3, status="POSTPONED"),
    unplayed(23, 27, 4, 1),
    # Kickoff was brought forward to before v2's prediction was saved.
    played(24, 20, 2, 1, 1, 0, odds=(1.8, 3.6, 4.5), hour=12),
]


def both(match_id: int, when: datetime) -> list[dict[str, Any]]:
    return [saved(match_id, "v2", when, V2), saved(match_id, "v1", when, V1)]


PREDICTIONS = [
    *both(20, at(18, 9)),
    *both(21, at(18, 9)),
    *both(22, at(20, 9)),
    *both(23, at(26, 9)),
    saved(24, "v1", at(19, 9), V1),
    saved(24, "v2", at(20, 13), V2),  # an hour after the (new) kickoff
]


def record(
    matches: pd.DataFrame | None = None, predictions: pd.DataFrame | None = None, **kw: Any
) -> Any:
    kw.setdefault("live_version", "v2")
    return track_record(
        make_predictions(*PREDICTIONS) if predictions is None else predictions,
        make_matches(*MATCHES) if matches is None else matches,
        TEAM_MAP,
        **kw,
    )


def implied(odds: tuple[float, float, float]) -> np.ndarray:
    """(home, draw, away) decimal odds -> margin-free probabilities."""
    raw = 1 / np.array(odds)
    return raw / raw.sum()


# --- status of each prediction -------------------------------------------------------


def test_each_prediction_is_scored_pending_postponed_or_late() -> None:
    models = {m.version: m for m in record().models}
    assert models["v2"].model_dump() == {
        "version": "v2",
        "role": "live",
        "scored": 2,
        "pending": 1,
        "postponed": 1,
        "late": 1,
    }
    assert models["v1"].model_dump() == {
        "version": "v1",
        "role": "shadow",
        "scored": 3,
        "pending": 1,
        "postponed": 1,
        "late": 0,
    }


def test_a_prediction_saved_after_kickoff_never_counts() -> None:
    result = record()
    (m24,) = [m for m in result.matches if m.match_id == 24]
    v2, v1 = m24.predictions
    assert (v2.model_version, v2.status, v2.correct) == ("v2", "late", None)
    assert (v1.model_version, v1.status, v1.correct) == ("v1", "scored", True)
    # v2 has no counted prediction for it, so it is not compared at all.
    assert result.compared_matches == 2


def test_a_prediction_exactly_at_kickoff_is_late() -> None:
    predictions = make_predictions(saved(20, "v2", at(19, 14), V2))
    (m,) = record(predictions=predictions).models
    assert (m.scored, m.late) == (0, 1)


def test_a_postponed_match_is_not_counted_until_it_is_played() -> None:
    result = record()
    (m22,) = [m for m in result.matches if m.match_id == 22]
    assert {p.status for p in m22.predictions} == {"postponed"}
    assert m22.score is None and m22.actual is None

    # Rescheduled a month later and played. The prediction saved before the
    # original kickoff is also before the new one, so it now counts.
    rows = [r for r in MATCHES if r["id"] != 22]
    rescheduled = match(
        22, "2026-27", date(2026, 10, 21), 2, 3, 1, 1,
        kickoff_at=at(21, 19, month=10), status="FINISHED", odds=(2.9, 3.3, 2.6),
    )  # fmt: skip
    result = record(matches=make_matches(*rows, rescheduled))
    (m22,) = [m for m in result.matches if m.match_id == 22]
    assert {p.status for p in m22.predictions} == {"scored"}
    assert m22.actual == "draw"
    assert result.compared_matches == 3


def test_a_prediction_is_not_changed_by_scoring() -> None:
    (m20,) = [m for m in record().matches if m.match_id == 20]
    v2 = m20.predictions[0]
    assert v2.predicted_at == at(18, 9)
    assert v2.prediction.probabilities.model_dump() == {
        "home_win": 0.5,
        "draw": 0.3,
        "away_win": 0.2,
    }
    assert v2.prediction.most_likely == "home_win"


# --- scores ------------------------------------------------------------------------


def test_models_and_bookmaker_are_scored_on_the_same_matches() -> None:
    result = record()
    scores = {s.name: s for s in result.scores}
    assert [s.name for s in result.scores] == ["v2", "v1", "bookmaker"]
    assert scores["bookmaker"].kind == "bookmaker"

    # Match 20 was a home win, match 21 an away win.
    assert scores["v2"].metrics.log_loss == pytest.approx(-(math.log(0.5) + math.log(0.2)) / 2)
    assert scores["v1"].metrics.log_loss == pytest.approx(-(math.log(0.4) + math.log(0.3)) / 2)
    bookie = [implied((2.0, 3.5, 4.0))[0], implied((2.5, 3.4, 3.0))[2]]
    assert scores["bookmaker"].metrics.log_loss == pytest.approx(-np.mean(np.log(bookie)))

    assert scores["v2"].metrics.accuracy == 0.5  # home pick right, then wrong
    # v2 Brier: match 20 (0.5-1)^2 + 0.3^2 + 0.2^2 = 0.38; match 21 0.5^2 + 0.3^2 + 0.8^2 = 0.98.
    assert scores["v2"].metrics.brier == pytest.approx((0.38 + 0.98) / 2)


def test_matches_without_odds_are_left_out_of_the_comparison() -> None:
    rows = [r for r in MATCHES if r["id"] != 21]
    no_odds = played(21, 20, 3, 4, 0, 1, odds=None, hour=15)
    result = record(matches=make_matches(*rows, no_odds))
    assert result.compared_matches == 1
    (m21,) = [m for m in result.matches if m.match_id == 21]
    assert m21.bookmaker is None
    assert m21.predictions[0].status == "scored"  # still scored, just not compared


def test_running_log_loss_has_one_point_per_match_date() -> None:
    running = record().running
    assert [(p.match_date, p.matches) for p in running] == [
        (date(2026, 9, 19), 1),
        (date(2026, 9, 20), 2),
    ]
    assert running[0].log_loss["v2"] == pytest.approx(-math.log(0.5))
    final = {s.name: s.metrics.log_loss for s in record().scores}
    assert running[-1].log_loss == pytest.approx(final)


def test_matches_are_newest_first_with_the_live_model_first() -> None:
    result = record()
    assert [m.match_id for m in result.matches] == [23, 22, 21, 24, 20]
    assert all([p.model_version for p in m.predictions] == ["v2", "v1"] for m in result.matches)
    m20 = result.matches[-1]
    assert m20.score is not None and (m20.score.home_goals, m20.score.away_goals) == (2, 0)
    assert m20.home_team.name == "Arsenal"
    assert m20.bookmaker is not None
    assert m20.bookmaker.home_win == pytest.approx(implied((2.0, 3.5, 4.0))[0])


def test_without_a_live_model_every_model_is_a_shadow() -> None:
    result = record(live_version=None)
    assert [(m.version, m.role) for m in result.models] == [("v2", "shadow"), ("v1", "shadow")]


def test_nothing_saved_yet_is_an_empty_record() -> None:
    result = record(predictions=make_predictions())
    assert result.season is None
    assert (result.models, result.scores, result.running, result.matches) == ([], [], [], [])


def test_only_the_requested_season_is_included() -> None:
    assert record(season="2025-26").matches == []
    assert record().season == "2026-27"


# --- which fixtures the worker predicts ------------------------------------------------


def test_only_scheduled_fixtures_kicking_off_soon_are_predicted() -> None:
    now = datetime(2026, 9, 25, 12, tzinfo=UTC)

    def fixture(id: int, kickoff: datetime | None, status: str = "TIMED", **kw: Any):
        return match(id, "2026-27", date(2026, 9, 25), 1, 2, None, None,
                     kickoff_at=kickoff, status=status, **kw)  # fmt: skip

    matches = make_matches(
        fixture(30, now + timedelta(hours=2)),  # due
        fixture(31, now + timedelta(hours=24)),  # due: right at the edge of the window
        fixture(32, now + timedelta(hours=30)),  # too early to predict
        fixture(33, now - timedelta(minutes=1)),  # already kicked off
        fixture(34, now + timedelta(hours=2), status="POSTPONED"),
        fixture(35, None, status="SCHEDULED"),  # no kickoff time
        fixture(36, now + timedelta(hours=2), status="IN_PLAY"),
    )
    due = fixtures_to_predict(matches, now, timedelta(hours=24))
    assert due["id"].tolist() == [30, 31]


# --- GET /track-record -----------------------------------------------------------------


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository(make_matches(*MATCHES), make_predictions(*PREDICTIONS))


@pytest.fixture(autouse=True)
def live_v2() -> None:
    main.app.dependency_overrides[live_model_version] = lambda: "v2"  # cleared by conftest


def test_endpoint_returns_the_track_record(client: TestClient) -> None:
    r = client.get("/track-record")
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == "2026-27"
    assert body["live_version"] == "v2"
    assert body["compared_matches"] == 2
    assert [s["name"] for s in body["scores"]] == ["v2", "v1", "bookmaker"]
    assert [p["match_date"] for p in body["running"]] == ["2026-09-19", "2026-09-20"]
    assert body["matches"][0]["predictions"][0] == {
        "model_version": "v2",
        "predicted_at": "2026-09-26T09:00:00Z",
        "status": "pending",
        "prediction": {
            "probabilities": {"home_win": 0.5, "draw": 0.3, "away_win": 0.2},
            "most_likely": "home_win",
        },
        "correct": None,
    }


def test_endpoint_works_without_a_model(client_without_model: TestClient) -> None:
    main.app.dependency_overrides.pop(live_model_version)
    r = client_without_model.get("/track-record")
    assert r.status_code == 200
    assert r.json()["live_version"] is None


def test_endpoint_rejects_a_malformed_season(client: TestClient) -> None:
    assert client.get("/track-record", params={"season": "2026"}).status_code == 422


def test_endpoint_is_cached_under_the_data_version(
    client: TestClient, repo: FakeRepository, inspect_redis: FakeRedis
) -> None:
    assert client.get("/track-record").headers["X-Cache"] == "MISS"
    assert client.get("/track-record").headers["X-Cache"] == "HIT"
    (key,) = [k.decode() for k in inspect_redis.keys("*")]
    assert key == "epl:v1:track-record:live=v2:d1:latest"

    repo.version += 1  # the worker saved predictions or results came in
    assert client.get("/track-record").headers["X-Cache"] == "MISS"


# --- in Postgres, rolled back ----------------------------------------------------------

SEASON = "2099-00"


async def make_fixture(
    conn: AsyncConnection, kickoff: datetime | None, goals: tuple[int, int] | None = None
) -> int:
    """A season-2099 match, with a new pairing of existing teams each call (a pairing
    happens once a season)."""
    teams = (await conn.execute(select(Team.id).order_by(Team.id).limit(10))).scalars().all()
    taken = (
        await conn.execute(select(func.count()).select_from(Match).where(Match.season == SEASON))
    ).scalar_one()
    home, away = teams[0], teams[taken + 1]
    hg, ag = goals or (None, None)
    return (
        await conn.execute(
            insert(Match)
            .values(
                season=SEASON,
                match_date=(kickoff or datetime.now(UTC)).date(),
                home_team_id=home,
                away_team_id=away,
                home_goals=hg,
                away_goals=ag,
                kickoff_at=kickoff,
                status="TIMED" if goals is None else "FINISHED",
            )
            .returning(Match.id)
        )
    ).scalar_one()


def row(
    match_id: int, version: str = "v2", proba: tuple[float, float, float] = V2
) -> dict[str, Any]:
    p_home, p_draw, p_away = proba
    return dict(
        match_id=match_id, model_version=version, p_home=p_home, p_draw=p_draw, p_away=p_away
    )


async def saved_rows(conn: AsyncConnection, match_id: int) -> list[Any]:
    return (
        await conn.execute(
            select(Prediction)
            .where(Prediction.match_id == match_id)
            .order_by(Prediction.model_version)
        )
    ).all()


def soon() -> datetime:
    return datetime.now(UTC) + timedelta(hours=2)


def test_a_saved_prediction_cannot_be_updated_or_deleted() -> None:
    async def test(conn: AsyncConnection) -> None:
        match_id = await make_fixture(conn, soon())
        assert await insert_predictions(conn, [row(match_id)]) == 1
        (before,) = await saved_rows(conn, match_id)

        for stmt in (
            update(Prediction)
            .where(Prediction.match_id == match_id)
            .values(p_home=0.9, p_away=0.0),
            update(Prediction)
            .where(Prediction.match_id == match_id)
            .values(predicted_at=datetime(2000, 1, 1, tzinfo=UTC)),
            delete(Prediction).where(Prediction.match_id == match_id),
        ):
            with pytest.raises(IntegrityError, match="predictions are frozen"):
                async with conn.begin_nested():  # a savepoint, so the test can carry on
                    await conn.execute(stmt)

        assert await saved_rows(conn, match_id) == [before]

    run_in_rollback(test)


def test_saving_again_keeps_the_first_prediction() -> None:
    async def test(conn: AsyncConnection) -> None:
        match_id = await make_fixture(conn, soon())
        assert await insert_predictions(conn, [row(match_id)]) == 1
        (first,) = await saved_rows(conn, match_id)

        changed_mind = row(match_id, proba=(0.1, 0.1, 0.8))
        assert await insert_predictions(conn, [changed_mind, row(match_id, "v1", V1)]) == 1
        v1, v2 = await saved_rows(conn, match_id)
        assert v2 == first
        assert (v1.model_version, v1.p_home) == ("v1", 0.4)

    run_in_rollback(test)


def test_nothing_is_saved_at_or_after_kickoff() -> None:
    async def test(conn: AsyncConnection) -> None:
        now = (await conn.execute(select(func.now()))).scalar_one()
        kicked_off = await make_fixture(conn, now - timedelta(minutes=1))
        right_now = await make_fixture(conn, now)  # Postgres's now() is fixed for the transaction
        has_result = await make_fixture(conn, soon(), goals=(1, 0))
        no_kickoff = await make_fixture(conn, None)
        ok = await make_fixture(conn, soon())

        ids = [kicked_off, right_now, has_result, no_kickoff, ok]
        assert await insert_predictions(conn, [row(i) for i in ids]) == 1
        assert [len(await saved_rows(conn, i)) for i in ids] == [0, 0, 0, 0, 1]

    run_in_rollback(test)


def test_predicted_at_is_set_by_the_database_before_kickoff() -> None:
    async def test(conn: AsyncConnection) -> None:
        kickoff = soon()
        match_id = await make_fixture(conn, kickoff)
        await insert_predictions(conn, [row(match_id)])
        (saved_row,) = await saved_rows(conn, match_id)
        now = (await conn.execute(select(func.now()))).scalar_one()
        assert saved_row.predicted_at == now < kickoff

    run_in_rollback(test)


def test_the_worker_saves_every_tracked_model_once() -> None:
    def predictor(version: str) -> Predictor:
        return Predictor.from_bundle({**make_bundle(StubModel()), "version": version})

    async def data_version(conn: AsyncConnection) -> int:
        return (await conn.execute(select(DataVersion.version))).scalar_one()

    async def test(conn: AsyncConnection) -> None:
        now = datetime.now(UTC)
        due = await make_fixture(conn, now + timedelta(hours=2))
        later = await make_fixture(conn, now + timedelta(days=3))
        version = await data_version(conn)
        predictors = [predictor("live"), predictor("shadow")]

        assert await record_predictions(conn, predictors, now, timedelta(hours=24)) >= 2
        assert await data_version(conn) > version
        rows = await saved_rows(conn, due)
        assert [(r.model_version, r.p_home, r.p_draw, r.p_away) for r in rows] == [
            ("live", 0.5, 0.3, 0.2),
            ("shadow", 0.5, 0.3, 0.2),
        ]
        assert await saved_rows(conn, later) == []  # not due yet

        # An hour later: the saved predictions for this match stay as they were.
        await record_predictions(conn, predictors, now + timedelta(hours=1), timedelta(hours=24))
        assert await saved_rows(conn, due) == rows

    run_in_rollback(test)
