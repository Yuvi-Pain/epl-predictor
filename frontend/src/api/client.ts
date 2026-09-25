// Typed calls to the backend. Every type here comes from schema.gen.ts, which
// is generated from the backend's OpenAPI schema, so a backend change that
// breaks the frontend shows up as a type error rather than a runtime surprise.
import type { components, paths } from "./schema.gen";

type Schemas = components["schemas"];
export type Team = Schemas["Team"];
export type TeamList = Schemas["TeamList"];
export type PredictResponse = Schemas["PredictResponse"];
export type MatchFeatures = Schemas["MatchFeatures"];
export type MatchList = Schemas["MatchList"];
export type MatchResult = Schemas["MatchResult"];
export type UpcomingFixtures = Schemas["UpcomingFixtures"];
export type UpcomingFixture = Schemas["UpcomingFixture"];
export type ModelInfo = Schemas["ModelInfo"];
export type Metrics = Schemas["Metrics"];
export type SplitMetrics = Schemas["SplitMetrics"];
export type Outcome = MatchResult["actual"];
export type OutcomeProbabilities = Schemas["OutcomeProbabilities"];
export type TrackRecord = Schemas["TrackRecord"];
export type TrackedModel = Schemas["TrackedModel"];
export type TrackedMatch = Schemas["TrackedMatch"];
export type SavedPrediction = Schemas["SavedPrediction"];
export type RunningLogLoss = Schemas["RunningLogLoss"];
export type TrackRecordScore = Schemas["TrackRecordScore"];
export type PredictionStatus = SavedPrediction["status"];

type Query<P extends keyof paths> = paths[P]["get"]["parameters"]["query"];
type Ok<P extends keyof paths> = paths[P]["get"]["responses"][200]["content"]["application/json"];

/** A non-2xx response. `detail` is the backend's own explanation when it gave one. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// The Vite dev server forwards /api/* to the backend (see vite.config.ts).
const API_BASE = "/api";

async function get<P extends keyof paths>(
  path: P,
  query: Query<P>,
  signal?: AbortSignal,
): Promise<Ok<P>> {
  const url = new URL(API_BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  const res = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new ApiError(res.status, await errorDetail(res));
  return (await res.json()) as Ok<P>;
}

async function errorDetail(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Not JSON (a proxy error page, say): fall through to the status text.
  }
  return res.statusText || `Request failed with status ${res.status}`;
}

export const api = {
  teams: (signal?: AbortSignal) => get("/teams", undefined, signal),
  predict: (home: number, away: number, signal?: AbortSignal) =>
    get("/predict", { home, away }, signal),
  matches: (season: string, signal?: AbortSignal) => get("/matches", { season }, signal),
  model: (signal?: AbortSignal) => get("/model", undefined, signal),
  upcoming: (signal?: AbortSignal) => get("/fixtures/upcoming", undefined, signal),
  trackRecord: (signal?: AbortSignal) => get("/track-record", {}, signal),
};
