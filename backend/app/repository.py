"""Read teams and matches from Postgres.

Training (`scripts/train_model.py`) and the API both load matches through
`load_matches`, so the model is always fed the same columns and dtypes.
"""

from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models import Match, Team

# Nullable integers: unplayed matches have no goals or shots.
_NULLABLE_INT_COLUMNS = ("home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target")


@dataclass(frozen=True)
class TeamRow:
    """One row of the teams table."""

    id: int
    name: str


async def load_matches(conn: AsyncConnection) -> pd.DataFrame:
    """Every match in the database as a DataFrame, one row per fixture, oldest first."""
    columns = list(Match.__table__.columns)
    rows = (await conn.execute(select(*columns).order_by(Match.match_date, Match.id))).all()
    df = pd.DataFrame(rows, columns=[c.name for c in columns])
    for col in _NULLABLE_INT_COLUMNS:
        df[col] = df[col].astype("Int16")
    return df


class Repository:
    """Database reads the API needs, over one connection.

    Endpoints receive this through a FastAPI dependency, so tests can swap in an
    in-memory fake with the same methods.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_teams(self) -> list[TeamRow]:
        """All teams, alphabetically."""
        rows = await self._conn.execute(select(Team.id, Team.name).order_by(Team.name))
        return [TeamRow(id=r.id, name=r.name) for r in rows]

    async def get_teams(self, team_ids: list[int]) -> dict[int, TeamRow]:
        """The teams with these ids that exist, keyed by id. Missing ids are left out."""
        rows = await self._conn.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids)))
        return {r.id: TeamRow(id=r.id, name=r.name) for r in rows}

    async def load_matches(self) -> pd.DataFrame:
        """See the module-level `load_matches`."""
        return await load_matches(self._conn)
