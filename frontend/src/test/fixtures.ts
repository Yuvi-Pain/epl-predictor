import type { MatchList, MatchResult, ModelInfo, PredictResponse, TeamList } from "../api/client";

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
