# EPL Predictor

Skeleton app: a FastAPI backend, a React + Vite + TypeScript frontend, Postgres and Redis, all run with Docker Compose. No football logic yet.

## Run it

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine with the Compose plugin).

```bash
cp .env.example .env        # then edit .env and set a real password
docker compose up --build
```

The first start takes a few minutes while images download and dependencies install.

When it's ready:

| What | URL |
|------|-----|
| Frontend (shows backend health) | http://localhost:5173 |
| Backend health check | http://localhost:8000/health |
| Backend API docs | http://localhost:8000/docs |

Check that all four services are healthy:

```bash
docker compose ps
```

Each row should say `(healthy)`. Stop everything with `Ctrl+C`, or `docker compose down` from another terminal. Add `-v` to `down` to also delete the database data.

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

If it stops with `Unknown team names`, a data source used a spelling we haven't seen. Add it to `backend/app/teams.py` and rerun.

## Train the baseline model

After loading history, train a match outcome model (home win / draw / away win):

```bash
docker compose exec backend python -m scripts.train_model
```

It builds pre-match features from matches played on earlier dates only: Elo ratings, and average points, goals and shots on target over each team's last 5 matches. It then fits a multinomial logistic regression. Seasons are split by time: train on 2015-16 to 2023-24, choose the regularisation strength on 2024-25, test on 2025-26. The script prints accuracy, log loss and Brier score for the model and three baselines: always home win, training-set outcome rates, and Bet365's odds with the margin removed.

The model is saved to `backend/models/match_outcome_logreg_v1.joblib` (git-ignored). Pass `--version v2` to save a new one, or `--force` to overwrite.

## Prediction API

The backend loads the model once at startup (`MODEL_VERSION` in `.env`, default `v1`). After training or switching versions, restart it: `docker compose restart backend`.

| Endpoint | Returns |
|----------|---------|
| `GET /teams` | Every team with its id |
| `GET /predict?home=1&away=17` | Home win / draw / away win probabilities and the features used. Optional `as_of=2026-10-04` predicts as if the match were on that date (default today); only earlier results are used |
| `GET /matches?season=2026-27` | Each played match in the season with the model's pre-match prediction and the actual result. `model_split` says whether the model trained on that season (then the predictions flatter it) |
| `GET /model` | Model version, training time, and validation/test scores next to the baselines |

Errors: `400` if home and away are the same team, `404` for an unknown team id or a season with no matches, `422` for malformed parameters, `503` from `/predict`, `/matches` and `/model` when no model file is loaded (`/health` and `/teams` still work). Full schemas are at http://localhost:8000/docs.

Live predictions build features with the same `build_features` function used in training: the hypothetical match is added to the history and featurised alongside it. Elo settings and the form window are read from the model file, not the code defaults.

## Response caching (Redis)

`/teams`, `/predict` and `/matches` are cached in Redis using cache-aside: look in Redis first; on a miss, build the response from Postgres and the model, store it with a TTL, and return it. Each response has an `X-Cache: HIT` or `X-Cache: MISS` header:

```bash
curl -si "localhost:8000/predict?home=1&away=17" | grep -i x-cache
```

**Keys include versions, so nothing is ever deleted.** A key looks like `epl:v1:predict:mv1@<trained_at>:d7:1:17:2026-10-04`:

- `mv1@<trained_at>` is the loaded model. Training a new version, or retraining with `--force`, changes it.
- `d7` is the **data version**, a counter in the `data_version` table. `load_history` bumps it in the same transaction as the match writes, but only when a team or match was actually inserted or updated.
- After that come the request parameters. For `/predict`, a missing `as_of` is replaced with today's date before the key is built, so "today" gets a new key each day.

When the data or model changes, requests look up keys that don't exist yet. They miss and are rebuilt from the new data. Old entries are never read again and expire on their TTL. Errors (400/404) are never cached.

| Endpoint | TTL | Why |
|----------|-----|-----|
| `/teams` | 24 h | Tiny and almost never changes (teams are only added for a new season). The data version already covers changes. |
| `/matches` | 6 h | The most expensive response (features for every match since 2015), with about 12 possible keys. Keeping it long is cheap. |
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
