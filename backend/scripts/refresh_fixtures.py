"""Fetch the Premier League fixture list from football-data.org into Postgres once.

The worker service does this on a schedule; run it by hand with:

    docker compose exec backend python -m scripts.refresh_fixtures

Needs FOOTBALL_DATA_API_KEY in .env. Safe to rerun: fixtures are upserted.
"""

import asyncio
import logging

from app.db import engine
from app.fixtures import refresh_fixtures
from app.football_data_org import FootballDataClient, api_key_from_env


async def main() -> None:
    try:
        async with FootballDataClient(api_key_from_env()) as client:
            await refresh_fixtures(client)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
