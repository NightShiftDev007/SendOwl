"""Strict public contracts for bounded MatrAIx Playwright evaluations."""

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

from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type WebStatus = Literal["queued", "running", "succeeded", "failed"]
type WebTaskId = Literal["matraix/quotes-playwright-choice"]
type WebTaskVersion = Literal["1.0.0"]
type WebPromptSchemaVersion = Literal["matraix-web-quotes-choice/v1"]
type WebRunnerVersion = Literal["1.0.0"]
type WebExecutorSchemaVersion = Literal["matraix-web-browser-executor/v1"]
type WebText = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
type WebReason = Annotated[str, StringConstraints(min_length=20, max_length=2000)]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class MatraixWebTaskSource(ContractModel):
    kind: Literal["source_sample"]
    project: Literal["MatrAIx"]
    canonical_path: Literal["application/tasks/example-web-playwright_quote-choice"]
    production_sut: Literal[False]


class MatraixWebTask(ContractModel):
    task_id: WebTaskId
    version: WebTaskVersion
    schema_version: Literal["matraix-web-task/quote-choice-v1"]
    title: Literal["Quote to save"]
    domain: Literal["arts-culture"]
    source: MatraixWebTaskSource
    transport: Literal["playwright_chromium"]
    target_origin: Literal["https://quotes.toscrape.com"]
    instruction: WebText
    context: WebText
    page_count: Literal[3]
    maximum_quote_count: Literal[60]
    task_spec_sha256: Sha256Digest
    executor_schema_version: WebExecutorSchemaVersion
    executor_spec_sha256: Sha256Digest
    limitations: Annotated[tuple[WebText, ...], Field(min_length=1)]


class MatraixWebTasksResponse(ContractModel):
    items: tuple[MatraixWebTask, ...]
    total: Annotated[int, Field(ge=0)]


class MatraixWebEvaluationCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cohort_id: UUID
    task_id: WebTaskId
    task_version: WebTaskVersion

    @field_validator("cohort_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)


class WebCohortRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=4)]


class WebPersonaRef(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=3)]
    persona_id: Identifier
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    profile_sha256: Sha256Digest


class WebQuoteObservation(ContractModel):
    position: Annotated[int, Field(ge=0, le=59)]
    quote_id: Sha256Digest
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    author: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    tags: Annotated[tuple[Identifier, ...], Field(max_length=20)]


class WebPageObservation(ContractModel):
    position: Annotated[int, Field(ge=0, le=2)]
    url: Annotated[
        str,
        StringConstraints(
            min_length=28,
            max_length=200,
            pattern=r"^https://quotes\.toscrape\.com/(?:page/[1-9][0-9]*/)?$",
        ),
    ]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    screenshot_sha256: Sha256Digest
    screenshot_path: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=200,
            pattern=r"^/api/v2/matraix/web-trials/[0-9a-f-]{36}/screenshots/[0-2]$",
        ),
    ]
    observed_at: AwareDatetime
    quotes: Annotated[tuple[WebQuoteObservation, ...], Field(min_length=1, max_length=20)]


class WebTrialResult(ContractModel):
    runner_version: WebRunnerVersion
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    web_config_sha256: Sha256Digest
    prompt_schema_version: WebPromptSchemaVersion
    trace_sha256: Sha256Digest
    result_sha256: Sha256Digest
    decision_subject_id: Sha256Digest
    decision_subject_label: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    decision_outcome: Literal["selected"]
    basis_primary: Literal[
        "price",
        "quality",
        "features",
        "convenience",
        "taste",
        "trust",
        "familiarity",
        "novelty",
        "fit",
        "other",
    ]
    exploration_style: Literal["compared_multiple"]
    reason: WebReason
    task_author: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(ge=1, le=10)]


class WebTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class MatraixWebTrial(ContractModel):
    id: UUID
    status: WebStatus
    persona: WebPersonaRef
    trial_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    pages: Annotated[tuple[WebPageObservation, ...], Field(max_length=3)]
    result: WebTrialResult | None
    error: WebTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        page_positions = tuple(page.position for page in self.pages)
        if page_positions != tuple(range(len(self.pages))):
            raise ValueError("web page positions must be contiguous and start at zero")
        quote_positions = tuple(quote.position for page in self.pages for quote in page.quotes)
        if quote_positions and quote_positions != tuple(range(len(quote_positions))):
            raise ValueError("web quote positions must be contiguous and start at zero")
        if self.status == "queued":
            valid = (
                self.started_at is None
                and self.completed_at is None
                and not self.pages
                and self.result is None
                and self.error is None
            )
        elif self.status == "running":
            valid = (
                self.started_at is not None
                and self.completed_at is None
                and self.result is None
                and self.error is None
            )
        elif self.status == "succeeded":
            quote_ids = {quote.quote_id for page in self.pages for quote in page.quotes}
            valid = self.result is not None and (
                self.started_at is not None
                and self.completed_at is not None
                and len(self.pages) == 3
                and self.error is None
                and self.result.decision_subject_id in quote_ids
            )
        else:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.result is None
                and self.error is not None
            )
        if not valid:
            raise ValueError(f"web trial fields do not match status {self.status}")
        return self


