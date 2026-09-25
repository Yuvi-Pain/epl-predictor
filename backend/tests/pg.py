"""Helpers for tests that run against the real Postgres at $DATABASE_URL.

Locally these tests skip when Postgres is not reachable. In CI, where
REQUIRE_POSTGRES=1, an unreachable database fails them instead, so a broken
service container can never turn them into silent skips.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool


def postgres_unreachable(exc: Exception) -> None:
    """Skip the test, or fail it when REQUIRE_POSTGRES is set. Never returns."""
    message = f"Postgres not reachable: {exc}"
    if os.environ.get("REQUIRE_POSTGRES") == "1":
        pytest.fail(f"{message} (REQUIRE_POSTGRES=1)")
    pytest.skip(message)


def run_in_rollback(test: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    """Run `test` in a transaction on the real database, then roll everything back."""

    async def go() -> None:
        engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
        try:
            try:
                conn = await engine.connect()
            except Exception as exc:  # no database here: these tests need one
                postgres_unreachable(exc)
            try:
                async with conn.begin() as tx:
                    await test(conn)
                    await tx.rollback()
            finally:
                await conn.close()
        finally:
            await engine.dispose()

    asyncio.run(go())
