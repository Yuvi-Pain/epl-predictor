"""Tests for the football-data.org client: rate limiting, retries and backoff.

The network is an httpx.MockTransport and time is a FakeClock whose sleep()
advances the clock instead of waiting, so every test runs instantly and can
assert exactly how long the client would have waited.
"""

import asyncio
import logging
from collections.abc import Callable

import httpx
import pytest

from app.football_data_org import (
    API_KEY_ENV,
    FootballDataClient,
    FootballDataError,
    MissingApiKeyError,
    RateLimiter,
    RetryPolicy,
    api_key_from_env,
)

KEY = "test-key-123"
MATCHES_PATH = "/v4/competitions/PL/matches"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


Handler = Callable[[httpx.Request], httpx.Response]


def scripted(*responses: httpx.Response | Exception) -> tuple[Handler, list[httpx.Request]]:
    """A transport handler that answers with `responses` in order and records requests."""
    queue = list(responses)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, seen


def ok(**headers: str) -> httpx.Response:
    return httpx.Response(200, json={"matches": []}, headers=headers)


def make_client(handler: Handler, clock: FakeClock, **kwargs: object) -> FootballDataClient:
    return FootballDataClient(
        KEY,
        limiter=RateLimiter(clock=clock, sleep=clock.sleep),
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        rand=lambda: 1.0,  # no jitter: backoff is exactly base * 2**(n-1)
        **kwargs,  # type: ignore[arg-type]
    )


def fetch(client: FootballDataClient) -> dict[str, object]:
    async def go() -> dict[str, object]:
        async with client:
            return await client.competition_matches("PL")

    return asyncio.run(go())


# --- happy path ----------------------------------------------------------------------


def test_sends_the_key_in_the_auth_header_only() -> None:
    handler, seen = scripted(ok())
    assert fetch(make_client(handler, FakeClock())) == {"matches": []}
    (request,) = seen
    assert request.url.path == MATCHES_PATH
    assert request.headers["X-Auth-Token"] == KEY
    assert KEY not in str(request.url)


def test_season_is_passed_as_a_query_parameter() -> None:
    handler, seen = scripted(ok())
    client = make_client(handler, FakeClock())

    async def go() -> None:
        async with client:
            await client.competition_matches("PL", season=2026)

    asyncio.run(go())
    assert seen[0].url.params["season"] == "2026"


# --- rate limiting -------------------------------------------------------------------


def test_limiter_lets_ten_through_then_waits_for_the_window() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=10, period=60, clock=clock, sleep=clock.sleep)

    async def go() -> None:
        for _ in range(10):
            await limiter.acquire()
        assert clock.sleeps == []  # the first ten go straight through
        await limiter.acquire()

    asyncio.run(go())
    assert clock.sleeps == [60.0]  # the 11th waits until the 1st is a minute old


def test_limiter_window_slides() -> None:
    clock = FakeClock()
    limiter = RateLimiter(limit=2, period=60, clock=clock, sleep=clock.sleep)

    async def go() -> None:
        await limiter.acquire()  # t=0
        clock.now += 50
        await limiter.acquire()  # t=50
        await limiter.acquire()  # must wait until t=60, when the first leaves the window

    asyncio.run(go())
    assert clock.sleeps == [pytest.approx(10.0)]


def test_client_never_sends_more_than_ten_requests_a_minute() -> None:
    clock = FakeClock()
    sent_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(clock.now)
        return ok()

    client = make_client(handler, clock)

    async def go() -> None:
        async with client:
            for _ in range(25):
                await client.competition_matches()

    asyncio.run(go())
    assert len(sent_at) == 25
    for t in sent_at:
        in_window = [s for s in sent_at if t <= s < t + 60]
        assert len(in_window) <= 10


