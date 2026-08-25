from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models.agent_version import AgentVersion
from app.models.enums import Language
from app.models.persona import Persona
from app.schemas.compiled_jd import CompiledJD
from app.services.jd_compiler import build_agent_version
from tests.services.conftest import load_compiled_fixture

# Fixed to one well-understood fixture (delivery_rider_chennai) rather than parametrized across
# all three like test_jd_compiler.py/test_personas.py: these tests are about simulate.py's and
# score.py's own mechanics, not about JD-to-JD variation, and hand-building personas/transcripts
# is much easier to get right against one known set of questions.
#
#   has_two_wheeler (boolean), has_licence (boolean),
#   preferred_shift (enum: morning/evening/either), years_riding (number),
#   has_smartphone (boolean)
# knockouts: has_two_wheeler/has_licence/has_smartphone eq false.


@pytest.fixture
def compiled() -> CompiledJD:
    return CompiledJD.model_validate(load_compiled_fixture("delivery_rider_chennai"))


@pytest.fixture
def agent_version(compiled: CompiledJD) -> AgentVersion:
    return build_agent_version(compiled, Language.ENGLISH, job_id=uuid.uuid4())


@pytest.fixture
def qualified_ground_truth() -> dict[str, Any]:
    return {
        "has_two_wheeler": True,
        "has_licence": True,
        "preferred_shift": "morning",
        "years_riding": 3.0,
        "has_smartphone": True,
        "interested": True,
        "qualified": True,
    }


@pytest.fixture
def persona(qualified_ground_truth: dict[str, Any]) -> Persona:
    return Persona(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        archetype="QUALIFIED_EAGER",
        profile={
            "name": "Arun Kumar",
            "background": "Has ridden a two-wheeler for years and done gig delivery before.",
            "years_experience": 3.0,
            "skills": ["two-wheeler riding", "city navigation"],
            "situation": "Currently freelancing, looking for steady work.",
            "location": "Chennai",
            "language": "ENGLISH",
        },
        ground_truth=qualified_ground_truth,
        behaviour={
            "verbosity": "normal",
            "cooperativeness": "cooperative",
            "language_switching": False,
            "off_script_questions": [],
        },
    )


def extraction_payload(
    compiled: CompiledJD,
    ground_truth: dict[str, Any],
    *,
    interested: bool | None = None,
    qualified: bool | None = None,
    rejection_reason: str = "",
    earliest_start: str = "Immediately",
) -> dict[str, Any]:
    """A result payload matching build_result_schema(compiled) exactly — every question id plus
    the four standard fields — so it validates against the dynamic extraction model on the
    first try (no repair-retry round trip to account for in a test)."""
    payload = {question.id: ground_truth[question.id] for question in compiled.screening_questions}
    payload["interested"] = ground_truth["interested"] if interested is None else interested
    payload["qualified"] = ground_truth["qualified"] if qualified is None else qualified
    payload["earliest_start"] = earliest_start
    payload["rejection_reason"] = rejection_reason
    return payload
