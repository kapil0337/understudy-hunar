from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from tenacity import wait_none

from app.integrations.sourcing.pdl import PDLProvider
from app.integrations.sourcing.ratelimit import TokenBucket

# Not a real key: exists only so the auth header has something deterministic to check.
TEST_API_KEY = "test-key-not-a-real-credential"
BASE_URL = "https://api.peopledatalabs.com/v5/person/search"


@pytest.fixture
async def pdl_provider() -> AsyncIterator[PDLProvider]:
    # max_attempts=2 exercises more than one attempt; wait_none drops the backoff. A large,
    # effectively-unlimited rate limiter here — the rate limiter itself has its own test.
    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        provider = PDLProvider(
            TEST_API_KEY,
            max_attempts=2,
            retry_wait=wait_none(),
            rate_limiter=TokenBucket(capacity=1000, period_seconds=60),
            client=transport,
        )
        yield provider
