"""Database tables for teams and match results."""

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    Double,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Team(Base):
    """A club, stored once under its canonical name (e.g. "Manchester United")."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

    aliases: Mapped[list["TeamAlias"]] = relationship(back_populates="team")


class TeamAlias(Base):
    """One spelling of a team name used by some data source (e.g. "Man United").

    Every incoming team name is resolved through this table, so the canonical
    name is also stored here as an alias of itself.
    """

    __tablename__ = "team_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)

    team: Mapped[Team] = relationship(back_populates="aliases")


class Match(Base):
    """One league fixture. Goals and shots are NULL until the match is played."""

    __tablename__ = "matches"
    __table_args__ = (
        # A pairing happens exactly once per season (home and away are separate fixtures).
        # This is also the conflict target the history loader upserts on.
        UniqueConstraint("season", "home_team_id", "away_team_id"),
        CheckConstraint("home_team_id <> away_team_id", name="distinct_teams"),
        CheckConstraint("home_goals >= 0 AND away_goals >= 0", name="non_negative_goals"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    season: Mapped[str] = mapped_column(String(7))  # "2024-25"
    match_date: Mapped[date] = mapped_column(Date, index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    home_goals: Mapped[int | None] = mapped_column(SmallInteger)
    away_goals: Mapped[int | None] = mapped_column(SmallInteger)
    home_shots: Mapped[int | None] = mapped_column(SmallInteger)
    away_shots: Mapped[int | None] = mapped_column(SmallInteger)
    home_shots_on_target: Mapped[int | None] = mapped_column(SmallInteger)
    away_shots_on_target: Mapped[int | None] = mapped_column(SmallInteger)
    # Bet365 pre-match decimal odds; NULL when the source file has none.
    odds_home: Mapped[float | None] = mapped_column(Double)
    odds_draw: Mapped[float | None] = mapped_column(Double)
    odds_away: Mapped[float | None] = mapped_column(Double)

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
