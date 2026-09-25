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


# --- track record --------------------------------------------------------------------

PredictionStatus = Literal["scored", "pending", "postponed", "late"]
ModelRole = Literal["live", "shadow"]


class TrackedModel(BaseModel):
    """How many of one model's saved predictions are in each state."""

    version: str
    role: ModelRole = Field(
        description="'live' is the model users see; 'shadow' runs alongside it for comparison."
    )
    scored: int = Field(description="Saved before kickoff and the result is in.")
    pending: int = Field(description="Waiting for kickoff or for the result.")
    postponed: int = Field(description="Not counted until the match is played.")
    late: int = Field(description="Saved at or after kickoff, so never counted.")


class TrackRecordScore(BaseModel):
    """One predictor's scores over the compared matches."""

    name: str = Field(description="A model version, or 'bookmaker'.")
    kind: Literal["model", "bookmaker"]
    metrics: Metrics


class RunningLogLoss(BaseModel):
    """Mean log loss over every compared match up to and including this date."""

    match_date: date
    matches: int
    log_loss: dict[str, float] = Field(
        description="Keyed by score name: model versions and 'bookmaker'."
    )


class SavedPrediction(BaseModel):
    """What one model said about a match, frozen when it was saved."""

    model_version: str
    predicted_at: datetime
    status: PredictionStatus
    prediction: Prediction
    correct: bool | None = Field(description="Null unless the prediction is scored.")


class TrackedMatch(BaseModel):
    """A match with saved predictions and, once played, the result and the bookmaker's view."""

    match_id: int
    match_date: date
    kickoff: datetime | None
    home_team: Team
    away_team: Team
    score: MatchScore | None
    actual: Outcome | None
    bookmaker: OutcomeProbabilities | None = Field(
        description="Implied by Bet365's odds with the margin removed, when the odds are known."
    )
    predictions: list[SavedPrediction]


class TrackRecord(BaseModel):
    season: str | None = Field(description="Null when no predictions have been saved yet.")
    live_version: str | None = Field(description="The model users see; null if none is loaded.")
    models: list[TrackedModel]
    compared_matches: int = Field(
        description=(
            "Matches every model predicted before kickoff, with a result and bookmaker odds. "
            "All scores and the running log loss use exactly these matches."
        )
    )
    scores: list[TrackRecordScore]
    running: list[RunningLogLoss] = Field(description="Oldest first, one point per match date.")
    matches: list[TrackedMatch] = Field(description="Newest kickoff first.")
