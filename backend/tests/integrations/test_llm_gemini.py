from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from pydantic import BaseModel
from tenacity import wait_none

from app.integrations.llm.base import LLMProviderError, LLMQuotaExceeded
from app.integrations.llm.gemini import GeminiProvider, _to_gemini_contents, _to_gemini_schema

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@pytest.fixture
async def provider() -> AsyncIterator[GeminiProvider]:
    async with httpx.AsyncClient(verify=False) as transport:  # noqa: S501
        yield GeminiProvider(
            "test-gemini-key", max_attempts=2, retry_wait=wait_none(), client=transport
        )


def gen_response(text: str) -> dict[str, object]:
    return {
        "candidates": [{"content": {"parts": [{"text": text}], "role": "model"}}],
        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3},
    }


# ------------------------------------------------------------------- message mapping


def test_to_gemini_contents_splits_system_and_maps_assistant_to_model() -> None:
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]

    contents, system = _to_gemini_contents(messages)

    assert system == "You are helpful."
    assert contents == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
    ]


def test_to_gemini_contents_merges_multiple_system_messages() -> None:
    messages = [
        {"role": "system", "content": "first"},
        {"role": "system", "content": "second"},
        {"role": "user", "content": "hi"},
    ]

    _, system = _to_gemini_contents(messages)

    assert system == "first\n\nsecond"


def test_to_gemini_contents_no_system_message() -> None:
    _, system = _to_gemini_contents([{"role": "user", "content": "hi"}])

    assert system is None


# --------------------------------------------------------------------- schema mapping


def test_schema_translation_keeps_simple_object() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        "required": ["a"],
    }

    out = _to_gemini_schema(schema)

    assert out == schema


def test_schema_translation_drops_unsupported_keywords() -> None:
    schema = {
        "type": "object",
        "title": "Foo",
        "additionalProperties": False,
        "properties": {"a": {"type": "string", "title": "A"}},
    }

    out = _to_gemini_schema(schema)

    assert "title" not in out
    assert "additionalProperties" not in out
    assert "title" not in out["properties"]["a"]


def test_schema_translation_inlines_refs() -> None:
    """Pydantic's model_json_schema() emits $ref/$defs for nested models; Gemini understands
    neither, so refs must be resolved inline."""

    class Inner(BaseModel):
        value: str

    class Outer(BaseModel):
        inner: Inner

    schema = Outer.model_json_schema()
    assert "$defs" in schema  # sanity check on the input shape

    out = _to_gemini_schema(schema)

    assert "$ref" not in json.dumps(out)
    assert out["properties"]["inner"]["type"] == "object"
    assert out["properties"]["inner"]["properties"]["value"]["type"] == "string"


def test_schema_translation_handles_optional_field_anyof() -> None:
    """`X | None` renders as anyOf in Pydantic's schema; Gemini wants `nullable: true` on the
    base type instead."""

    class WithOptional(BaseModel):
        maybe: str | None = None

    schema = WithOptional.model_json_schema()
    out = _to_gemini_schema(schema)

    field = out["properties"]["maybe"]
    assert field["type"] == "string"
    assert field["nullable"] is True


def test_schema_translation_handles_nested_arrays() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"x": {"type": "integer"}}},
            }
        },
    }

    out = _to_gemini_schema(schema)

    assert out["properties"]["items"]["items"]["properties"]["x"]["type"] == "integer"


# ---------------------------------------------------------------------------- HTTP


@respx.mock
async def test_complete_sends_key_in_header_not_query_string(provider: GeminiProvider) -> None:
    route = respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(200, json=gen_response("hello"))
    )

    result = await provider.complete("gemini-2.0-flash", [{"role": "user", "content": "hi"}], 0.2)

    assert result.text == "hello"
    request = route.calls.last.request
    assert request.headers["x-goog-api-key"] == "test-gemini-key"
    assert "key=" not in str(request.url)


@respx.mock
async def test_structured_complete_sets_response_schema(provider: GeminiProvider) -> None:
    route = respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(200, json=gen_response('{"a": 1}'))
    )

    await provider.structured_complete(
        "gemini-2.0-flash",
        [{"role": "user", "content": "hi"}],
        {"type": "object", "properties": {"a": {"type": "integer"}}},
        "MySchema",
        0.2,
    )

    body = json.loads(route.calls.last.request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["properties"]["a"]["type"] == "integer"


@respx.mock
async def test_429_raises_quota_exceeded(provider: GeminiProvider) -> None:
    respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(429, json={"error": "rate limited"})
    )

    with pytest.raises(LLMQuotaExceeded):
        await provider.complete("gemini-2.0-flash", [{"role": "user", "content": "hi"}], 0.2)


@respx.mock
async def test_5xx_is_retried(provider: GeminiProvider) -> None:
    route = respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        side_effect=[httpx.Response(503, text="down"), httpx.Response(200, json=gen_response("ok"))]
    )

    result = await provider.complete("gemini-2.0-flash", [{"role": "user", "content": "hi"}], 0.2)

    assert result.text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_400_not_retried(provider: GeminiProvider) -> None:
    route = respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(400, text="bad")
    )

    with pytest.raises(LLMProviderError):
        await provider.complete("gemini-2.0-flash", [{"role": "user", "content": "hi"}], 0.2)

    assert route.call_count == 1


@respx.mock
async def test_unexpected_shape_raises(provider: GeminiProvider) -> None:
    respx.post(f"{BASE_URL}/models/gemini-2.0-flash:generateContent").mock(
        return_value=httpx.Response(200, json={"nope": True})
    )

    with pytest.raises(LLMProviderError, match="unexpected response shape"):
        await provider.complete("gemini-2.0-flash", [{"role": "user", "content": "hi"}], 0.2)


async def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GeminiProvider("")
