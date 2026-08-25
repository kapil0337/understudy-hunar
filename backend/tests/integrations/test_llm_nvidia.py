from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from tenacity import wait_none

from app.integrations.llm.base import LLMProviderError, LLMQuotaExceeded
from app.integrations.llm.nvidia import NvidiaProvider

BASE_URL = "https://integrate.api.nvidia.com/v1"


@pytest.fixture
async def provider() -> AsyncIterator[NvidiaProvider]:
    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        yield NvidiaProvider(
            "test-nvidia-key", max_attempts=2, retry_wait=wait_none(), client=transport
        )


def chat_response(text: str, *, model: str = "model-a") -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@respx.mock
async def test_complete_sends_auth_header_and_parses_text(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json=chat_response("hello"))
    )

    result = await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)

    assert result.text == "hello"
    assert result.provider == "nvidia"
    assert result.prompt_tokens == 10
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-nvidia-key"


@respx.mock
async def test_complete_sends_no_response_format(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json=chat_response("hi"))
    )

    await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.5)

    import json

    body = json.loads(route.calls.last.request.content)
    assert "response_format" not in body
    assert body["temperature"] == 0.5


@respx.mock
async def test_structured_complete_sends_json_schema_response_format(
    provider: NvidiaProvider,
) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json=chat_response('{"a": 1}'))
    )

    result = await provider.structured_complete(
        "model-a",
        [{"role": "user", "content": "hi"}],
        {"type": "object", "properties": {"a": {"type": "integer"}}},
        "MySchema",
        0.2,
    )

    assert result.text == '{"a": 1}'

    import json

    body = json.loads(route.calls.last.request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "MySchema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["properties"]["a"]["type"] == "integer"


@respx.mock
async def test_429_raises_quota_exceeded_not_retried(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )

    with pytest.raises(LLMQuotaExceeded):
        await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)

    assert route.call_count == 1


@respx.mock
async def test_402_raises_quota_exceeded(provider: NvidiaProvider) -> None:
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(402, json={"error": "insufficient credit"})
    )

    with pytest.raises(LLMQuotaExceeded):
        await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)


@respx.mock
async def test_5xx_is_retried_then_succeeds(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=chat_response("ok")),
        ]
    )

    result = await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)

    assert result.text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_5xx_exhausted_raises_provider_error(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )

    with pytest.raises(LLMProviderError):
        await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)

    assert route.call_count == 2  # max_attempts


@respx.mock
async def test_400_is_not_retried(provider: NvidiaProvider) -> None:
    route = respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(400, text="bad request")
    )

    with pytest.raises(LLMProviderError):
        await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)

    assert route.call_count == 1


@respx.mock
async def test_unexpected_response_shape_raises_rather_than_guessing(
    provider: NvidiaProvider,
) -> None:
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    with pytest.raises(LLMProviderError, match="unexpected response shape"):
        await provider.complete("model-a", [{"role": "user", "content": "hi"}], 0.2)


async def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        NvidiaProvider("")
