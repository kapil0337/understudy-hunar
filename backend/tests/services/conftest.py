from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.settings import Settings
from app.integrations.llm.base import LLMResponse, Message

JD_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "jd"
RAW_JD_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "jd"

JD_NAMES = (
    "delivery_rider_chennai",
    "retail_associate_bengaluru",
    "warehouse_picker_pune",
)


def load_compiled_fixture(name: str) -> dict[str, Any]:
    text = (JD_FIXTURE_DIR / f"compiled_{name}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def load_raw_jd(name: str) -> str:
    return (RAW_JD_DIR / f"{name}.txt").read_text(encoding="utf-8")


class FakeProvider:
    """A scriptable stand-in for a real provider.

    `responses` is consumed in order; an entry that is an Exception is raised instead of
    returned, which is how the fallback and retry paths get exercised without a network.
    """

    def __init__(self, name: str, responses: list[Any] | None = None) -> None:
        self.name = name
        self.responses: list[Any] = responses or []
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def _next(self, model: str) -> LLMResponse:
        if not self.responses:
            raise AssertionError(f"FakeProvider({self.name}) ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(text=str(item), model=model, provider=self.name)

    async def complete(
        self, model: str, messages: list[Message], temperature: float
    ) -> LLMResponse:
        self.calls.append(
            {"kind": "complete", "model": model, "messages": messages, "temperature": temperature}
        )
        return self._next(model)

    async def structured_complete(
        self,
        model: str,
        messages: list[Message],
        schema: dict[str, Any],
        schema_name: str,
        temperature: float,
    ) -> LLMResponse:
        self.calls.append(
            {
                "kind": "structured",
                "model": model,
                "messages": messages,
                "schema": schema,
                "schema_name": schema_name,
                "temperature": temperature,
            }
        )
        return self._next(model)

    async def aclose(self) -> None:
        self.closed = True


class SampleModel(BaseModel):
    name: str
    count: int


@pytest.fixture
def llm_settings() -> Settings:
    """Settings with both roles routed nvidia -> gemini, and no real keys anywhere."""
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        llm_provider_compiler="nvidia",
        llm_model_compiler="model-a",
        llm_fallback_provider_compiler="gemini",
        llm_fallback_model_compiler="model-b",
        llm_provider_simulator="nvidia",
        llm_model_simulator="model-a",
        llm_fallback_provider_simulator="gemini",
        llm_fallback_model_simulator="model-b",
    )
