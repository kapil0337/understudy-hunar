from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from tenacity import wait_none

from app.integrations.hunar.client import HunarClient

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "hunar"

# Not a real key: it matches no live credential and exists only so the signature/auth paths
# have something deterministic to work with.
TEST_API_KEY = "test-key-not-a-real-credential"
BASE_URL = "https://api.voice.hunar.ai/external/v1/"


def load_fixture(name: str) -> Any:
    """Load a captured Hunar response. See tests/fixtures/hunar/README.md for provenance."""
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
async def hunar_client() -> AsyncIterator[HunarClient]:
    # max_attempts=2 exercises more than one attempt; wait_none drops the backoff so the
    # retry tests do not spend real seconds sleeping.
    #
    # verify=False on the injected transport is purely a speed measure: building an
    # httpx.AsyncClient with TLS verification loads the CA bundle, which costs ~0.5s per
    # test on Windows. respx intercepts every request well before TLS, so no verification
    # would happen either way. Production clients build their own verifying client.
    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        client = HunarClient(TEST_API_KEY, max_attempts=2, retry_wait=wait_none(), client=transport)
        yield client
