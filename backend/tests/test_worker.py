"""Tests for the worker's scheduling loop. Jobs are fakes; time is a plain counter."""

import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from app.football_data_org import API_KEY_ENV, RateLimiter
from scripts import worker
from scripts.worker import Job, build_jobs, load_tracked_predictors, run_due, tracked_versions


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def recording_job(name: str, calls: list[str], every_hours: float, fail: bool = False) -> Job:
    async def run() -> int:
        calls.append(name)
        if fail:
            raise RuntimeError(f"{name} broke")
        return 3

    return Job(name, run, timedelta(hours=every_hours))


def test_every_job_runs_at_startup_then_on_its_interval() -> None:
    clock, calls = Clock(), []
    jobs = [recording_job("fixtures", calls, 6), recording_job("history", calls, 24)]

    wait = asyncio.run(run_due(jobs, clock))
    assert calls == ["fixtures", "history"]
    assert wait == 6 * 3600

    clock.now += wait
    wait = asyncio.run(run_due(jobs, clock))
    assert calls == ["fixtures", "history", "fixtures"]
    assert wait == 6 * 3600

    clock.now = 24 * 3600
    asyncio.run(run_due(jobs, clock))
    assert calls[-2:] == ["fixtures", "history"]


def test_nothing_runs_before_it_is_due() -> None:
    clock, calls = Clock(), []
    jobs = [recording_job("fixtures", calls, 6)]
    asyncio.run(run_due(jobs, clock))
    clock.now += 3600
    assert asyncio.run(run_due(jobs, clock)) == 5 * 3600
    assert calls == ["fixtures"]


def test_a_failed_job_is_retried_soon_and_does_not_stop_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock, calls = Clock(), []
    jobs = [recording_job("fixtures", calls, 6, fail=True), recording_job("history", calls, 24)]

    wait = asyncio.run(run_due(jobs, clock))
    assert calls == ["fixtures", "history"]  # history still ran
    assert wait == 15 * 60  # the failed job comes back in 15 minutes, not 6 hours
    assert "fixtures failed" in caplog.text and "fixtures broke" in caplog.text


def test_without_an_api_key_only_the_history_job_runs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "your-key-here")
    with caplog.at_level(logging.WARNING):
        jobs = build_jobs(RateLimiter())
    assert [j.name for j in jobs] == ["history"]
    assert "fixture refresh disabled" in caplog.text


def test_intervals_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "a-real-looking-key")
    monkeypatch.setenv("FIXTURES_REFRESH_HOURS", "8")
    monkeypatch.delenv("HISTORY_REFRESH_HOURS", raising=False)
    monkeypatch.delenv("PREDICTIONS_REFRESH_HOURS", raising=False)
    jobs = {j.name: j.every for j in build_jobs(RateLimiter())}
    assert jobs == {
        "fixtures": timedelta(hours=8),
        "history": timedelta(hours=24),
        "predictions": timedelta(hours=1),
    }


def test_predictions_run_after_fixtures_and_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "a-real-looking-key")
    assert [j.name for j in build_jobs(RateLimiter())] == ["fixtures", "history", "predictions"]


def test_tracked_models_default_to_live_v2_and_shadow_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRACKED_MODEL_VERSIONS", raising=False)
    assert tracked_versions() == ["v2", "v1"]
    monkeypatch.setenv("TRACKED_MODEL_VERSIONS", " v3, v2 ,")
    assert tracked_versions() == ["v3", "v2"]


def test_a_missing_model_file_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(worker, "MODELS_DIR", tmp_path)
    assert load_tracked_predictors(["v1", "v2"]) == []
