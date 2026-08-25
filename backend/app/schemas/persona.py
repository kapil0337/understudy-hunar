"""Draft schema the LLM fills in when generating one persona.

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

# Not a per-question dynamic type on purpose: KnockoutCriterion.value takes the same approach
# (bool | float | str | list[str]) rather than a schema built fresh per JD. Type CORRECTNESS
# per question is checked afterwards in app/services/personas.py, against answer_type.
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


class PersonaDraft(BaseModel):
    """One persona as the LLM produces it. `qualified` is deliberately absent — see the module
    docstring."""

    model_config = ConfigDict(extra="forbid")

    archetype: Archetype
    profile: PersonaProfileDraft
    ground_truth_answers: dict[str, AnswerValue] = Field(
        description="One entry per screening question id, in the type its answer_type implies."
    )
    expected_interested: bool
    behaviour: PersonaBehaviourDraft


class PersonaBatch(BaseModel):
    """Exactly the six archetypes generate_personas requires, generated together in one call so
    they stay comparable across runs (CLAUDE.md)."""

    model_config = ConfigDict(extra="forbid")

    personas: list[PersonaDraft] = Field(min_length=6, max_length=6)
