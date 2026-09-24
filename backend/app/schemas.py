"""Pydantic response models for the prediction API."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Outcome = Literal["home_win", "draw", "away_win"]
Split = Literal["train", "validation", "test", "unseen"]


class Team(BaseModel):
    id: int
    name: str


class TeamList(BaseModel):
    teams: list[Team]


class OutcomeProbabilities(BaseModel):
    """Probabilities of each full-time result. They add up to 1."""

    home_win: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away_win: float = Field(ge=0, le=1)


class Prediction(BaseModel):
    """What the model expects from one match."""

    probabilities: OutcomeProbabilities
    most_likely: Outcome


class MatchFeatures(BaseModel):
    """The model's inputs. Form stats average the team's last few league matches
    (any venue). Null means the team has no earlier matches in the data; the
    model fills those with its training average."""

    home_elo: float
    away_elo: float
    home_form_points: float | None
    home_form_goals_for: float | None
    home_form_goals_against: float | None
    home_form_sot_for: float | None
    home_form_sot_against: float | None
    away_form_points: float | None
    away_form_goals_for: float | None
    away_form_goals_against: float | None
    away_form_sot_for: float | None
    away_form_sot_against: float | None


class PredictResponse(BaseModel):
    home_team: Team
    away_team: Team
    as_of: date = Field(description="Only results from before this date were used.")
    prediction: Prediction
    features: MatchFeatures
    model_version: str


class MatchScore(BaseModel):
    home_goals: int
    away_goals: int


class MatchResult(BaseModel):
    """A played match, what the model predicted beforehand, and what happened."""

    match_id: int
    match_date: date
    home_team: Team
    away_team: Team
    score: MatchScore
    actual: Outcome
    prediction: Prediction
    correct: bool = Field(description="Whether the most likely outcome is what happened.")


class MatchList(BaseModel):
    season: str
    model_version: str
    model_split: Split = Field(
        description=(
            "How the model used this season: 'train' means it learned from these results, "
            "so predictions here are optimistic; 'test' and 'unseen' are honest."
        )
    )
    matches: list[MatchResult]


class Metrics(BaseModel):
    accuracy: float
    log_loss: float
    brier: float


class SplitMetrics(BaseModel):
    season: str
    model: Metrics
    baselines: dict[str, Metrics]


class ModelInfo(BaseModel):
    version: str
    trained_at: str
    features: list[str]
    train_seasons: list[str]
    validation: SplitMetrics
    test: SplitMetrics


class ErrorResponse(BaseModel):
    detail: str


class UpcomingFixture(BaseModel):
    """A match not played yet, with the model's prediction."""

    match_id: int
    match_date: date = Field(description="UK date of the match.")
    kickoff: datetime | None = Field(description="Kickoff time in UTC, when known.")
    home_team: Team
    away_team: Team
    prediction: Prediction


class UpcomingFixtures(BaseModel):
    season: str | None = Field(description="Null when there are no upcoming fixtures.")
    matchday: int | None = Field(description="Matchweek number, when the fixture list gives one.")
    model_version: str
    fixtures: list[UpcomingFixture]
