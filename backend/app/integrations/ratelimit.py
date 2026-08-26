"""A minimal async token bucket, used to keep a provider under its documented rate limit
regardless of how many calls the app fires concurrently — e.g. PDLProvider's 10 req/min, or
GroqProvider's account-wide tokens/minute budget (approximated here as a request rate, since the
actual cost of a call is not known ahead of it)."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """`capacity` tokens, refilled continuously at `capacity` per `period_seconds`.

    `acquire()` waits (does not raise) until a token is available — the caller is making a
    search the user asked for, so the right behaviour is "go slower", not "fail".
    """

    def __init__(self, capacity: int, period_seconds: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")

        self._capacity = float(capacity)
        self._refill_rate = capacity / period_seconds  # tokens per second
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._updated_at
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._updated_at = now

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_seconds = (1.0 - self._tokens) / self._refill_rate
            await asyncio.sleep(wait_seconds)
