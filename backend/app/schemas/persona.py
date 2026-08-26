"""The JD-independent pieces of the draft schema the LLM fills in when generating one persona.

The full schema (including ground_truth_answers) is JD-specific — built fresh per compiled JD by
app/services/personas.py._build_persona_batch_model — but a persona's profile and behaviour
don't depend on the JD's own questions, so those two pieces live here and get reused as-is.

The model only invents flavour — names, backstories, and the raw answer values a persona would
give for each screening question. `ground_truth.qualified` is never asked of it:
app/services/personas.py computes that itself by applying the JD's knockout_criteria to these
answers, which is what keeps persona scoring objective rather than a self-graded vibe check.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Language

Archetype = Literal[
    "QUALIFIED_EAGER",
    "QUALIFIED_TERSE",
    "UNQUALIFIED_CLEAR",
    "SALARY_FIRST",
    "CODE_SWITCHER",
    "BUSY_HOSTILE",
]
ARCHETYPES: tuple[Archetype, ...] = (
    "QUALIFIED_EAGER",
    "QUALIFIED_TERSE",
    "UNQUALIFIED_CLEAR",
    "SALARY_FIRST",
    "CODE_SWITCHER",
    "BUSY_HOSTILE",
)

Verbosity = Literal["terse", "normal", "verbose"]
Cooperativeness = Literal["cooperative", "neutral", "hostile"]

# The shape one ground-truth answer takes once app/services/personas.py has converted the LLM's
# response back to a plain dict (see _personas_from_batch). The LLM itself is never asked to fill
# a dict[str, AnswerValue] directly — that shape can only ask in prose for one entry per
# screening question, never enforce it. app/services/personas.py._build_persona_batch_model
# builds a fresh, JD-specific model instead, with one REQUIRED field per question id, typed by
# that question's answer_type — the same fresh-schema idea app/services/jd_compiler.py's
# _require_all_properties uses to keep a compiled JD's own fields from being silently optional.
AnswerValue = bool | float | str


class PersonaProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    background: str = Field(min_length=1)
    years_experience: float = Field(ge=0)
    skills: list[str] = Field(default_factory=list)
    situation: str = Field(min_length=1)
    location: str = Field(min_length=1)
    language: Language


class PersonaBehaviourDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verbosity: Verbosity
    cooperativeness: Cooperativeness
    language_switching: bool
    off_script_questions: list[str] = Field(default_factory=list)
