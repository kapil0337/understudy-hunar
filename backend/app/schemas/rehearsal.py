"""Schemas shared by app/services/rehearsal/simulate.py and app/services/rehearsal/score.py.

Kept separate from the ORM rows (app/models/rehearsal.py, app/models/persona.py) so simulation
and scoring stay testable against plain data, without a database.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Speaker = Literal["agent", "candidate"]
Severity = Literal["critical", "major", "minor"]
Metric = Literal["extraction_accuracy", "coverage", "faithfulness", "efficiency"]


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: Speaker
    text: str
    turn: int


class SimulatedCall(BaseModel):
    """What simulate_call() produces for one persona. Not yet persisted — the caller turns
    this into a RehearsalCase row."""

    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    transcript: list[TranscriptTurn]
    extracted_result: dict[str, Any]
    turn_count: int
    estimated_seconds: float


class CaseInput(BaseModel):
    """What score.py needs about one simulated persona case. Deliberately not the RehearsalCase
    / Persona ORM rows, so scoring is testable against plain data without a database."""

    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    archetype: str
    ground_truth: dict[str, Any]
    off_script_questions: list[str] = Field(default_factory=list)
    transcript: list[TranscriptTurn]
    extracted_result: dict[str, Any]
    estimated_seconds: float
    turn_count: int


class FieldAccuracy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    field: str
    expected: Any
    actual: Any
    correct: bool


class ExtractionAccuracyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    fields: list[FieldAccuracy]


class EfficiencyCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    estimated_seconds: float
    turn_count: int
    score: float
    flagged: bool


class EfficiencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    cases: list[EfficiencyCase]


class CoverageCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    asked: dict[str, bool]


class CoverageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    cases: list[CoverageCase]


class FaithfulnessViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str
    reason: str


class FaithfulnessCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    score: float
    violations: list[FaithfulnessViolation]


class FaithfulnessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    cases: list[FaithfulnessCase]


class Failure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    metric: Metric
    severity: Severity
    description: str
    transcript_excerpt: str


class RehearsalScore(BaseModel):
    """The composite is never returned without this breakdown (see score.py's module
    docstring) — every caller gets all four components plus the failures list together."""

    model_config = ConfigDict(extra="forbid")

    composite: float
    extraction_accuracy: ExtractionAccuracyResult
    coverage: CoverageResult
    faithfulness: FaithfulnessResult
    efficiency: EfficiencyResult
    failures: list[Failure]
