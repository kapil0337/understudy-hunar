"""LLM provider adapters.

These live under app/integrations/ rather than app/services/ because they make external HTTP
calls, which CLAUDE.md requires to go through an adapter with a typed response model, a timeout
and a retry policy. app/services/llm.py sits on top and owns routing, caching and validation.
"""

from app.integrations.llm.base import (
    LLMProvider,
    LLMProviderError,
    LLMQuotaExceeded,
    LLMResponse,
)
from app.integrations.llm.gemini import GeminiProvider
from app.integrations.llm.nvidia import NvidiaProvider

__all__ = [
    "GeminiProvider",
    "LLMProvider",
    "LLMProviderError",
    "LLMQuotaExceeded",
    "LLMResponse",
    "NvidiaProvider",
]
