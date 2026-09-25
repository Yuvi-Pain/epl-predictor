import type {
  MatchList,
  MatchResult,
  ModelInfo,
  PredictResponse,
  TeamList,
  TrackRecord,
  UpcomingFixture,
  UpcomingFixtures,
} from "../api/client";

export const teams: TeamList = {
  teams: [
    { id: 1, name: "Arsenal" },
    { id: 2, name: "Aston Villa" },
    { id: 3, name: "Nott'm Forest" },
  ],
};

export const prediction: PredictResponse = {
  home_team: { id: 1, name: "Arsenal" },
  away_team: { id: 2, name: "Aston Villa" },
  as_of: "2026-09-24",
  prediction: {
    probabilities: { home_win: 0.56, draw: 0.24, away_win: 0.2 },
    most_likely: "home_win",
  },
  features: {
    home_elo: 1712.4,
    away_elo: 1630.1,
    home_form_points: 2.2,
    home_form_goals_for: 2.0,
    home_form_goals_against: 0.6,
    home_form_sot_for: 6.2,
    home_form_sot_against: 2.8,
    away_form_points: 1.4,
    away_form_goals_for: 1.2,
    away_form_goals_against: 1.4,
    away_form_sot_for: 4.0,
    away_form_sot_against: null,
  },
  model_version: "v1",
};

function match(
  id: number,
  date: string,
  goals: [number, number],
  actual: MatchResult["actual"],
  mostLikely: MatchResult["actual"],
): MatchResult {
  return {
    match_id: id,
    match_date: date,
    home_team: { id: 1, name: "Arsenal" },
    away_team: { id: 3, name: "Nott'm Forest" },
    score: { home_goals: goals[0], away_goals: goals[1] },
    actual,
    prediction: {
      probabilities: { home_win: 0.5, draw: 0.3, away_win: 0.2 },
      most_likely: mostLikely,
    },
    correct: actual === mostLikely,
  };
}

export const season: MatchList = {
  season: "2026-27",
  model_version: "v1",
  model_split: "unseen",
  matches: [
    match(10, "2026-08-15", [2, 0], "home_win", "home_win"),
    match(11, "2026-08-22", [1, 1], "draw", "home_win"),
    match(12, "2026-08-29", [3, 1], "home_win", "home_win"),
    match(13, "2026-08-29", [0, 1], "away_win", "home_win"),
  ],
};

export const modelInfo: ModelInfo = {
  version: "v1",
  trained_at: "2026-09-01T10:00:00+00:00",
  features: ["home_elo", "away_elo"],
  train_seasons: ["2015-16", "2016-17", "2023-24"],
  validation: {
    season: "2024-25",
    model: { accuracy: 0.52, log_loss: 1.0, brier: 0.6 },
    baselines: { "always home win": { accuracy: 0.45, log_loss: 19.8, brier: 1.1 } },
  },
  test: {
    season: "2025-26",
    model: { accuracy: 0.51, log_loss: 1.004, brier: 0.598 },
    baselines: {
      "always home win": { accuracy: 0.43, log_loss: 20.1, brier: 1.14 },
      "training base rates": { accuracy: 0.43, log_loss: 1.07, brier: 0.64 },
      "bookmaker (Bet365)": { accuracy: 0.53, log_loss: 0.982, brier: 0.586 },
    },
  },
};

function upcomingFixture(
  id: number,
  date: string,
  kickoff: string | null,
  home: [number, string],
  away: [number, string],
  probabilities: UpcomingFixture["prediction"]["probabilities"],
  most_likely: UpcomingFixture["prediction"]["most_likely"],
): UpcomingFixture {
  return {
    match_id: id,
    match_date: date,
    kickoff,
    home_team: { id: home[0], name: home[1] },
    away_team: { id: away[0], name: away[1] },
    prediction: { probabilities, most_likely },
  };
}

// Kick-offs in UTC; in October the UK is on BST, one hour ahead.
export const upcoming: UpcomingFixtures = {
  season: "2026-27",
  matchday: 6,
  model_version: "v2",
  fixtures: [
    upcomingFixture(
      101,
      "2026-10-10",
      "2026-10-10T11:30:00Z",
      [1, "Arsenal"],
      [2, "Aston Villa"],
      { home_win: 0.63, draw: 0.22, away_win: 0.15 },
      "home_win",
    ),
    upcomingFixture(
      102,
      "2026-10-10",
      "2026-10-10T14:00:00Z",
      [3, "Nott'm Forest"],
      [1, "Arsenal"],
      { home_win: 0.24, draw: 0.27, away_win: 0.49 },
      "away_win",
    ),
    upcomingFixture(
      103,
      "2026-10-12",
      null,
      [2, "Aston Villa"],
      [3, "Nott'm Forest"],
      { home_win: 0.45, draw: 0.3, away_win: 0.25 },
      "home_win",
    ),
  ],
};