def test_pauses_when_the_api_reports_the_quota_used_up() -> None:
    """Requests made elsewhere with the same key count too: obey the server's counter."""
    clock = FakeClock()
    handler, seen = scripted(
        ok(**{"X-Requests-Available-Minute": "0", "X-RequestCounter-Reset": "42"}), ok()
    )
    client = make_client(handler, clock)

    async def go() -> None:
        async with client:
            await client.competition_matches()
            await client.competition_matches()

    asyncio.run(go())
    assert len(seen) == 2
    assert clock.sleeps == [43.0]  # the reset time plus one second


# --- retries and backoff -------------------------------------------------------------


def test_429_waits_for_the_reset_time_then_retries() -> None:
    clock = FakeClock()
    handler, seen = scripted(
        httpx.Response(
            429,
            json={"message": "You reached your request limit."},
            headers={"X-RequestCounter-Reset": "17"},
        ),
        ok(),
    )
    assert fetch(make_client(handler, clock)) == {"matches": []}
    assert len(seen) == 2
    assert sum(clock.sleeps) == pytest.approx(18.0)  # 17 s reset + 1 s margin, not backoff


def test_429_without_a_reset_header_backs_off() -> None:
    clock = FakeClock()
    handler, seen = scripted(httpx.Response(429), httpx.Response(429), ok())
    fetch(make_client(handler, clock, retry=RetryPolicy(base_delay=2)))
    assert clock.sleeps == [2.0, 4.0]


def test_server_errors_and_timeouts_back_off_exponentially() -> None:
    clock = FakeClock()
    request = httpx.Request("GET", "https://api.football-data.org" + MATCHES_PATH)
    handler, seen = scripted(
        httpx.Response(503),
        httpx.ReadTimeout("slow", request=request),
        httpx.ConnectError("refused", request=request),
        httpx.Response(500),
        ok(),
    )
    result = fetch(make_client(handler, clock, retry=RetryPolicy(max_attempts=5, base_delay=2)))
    assert result == {"matches": []}
    assert len(seen) == 5
    assert clock.sleeps == [2.0, 4.0, 8.0, 16.0]


def test_backoff_is_capped_and_jittered() -> None:
    policy = RetryPolicy(base_delay=2, max_delay=60)
    assert policy.backoff(10, rand=1.0) == 60.0  # 2 * 2**9 = 1024, capped
    assert policy.backoff(3, rand=0.0) == 4.0  # 8 s scaled down to half
    assert policy.backoff(3, rand=0.5) == 6.0


def test_gives_up_after_max_attempts() -> None:
    clock = FakeClock()
    handler, seen = scripted(*[httpx.Response(502) for _ in range(3)])
    with pytest.raises(FootballDataError, match="after 3 attempts.*HTTP 502"):
        fetch(make_client(handler, clock, retry=RetryPolicy(max_attempts=3, base_delay=1)))
    assert len(seen) == 3
    assert clock.sleeps == [1.0, 2.0]  # no pointless wait after the last attempt


@pytest.mark.parametrize("status", [400, 403, 404])
def test_client_errors_are_not_retried(status: int) -> None:
    clock = FakeClock()
    handler, seen = scripted(
        httpx.Response(status, json={"message": "The resource you are looking for is restricted."})
    )
    with pytest.raises(FootballDataError, match=f"HTTP {status}: The resource .* restricted"):
        fetch(make_client(handler, clock))
    assert len(seen) == 1
    assert clock.sleeps == []


def test_the_key_never_appears_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    handler, _ = scripted(httpx.Response(500), httpx.Response(403, json={"message": "bad token"}))
    with pytest.raises(FootballDataError) as excinfo:
        fetch(make_client(handler, FakeClock()))
    assert KEY not in str(excinfo.value)
    assert KEY not in caplog.text
    assert "retry 1/4" in caplog.text


# --- the key -------------------------------------------------------------------------


def test_key_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, f"  {KEY}\n")
    assert api_key_from_env() == KEY


@pytest.mark.parametrize("value", [None, "", "your-key-here"])
def test_missing_or_placeholder_key_is_an_error(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(API_KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(API_KEY_ENV, value)
    with pytest.raises(MissingApiKeyError, match=API_KEY_ENV):
        api_key_from_env()
