"""Database tables for teams, match results and saved predictions."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
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
    # From the football-data.org fixture list; NULL for matches only in the results CSVs.
    matchday: Mapped[int | None] = mapped_column(SmallInteger)
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # football-data.org's status: SCHEDULED, TIMED, POSTPONED, FINISHED, ...
    status: Mapped[str | None] = mapped_column(String(16))

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])


class DataVersion(Base):
    """A counter bumped whenever the history loader or fixture refresh changes teams or matches.

    Exactly one row (id 1). The API puts the counter in its cache keys, so a
    bump makes every cached response built from older data unreachable.
    """

    __tablename__ = "data_version"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger)


class Prediction(Base):
    """A model's prediction for one match, saved by the worker before kickoff.

    One row per (match, model version), and rows are frozen: a trigger (see the
    migration) rejects every UPDATE and DELETE, and the worker inserts with
    ON CONFLICT DO NOTHING, so the first prediction saved is the one scored.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("match_id", "model_version"),
        CheckConstraint(
            "p_home BETWEEN 0 AND 1 AND p_draw BETWEEN 0 AND 1 AND p_away BETWEEN 0 AND 1",
            name="probabilities_in_range",
        ),
        CheckConstraint("abs(p_home + p_draw + p_away - 1) < 1e-6", name="probabilities_sum_to_1"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    model_version: Mapped[str] = mapped_column(String(16))
    p_home: Mapped[float] = mapped_column(Double)
    p_draw: Mapped[float] = mapped_column(Double)
    p_away: Mapped[float] = mapped_column(Double)
    # Postgres sets this at insert time; callers never pass it, so it cannot be backdated.
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
