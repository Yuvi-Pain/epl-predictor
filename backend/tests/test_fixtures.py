"""Tests for turning football-data.org fixtures into matches rows.

`parse_fixtures` is pure and tested directly. The database tests run the real
upsert against Postgres inside a transaction that is always rolled back, so
they leave no trace; they are skipped when Postgres is not reachable. They use
season 2099-00 so they cannot collide with real rows. The API itself is
always mocked.
"""

import asyncio
import os
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app import fixtures
from app.fixtures import UnknownTeamError, parse_fixtures, refresh_fixtures, store_fixtures
from app.football_data_org import FootballDataClient, RateLimiter
from app.ingest import seed_teams
from app.models import DataVersion, Match

from pg import postgres_unreachable, run_in_rollback

ALIASES = {"Arsenal": 1, "Arsenal FC": 1, "Chelsea": 2, "Chelsea FC": 2, "Manchester United FC": 3}
SEASON_START = "2099-08-14"
SEASON = "2099-00"


def api_match(
    home: str,
    away: str,
    utc: str = "2099-08-15T14:00:00Z",
    status: str = "TIMED",
    matchday: int | None = 1,
) -> dict[str, Any]:
    """Shaped like one entry of /v4/competitions/PL/matches, with a few extra fields."""
    return {
        "id": 500001,
        "utcDate": utc,
        "status": status,
        "matchday": matchday,
        "stage": "REGULAR_SEASON",
        "season": {"id": 9999, "startDate": SEASON_START, "endDate": "2100-05-23"},
        "homeTeam": {"id": 57, "name": home, "shortName": home.split()[0], "tla": "HOM"},
        "awayTeam": {"id": 61, "name": away, "shortName": away.split()[0], "tla": "AWY"},
        "score": {"winner": None, "fullTime": {"home": None, "away": None}},
    }


def payload(*matches: dict[str, Any]) -> dict[str, Any]:
    return {
        "filters": {"season": "2099"},
        "resultSet": {"count": len(matches)},
        "matches": list(matches),
    }


# --- parse_fixtures ------------------------------------------------------------------


def test_parses_a_fixture_into_a_matches_row() -> None:
    (row,) = parse_fixtures(payload(api_match("Arsenal FC", "Chelsea FC", matchday=7)), ALIASES)
    assert row == {
        "season": SEASON,
        "match_date": date(2099, 8, 15),
        "kickoff_at": datetime(2099, 8, 15, 14, tzinfo=UTC),
        "matchday": 7,
        "status": "TIMED",
        "home_team_id": 1,
        "away_team_id": 2,
    }
    assert "home_goals" not in row  # goals stay NULL; results come from the CSVs


def test_match_date_is_the_uk_date() -> None:
    # 23:30 UTC on 14 August is 00:30 on 15 August in London (BST).
    (row,) = parse_fixtures(
        payload(api_match("Arsenal", "Chelsea", utc="2099-08-14T23:30:00Z")), ALIASES
    )
    assert row["match_date"] == date(2099, 8, 15)


def test_team_names_go_through_the_alias_table_ignoring_case_and_spacing() -> None:
    (row,) = parse_fixtures(payload(api_match("  manchester  united fc", "ARSENAL FC")), ALIASES)
    assert (row["home_team_id"], row["away_team_id"]) == (3, 1)


def test_unknown_team_names_are_all_reported() -> None:
    body = payload(
        api_match("Arsenal FC", "Wrexham AFC"),
        api_match("Wrexham AFC", "Chelsea FC"),
        api_match("Arsenal FC", "Portsmouth FC"),
    )
    with pytest.raises(UnknownTeamError) as excinfo:
        parse_fixtures(body, ALIASES)
    assert excinfo.value.names == ["Portsmouth FC", "Wrexham AFC"]
    assert "app/teams.py" in str(excinfo.value)


def test_cancelled_fixtures_are_skipped_but_postponed_ones_kept() -> None:
    rows = parse_fixtures(
        payload(
            api_match("Arsenal", "Chelsea", status="CANCELLED"),
            api_match("Chelsea", "Arsenal", status="POSTPONED"),
        ),
        ALIASES,
    )
    assert [(r["home_team_id"], r["status"]) for r in rows] == [(2, "POSTPONED")]


def test_every_api_spelling_of_a_current_club_is_known() -> None:
    """The 2026-27 clubs as football-data.org names them."""
    from app.teams import KNOWN_TEAMS

    aliases = {
        a: i for i, (name, others) in enumerate(KNOWN_TEAMS.items()) for a in [name, *others]
    }
    api_names = [
        "Arsenal FC",
        "Aston Villa FC",
        "AFC Bournemouth",
        "Brentford FC",
        "Brighton & Hove Albion FC",
        "Burnley FC",
        "Chelsea FC",
        "Crystal Palace FC",
        "Everton FC",
        "Fulham FC",
        "Leeds United FC",
        "Liverpool FC",
        "Manchester City FC",
        "Manchester United FC",
        "Newcastle United FC",
        "Nottingham Forest FC",
        "Sunderland AFC",
        "Tottenham Hotspur FC",
        "West Ham United FC",
        "Wolverhampton Wanderers FC",
    ]
    body = payload(*(api_match(n, "Arsenal FC") for n in api_names if n != "Arsenal FC"))
    assert len(parse_fixtures(body, aliases)) == 19


