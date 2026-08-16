"""Strict contracts for the fixed MatrAIx Linux artifact task."""

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

type LinuxStatus = Literal["queued", "running", "succeeded", "failed"]
type LinuxText = Annotated[str, StringConstraints(min_length=1, max_length=4_000)]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class MatraixLinuxTaskSource(ContractModel):
    kind: Literal["source_sample"]
    project: Literal["MatrAIx"]
    canonical_path: Literal["application/tasks/example-computer-use-linux_note-to-csv"]
    production_sut: Literal[False]


class MatraixLinuxTask(ContractModel):
    task_id: Literal["matraix/linux-note-to-csv"]
    version: Literal["1.0.0"]
    schema_version: Literal["matraix-linux-task/note-to-csv-v1"]
    title: Literal["Note to CSV cleanup"]
    domain: Literal["software"]
    source: MatraixLinuxTaskSource
    execution_kind: Literal["linux_artifact_runner"]
    computer_use: Literal[False]
    instruction: LinuxText
    context: LinuxText
    required_artifacts: Annotated[tuple[Identifier, ...], Field(min_length=4, max_length=4)]
    task_spec_sha256: Sha256Digest
    runner_schema_version: Literal["matraix-linux-artifact-runner/v1"]
    runner_spec_sha256: Sha256Digest
    limitations: Annotated[tuple[LinuxText, ...], Field(min_length=1)]


class MatraixLinuxTasksResponse(ContractModel):
    items: tuple[MatraixLinuxTask, ...]
    total: Annotated[int, Field(ge=0)]


class MatraixLinuxTrialCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    cohort_id: UUID
    persona_id: UUID
    task_id: Literal["matraix/linux-note-to-csv"]
    task_version: Literal["1.0.0"]

    @field_validator("cohort_id", "persona_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)


class LinuxCohortRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest


class LinuxPersonaRef(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=99)]
    persona_id: Identifier
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    profile_sha256: Sha256Digest


class LinuxArtifactHashes(ContractModel):
    cleaned_list_csv: Sha256Digest
    submission_json: Sha256Digest
    user_feedback_json: Sha256Digest
    verifier_json: Sha256Digest


class LinuxTrialResult(ContractModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    linux_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    runner_schema_version: Literal["matraix-linux-artifact-runner/v1"]
    runner_spec_sha256: Sha256Digest
    verifier_passed: Literal[True]
    rows_written: Literal[3]
    artifact_sha256: Sha256Digest
    file_sha256: LinuxArtifactHashes
    result_sha256: Sha256Digest
    reason: Annotated[str, StringConstraints(min_length=10, max_length=2_000)]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(ge=1, le=10)]
    feedback_reason: Annotated[str, StringConstraints(min_length=1, max_length=2_000)]


class LinuxTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4_000)]


class MatraixLinuxTrial(ContractModel):
    id: UUID
    status: LinuxStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    task: MatraixLinuxTask
    cohort: LinuxCohortRef
    persona: LinuxPersonaRef
    trial_sha256: Sha256Digest
    result: LinuxTrialResult | None
    error: LinuxTrialError | None

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
            raise ValueError(f"Linux trial fields do not match status {self.status}")
        return self


class MatraixLinuxEvaluation(ContractModel):
    id: UUID
    status: LinuxStatus
    execution_kind: Literal["linux_artifact_runner"]
    registry_eligibility: Literal["sealed_parent"]
    created_at: AwareDatetime
    sealed_at: AwareDatetime
    evaluation_sha256: Sha256Digest
    trial: MatraixLinuxTrial

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if self.sealed_at < self.created_at:
            raise ValueError("Linux evaluation sealed_at must not precede created_at")
        if self.status != self.trial.status:
            raise ValueError("Linux evaluation status must match its single frozen trial")
        return self


class MatraixLinuxTrialsResponse(ContractModel):
    items: tuple[MatraixLinuxTrial, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("Linux trial page exceeds page_size")
        if self.total == 0 and (self.page != 1 or self.items):
            raise ValueError("empty Linux trial directory must return page one")
        if self.total > 0 and (self.page - 1) * self.page_size >= self.total:
            raise ValueError("Linux trial page starts beyond total")
        return self


class MatraixLinuxReadiness(ContractModel):
    engine: Literal["matraix-linux-artifact"]
    runner_version: Literal["1.0.0"]
    worker_online: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    linux_runtime_ready: bool
    configuration_conflict: bool
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None
    linux_config_sha256: Sha256Digest | None
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"] | None
    task: MatraixLinuxTask
    limitations: Annotated[tuple[LinuxText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_configuration(self) -> Self:
        configured = (
            self.model_name is not None
            and self.linux_config_sha256 is not None
            and self.prompt_schema_version is not None
        )
        if self.linux_runtime_ready != configured:
            raise ValueError("Linux readiness configuration must be complete exactly when ready")
        if self.linux_runtime_ready and (not self.worker_online or self.configuration_conflict):
            raise ValueError("Linux runtime cannot be ready without one consistent live worker")
        return self
