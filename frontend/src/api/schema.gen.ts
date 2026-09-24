// Generated from the backend's OpenAPI schema by scripts/gen-api-types.mjs.
// Do not edit by hand: run `npm run gen:api` after changing the API.

export interface paths {
    "/teams": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Teams
         * @description Every team in the database, alphabetically. Use the ids with /predict.
         */
        get: operations["list_teams_teams_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/predict": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Predict
         * @description Win/draw/loss probabilities for a match between two teams.
         *
         *     Features are built from results before `as_of` only, with the same code
         *     used in training.
         */
        get: operations["predict_predict_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/matches": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Matches
         * @description Played matches in a season, oldest first, each with the model's pre-match prediction.
         *
         *     Each prediction uses only results from before that match's date, exactly as
         *     in training, so it is what the model would have said beforehand.
         */
        get: operations["list_matches_matches_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/fixtures/upcoming": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Upcoming Fixtures
         * @description The next matchweek's fixtures, soonest first, each with the model's prediction.
         *
         *     Fixtures come from football-data.org via the worker. An empty list means
         *     none are stored yet (or the season is over).
         */
        get: operations["upcoming_fixtures_fixtures_upcoming_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/model": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Model Info
         * @description The loaded model's version, training date, and validation and test scores
         *     alongside the baselines it was compared with.
         */
        get: operations["model_info_model_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Report whether the API can reach Postgres and Redis. 503 if either is down.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** ErrorResponse */
        ErrorResponse: {
            /** Detail */
            detail: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * MatchFeatures
         * @description The model's inputs. Form stats average the team's last few league matches
         *     (any venue). Null means the team has no earlier matches in the data; the
         *     model fills those with its training average.
         */
        MatchFeatures: {
            /** Home Elo */
            home_elo: number;
            /** Away Elo */
            away_elo: number;
            /** Home Form Points */
            home_form_points: number | null;
            /** Home Form Goals For */
            home_form_goals_for: number | null;
            /** Home Form Goals Against */
            home_form_goals_against: number | null;
            /** Home Form Sot For */
            home_form_sot_for: number | null;
            /** Home Form Sot Against */
            home_form_sot_against: number | null;
            /** Away Form Points */
            away_form_points: number | null;
            /** Away Form Goals For */
            away_form_goals_for: number | null;
            /** Away Form Goals Against */
            away_form_goals_against: number | null;
            /** Away Form Sot For */
            away_form_sot_for: number | null;
            /** Away Form Sot Against */
            away_form_sot_against: number | null;
        };
        /** MatchList */
        MatchList: {
            /** Season */
            season: string;
            /** Model Version */
            model_version: string;
            /**
             * Model Split
             * @description How the model used this season: 'train' means it learned from these results, so predictions here are optimistic; 'test' and 'unseen' are honest.
             * @enum {string}
             */
            model_split: "train" | "validation" | "test" | "unseen";
            /** Matches */
            matches: components["schemas"]["MatchResult"][];
        };
        /**
         * MatchResult
         * @description A played match, what the model predicted beforehand, and what happened.
         */
        MatchResult: {
            /** Match Id */
            match_id: number;
            /**
             * Match Date
             * Format: date
             */
            match_date: string;
            home_team: components["schemas"]["Team"];
            away_team: components["schemas"]["Team"];
            score: components["schemas"]["MatchScore"];
            /**
             * Actual
             * @enum {string}
             */
            actual: "home_win" | "draw" | "away_win";
            prediction: components["schemas"]["Prediction"];
            /**
             * Correct
             * @description Whether the most likely outcome is what happened.
             */
            correct: boolean;
        };
        /** MatchScore */
        MatchScore: {
            /** Home Goals */
            home_goals: number;
            /** Away Goals */
            away_goals: number;
        };
        /** Metrics */
        Metrics: {
            /** Accuracy */
            accuracy: number;
            /** Log Loss */
            log_loss: number;
            /** Brier */
            brier: number;
        };
        /** ModelInfo */
        ModelInfo: {
            /** Version */
            version: string;
            /** Trained At */
            trained_at: string;
            /** Features */
            features: string[];
            /** Train Seasons */
            train_seasons: string[];
            validation: components["schemas"]["SplitMetrics"];
            test: components["schemas"]["SplitMetrics"];
        };
        /**
         * OutcomeProbabilities
         * @description Probabilities of each full-time result. They add up to 1.
         */
        OutcomeProbabilities: {
            /** Home Win */
            home_win: number;
            /** Draw */
            draw: number;
            /** Away Win */
            away_win: number;
        };
        /** PredictResponse */
        PredictResponse: {
            home_team: components["schemas"]["Team"];
            away_team: components["schemas"]["Team"];
            /**
             * As Of
             * Format: date
             * @description Only results from before this date were used.
             */
            as_of: string;
            prediction: components["schemas"]["Prediction"];
            features: components["schemas"]["MatchFeatures"];
            /** Model Version */
            model_version: string;
        };
        /**
         * Prediction
         * @description What the model expects from one match.
         */
        Prediction: {
            probabilities: components["schemas"]["OutcomeProbabilities"];
            /**
             * Most Likely
             * @enum {string}
             */
            most_likely: "home_win" | "draw" | "away_win";
        };
        /** SplitMetrics */
        SplitMetrics: {
            /** Season */
            season: string;
            model: components["schemas"]["Metrics"];
            /** Baselines */
            baselines: {
                [key: string]: components["schemas"]["Metrics"];
            };
        };
        /** Team */
        Team: {
            /** Id */
            id: number;
            /** Name */
            name: string;
        };
        /** TeamList */
        TeamList: {
            /** Teams */
            teams: components["schemas"]["Team"][];
        };
        /**
         * UpcomingFixture
         * @description A match not played yet, with the model's prediction.
         */
        UpcomingFixture: {
            /** Match Id */
            match_id: number;
            /**
             * Match Date
             * Format: date
             * @description UK date of the match.
             */
            match_date: string;
            /**
             * Kickoff
             * @description Kickoff time in UTC, when known.
             */
            kickoff: string | null;
            home_team: components["schemas"]["Team"];
            away_team: components["schemas"]["Team"];
            prediction: components["schemas"]["Prediction"];
        };
        /** UpcomingFixtures */
        UpcomingFixtures: {
            /**
             * Season
             * @description Null when there are no upcoming fixtures.
             */
            season: string | null;
            /**
             * Matchday
             * @description Matchweek number, when the fixture list gives one.
             */
            matchday: number | null;
            /** Model Version */
            model_version: string;
            /** Fixtures */
            fixtures: components["schemas"]["UpcomingFixture"][];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_teams_teams_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HIT if served from Redis, MISS if built for this request. */
                    "X-Cache"?: unknown;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TeamList"];
                };
            };
        };
    };
    predict_predict_get: {
        parameters: {
            query: {
                /** @description Home team id, from /teams. */
                home: number;
                /** @description Away team id, from /teams. */
                away: number;
                /** @description Predict as if the match were on this date. Defaults to today. */
                as_of?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HIT if served from Redis, MISS if built for this request. */
                    "X-Cache"?: unknown;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PredictResponse"];
                };
            };
            /** @description Home and away are the same team. */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description A team id does not exist. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description No usable model file is loaded. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_matches_matches_get: {
        parameters: {
            query?: {
                /** @description e.g. "2026-27". Defaults to the latest season. */
                season?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HIT if served from Redis, MISS if built for this request. */
                    "X-Cache"?: unknown;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MatchList"];
                };
            };
            /** @description No matches for that season. */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
            /** @description No usable model file is loaded. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    upcoming_fixtures_fixtures_upcoming_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HIT if served from Redis, MISS if built for this request. */
                    "X-Cache"?: unknown;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpcomingFixtures"];
                };
            };
            /** @description No usable model file is loaded. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    model_info_model_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ModelInfo"];
                };
            };
            /** @description No usable model file is loaded. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
}
