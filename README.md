# EPL Predictor

Premier League match predictions: a FastAPI backend with an Elo and form model, a React + Vite + TypeScript frontend, Postgres and Redis, all run with Docker Compose.

## Run it

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the Compose plugin).

```bash
cp .env.example .env     
docker compose up --build
```

The first start takes a few minutes while images download and dependencies install.

When it's ready:

| What | URL |
|------|-----|
| Frontend | http://localhost:5173 |
| Backend health check | http://localhost:8000/health |
| Backend API docs | http://localhost:8000/docs |

Check that the services are up:

```bash
docker compose ps
```

The postgres, redis, backend and frontend rows should say `(healthy)`; the worker has no health check and just says `Up`. Stop everything with `Ctrl+C`, or `docker compose down` from another terminal. Add `-v` to `down` to also delete the database data.

## Backend tests

```bash
docker compose exec backend pytest
```

## Database migrations (Alembic)

Migrations run automatically when the backend starts. To create a new one after adding a model that subclasses `Base` in `backend/app/db.py`:

```bash
docker compose exec backend alembic revision --autogenerate -m "describe the change"
```

The new file appears in `backend/alembic/versions/`. Commit it.

## Load historical results

Downloads Premier League results for 2015-16 through the current season, 2026-27, from [football-data.co.uk](https://www.football-data.co.uk/) and upserts them into the `teams`, `team_aliases` and `matches` tables:

```bash
docker compose exec backend python -m scripts.load_history
```

It ends with a per-season table of match and goal counts; every finished season should show 380 matches, and the current one is marked `(in progress)`. It is safe to rerun: existing matches are updated in place, never duplicated. Downloaded CSVs are cached in `backend/data/raw/` (git-ignored); pass `--refresh` to download them again. The current season's file grows as matches are played, so it is always downloaded fresh: rerun the loader after each round to pick up new results.

If it stops with `Unknown team names`, a data source used a spelling we haven't seen. Add it to `backend/app/teams.py` and rerun. The `worker` service (below) reruns this daily.

## Live fixtures and the worker

The fixture list comes from the [football-data.org](https://www.football-data.org/) v4 API. Get a free key at https://www.football-data.org/client/register and put it in `.env`:

```bash
FOOTBALL_DATA_API_KEY=your-key
```

The key is only read from the environment and sent in the `X-Auth-Token` header; it is never logged.

The `worker` service in `docker-compose.yml` runs three scheduled jobs from the backend image (`backend/scripts/worker.py`):

| Job | Every | Does |
|-----|-------|------|
| fixtures | `FIXTURES_REFRESH_HOURS` (default 6) | Fetches the current season's fixtures (one request) and upserts them as matches with no goals, plus their matchday, kick-off time and status |
| history | `HISTORY_REFRESH_HOURS` (default 24) | Reruns the history loader, which fills in results as football-data.co.uk publishes them |
| predictions | `PREDICTIONS_REFRESH_HOURS` (default 1) | Saves every tracked model's prediction for fixtures kicking off within `PREDICTION_LEAD_HOURS` (default 24). See [Track record](#track-record) |

All run once when the worker starts, in that order. Each bumps the data version when it changes anything, so the API's cached responses are rebuilt. A failed job is logged and retried after 15 minutes; the worker keeps running. Without an API key the fixtures and predictions jobs are skipped with a warning (predictions need kick-off times, which only the fixture list has) and the history job still runs.

Results only ever come from the CSVs, which also have the shots the model needs. The fixture refresh never writes goals, and for a played match it keeps the CSV's date. Team names go through the same alias table as the CSVs; if the API uses a new spelling, the refresh fails with `Unknown team names`, writes nothing, and you add the name to `backend/app/teams.py`.

The free plan allows 10 requests a minute. The client keeps a sliding one-minute window of its own requests, and also pauses when the API's `X-Requests-Available-Minute` header reaches 0. A `429` waits for the reset time the API sends; `5xx` errors, timeouts and dropped connections are retried with exponential backoff (2 s, 4 s, 8 s, 16 s, capped at 60 s, each randomly shortened by up to half) for up to 5 attempts. Other errors, such as a bad key (`403`), fail straight away.

Run either job by hand:

```bash
docker compose exec backend python -m scripts.refresh_fixtures
docker compose exec backend python -m scripts.load_history
```

Watch the worker with `docker compose logs -f worker`.

## Train the model

After loading history, train a match outcome model (home win / draw / away win):

```bash
docker compose exec backend python -m scripts.train_model
```

It builds pre-match features from matches played on earlier dates only: Elo ratings, and average points, goals and shots on target over each team's last 5 matches. It then fits a multinomial logistic regression. Seasons are split by time: train on 2015-16 to 2023-24, make every choice on 2024-25 (validation), and score 2025-26 (test) once at the end. The script prints accuracy, log loss and Brier score for the model, the v1 model and three baselines: always home win, training-set outcome rates, and Bet365's odds with the margin removed.

There are two feature sets (`--features`, default `v2`):

- **v1** uses each team's own Elo and form as separate features. Because home and away Elo get separate weights, two equal teams get a different home advantage at different rating levels.
- **v2** uses home-minus-away differences (`elo_diff`, `form_*_diff`), so only the gap between the teams matters and the home advantage is a single constant. It also searches the Elo K-factor, how far ratings are pulled back to the average between seasons (0–40%), the promoted teams' starting rating, and whether to keep the form-points feature, all on the validation season.

| 2025-26 test season (380 matches) | accuracy | log loss | Brier |
|---|---|---|---|
| v1 | 0.474 | 1.0413 | 0.6277 |
| v2 | 0.479 | 1.0520 | 0.6334 |
| Bookmaker (Bet365) | 0.489 | 1.0185 | 0.6115 |

The model is saved to `backend/models/match_outcome_logreg_<version>.joblib` (git-ignored). Pass `--version` to name it differently, or `--force` to overwrite.

## Prediction API

The backend loads the model once at startup (`MODEL_VERSION` in `.env`, default `v2`; set `MODEL_VERSION=v1` to serve the old one). After training or switching versions, restart it: `docker compose restart backend`.

| Endpoint | Returns |
|----------|---------|
| `GET /teams` | Every team with its id |
| `GET /predict?home=1&away=17` | Home win / draw / away win probabilities and the features used. Optional `as_of=2026-10-04` predicts as if the match were on that date (default today); only earlier results are used |
| `GET /matches?season=2026-27` | Each played match in the season with the model's pre-match prediction and the actual result. `model_split` says whether the model trained on that season (then the predictions flatter it) |
| `GET /fixtures/upcoming` | The next matchweek's unplayed fixtures, soonest first, each with win/draw/loss probabilities. An empty list (not an error) if no fixtures are stored yet |
| `GET /model` | Model version, training time, and validation/test scores next to the baselines |
| `GET /track-record` | Predictions saved before kickoff and how they scored: per-model and bookmaker accuracy, log loss and Brier on the same matches, a running log loss per match date, and every saved prediction with its status. Optional `season=2026-27` (default: latest with predictions). Works without a model loaded |

Errors: `400` if home and away are the same team, `404` for an unknown team id or a season with no matches, `422` for malformed parameters, `503` from `/predict`, `/matches`, `/fixtures/upcoming` and `/model` when no model file is loaded (`/health` and `/teams` still work). Full schemas are at http://localhost:8000/docs.

Live predictions build features with the same `build_features` function used in training: the hypothetical match is added to the history and featurised alongside it. Elo settings and the form window are read from the model file, not the code defaults.

## Track record

`/matches` and the This season page recompute the model's predictions from history, so they can change when the model changes. The track record can't: it only uses predictions saved before kickoff.

- **Saving.** The worker's predictions job saves one row per (match, model version) in the `predictions` table for fixtures that are still scheduled and kick off within the next `PREDICTION_LEAD_HOURS`. `TRACKED_MODEL_VERSIONS` (default `v2,v1`) lists the models: `v2` is live (what users see), `v1` runs in **shadow mode** (saved and scored the same way, never shown). Postgres stamps `predicted_at` itself and the insert only keeps rows whose match has not kicked off by Postgres's clock.
- **Frozen.** A trigger rejects every `UPDATE` and `DELETE` on `predictions`, and a second save for the same match and model is ignored (`ON CONFLICT DO NOTHING`), so the first prediction is the one scored. To remove the table entirely, `alembic downgrade d31a7c5e9f82`.
- **Scoring.** A prediction is *scored* once the result is in, *pending* before that, *postponed* while the match is postponed or suspended (it counts once the rescheduled match is played), and *late* if it was saved at or after kickoff (possible only if kickoff is later moved earlier; never counted). Models and the bookmaker (Bet365, margin removed) are compared on exactly the same matches: those every model predicted before kickoff, with a result and odds.

## Response caching (Redis)

`/teams`, `/predict`, `/matches`, `/fixtures/upcoming` and `/track-record` are cached in Redis using cache-aside: look in Redis first; on a miss, build the response from Postgres and the model, store it with a TTL, and return it. Each response has an `X-Cache: HIT` or `X-Cache: MISS` header:

```bash
curl -si "localhost:8000/predict?home=1&away=17" | grep -i x-cache
```

**Keys include versions, so nothing is ever deleted.** A key looks like `epl:v1:predict:mv1@<trained_at>:d7:1:17:2026-10-04`:

- `mv1@<trained_at>` is the loaded model. Training a new version, or retraining with `--force`, changes it.
- `d7` is the **data version**, a counter in the `data_version` table. `load_history`, the fixture refresh and the predictions job bump it in the same transaction as their match writes, but only when a team or match was actually inserted or updated.
- After that come the request parameters. For `/predict`, a missing `as_of` is replaced with today's date before the key is built, so "today" gets a new key each day.

When the data or model changes, requests look up keys that don't exist yet. They miss and are rebuilt from the new data. Old entries are never read again and expire on their TTL. Errors (400/404) are never cached.

| Endpoint | TTL | Why |
|----------|-----|-----|
| `/teams` | 24 h | Tiny and almost never changes (teams are only added for a new season). The data version already covers changes. |
| `/matches` | 6 h | The most expensive response (features for every match since 2015), with about 12 possible keys. Keeping it long is cheap. |
| `/fixtures/upcoming` | 6 h | As expensive as `/matches` (it builds the same features), but only one key a day: today's date is in the key, so fixtures already played drop off the next day. |
| `/track-record` | 6 h | One key per season. It only changes when predictions are saved or results come in, and both bump the data version. |
| `/predict` | 1 h | Many possible keys (team pairs × dates), each fairly cheap to rebuild. A short TTL keeps memory use small while still covering the repeat requests around a match day. |

Correctness never depends on the TTLs: the versions in the key do that. TTLs only decide how long unused entries take up memory. Redis is also capped at 128 MB with LRU eviction (see `docker-compose.yml`).

**If Redis is down,** the API keeps answering, just without the cache (`X-Cache: MISS`). It logs one `Redis unavailable` warning and doesn't try Redis again for 30 seconds, so the outage doesn't add a connection timeout to every request. `/health` still reports Redis as down.

## Layout

```
backend/    FastAPI app, Alembic migrations, pytest tests
frontend/   React + Vite + TypeScript single page
docker-compose.yml
.env.example  template for .env (the real .env is never committed)
```

## Frontend

Five pages, served by Vite at http://localhost:5173:

| Page | Shows |
|------|-------|
| Fixtures (`/`) | The next matchweek with a probability bar for each match. Each links to its prediction on the Predict page |
| Predict (`/predict`) | Pick a home and away team for win/draw/loss chances and the Elo and form numbers behind them. The teams are kept in the URL (`/predict?home=1&away=17`), so a prediction can be shared. Old `/?home=1&away=17` links are redirected here |
| This season (`/season`) | Every 2026-27 match played so far, the model's pre-match pick next to the result, and its running record |
| Track record (`/track-record`) | Predictions saved before kickoff: scores for the live model, the shadow model and the bookmaker on the same matches, a chart of their running log loss over the season (with a table view), and every saved prediction next to the result |
| Model (`/model`) | The loaded model's version and seasons, and its test scores against the baselines and the bookmaker |

The browser calls `/api/...` on the Vite server, which strips `/api` and forwards to the backend.

### API types

`frontend/src/api/schema.gen.ts` is generated from the backend's OpenAPI schema with [openapi-typescript](https://openapi-ts.dev/), so a backend change that breaks the frontend fails the type check. After changing a backend response model, with the backend running:

```bash
docker compose exec frontend npm run gen:api
```

Commit the regenerated file. `npm run check:api` exits non-zero if it is out of date. Outside Docker, the scripts read the backend from `BACKEND_URL` (default `http://localhost:8000`), or from a saved schema file: `npm run gen:api -- openapi.json`.

### Frontend tests

Vitest and React Testing Library:

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run typecheck
```
