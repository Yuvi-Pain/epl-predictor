import type { MatchResult } from "../api/client";

export interface RecordPoint {
  match: MatchResult;
  /** Top picks right so far, including this match. */
  correct: number;
  /** Matches so far, including this one. */
  played: number;
}

export interface SeasonRecord {
  points: RecordPoint[];
  correct: number;
  played: number;
  /** How often the home team won: what "always pick the home side" would score. */
  homeWinRate: number;
}

/** The model's running record over matches given oldest first. */
export function seasonRecord(matches: readonly MatchResult[]): SeasonRecord {
  let correct = 0;
  let homeWins = 0;
  const points = matches.map((match, i) => {
    if (match.correct) correct += 1;
    if (match.actual === "home_win") homeWins += 1;
    return { match, correct, played: i + 1 };
  });
  return {
    points,
    correct,
    played: matches.length,
    homeWinRate: matches.length ? homeWins / matches.length : 0,
  };
}
