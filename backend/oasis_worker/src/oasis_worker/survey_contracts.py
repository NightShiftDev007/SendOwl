"""Strict worker contracts for bounded MatrAIx scenario-preference surveys."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SemanticPersona

SURVEY_RUNNER_VERSION = "1.0.0"
SURVEY_INSTRUMENT_SCHEMA_VERSION = "scenario-preference/v1"
SURVEY_PROMPT_SCHEMA_VERSION = "matraix-survey-scenario-preference/v1"
SURVEY_PROFILE_SCHEMA_VERSION = "matraix-survey-profile/v1"
SURVEY_TOOL_NAME = "submit_scenario_preference"
SURVEY_ANSWER_IDS = (
    "preferred_variant",
    "alternative_support",
    "primary_reason",
)


class SurveyRuntimeConfig(StrictModel):
    """Complete non-persisted provider configuration and its public survey identity."""

    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)] = Field(
        repr=False
    )
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["matraix-survey-scenario-preference/v1"]


class SurveyChoice(StrictModel):
    id: Literal["baseline", "alternative"]
    label: Annotated[RequiredText, Field(max_length=200)]
    description: Annotated[RequiredText, Field(max_length=2000)]


class SurveyQuestion(StrictModel):
    position: Annotated[int, Field(ge=0, le=2)]
    id: Literal["preferred_variant", "alternative_support", "primary_reason"]
    type: Literal["single_choice", "likert", "free_text"]
    prompt: Annotated[RequiredText, Field(max_length=4000)]
    required: Literal[True]
    options: tuple[SurveyChoice, ...]
    min_value: Annotated[int, Field(ge=1, le=5)] | None
    max_value: Annotated[int, Field(ge=1, le=5)] | None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        expected = (
            ("preferred_variant", "single_choice"),
            ("alternative_support", "likert"),
            ("primary_reason", "free_text"),
        )[self.position]
        if (self.id, self.type) != expected:
            raise ValueError("survey question id/type must match its fixed position")
        if self.type == "single_choice":
            if tuple(option.id for option in self.options) != ("baseline", "alternative"):
                raise ValueError("preferred_variant options must be baseline then alternative")
            if self.min_value is not None or self.max_value is not None:
                raise ValueError("single-choice question must not define numeric bounds")
        elif self.type == "likert":
            if self.options or self.min_value != 1 or self.max_value != 5:
                raise ValueError("alternative_support must be an optionless 1..5 Likert question")
        elif self.options or self.min_value is not None or self.max_value is not None:
            raise ValueError("free-text question must not define options or numeric bounds")
        return self


class ScenarioPreferenceInstrument(StrictModel):
    schema_version: Literal["scenario-preference/v1"]
    title: Literal["Scenario preference"]
    description: Annotated[RequiredText, Field(max_length=4000)]
    questions: Annotated[tuple[SurveyQuestion, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_questions(self) -> Self:
        if tuple(question.position for question in self.questions) != (0, 1, 2):
            raise ValueError("survey questions must occupy contiguous positions zero through two")
        return self


class SurveyExperiment(StrictModel):
    id: UUID
    scenario_id: UUID
    scenario_sha256: Sha256
    scenario_title: Annotated[RequiredText, Field(max_length=300)]
    decision_question: Annotated[RequiredText, Field(max_length=2000)]
    cohort_id: UUID
    cohort_sha256: Sha256
    cohort_title: Annotated[RequiredText, Field(max_length=200)]
    dataset_sha256: Sha256
    persona_count: Annotated[int, Field(ge=1, le=8)]
    baseline_id: UUID
    baseline_position: Literal[0]
    baseline_name: Annotated[RequiredText, Field(max_length=200)]
    baseline_hypothesis: Annotated[RequiredText, Field(max_length=2000)]
    alternative_id: UUID
    alternative_position: Annotated[int, Field(ge=1, le=5)]
    alternative_name: Annotated[RequiredText, Field(max_length=200)]
    alternative_hypothesis: Annotated[RequiredText, Field(max_length=2000)]
    instrument_schema_version: Literal["scenario-preference/v1"]
    instrument: ScenarioPreferenceInstrument
    instrument_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    survey_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-survey-scenario-preference/v1"]
    experiment_sha256: Sha256
    retry_of_experiment_id: UUID | None
    retry_of_experiment_sha256: Sha256 | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    created_at: datetime

    @model_validator(mode="after")
    def require_distinct_variants(self) -> Self:
        if self.baseline_id == self.alternative_id:
            raise ValueError("survey baseline and alternative must be distinct")
        has_parent = (
            self.retry_of_experiment_id is not None and self.retry_of_experiment_sha256 is not None
        )
        if (self.attempt_number == 1) == has_parent:
            raise ValueError("survey retry lineage does not match attempt number")
        return self


class SurveyCohortMember(StrictModel):
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
            strict=True,
        ),
    ]
    profile_sha256: Sha256


class ClaimedSurveyTrial(StrictModel):
    id: UUID
    status: Literal["running"]
    created_at: datetime
    persona_position: Annotated[int, Field(ge=0, le=7)]
    persona_id: UUID
    persona_external_id: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
            strict=True,
        ),
    ]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile_sha256: Sha256
    trial_sha256: Sha256
    experiment: SurveyExperiment
    persona: SemanticPersona
    cohort_members: Annotated[tuple[SurveyCohortMember, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def validate_persona_binding(self) -> Self:
        if (
            self.persona.position != self.persona_position
            or self.persona.id != self.persona_id
            or self.persona.persona_id != self.persona_external_id
            or self.persona.display_name != self.persona_display_name
            or self.persona.profile_sha256 != self.persona_profile_sha256
        ):
            raise ValueError("survey trial persona does not match the frozen persona binding")
        if len(self.cohort_members) != self.experiment.persona_count:
            raise ValueError("survey cohort member count does not match the experiment")
        if tuple(item.position for item in self.cohort_members) != tuple(
            range(len(self.cohort_members))
        ):
            raise ValueError("survey cohort member positions must be contiguous from zero")
        return self


class PreferredVariantAnswer(StrictModel):
    question_id: Literal["preferred_variant"]
    type: Literal["single_choice"]
    value: Literal["baseline", "alternative"]


class AlternativeSupportAnswer(StrictModel):
    question_id: Literal["alternative_support"]
    type: Literal["likert"]
    value: Annotated[int, Field(strict=True, ge=1, le=5)]


class PrimaryReasonAnswer(StrictModel):
    question_id: Literal["primary_reason"]
    type: Literal["free_text"]
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000, strict=True),
    ]


SurveyAnswer = PreferredVariantAnswer | AlternativeSupportAnswer | PrimaryReasonAnswer


class ExtractedSurveyResponse(StrictModel):
    answers: tuple[
        PreferredVariantAnswer,
        AlternativeSupportAnswer,
        PrimaryReasonAnswer,
    ]

    @field_validator("answers")
    @classmethod
    def require_exact_answer_order(
        cls,
        value: tuple[SurveyAnswer, ...],
    ) -> tuple[SurveyAnswer, ...]:
        if tuple(item.question_id for item in value) != SURVEY_ANSWER_IDS:
            raise ValueError("survey answers must contain the three required questions in order")
        return value


class PositionedPreferredVariantAnswer(PreferredVariantAnswer):
    position: Literal[0]


class PositionedAlternativeSupportAnswer(AlternativeSupportAnswer):
    position: Literal[1]


class PositionedPrimaryReasonAnswer(PrimaryReasonAnswer):
    position: Literal[2]


PositionedSurveyAnswer = (
    PositionedPreferredVariantAnswer
    | PositionedAlternativeSupportAnswer
    | PositionedPrimaryReasonAnswer
)


class SurveySuccess(StrictModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    survey_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-survey-scenario-preference/v1"]
    answers: tuple[
        PositionedPreferredVariantAnswer,
        PositionedAlternativeSupportAnswer,
        PositionedPrimaryReasonAnswer,
    ]
    answers_sha256: Sha256
