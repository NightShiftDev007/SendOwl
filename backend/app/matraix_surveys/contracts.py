"""Strict public contracts for MatrAIx scenario-preference surveys."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest

type SurveyStatus = Literal["queued", "running", "succeeded", "failed"]
type SurveyPromptSchemaVersion = Literal["matraix-survey-scenario-preference/v1"]
type SurveyInstrumentSchemaVersion = Literal["scenario-preference/v1"]
type SurveyRunnerVersion = Literal["1.0.0"]
type SurveyModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenCohortTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenHypothesis = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type QuestionPrompt = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type ReasonText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class MatraixSurveyCreateRequest(ContractModel):
    """One immutable Scenario alternative evaluated by every Cohort persona."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario_id: UUID
    cohort_id: UUID
    alternative_id: UUID

    @field_validator("scenario_id", "cohort_id", "alternative_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)


class SurveyScenarioRef(ContractModel):
    id: UUID
    title: FrozenTitle
    decision_question: FrozenHypothesis
    scenario_sha256: Sha256Digest


class SurveyCohortRef(ContractModel):
    id: UUID
    title: FrozenCohortTitle
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]


class SurveyVariantRef(ContractModel):
    id: UUID
    role: Literal["baseline", "alternative"]
    position: Annotated[int, Field(ge=0, le=5)]
    name: FrozenCohortTitle
    hypothesis: FrozenHypothesis

    @model_validator(mode="after")
    def validate_role_position(self) -> Self:
        if (self.role == "baseline") != (self.position == 0):
            raise ValueError("baseline must use position zero and alternative must be nonzero")
        return self


