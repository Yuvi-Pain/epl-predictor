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

Downloads Premier League results for 2015-16 through 2025-26 from [football-data.co.uk](https://www.football-data.co.uk/) and upserts them into the `teams`, `team_aliases` and `matches` tables:

```bash
docker compose exec backend python -m scripts.load_history
```

It ends with a per-season table of match and goal counts; every season should show 380 matches. It is safe to rerun: existing matches are updated in place, never duplicated. Downloaded CSVs are cached in `backend/data/raw/` (git-ignored); pass `--refresh` to download them again.

If it stops with `Unknown team names`, a data source used a spelling we haven't seen. Add it to `backend/app/teams.py` and rerun.

## Layout

```
backend/    FastAPI app, Alembic migrations, pytest tests
frontend/   React + Vite + TypeScript single page
docker-compose.yml
.env.example  template for .env (the real .env is never committed)
```