# --- against Postgres, rolled back ---------------------------------------------------


async def data_version(conn: AsyncConnection) -> int:
    return (await conn.execute(select(DataVersion.version))).scalar_one()


async def stored_rows(conn: AsyncConnection) -> list[Any]:
    return (
        await conn.execute(
            select(Match).where(Match.season == SEASON).order_by(Match.match_date, Match.id)
        )
    ).all()


def test_store_inserts_fixtures_with_null_goals_and_bumps_the_version() -> None:
    async def test(conn: AsyncConnection) -> None:
        await seed_teams(conn)  # so the count below is fixtures only, even on an empty database
        before = await data_version(conn)
        body = payload(
            api_match("Arsenal FC", "Chelsea FC", matchday=1),
            api_match(
                "Manchester United FC", "Liverpool FC", utc="2099-08-16T15:30:00Z", matchday=1
            ),
        )
        assert await store_fixtures(conn, body) == 2
        assert await data_version(conn) == before + 1

        rows = await stored_rows(conn)
        assert len(rows) == 2
        assert all(r.home_goals is None and r.away_goals is None for r in rows)
        assert [(r.matchday, r.status) for r in rows] == [(1, "TIMED"), (1, "TIMED")]
        assert rows[1].kickoff_at == datetime(2099, 8, 16, 15, 30, tzinfo=UTC)

    run_in_rollback(test)


def test_store_is_idempotent_and_leaves_the_version_alone_when_nothing_changed() -> None:
    async def test(conn: AsyncConnection) -> None:
        body = payload(api_match("Arsenal FC", "Chelsea FC"))
        await store_fixtures(conn, body)
        version = await data_version(conn)

        assert await store_fixtures(conn, body) == 0
        assert await data_version(conn) == version
        assert len(await stored_rows(conn)) == 1

    run_in_rollback(test)


def test_a_rescheduled_fixture_moves_and_bumps_the_version() -> None:
    async def test(conn: AsyncConnection) -> None:
        await store_fixtures(conn, payload(api_match("Arsenal FC", "Chelsea FC")))
        version = await data_version(conn)

        moved = api_match("Arsenal FC", "Chelsea FC", utc="2099-09-20T19:45:00Z")
        assert await store_fixtures(conn, payload(moved)) == 1
        assert await data_version(conn) == version + 1
        (row,) = await stored_rows(conn)
        assert row.match_date == date(2099, 9, 20)

    run_in_rollback(test)


def test_a_played_match_keeps_its_result_and_date() -> None:
    """Results belong to the history loader: the fixture refresh never overwrites them."""

    async def test(conn: AsyncConnection) -> None:
        await store_fixtures(conn, payload(api_match("Arsenal FC", "Chelsea FC")))
        # What load_history does once the result is in the CSV.
        await conn.execute(
            update(Match).where(Match.season == SEASON).values(home_goals=2, away_goals=1)
        )
        later = api_match("Arsenal FC", "Chelsea FC", utc="2099-08-16T14:00:00Z", status="FINISHED")
        assert await store_fixtures(conn, payload(later)) == 1  # the status changed

        (row,) = await stored_rows(conn)
        assert (row.home_goals, row.away_goals) == (2, 1)
        assert row.match_date == date(2099, 8, 15)
        assert row.status == "FINISHED"

    run_in_rollback(test)


def test_an_unknown_team_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through refresh_fixtures, with the API mocked: the whole refresh is one transaction."""
    body = payload(api_match("Arsenal FC", "Chelsea FC"), api_match("Wrexham AFC", "Chelsea FC"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))

    async def go() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        monkeypatch.setattr(fixtures, "engine", engine)
        try:
            try:
                async with engine.connect() as conn:
                    before = (await data_version(conn), await func_count(conn))
            except Exception as exc:
                postgres_unreachable(exc)

            async with FootballDataClient(
                "k", transport=transport, limiter=RateLimiter()
            ) as client:
                with pytest.raises(UnknownTeamError, match="Wrexham AFC"):
                    await refresh_fixtures(client)

            async with engine.connect() as conn:
                assert (await data_version(conn), await func_count(conn)) == before
        finally:
            await engine.dispose()

    asyncio.run(go())


async def func_count(conn: AsyncConnection) -> int:
    return (await conn.execute(select(func.count()).select_from(Match))).scalar_one()
