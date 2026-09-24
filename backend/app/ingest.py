"""Database writes shared by the history loader and the fixture refresh."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import DataVersion, Team, TeamAlias
from app.teams import KNOWN_TEAMS


async def seed_teams(conn: AsyncConnection) -> tuple[dict[str, int], int]:
    """Upsert KNOWN_TEAMS into teams/team_aliases.

    Returns the alias -> team id map and how many new teams were inserted.
    """
    new_teams = (
        await conn.execute(
            insert(Team)
            .values([{"name": name} for name in KNOWN_TEAMS])
            .on_conflict_do_nothing(index_elements=[Team.name])
            .returning(Team.id)
        )
    ).all()
    team_ids = dict((await conn.execute(select(Team.name, Team.id))).tuples().all())

    alias_rows = [
        {"alias": alias, "team_id": team_ids[name]}
        for name, others in KNOWN_TEAMS.items()
        for alias in [name, *others]
    ]
    stmt = insert(TeamAlias).values(alias_rows)
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[TeamAlias.alias], set_={"team_id": stmt.excluded.team_id}
        )
    )
    # Read back the whole table, so aliases added by other means are honoured too.
    aliases = dict((await conn.execute(select(TeamAlias.alias, TeamAlias.team_id))).tuples().all())
    return aliases, len(new_teams)


async def bump_data_version(conn: AsyncConnection) -> int:
    """Increment the data version and return the new value.

    The API puts this number in its cache keys, so bumping it (in the same
    transaction as the match writes) retires every cached response at once.
    """
    stmt = (
        update(DataVersion)
        .where(DataVersion.id == 1)
        .values(version=DataVersion.version + 1)
        .returning(DataVersion.version)
    )
    return (await conn.execute(stmt)).scalar_one()
