"""Scheduled jobs, run as the `worker` service in docker-compose.yml.

- Every FIXTURES_REFRESH_HOURS (default 6): fetch the fixture list from
  football-data.org (`app/fixtures.py`).
- Every HISTORY_REFRESH_HOURS (default 24): rerun the history loader to pull in
  new results (`scripts/load_history.py`).
- Every PREDICTIONS_REFRESH_HOURS (default 1): save each tracked model's
  prediction for fixtures kicking off within PREDICTION_LEAD_HOURS (default
  24), for the track record (`app/tracking.py`). TRACKED_MODEL_VERSIONS
  (default "v2,v1") names the models: the live one users see and any shadows.

All run once at startup, then on their interval. All bump the data version
when they change anything, which retires the API's cached responses.

Jobs run one at a time in this one process, so they never write at the same
time. A failed job is logged and tried again after RETRY_AFTER_FAILURE rather
than waiting for its next full interval; the worker itself keeps running.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db import engine
from app.fixtures import refresh_fixtures
from app.football_data_org import (
    FootballDataClient,
    MissingApiKeyError,
    RateLimiter,
    api_key_from_env,
)
from app.predictor import MODELS_DIR, ModelLoadError, Predictor, load_predictor
from app.tracking import record_predictions
from scripts.load_history import load

log = logging.getLogger("worker")

RETRY_AFTER_FAILURE = timedelta(minutes=15)


@dataclass
class Job:
    """A coroutine to run every `every`. `next_run` is a monotonic time; 0 means now."""

    name: str
    run: Callable[[], Awaitable[object]]
    every: timedelta
    retry_after_failure: timedelta = RETRY_AFTER_FAILURE
    next_run: float = 0.0


async def run_due(jobs: list[Job], clock: Callable[[], float] = time.monotonic) -> float:
    """Run every job that is due, one after another, and reschedule it.

    Returns:
        Seconds until the next job is due (0 or more).
    """
    for job in sorted(jobs, key=lambda j: j.next_run):
        if job.next_run > clock():
            continue
        started = clock()
        try:
            result = await job.run()
        except Exception:  # a failed job must not stop the worker
            log.exception("%s failed; retrying in %s", job.name, job.retry_after_failure)
            job.next_run = clock() + job.retry_after_failure.total_seconds()
        else:
            log.info("%s done in %.1fs (%s rows changed)", job.name, clock() - started, result)
            job.next_run = clock() + job.every.total_seconds()
    return max(0.0, min(j.next_run for j in jobs) - clock())


async def run_forever(jobs: list[Job]) -> None:
    while True:
        await asyncio.sleep(await run_due(jobs))


def _hours_from_env(name: str, default: float) -> timedelta:
    return timedelta(hours=float(os.environ.get(name, default)))


def tracked_versions() -> list[str]:
    """The model versions to save predictions for, from $TRACKED_MODEL_VERSIONS."""
    raw = os.environ.get("TRACKED_MODEL_VERSIONS", "v2,v1")
    return [v.strip() for v in raw.split(",") if v.strip()]


def load_tracked_predictors(versions: list[str]) -> list[Predictor]:
    """Load each tracked model's file. A missing or unusable file is logged and skipped.

    Loaded afresh on every run, so a retrained model is picked up without a restart.
    """
    predictors = []
    for version in versions:
        path = MODELS_DIR / f"match_outcome_logreg_{version}.joblib"
        try:
            predictor = load_predictor(path)
        except ModelLoadError as exc:
            log.error("not saving %s predictions: %s", version, exc)
            continue
        if predictor is not None:
            predictors.append(predictor)
    return predictors


def build_jobs(limiter: RateLimiter) -> list[Job]:
    """The worker's jobs.

    The fixture and prediction jobs are left out, with a warning, if there is
    no API key: predictions are only saved for fixtures with a known kickoff
    time, which only the fixture list provides.
    """

    async def history() -> int:
        return await load(refresh=False, sanity_check=False)

    jobs = [Job("history", history, _hours_from_env("HISTORY_REFRESH_HOURS", 24))]

    try:
        api_key = api_key_from_env()
    except MissingApiKeyError as exc:
        log.warning("fixture refresh disabled: %s", exc)
        return jobs

    async def fixtures() -> int:
        # One limiter for the process, so the 10/minute budget spans every run.
        async with FootballDataClient(api_key, limiter=limiter) as client:
            return await refresh_fixtures(client)

    versions = tracked_versions()
    lead = _hours_from_env("PREDICTION_LEAD_HOURS", 24)

    async def predictions() -> int:
        predictors = load_tracked_predictors(versions)
        async with engine.begin() as conn:
            return await record_predictions(conn, predictors, datetime.now(UTC), lead)

    # Fixtures first: at startup the fixture list is what the home page needs.
    # Predictions last, so they use the freshest fixtures and results.
    return [
        Job("fixtures", fixtures, _hours_from_env("FIXTURES_REFRESH_HOURS", 6)),
        *jobs,
        Job("predictions", predictions, _hours_from_env("PREDICTIONS_REFRESH_HOURS", 1)),
    ]


async def main() -> None:
    jobs = build_jobs(RateLimiter())
    for job in jobs:
        log.info("scheduled %s every %s", job.name, job.every)
    try:
        await run_forever(jobs)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is noise
    asyncio.run(main())
