"""Store the Premier League fixture list from football-data.org as matches.

Fixtures become rows in the matches table with NULL goals. Results still come
only from the football-data.co.uk CSVs (`scripts/load_history.py`), which also
carry the shots the model needs, so this module never writes goals or stats.
It sets the date, matchday, kickoff time and status, and inserts fixtures the
table does not have yet.

Run by the worker a few times a day, or by hand:

    docker compose exec backend python -m scripts.refresh_fixtures
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, and_, case, literal_column, or_, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import engine
from app.football_data import normalize_team_name
from app.football_data_org import FootballDataClient
from app.ingest import bump_data_version, seed_teams
from app.models import Match

log = logging.getLogger(__name__)

# Match dates are UK dates, as in the results CSVs; the API gives UTC times.
UK = ZoneInfo("Europe/London")
# Fixtures in these states are not stored: the match will not be played as listed.
SKIPPED_STATUSES = frozenset({"CANCELLED"})
# States in which a match still counts as upcoming. Anything else (POSTPONED,
# SUSPENDED, IN_PLAY, FINISHED, ...) is left off the upcoming list.
UPCOMING_STATUSES = frozenset({"SCHEDULED", "TIMED"})


class UnknownTeamError(ValueError):
    """The API used team names that are not in the alias table."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = sorted(set(names))
        super().__init__(
            f"Unknown team names from football-data.org (add them to app/teams.py): {self.names}"
        )


# Only the fields we use; the API sends many more, which are ignored.
class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ApiTeam(_ApiModel):
    name: str


class ApiSeason(_ApiModel):
    startDate: date


class ApiMatch(_ApiModel):
    utcDate: datetime
    status: str
    matchday: int | None = None
    season: ApiSeason
    homeTeam: ApiTeam
    awayTeam: ApiTeam


class ApiMatches(_ApiModel):
    matches: list[ApiMatch]


def season_label(start: date) -> str:
    """The season a start date begins: 2026-08-15 -> "2026-27"."""
    return f"{start.year}-{(start.year + 1) % 100:02d}"


def parse_fixtures(
    payload: Mapping[str, Any], alias_to_id: Mapping[str, int]
) -> list[dict[str, object]]:
    """Turn a /competitions/PL/matches response into rows for the matches table.

    Args:
        payload: The API's JSON body.
        alias_to_id: Alias -> team id, from the team_aliases table.

    Returns:
        One dict per fixture with season, match_date, kickoff_at, matchday,
        status and team ids. Cancelled fixtures are left out.

    Raises:
        UnknownTeamError: If any team name has no alias. Nothing should be
            stored then, rather than skipping that team's fixtures quietly.
        pydantic.ValidationError: If the payload is not shaped as expected.
    """
    lookup = {normalize_team_name(alias): team_id for alias, team_id in alias_to_id.items()}
    matches = [
        m for m in ApiMatches.model_validate(payload).matches if m.status not in SKIPPED_STATUSES
    ]

    unknown = [
        team.name
        for m in matches
        for team in (m.homeTeam, m.awayTeam)
        if normalize_team_name(team.name) not in lookup
    ]
    if unknown:
        raise UnknownTeamError(unknown)

    return [
        {
            "season": season_label(m.season.startDate),
            "match_date": m.utcDate.astimezone(UK).date(),
            "kickoff_at": m.utcDate,
            "matchday": m.matchday,
            "status": m.status,
            "home_team_id": lookup[normalize_team_name(m.homeTeam.name)],
            "away_team_id": lookup[normalize_team_name(m.awayTeam.name)],
        }
        for m in matches
    ]


async def upsert_fixtures(
    conn: AsyncConnection, records: list[dict[str, object]]
) -> tuple[int, int]:
    """Insert new fixtures and update changed ones. Returns (inserted, updated).

    A played match (goals present) keeps the date from the results CSV; only
    unplayed ones follow the API when a match is rescheduled. Rows where
    nothing would change are not touched, so an unchanged fixture list writes
    nothing and reports (0, 0).
    """
    if not records:
        return 0, 0
    stmt = insert(Match).values(records)
    new = stmt.excluded
    unplayed = Match.home_goals.is_(None)
    upsert = stmt.on_conflict_do_update(
        index_elements=[Match.season, Match.home_team_id, Match.away_team_id],
        set_={
            "match_date": case((unplayed, new.match_date), else_=Match.match_date),
            "kickoff_at": new.kickoff_at,
            "matchday": new.matchday,
            "status": new.status,
        },
        where=or_(
            tuple_(Match.kickoff_at, Match.matchday, Match.status).is_distinct_from(
                tuple_(new.kickoff_at, new.matchday, new.status)
            ),
            and_(unplayed, Match.match_date.is_distinct_from(new.match_date)),
        ),
    ).returning(literal_column("xmax = 0", Boolean).label("inserted"))
    flags = (await conn.execute(upsert)).scalars().all()
    inserted = sum(flags)
    return inserted, len(flags) - inserted


async def store_fixtures(conn: AsyncConnection, payload: Mapping[str, Any]) -> int:
    """Write an API response to the database and bump the data version if anything changed.

    Runs in the caller's transaction, so an unknown team leaves nothing written.
    Returns the number of new teams plus inserted and updated fixtures.
    """
    alias_to_id, new_teams = await seed_teams(conn)
    records = parse_fixtures(payload, alias_to_id)
    inserted, updated = await upsert_fixtures(conn, records)
    log.info(
        "fixtures: %d from the API, %d inserted, %d updated, %d unchanged",
        len(records),
        inserted,
        updated,
        len(records) - inserted - updated,
    )
    changed = new_teams + inserted + updated
    if changed:
        log.info("data version is now %d", await bump_data_version(conn))
    return changed


async def refresh_fixtures(client: FootballDataClient) -> int:
    """Fetch the current season's fixtures and store them. Returns how many rows changed."""
    # Fetch before opening the transaction: no connection is held during retries.
    payload = await client.competition_matches("PL")
    async with engine.begin() as conn:
        return await store_fixtures(conn, payload)
