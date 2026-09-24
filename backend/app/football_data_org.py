"""A small client for the football-data.org v4 API, used for the fixture list.

The free plan allows 10 requests a minute. Two things keep us inside that:

- `RateLimiter` spaces our own requests so no 60-second window holds more than
  10 of them, and pauses everyone when the API says the quota is used up (the
  same key may be used elsewhere).
- `FootballDataClient.get_json` retries what is worth retrying: 429 (too many
  requests) waits for the reset time the API sends; 5xx errors, timeouts and
  dropped connections wait with exponential backoff and jitter. Anything else
  (a bad key, a wrong URL) fails at once, since trying again cannot help.

The API key is read from $FOOTBALL_DATA_API_KEY and only ever sent in the
X-Auth-Token header. It is never logged or put in an error message.
"""

import asyncio
import logging
import os
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"
API_KEY_ENV = "FOOTBALL_DATA_API_KEY"
PLACEHOLDER_KEY = "your-key-here"  # the value in .env.example

# The free plan's limit.
REQUESTS_PER_MINUTE = 10

Sleep = Callable[[float], Awaitable[None]]


class FootballDataError(RuntimeError):
    """The API could not be reached or refused the request."""


class MissingApiKeyError(FootballDataError):
    """$FOOTBALL_DATA_API_KEY is not set."""


def api_key_from_env() -> str:
    """The API key from the environment.

    Raises:
        MissingApiKeyError: If it is unset, empty or still the .env.example placeholder.
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key or key == PLACEHOLDER_KEY:
        raise MissingApiKeyError(
            f"{API_KEY_ENV} is not set; get a free key at https://www.football-data.org/client/register"
        )
    return key


class RateLimiter:
    """Allows at most `limit` requests in any `period` seconds (a sliding window).

    `acquire()` returns at once while there is room, otherwise sleeps until the
    oldest request in the window is `period` seconds old. `pause()` holds every
    caller back for a while, for when the server says the quota is used up.
    """

    def __init__(
        self,
        limit: int = REQUESTS_PER_MINUTE,
        period: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._limit = limit
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until one more request fits in the window, and count it."""
        # One caller at a time, so two waiters cannot both take the last slot.
        async with self._lock:
            while (wait := self._wait_time()) > 0:
                await self._sleep(wait)
            self._sent.append(self._clock())

    def pause(self, seconds: float) -> None:
        """Hold every request back for `seconds` from now."""
        self._paused_until = max(self._paused_until, self._clock() + seconds)

    def _wait_time(self) -> float:
        now = self._clock()
        while self._sent and self._sent[0] <= now - self._period:
            self._sent.popleft()
        wait = self._paused_until - now
        if len(self._sent) >= self._limit:
            wait = max(wait, self._sent[0] + self._period - now)
        return wait


@dataclass(frozen=True)
class RetryPolicy:
    """How often and how patiently to retry a failed request.

    The wait before retry n (1, 2, 3, ...) is `base_delay * 2**(n-1)`, capped
    at `max_delay`, then scaled by a random factor between 0.5 and 1 (jitter)
    so that several clients that failed together do not all retry together.
    A 429 waits for the time the server asks for instead.
    """

    max_attempts: int = 5
    base_delay: float = 2.0
    max_delay: float = 60.0

    def backoff(self, retry: int, rand: float) -> float:
        """Seconds to wait before retry number `retry` (1-based); `rand` is in [0, 1)."""
        capped = min(self.max_delay, self.base_delay * 2 ** (retry - 1))
        return capped * (0.5 + rand / 2)


def _seconds_header(response: httpx.Response, *names: str) -> float | None:
    """The first of these headers that holds a number of seconds, if any."""
    for name in names:
        try:
            return float(response.headers[name])
        except (KeyError, ValueError):
            continue
    return None


def _error_message(response: httpx.Response) -> str:
    """The API's own explanation from an error body, e.g. "The resource you are
    looking for is restricted.", falling back to the status text."""
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return str(body["message"])
    return response.reason_phrase


class FootballDataClient:
    """Rate-limited, retrying GETs against football-data.org. Use with `async with`.

    Args:
        api_key: Sent as X-Auth-Token.
        limiter: Shared if several clients use the same key in one process.
        retry: Retry settings.
        transport: For tests: an httpx.MockTransport instead of the network.
        sleep: For tests: a fake that records waits instead of sleeping.
        rand: For tests: a fixed jitter source.
    """

    def __init__(
        self,
        api_key: str,
        *,
        limiter: RateLimiter | None = None,
        retry: RetryPolicy = RetryPolicy(),
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        rand: Callable[[], float] = random.random,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
    ) -> None:
        self._limiter = limiter or RateLimiter(sleep=sleep)
        self._retry = retry
        self._sleep = sleep
        self._rand = rand
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Auth-Token": api_key},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def competition_matches(
        self, competition: str = "PL", season: int | None = None
    ) -> dict[str, Any]:
        """Every match of a competition's season (default: the current one), in one request.

        Args:
            competition: Competition code; "PL" is the Premier League.
            season: Starting year, e.g. 2026 for 2026-27.
        """
        params = {"season": season} if season is not None else None
        return await self.get_json(f"/competitions/{competition}/matches", params)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET `path` and return the JSON body, retrying as described in the module docstring.

        Raises:
            FootballDataError: On a non-retryable error, or once every attempt has failed.
        """
        attempts = self._retry.max_attempts
        for attempt in range(1, attempts + 1):
            await self._limiter.acquire()
            try:
                response = await self._http.get(path, params=params)
            except httpx.TransportError as exc:  # timeouts, refused or dropped connections
                problem = f"{type(exc).__name__}"
                delay = self._retry.backoff(attempt, self._rand())
            else:
                self._respect_quota(response)
                if response.is_success:
                    body: dict[str, Any] = response.json()
                    return body
                problem = f"HTTP {response.status_code}: {_error_message(response)}"
                if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    # The server says exactly when the quota resets; one extra
                    # second covers rounding. Without the header, back off.
                    reset = _seconds_header(response, "X-RequestCounter-Reset", "Retry-After")
                    delay = (
                        reset + 1
                        if reset is not None
                        else self._retry.backoff(attempt, self._rand())
                    )
                    self._limiter.pause(delay)
                elif response.is_server_error:
                    delay = self._retry.backoff(attempt, self._rand())
                else:
                    # 400/403/404: a bad request or key. Retrying cannot fix it.
                    raise FootballDataError(f"GET {path} failed with {problem}")

            if attempt == attempts:
                raise FootballDataError(
                    f"GET {path} failed after {attempts} attempts; last: {problem}"
                )
            log.warning(
                "GET %s failed (%s); retry %d/%d in %.1fs",
                path,
                problem,
                attempt,
                attempts - 1,
                delay,
            )
            await self._sleep(delay)
        raise AssertionError("unreachable")  # the loop always returns or raises

    def _respect_quota(self, response: httpx.Response) -> None:
        """If the API reports no requests left this minute, pause until it resets.

        This catches requests made with the same key by something else (another
        worker, a manual run), which our own window cannot see.
        """
        remaining = _seconds_header(response, "X-Requests-Available-Minute")
        reset = _seconds_header(response, "X-RequestCounter-Reset")
        if remaining is not None and remaining <= 0 and reset is not None:
            self._limiter.pause(reset + 1)
