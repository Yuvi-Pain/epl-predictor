// TanStack Query hooks: one per endpoint. Components call these and never
// fetch directly, so caching and retries are configured in one place.
import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

// Results change at most a few times a week, and the model only on a restart,
// so data stays fresh for a while and is kept in memory after a page is left.
const MINUTE = 60_000;

export const queryKeys = {
  teams: ["teams"] as const,
  predict: (home: number, away: number) => ["predict", home, away] as const,
  matches: (season: string) => ["matches", season] as const,
  model: ["model"] as const,
};

export function useTeams() {
  return useQuery({
    queryKey: queryKeys.teams,
    queryFn: ({ signal }) => api.teams(signal),
    staleTime: 60 * MINUTE,
  });
}

/** Only runs once two different teams are chosen. */
export function usePrediction(home: number | null, away: number | null) {
  const ready = home !== null && away !== null && home !== away;
  return useQuery({
    queryKey: queryKeys.predict(home ?? 0, away ?? 0),
    queryFn: ({ signal }) => api.predict(home!, away!, signal),
    enabled: ready,
    staleTime: 10 * MINUTE,
  });
}

export function useSeasonMatches(season: string) {
  return useQuery({
    queryKey: queryKeys.matches(season),
    queryFn: ({ signal }) => api.matches(season, signal),
    staleTime: 10 * MINUTE,
  });
}

export function useModelInfo() {
  return useQuery({
    queryKey: queryKeys.model,
    queryFn: ({ signal }) => api.model(signal),
    staleTime: 60 * MINUTE,
  });
}
