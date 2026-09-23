"""Load historical Premier League results from football-data.co.uk into Postgres.

Run inside the backend container:

    docker compose exec backend python -m scripts.load_history
    docker compose exec backend python -m scripts.load_history --refresh   # re-download CSVs

Safe to run repeatedly: teams, aliases and matches are all upserted, so a rerun
updates changed rows and never creates duplicates. Downloaded CSVs are cached in
backend/data/raw/ and reused unless --refresh is given. The current season's
file grows as matches are played, so it is always downloaded again.
"""

import argparse
import asyncio
import logging
from pathlib import Path

import httpx
from sqlalchemy import Boolean, func, literal_column, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import engine
from app.football_data import (
    ODDS_COLUMNS,
    STAT_COLUMNS,
    clean_results,
    read_raw_csv,
    season_code,
    to_records,
)
from app.models import DataVersion, Match, Team, TeamAlias
from app.teams import KNOWN_TEAMS

log = logging.getLogger("load_history")

SEASONS = [f"20{y:02d}-{y + 1:02d}" for y in range(15, 27)]  # 2015-16 .. 2026-27
# In progress: football-data only lists played matches, so this file is never final.
CURRENT_SEASON = SEASONS[-1]
URL_TEMPLATE = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
EXPECTED_MATCHES_PER_SEASON = 380  # 20 teams, each plays the other 19 home and away


async def download_csv(client: httpx.AsyncClient, season: str, refresh: bool) -> Path:
    """Return the cached CSV for a season, downloading it first if needed.

    The file is written to a temporary name and renamed at the end, so an
    interrupted download never leaves a half-written file in the cache.
    """
    code = season_code(season)
    path = RAW_DIR / f"E0_{code}.csv"
    if path.exists() and not refresh and season != CURRENT_SEASON:
        log.info("%s: using cached %s", season, path.name)
        return path

    url = URL_TEMPLATE.format(code=code)
    log.info("%s: downloading %s", season, url)
    response = await client.get(url)
    response.raise_for_status()
    # The site answers some bad URLs with an HTML page; don't cache that as a CSV.
    if not response.content.removeprefix(b"\xef\xbb\xbf").startswith(b"Div,"):
        raise ValueError(f"{url} did not return a football-data CSV")

    tmp = path.with_suffix(".csv.part")
    tmp.write_bytes(response.content)
    tmp.replace(path)
    return path


async def download_all(refresh: bool) -> dict[str, Path]:
    """Fetch (or reuse) the CSV for every season in SEASONS."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        paths = await asyncio.gather(*(download_csv(client, s, refresh) for s in SEASONS))
    return dict(zip(SEASONS, paths, strict=True))


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


async def upsert_matches(
    conn: AsyncConnection, records: list[dict[str, object]]
) -> tuple[int, int]:
    """Insert new fixtures and update existing ones. Returns (inserted, updated).

    Rows whose values have not changed are left alone (the WHERE clause), so a
    rerun with the same data writes nothing and reports 0 inserted, 0 updated.
    """
    stmt = insert(Match).values(records)
    updatable = ["match_date", *STAT_COLUMNS, *ODDS_COLUMNS]
    upsert = stmt.on_conflict_do_update(
        index_elements=[Match.season, Match.home_team_id, Match.away_team_id],
        set_={col: stmt.excluded[col] for col in updatable},
        where=tuple_(*(Match.__table__.c[c] for c in updatable)).is_distinct_from(
            tuple_(*(stmt.excluded[c] for c in updatable))
        ),
    ).returning(
        # Postgres trick: xmax is 0 on a freshly inserted row, non-zero on an updated one.
        literal_column("xmax = 0", Boolean).label("inserted")
    )
    flags = (await conn.execute(upsert)).scalars().all()
    inserted = sum(flags)
    return inserted, len(flags) - inserted


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


async def print_sanity_check(conn: AsyncConnection) -> None:
    """Print matches and goals per season, flagging seasons without 380 matches."""
    query = (
        select(
            Match.season,
            func.count().label("matches"),
            func.count(Match.home_goals).label("played"),
            func.sum(Match.home_goals + Match.away_goals).label("goals"),
        )
        .group_by(Match.season)
        .order_by(Match.season)
    )
    rows = (await conn.execute(query)).all()

    print(f"\n{'season':<9}{'matches':>8}{'played':>8}{'goals':>7}")
    for season, matches, played, goals in rows:
        if matches == EXPECTED_MATCHES_PER_SEASON:
            flag = ""
        elif season == CURRENT_SEASON:
            flag = "  (in progress)"
        else:
            flag = f"  <-- expected {EXPECTED_MATCHES_PER_SEASON}"
        print(f"{season:<9}{matches:>8}{played:>8}{goals or 0:>7}{flag}")
    total = sum(r.matches for r in rows)
    print(
        f"{'total':<9}{total:>8}{sum(r.played for r in rows):>8}{sum(r.goals or 0 for r in rows):>7}"
    )


async def main(refresh: bool) -> None:
    paths = await download_all(refresh)
    try:
        # One transaction: if any season fails to clean or insert, nothing is written.
        async with engine.begin() as conn:
            alias_to_id, changed = await seed_teams(conn)
            for season, path in paths.items():
                cleaned = clean_results(read_raw_csv(path), season, alias_to_id)
                inserted, updated = await upsert_matches(conn, to_records(cleaned))
                changed += inserted + updated
                log.info(
                    "%s: %d rows in file, %d inserted, %d updated, %d unchanged",
                    season,
                    len(cleaned),
                    inserted,
                    updated,
                    len(cleaned) - inserted - updated,
                )
            if changed:
                log.info("data version is now %d", await bump_data_version(conn))
            else:
                log.info("no teams or matches changed; data version left as is")
            await print_sanity_check(conn)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load historical EPL results into Postgres.")
    parser.add_argument("--refresh", action="store_true", help="re-download CSVs even if cached")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise
    asyncio.run(main(args.refresh))