class MatraixWebTrialSummary(ContractModel):
    id: UUID
    status: WebStatus
    persona: WebPersonaRef
    trial_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    observed_page_count: Annotated[int, Field(ge=0, le=3)]
    observed_quote_count: Annotated[int, Field(ge=0, le=60)]
    selected_quote_id: Sha256Digest | None
    error: WebTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        terminal = self.status in {"succeeded", "failed"}
        valid_timestamps = (self.status == "queued") == (self.started_at is None)
        valid_timestamps = valid_timestamps and terminal == (self.completed_at is not None)
        if self.status == "succeeded":
            valid_output = (
                self.observed_page_count == 3
                and self.observed_quote_count >= 3
                and self.selected_quote_id is not None
                and self.error is None
            )
        elif self.status == "failed":
            valid_output = self.selected_quote_id is None and self.error is not None
        else:
            valid_output = self.selected_quote_id is None and self.error is None
        if not valid_timestamps or not valid_output:
            raise ValueError(f"web trial summary fields do not match status {self.status}")
        return self


class MatraixWebEvaluationSummary(ContractModel):
    id: UUID
    status: WebStatus
    created_at: AwareDatetime
    task: MatraixWebTask
    cohort: WebCohortRef
    trial_count: Annotated[int, Field(ge=1, le=4)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=4)]
    failed_trial_count: Annotated[int, Field(ge=0, le=4)]
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    web_config_sha256: Sha256Digest
    prompt_schema_version: WebPromptSchemaVersion
    evaluation_sha256: Sha256Digest
    retry_of_evaluation_id: UUID | None
    retry_of_evaluation_sha256: Sha256Digest | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.succeeded_trial_count + self.failed_trial_count > self.trial_count:
            raise ValueError("web terminal trial counts cannot exceed trial_count")
        has_parent = (
            self.retry_of_evaluation_id is not None and self.retry_of_evaluation_sha256 is not None
        )
        if (self.attempt_number == 1) == has_parent:
            raise ValueError("root Web attempts have no parent; later attempts require one")
        return self


class MatraixWebEvaluationDetail(MatraixWebEvaluationSummary):
    trials: tuple[MatraixWebTrialSummary, ...]

    @model_validator(mode="after")
    def validate_trials(self) -> Self:
        if len(self.trials) != self.trial_count:
            raise ValueError("web evaluation detail must contain every trial summary")
        if tuple(trial.persona.position for trial in self.trials) != tuple(range(self.trial_count)):
            raise ValueError("web evaluation trials must follow frozen Persona order")
        statuses = tuple(trial.status for trial in self.trials)
        succeeded_count = statuses.count("succeeded")
        failed_count = statuses.count("failed")
        if succeeded_count != self.succeeded_trial_count or failed_count != self.failed_trial_count:
            raise ValueError("web evaluation counts must match trial summaries")
        expected_status = (
            "queued"
            if all(status == "queued" for status in statuses)
            else "running"
            if any(status in {"queued", "running"} for status in statuses)
            else "succeeded"
            if all(status == "succeeded" for status in statuses)
            else "failed"
        )
        if self.status != expected_status:
            raise ValueError("web evaluation status must match trial summaries")
        return self


class MatraixWebEvaluationsResponse(ContractModel):
    items: tuple[MatraixWebEvaluationSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("web evaluation page exceeds page_size")
        if self.total == 0 and (self.page != 1 or self.items):
            raise ValueError("empty web evaluation directory must return page one")
        if self.total > 0 and (self.page - 1) * self.page_size >= self.total:
            raise ValueError("web evaluation page starts beyond total")
        return self


class MatraixWebReadiness(ContractModel):
    engine: Literal["matraix-web-playwright"]
    runner_version: WebRunnerVersion
    worker_online: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    web_runtime_ready: bool
    configuration_conflict: bool
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None
    web_config_sha256: Sha256Digest | None
    prompt_schema_version: WebPromptSchemaVersion | None
    task: MatraixWebTask
    limitations: Annotated[tuple[WebText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        configured = (
            self.model_name is not None
            and self.web_config_sha256 is not None
            and self.prompt_schema_version is not None
        )
        if self.web_runtime_ready != configured:
            raise ValueError("web readiness configuration must be complete exactly when ready")
        if self.web_runtime_ready and (not self.worker_online or self.configuration_conflict):
            raise ValueError("web runtime cannot be ready without one consistent live worker")
        return self
