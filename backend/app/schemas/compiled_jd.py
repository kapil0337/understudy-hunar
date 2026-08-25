"""The compiled representation of a job description.

This is the contract between the JD compiler and everything downstream: the agent prompt, the
screening logic, the candidate search, and the faithfulness metric.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import Language

AnswerType = Literal["boolean", "number", "enum", "free_text"]
KnockoutOperator = Literal["eq", "neq", "gte", "lte", "gt", "lt", "in", "not_in"]

MIN_SCREENING_QUESTIONS = 4
MAX_SCREENING_QUESTIONS = 6


class ScreeningQuestion(BaseModel):
    """One question the agent asks aloud.

    Must be answerable in a 90-second phone call with no resume in hand — so no "what was your
    CTC in 2019", no "read me your certificate number". See
    jd_compiler.find_document_dependent_questions for the (heuristic) backstop on that rule.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{0,39}$",
        description="snake_case; becomes a key in the flat result_schema",
    )
    text: str = Field(min_length=1)
    answer_type: AnswerType
    options: list[str] | None = Field(
        default=None, description="Required when answer_type is enum; forbidden otherwise."
    )
    why_it_matters: str = Field(min_length=1)

    @model_validator(mode="after")
    def _options_match_answer_type(self) -> ScreeningQuestion:
        if self.answer_type == "enum":
            if not self.options:
                raise ValueError(f"question {self.id!r}: answer_type 'enum' requires options")
            if len(self.options) < 2:
                raise ValueError(f"question {self.id!r}: enum needs at least 2 options")
        elif self.options:
            raise ValueError(
                f"question {self.id!r}: options are only valid when answer_type is 'enum'"
            )
        return self


class KnockoutCriterion(BaseModel):
    """A disqualifying condition, evaluated against one screening answer."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    operator: KnockoutOperator
    value: bool | float | str | list[str]


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    min_years: float | None = None


class CompiledJD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_title: str = Field(min_length=1)
    seniority: str
    employment_type: str

    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    min_years_experience: float | None = None

    locations: list[str] = Field(default_factory=list)
    shift_pattern: str | None = None
    salary_range: str | None = None

    candidate_languages: list[Language] = Field(
        default_factory=list,
        description="Hunar language enums, inferred from locations. Language belongs to the "
        "AGENT, so each entry implies a separate agent version.",
    )

    screening_questions: list[ScreeningQuestion] = Field(
        min_length=MIN_SCREENING_QUESTIONS, max_length=MAX_SCREENING_QUESTIONS
    )
    knockout_criteria: list[KnockoutCriterion] = Field(default_factory=list)

    facts_the_agent_may_state: list[str] = Field(
        min_length=1,
        description=(
            "The ONLY claims the agent may make about the role. Anything the agent says beyond "
            "this list counts as a fabrication at scoring time. This is what makes the "
            "faithfulness metric objective rather than a vibe check."
        ),
    )

    search_query: SearchQuery

    @model_validator(mode="after")
    def _knockouts_reference_real_questions(self) -> CompiledJD:
        known = {question.id for question in self.screening_questions}
        unknown = [c.question_id for c in self.knockout_criteria if c.question_id not in known]
        if unknown:
            raise ValueError(
                "knockout_criteria reference unknown question_id(s): "
                f"{', '.join(sorted(set(unknown)))}"
            )
        return self

    @model_validator(mode="after")
    def _question_ids_are_unique(self) -> CompiledJD:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for question in self.screening_questions:
            if question.id in seen:
                duplicates.add(question.id)
            seen.add(question.id)
        if duplicates:
            raise ValueError(f"duplicate screening question id(s): {', '.join(sorted(duplicates))}")
        return self

    @model_validator(mode="after")
    def _enum_knockouts_use_declared_options(self) -> CompiledJD:
        """An `in`/`eq` knockout against an enum question must use options that question offers,
        otherwise the criterion can never fire and the knockout is silently dead."""
        by_id = {question.id: question for question in self.screening_questions}
        for criterion in self.knockout_criteria:
            question = by_id.get(criterion.question_id)
            if question is None or question.answer_type != "enum" or not question.options:
                continue
            values = criterion.value if isinstance(criterion.value, list) else [criterion.value]
            unknown = [str(v) for v in values if isinstance(v, str) and v not in question.options]
            if unknown:
                raise ValueError(
                    f"knockout on {criterion.question_id!r} references value(s) not in that "
                    f"question's options: {', '.join(unknown)}"
                )
        return self
