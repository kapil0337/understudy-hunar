"""Typed request/response models for the Hunar Voice Agents API.

Enums are `Literal` aliases rather than Python enums: this layer mirrors the wire format
exactly, so an unexpected value from Hunar surfaces as a validation error at the boundary
instead of being silently coerced. The DB-side equivalents live in app/models/enums.py.

Response models are deliberately permissive about unknown fields (`extra="allow"`): per
CONTRIBUTING.md, when unsure about API behaviour, never invent fields and never drop them either —
log the raw response and keep what came back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

Language = Literal[
    "ENGLISH",
    "HINDI",
    "TAMIL",
    "TELUGU",
    "KANNADA",
    "MARATHI",
    "MALAYALAM",
    "GUJARATI",
    "BENGALI",
    "TURKISH",
    "ARABIC",
    "SPANISH",
]

VoicePersona = Literal["NEHA", "ROY", "ZOE", "SAM", "MIRA", "EESHA"]

CallStatus = Literal[
    "NOT_STARTED",
    "SCHEDULED",
    "INITIATED",
    "RINGING",
    "IN_PROGRESS",
    "COMPLETED",
    "NOT_CONNECTED",
    "CANCELLED",
    "FAILED",
]

RetryIntervalHours = Literal[0, 3, 6, 9, 12, 24]

WEEKDAYS: tuple[str, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# HH:MM, 24-hour.
TimeOfDay = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class _HunarModel(BaseModel):
    """Base for anything Hunar sends us: keep unknown fields rather than dropping them."""

    model_config = ConfigDict(extra="allow")


class _HunarRequest(BaseModel):
    """Base for anything we send: reject unknown fields so typos fail locally, not as a 422."""

    model_config = ConfigDict(extra="forbid")


class RetryConfig(_HunarRequest):
    """Must be complete or omitted entirely — a partial object is a 422.

    Note the request/response asymmetry documented in CONTRIBUTING.md: we send `max_retry_count`,
    Hunar returns `max_retries`. RetryConfigResponse below models the latter.
    """

    max_retry_count: int = Field(ge=0, le=10)
    retry_interval_hours: RetryIntervalHours


class RetryConfigResponse(_HunarModel):
    max_retries: int | None = None
    retry_interval_hours: int | None = None


class Guardrails(_HunarRequest):
    """Must be complete or omitted entirely; omitting inherits the org defaults.

    Structural rules (>= 3 distinct days, >= 3 hour window) are enforced in preflight.py so
    the failure is local and specific rather than a 422 from the server.
    """

    allowed_days: list[Weekday]
    earliest_call_time: TimeOfDay
    last_call_time: TimeOfDay


class CallbackConfig(_HunarRequest):
    call_status_callback_url: str | None = None
    call_recording_callback_url: str | None = None
    call_result_callback_url: str | None = None
    call_summary_callback_url: str | None = None


class Agent(_HunarModel):
    id: str
    name: str
    language: Language | None = None
    voice_persona: VoicePersona | None = None
    persona_name: str | None = None
    agent_prompt: str | None = None
    objective: str | None = None
    introduction: str | None = None
    result_prompt: str | None = None
    result_schema: dict[str, Any] | None = None
    custom_variables: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentCreate(_HunarRequest):
    """Every field here is required by POST /agents/ per CONTRIBUTING.md."""

    name: str
    language: Language
    voice_persona: VoicePersona
    agent_prompt: str
    objective: str
    introduction: str
    result_prompt: str
    result_schema: dict[str, Any]

    persona_name: str | None = None
    custom_variables: list[str] | None = None
    retry_config: RetryConfig | None = None
    guardrails: Guardrails | None = None
    callback_config: CallbackConfig | None = None


class AgentUpdate(_HunarRequest):
    """PUT /agents/{id}/.

    Changing voice_persona or language requires resending name, objective, language,
    voice_persona, persona_name, agent_prompt, introduction, result_prompt and result_schema
    together (CONTRIBUTING.md). Those fields are therefore all required here rather than optional:
    a partial update that silently drops them is the failure mode this guards against.
    """

    name: str
    objective: str
    language: Language
    voice_persona: VoicePersona
    persona_name: str
    agent_prompt: str
    introduction: str
    result_prompt: str
    result_schema: dict[str, Any]

    custom_variables: list[str] | None = None
    retry_config: RetryConfig | None = None
    guardrails: Guardrails | None = None
    callback_config: CallbackConfig | None = None


class Call(_HunarModel):
    id: str
    agent_id: str | None = None
    callee_name: str | None = None
    mobile_number: str | None = None
    status: CallStatus | None = None
    request_id: str | None = None
    duration_seconds: int | None = None
    recording_url: str | None = None
    # Shaped by the agent's result_schema. There is NO transcript field (CONTRIBUTING.md).
    result: dict[str, Any] | None = None
    custom_data: dict[str, Any] | None = None
    retry_config: RetryConfigResponse | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CallCreate(_HunarRequest):
    """POST /calls/.

    custom_data must contain EVERY key in the agent's custom_variables or Hunar returns 422 —
    preflight.check_custom_data catches that locally first.
    """

    agent_id: str
    callee_name: str
    mobile_number: str
    custom_data: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    retry_config: RetryConfig | None = None
    guardrails: Guardrails | None = None
    callback_config: CallbackConfig | None = None


class PhoneNumber(_HunarModel):
    id: str
    phone_number: str | None = None
    country: str | None = None
    allowed_countries: list[str] = Field(default_factory=list)
    is_active: bool | None = None


class Paginated[T](_HunarModel):
    """Hunar's list envelope.

    `results` accepts the usual DRF-style aliases: the exact key is not pinned down in
    CONTRIBUTING.md, and quietly returning an empty list because we guessed the wrong one would be a
    silent bug. extra="allow" keeps whatever else came back, so nothing is lost either way.
    """

    results: list[T] = Field(
        default_factory=list,
        validation_alias=AliasChoices("results", "data", "items"),
    )
    count: int | None = None
    next: str | None = None
    previous: str | None = None


class HunarError(_HunarModel):
    """Documented error envelope: {success, message, details}."""

    success: bool = False
    message: str | None = None
    details: Any = None


class _WebhookBase(_HunarModel):
    call_id: str | None = None
    request_id: str | None = None
    agent_id: str | None = None
    event_type: str | None = None
    timestamp: datetime | None = None


class CallStatusWebhook(_WebhookBase):
    status: CallStatus | None = None
    lifecycle_status: str | None = None
    answered_by: str | None = None
    engagement_status: str | None = None
    duration_seconds: int | None = None
    error_message: str | None = None


class CallRecordingWebhook(_WebhookBase):
    recording_url: str | None = None
    duration_seconds: int | None = None


class CallResultWebhook(_WebhookBase):
    # Shaped by the agent's result_schema; never assume specific keys.
    result: dict[str, Any] | None = None


class CallSummaryWebhook(_WebhookBase):
    summary: str | None = None
