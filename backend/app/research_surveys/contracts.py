"""Strict public contracts for native single-context Persona surveys."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type ResearchSurveyStatus = Literal["queued", "running", "succeeded", "failed"]
type ResearchSurveyPromptVersion = Literal["sandowl-research-survey/v1"]
type ResearchSurveyInstrumentVersion = Literal["single-context-observation/v1"]
type SurveyText = Annotated[
    str, StringConstraints(min_length=1, max_length=4000, strip_whitespace=True)
]


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string") from error


class ResearchSurveyCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_project_id: UUID
    research_simulation_run_id: UUID

    @field_validator("research_project_id", "research_simulation_run_id", mode="before")
    @classmethod
    def parse_id(cls, value: object, info) -> UUID:
        return _uuid(value, info.field_name)


class ResearchSurveyProjectRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$")]
    research_question: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    project_sha256: Sha256Digest


class ResearchSurveyRunRef(ContractModel):
    id: UUID
    simulation_requirement: SurveyText
    initial_post: SurveyText
    run_spec_sha256: Sha256Digest


class ResearchSurveyCohortRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")]
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]


class ResearchSurveyPersonaRef(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Identifier
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    profile_sha256: Sha256Digest


class ResearchSurveyInstrument(ContractModel):
    schema_version: ResearchSurveyInstrumentVersion
    instrument_sha256: Sha256Digest
    title: Literal["Single-context observation"]
    description: SurveyText


class ResearchSurveyLikertAnswer(ContractModel):
    position: Literal[0]
    question_id: Literal["context_clarity"]
    type: Literal["likert"]
    value: Annotated[int, Field(ge=1, le=5)]


class ResearchSurveyFocusAnswer(ContractModel):
    position: Literal[1]
    question_id: Literal["attention_priority"]
    type: Literal["single_choice"]
    value: Literal["evidence", "process", "timing", "impact"]


class ResearchSurveyQuestionAnswer(ContractModel):
    position: Literal[2]
    question_id: Literal["unanswered_question"]
    type: Literal["free_text"]
    value: Annotated[str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)]


class ResearchSurveyTrialResult(ContractModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[
        str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$")
    ]
    survey_config_sha256: Sha256Digest
    prompt_schema_version: ResearchSurveyPromptVersion
    answers_sha256: Sha256Digest
    answers: tuple[
        ResearchSurveyLikertAnswer, ResearchSurveyFocusAnswer, ResearchSurveyQuestionAnswer
    ]


class ResearchSurveyTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ResearchSurveyTrial(ContractModel):
    id: UUID
    status: ResearchSurveyStatus
    persona: ResearchSurveyPersonaRef
    trial_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    result: ResearchSurveyTrialResult | None
    error: ResearchSurveyTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if (self.status == "succeeded") != (self.result is not None):
            raise ValueError("only succeeded trials expose a result")
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("only failed trials expose an error")
        return self


class ResearchSurveyFocusCounts(ContractModel):
    evidence: Annotated[int, Field(ge=0, le=8)]
    process: Annotated[int, Field(ge=0, le=8)]
    timing: Annotated[int, Field(ge=0, le=8)]
    impact: Annotated[int, Field(ge=0, le=8)]


class ResearchSurveyAggregate(ContractModel):
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    context_clarity_mean: Annotated[float, Field(ge=1, le=5)] | None
    attention_priority: ResearchSurveyFocusCounts
    unanswered_questions: tuple[SurveyText, ...]
    limitations: tuple[SurveyText, ...]


class ResearchSurveySummary(ContractModel):
    id: UUID
    status: ResearchSurveyStatus
    project: ResearchSurveyProjectRef
    run: ResearchSurveyRunRef
    cohort: ResearchSurveyCohortRef
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: str
    survey_config_sha256: Sha256Digest
    prompt_schema_version: ResearchSurveyPromptVersion
    instrument_schema_version: ResearchSurveyInstrumentVersion
    instrument_sha256: Sha256Digest
    survey_sha256: Sha256Digest
    created_at: AwareDatetime


class ResearchSurveyDetail(ResearchSurveySummary):
    instrument: ResearchSurveyInstrument
    trials: tuple[ResearchSurveyTrial, ...]
    aggregate: ResearchSurveyAggregate


class ResearchSurveysResponse(ContractModel):
    items: tuple[ResearchSurveySummary, ...]
    total: Annotated[int, Field(ge=0)]


class ResearchSurveyReadiness(ContractModel):
    engine: Literal["matraix-survey"]
    runner_version: Literal["1.0.0"]
    survey_runtime_ready: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    model_name: str | None
    survey_config_sha256: Sha256Digest | None
    prompt_schema_version: ResearchSurveyPromptVersion | None
    instrument_schema_version: ResearchSurveyInstrumentVersion
    limitations: tuple[SurveyText, ...]