const probs = (home_win: number, draw: number, away_win: number) => ({
  probabilities: { home_win, draw, away_win },
  most_likely: (home_win >= draw && home_win >= away_win
    ? "home_win"
    : draw >= away_win
      ? "draw"
      : "away_win") as "home_win" | "draw" | "away_win",
});

export const trackRecord: TrackRecord = {
  season: "2026-27",
  live_version: "v2",
  models: [
    { version: "v2", role: "live", scored: 2, pending: 1, postponed: 1, late: 0 },
    { version: "v1", role: "shadow", scored: 2, pending: 1, postponed: 1, late: 0 },
  ],
  compared_matches: 2,
  scores: [
    { name: "v2", kind: "model", metrics: { accuracy: 0.5, log_loss: 1.151, brier: 0.68 } },
    { name: "v1", kind: "model", metrics: { accuracy: 0.5, log_loss: 1.060, brier: 0.63 } },
    { name: "bookmaker", kind: "bookmaker", metrics: { accuracy: 1, log_loss: 0.95, brier: 0.55 } },
  ],
  running: [
    { match_date: "2026-09-19", matches: 1, log_loss: { v2: 0.693, v1: 0.916, bookmaker: 0.73 } },
    { match_date: "2026-09-20", matches: 2, log_loss: { v2: 1.151, v1: 1.06, bookmaker: 0.95 } },
  ],
  matches: [
    {
      match_id: 23,
      match_date: "2026-09-27",
      kickoff: "2026-09-27T13:00:00Z",
      home_team: { id: 3, name: "Nott'm Forest" },
      away_team: { id: 1, name: "Arsenal" },
      score: null,
      actual: null,
      bookmaker: null,
      predictions: [
        { model_version: "v2", predicted_at: "2026-09-26T13:00:00Z", status: "pending", prediction: probs(0.3, 0.3, 0.4), correct: null },
        { model_version: "v1", predicted_at: "2026-09-26T13:00:00Z", status: "pending", prediction: probs(0.35, 0.3, 0.35), correct: null },
      ],
    },
    {
      match_id: 22,
      match_date: "2026-09-21",
      kickoff: "2026-09-21T19:00:00Z",
      home_team: { id: 2, name: "Aston Villa" },
      away_team: { id: 3, name: "Nott'm Forest" },
      score: null,
      actual: null,
      bookmaker: null,
      predictions: [
        { model_version: "v2", predicted_at: "2026-09-20T19:00:00Z", status: "postponed", prediction: probs(0.5, 0.3, 0.2), correct: null },
        { model_version: "v1", predicted_at: "2026-09-20T19:00:00Z", status: "postponed", prediction: probs(0.45, 0.3, 0.25), correct: null },
      ],
    },
    {
      match_id: 21,
      match_date: "2026-09-20",
      kickoff: "2026-09-20T14:00:00Z",
      home_team: { id: 3, name: "Nott'm Forest" },
      away_team: { id: 2, name: "Aston Villa" },
      score: { home_goals: 0, away_goals: 1 },
      actual: "away_win",
      bookmaker: { home_win: 0.3, draw: 0.3, away_win: 0.4 },
      predictions: [
        { model_version: "v2", predicted_at: "2026-09-19T14:00:00Z", status: "scored", prediction: probs(0.5, 0.3, 0.2), correct: false },
        { model_version: "v1", predicted_at: "2026-09-19T14:00:00Z", status: "scored", prediction: probs(0.4, 0.3, 0.3), correct: false },
      ],
    },
    {
      match_id: 20,
      match_date: "2026-09-19",
      kickoff: "2026-09-19T14:00:00Z",
      home_team: { id: 1, name: "Arsenal" },
      away_team: { id: 2, name: "Aston Villa" },
      score: { home_goals: 2, away_goals: 0 },
      actual: "home_win",
      bookmaker: { home_win: 0.52, draw: 0.28, away_win: 0.2 },
      predictions: [
        { model_version: "v2", predicted_at: "2026-09-18T14:00:00Z", status: "scored", prediction: probs(0.5, 0.3, 0.2), correct: true },
        { model_version: "v1", predicted_at: "2026-09-18T14:00:00Z", status: "scored", prediction: probs(0.4, 0.3, 0.3), correct: true },
      ],
    },
  ],
};