class SurveyPersonaRef(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Identifier
    display_name: FrozenCohortTitle
    profile_sha256: Sha256Digest


class SurveyOption(ContractModel):
    id: Literal["baseline", "alternative"]
    label: FrozenCohortTitle
    description: FrozenHypothesis


class SurveyQuestion(ContractModel):
    position: Annotated[int, Field(ge=0, le=2)]
    id: Literal["preferred_variant", "alternative_support", "primary_reason"]
    type: Literal["single_choice", "likert", "free_text"]
    prompt: QuestionPrompt
    required: Literal[True]
    options: tuple[SurveyOption, ...]
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


class SurveyInstrument(ContractModel):
    schema_version: SurveyInstrumentSchemaVersion
    instrument_sha256: Sha256Digest
    title: Literal["Scenario preference"]
    description: NonEmptyText
    questions: Annotated[tuple[SurveyQuestion, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_questions(self) -> Self:
        if tuple(question.position for question in self.questions) != (0, 1, 2):
            raise ValueError("survey questions must occupy contiguous positions zero through two")
        return self


class SurveyChoiceAnswer(ContractModel):
    position: Literal[0]
    question_id: Literal["preferred_variant"]
    type: Literal["single_choice"]
    value: Literal["baseline", "alternative"]


class SurveyLikertAnswer(ContractModel):
    position: Literal[1]
    question_id: Literal["alternative_support"]
    type: Literal["likert"]
    value: Annotated[int, Field(ge=1, le=5)]


class SurveyFreeTextAnswer(ContractModel):
    position: Literal[2]
    question_id: Literal["primary_reason"]
    type: Literal["free_text"]
    value: ReasonText


type SurveyAnswer = Annotated[
    SurveyChoiceAnswer | SurveyLikertAnswer | SurveyFreeTextAnswer,
    Field(discriminator="type"),
]


class SurveyTrialResult(ContractModel):
    runner_version: SurveyRunnerVersion
    model_name: SurveyModelName
    survey_config_sha256: Sha256Digest
    prompt_schema_version: SurveyPromptSchemaVersion
    answers_sha256: Sha256Digest
    answers: Annotated[tuple[SurveyAnswer, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_answers(self) -> Self:
        if tuple(answer.position for answer in self.answers) != (0, 1, 2):
            raise ValueError("successful survey answers must contain positions zero through two")
        return self


class SurveyTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class MatraixSurveyTrial(ContractModel):
    id: UUID
    status: SurveyStatus
    persona: SurveyPersonaRef
    trial_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    result: SurveyTrialResult | None
    error: SurveyTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None
            valid = valid and self.result is None and self.error is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
            valid = valid and self.result is None and self.error is None
        elif self.status == "succeeded":
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and self.result is not None and self.error is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and self.result is None and self.error is not None
        if not valid:
            raise ValueError(f"survey trial fields do not match status {self.status}")
        return self


class SurveyChoiceCounts(ContractModel):
    baseline_count: Annotated[int, Field(ge=0, le=8)]
    alternative_count: Annotated[int, Field(ge=0, le=8)]


class SurveyLikertAggregate(ContractModel):
    n: Annotated[int, Field(ge=0, le=8)]
    min: Annotated[int, Field(ge=1, le=5)] | None
    max: Annotated[int, Field(ge=1, le=5)] | None
    mean: Annotated[float, Field(strict=True, ge=1.0, le=5.0, allow_inf_nan=False)] | None

    @model_validator(mode="after")
    def validate_empty_state(self) -> Self:
        if (self.n == 0) != (self.min is None and self.max is None and self.mean is None):
            raise ValueError("empty Likert aggregate must expose null statistics")
        if self.n > 0 and (self.min is None or self.max is None or self.mean is None):
            raise ValueError("non-empty Likert aggregate requires min, max, and mean")
        return self


class SurveyFreeTextObservation(ContractModel):
    trial_id: UUID
    persona: SurveyPersonaRef
    text: ReasonText


class SurveyAggregate(ContractModel):
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    preferred_variant: SurveyChoiceCounts
    alternative_support: SurveyLikertAggregate
    primary_reasons: tuple[SurveyFreeTextObservation, ...]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        observed = self.preferred_variant.baseline_count + self.preferred_variant.alternative_count
        if observed != self.succeeded_trial_count:
            raise ValueError("choice counts must equal succeeded_trial_count")
        if self.alternative_support.n != self.succeeded_trial_count:
            raise ValueError("Likert n must equal succeeded_trial_count")
        if len(self.primary_reasons) != self.succeeded_trial_count:
            raise ValueError("primary reasons must contain one item per succeeded trial")
        return self


class MatraixSurveyExperimentSummary(ContractModel):
    id: UUID
    status: SurveyStatus
    created_at: AwareDatetime
    scenario: SurveyScenarioRef
    cohort: SurveyCohortRef
    baseline: SurveyVariantRef
    alternative: SurveyVariantRef
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: SurveyModelName
    survey_config_sha256: Sha256Digest
    prompt_schema_version: SurveyPromptSchemaVersion
    instrument_schema_version: SurveyInstrumentSchemaVersion
    instrument_sha256: Sha256Digest
    experiment_sha256: Sha256Digest
    retry_of_experiment_id: UUID | None
    retry_of_experiment_sha256: Sha256Digest | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]

    @model_validator(mode="after")
    def validate_attempt_lineage(self) -> Self:
        has_parent = (
            self.retry_of_experiment_id is not None and self.retry_of_experiment_sha256 is not None
        )
        if (self.attempt_number == 1) == has_parent:
            raise ValueError("root Survey attempts have no parent; later attempts require one")
        return self


class MatraixSurveyExperimentDetail(MatraixSurveyExperimentSummary):
    instrument: SurveyInstrument
    trials: Annotated[tuple[MatraixSurveyTrial, ...], Field(min_length=1, max_length=8)]
    aggregate: SurveyAggregate

    @model_validator(mode="after")
    def validate_trial_projection(self) -> Self:
        if len(self.trials) != self.trial_count:
            raise ValueError("trial_count must equal trials length")
        if tuple(trial.persona.position for trial in self.trials) != tuple(range(len(self.trials))):
            raise ValueError("survey trials must follow contiguous cohort positions")
        succeeded = sum(trial.status == "succeeded" for trial in self.trials)
        failed = sum(trial.status == "failed" for trial in self.trials)
        if succeeded != self.succeeded_trial_count or failed != self.failed_trial_count:
            raise ValueError("summary terminal counts must match trial statuses")
        return self


class MatraixSurveyExperimentsResponse(ContractModel):
    items: Annotated[tuple[MatraixSurveyExperimentSummary, ...], Field(max_length=50)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]
    total: Annotated[int, Field(ge=0)]


class MatraixSurveyReadiness(ContractModel):
    engine: Literal["matraix-survey"]
    runner_version: SurveyRunnerVersion
    worker_online: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    survey_runtime_ready: bool
    configuration_conflict: bool
    model_name: SurveyModelName | None
    survey_config_sha256: Sha256Digest | None
    prompt_schema_version: SurveyPromptSchemaVersion | None
    instrument_schema_version: SurveyInstrumentSchemaVersion
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.worker_online != (self.live_worker_count > 0):
            raise ValueError("worker_online must equal live_worker_count > 0")
        has_config = all(
            value is not None
            for value in (
                self.model_name,
                self.survey_config_sha256,
                self.prompt_schema_version,
            )
        )
        if (
            any(
                value is not None
                for value in (
                    self.model_name,
                    self.survey_config_sha256,
                    self.prompt_schema_version,
                )
            )
            != has_config
        ):
            raise ValueError("survey config fields must be all present or all absent")
        expected_ready = self.worker_online and not self.configuration_conflict and has_config
        if self.survey_runtime_ready != expected_ready:
            raise ValueError("survey_runtime_ready requires one non-conflicting live config")
        if not self.survey_runtime_ready and has_config:
            raise ValueError("unready survey projection must not expose a selected config")
        return self


__all__ = [
    "MatraixSurveyCreateRequest",
    "MatraixSurveyExperimentDetail",
    "MatraixSurveyExperimentSummary",
    "MatraixSurveyExperimentsResponse",
    "MatraixSurveyReadiness",
    "MatraixSurveyTrial",
    "SurveyAggregate",
    "SurveyAnswer",
    "SurveyCohortRef",
    "SurveyInstrument",
    "SurveyPersonaRef",
    "SurveyPromptSchemaVersion",
    "SurveyScenarioRef",
    "SurveyStatus",
    "SurveyTrialResult",
    "SurveyVariantRef",
]
