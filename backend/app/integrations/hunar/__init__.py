"""Adapter for the Hunar Voice Agents API.

Everything that talks to Hunar goes through here: typed request/response models, a client with
timeouts and a retry policy, webhook signature verification, and local preflight validators that
catch the documented 422s before a request is ever sent.
"""

from app.integrations.hunar.client import HunarClient
from app.integrations.hunar.exceptions import (
    HunarAPIError,
    HunarNotFound,
    HunarQuotaExhausted,
    HunarTelephonyError,
    HunarUnauthorized,
    HunarValidationError,
)
from app.integrations.hunar.signature import verify_webhook_signature

__all__ = [
    "HunarAPIError",
    "HunarClient",
    "HunarNotFound",
    "HunarQuotaExhausted",
    "HunarTelephonyError",
    "HunarUnauthorized",
    "HunarValidationError",
    "verify_webhook_signature",
]
