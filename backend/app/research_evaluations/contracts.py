"""Strict contracts for the native evaluation workspace."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Sha256Digest

type EvaluationKind = Literal["survey", "chat", "web", "app", "linux"]
type EvaluationIntegrationState = Literal[
    "native_bound", "target_defined", "source_sample_only", "not_implemented"
]
type EvaluationBoundaryState = Literal["available", "partial", "missing"]
type EvaluationText = Annotated[
    str, StringConstraints(min_length=1, max_length=1000, strip_whitespace=True)
]


class ResearchEvaluationProjectRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    project_sha256: Sha256Digest


class ResearchEvaluationRunRef(ContractModel):
    id: UUID
    run_spec_sha256: Sha256Digest
    status: Literal["succeeded"]


class ResearchEvaluationCohortRef(ContractModel):
    id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]


class ResearchEvaluationCapability(ContractModel):
    kind: EvaluationKind
    title: EvaluationText
    integration_state: EvaluationIntegrationState
    can_launch_for_scope: bool
    existing_run_count: Annotated[int, Field(ge=0)]
    explanation: EvaluationText


class ResearchEvaluationRuntimeBoundary(ContractModel):
    name: Literal["task_bundle", "job_runtime", "verifier", "trajectory", "artifact", "reward"]
    state: EvaluationBoundaryState
    explanation: EvaluationText


class ResearchPersonaQualityReport(ContractModel):
    selection_method: Literal["graph_match", "frozen_cohort"]
    graph_origin_sha256: Sha256Digest | None
    profile_count: Annotated[int, Field(ge=1, le=8)]
    populated_profile_count: Annotated[int, Field(ge=0, le=8)]
    minimum_dimension_count: Annotated[int, Field(ge=0, le=1290)]
    maximum_dimension_count: Annotated[int, Field(ge=0, le=1290)]
    quality_state: Literal["verified", "limited"]
    explanation: EvaluationText


class ResearchEvaluationTaskBundleCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_project_id: UUID
    research_simulation_run_id: UUID
    kind: Literal["survey"]

    @field_validator("research_project_id", "research_simulation_run_id", mode="before")
    @classmethod
    def parse_id(cls, value: object, info) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a UUID string")
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{info.field_name} must be a valid UUID string") from error


class ResearchEvaluationTaskBundlePayload(ContractModel):
    schema_version: Literal["sandowl-research-evaluation-task-bundle/v1"]
    kind: Literal["survey"]
    project_sha256: Sha256Digest
    run_spec_sha256: Sha256Digest
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    instrument_schema_version: Literal["single-context-observation/v1"]
    instrument_sha256: Sha256Digest
    persona_profile_sha256s: Annotated[tuple[Sha256Digest, ...], Field(min_length=1, max_length=8)]
    verifier_schema_version: Literal["research-survey-structural-verifier/v1"]
    trajectory_schema_version: Literal["ordered-persona-observations/v1"]
    artifact_schema_version: Literal["sandowl-research-survey-artifact/v1"]
    reward_policy: Literal["not_applicable"]
    limitations: Annotated[tuple[EvaluationText, ...], Field(min_length=1)]


class ResearchEvaluationExecutionProjection(ContractModel):
    evaluation_id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    evaluation_sha256: Sha256Digest
    verifier_state: Literal["pending", "passed", "failed"]
    trajectory_state: Literal["empty", "partial", "complete"]
    recorded_observation_count: Annotated[int, Field(ge=0, le=24)]
    artifact_state: Literal["unavailable", "partial", "sealed"]
    artifact_sha256: Sha256Digest | None
    reward_mode: Literal["not_applicable"]
    reward_value: None


class ResearchEvaluationTaskBundle(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    cohort_id: UUID
    payload: ResearchEvaluationTaskBundlePayload
    bundle_sha256: Sha256Digest
    execution: ResearchEvaluationExecutionProjection | None
    created_at: AwareDatetime
    sealed_at: AwareDatetime


class ResearchEvaluationTargetCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_project_id: UUID
    research_simulation_run_id: UUID
    kind: Literal["chat", "web", "app"]
    title: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=200,
            pattern=r"^[^\r\n]+$",
            strip_whitespace=True,
        ),
    ]
    target_url: Annotated[str, StringConstraints(min_length=8, max_length=500)] | None = None
    task_package: (
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=300,
                pattern=r"^(application/tasks|examples/tasks)/[A-Za-z0-9_.-]+$",
            ),
        ]
        | None
    ) = None
    transport: Literal["rest_chat", "mcp_streamable_http", "playwright_browser", "harbor_task"]
    task_goal: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
    ]
    success_criteria: Annotated[
        tuple[
            Annotated[
                str,
                StringConstraints(
                    min_length=1,
                    max_length=300,
                    pattern=r"^[^\r\n]+$",
                    strip_whitespace=True,
                ),
            ],
            ...,
        ],
        Field(min_length=1, max_length=8),
    ]

    @field_validator("research_project_id", "research_simulation_run_id", mode="before")
    @classmethod
    def parse_id(cls, value: object, info) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a UUID string")
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{info.field_name} must be a valid UUID string") from error

    @field_validator("success_criteria", mode="before")
    @classmethod
    def parse_criteria(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "target_url must be an HTTP(S) URL without credentials, query, or fragment"
            )
        return value

    @model_validator(mode="after")
    def validate_kind_transport(self) -> Self:
        if self.kind == "app":
            if self.transport != "harbor_task" or self.task_package is None:
                raise ValueError("App targets require harbor_task transport and task_package")
            if self.target_url is not None:
                raise ValueError("App targets do not accept target_url")
        elif self.target_url is None or self.task_package is not None:
            raise ValueError("Chat/Web targets require target_url and reject task_package")
        if self.kind == "web" and self.transport != "playwright_browser":
            raise ValueError("Web targets require playwright_browser transport")
        if self.kind == "chat" and self.transport == "playwright_browser":
            raise ValueError("Chat targets require rest_chat or mcp_streamable_http transport")
        if len(set(self.success_criteria)) != len(self.success_criteria):
            raise ValueError("success_criteria must be unique")
        return self


class ResearchEvaluationTargetPayload(ContractModel):
    schema_version: Literal["sandowl-research-evaluation-target/v1"]
    kind: Literal["chat", "web", "app"]
    project_sha256: Sha256Digest
    run_spec_sha256: Sha256Digest
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    target_url: Annotated[str, StringConstraints(min_length=8, max_length=500)] | None = None
    task_package: Annotated[str, StringConstraints(min_length=1, max_length=300)] | None = None
    transport: Literal["rest_chat", "mcp_streamable_http", "playwright_browser", "harbor_task"]
    task_goal: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    success_criteria: Annotated[tuple[EvaluationText, ...], Field(min_length=1, max_length=8)]
    verifier_schema_version: Literal[
        "research-chat-outcome-verifier/v1",
        "research-web-evidence-verifier/v1",
        "research-app-artifact-verifier/v1",
    ]
    execution_policy: Literal["definition_only"]
    limitations: Annotated[tuple[EvaluationText, ...], Field(min_length=1)]


class ResearchEvaluationTarget(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    cohort_id: UUID
    payload: ResearchEvaluationTargetPayload
    target_sha256: Sha256Digest
    created_at: AwareDatetime
    sealed_at: AwareDatetime


class ResearchEvaluationJobCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    research_project_id: UUID
    research_simulation_run_id: UUID
    target_id: UUID

    @field_validator(
        "research_project_id", "research_simulation_run_id", "target_id", mode="before"
    )
    @classmethod
    def parse_id(cls, value: object, info) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name} must be a UUID string")
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{info.field_name} must be a valid UUID string") from error


class ResearchEvaluationJob(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    cohort_id: UUID
    target_id: UUID
    kind: Literal["chat", "web", "app"]
    status: Literal["queued", "dispatching", "running", "succeeded", "failed", "cancelled"]
    job_sha256: Sha256Digest
    retry_of_job_id: UUID | None
    retry_of_job_sha256: Sha256Digest | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    remote_run_id: str | None
    trajectory_sha256: Sha256Digest | None
    artifact_sha256: Sha256Digest | None
    verifier_sha256: Sha256Digest | None
    reward_sha256: Sha256Digest | None
    reward_value: Annotated[float, Field(ge=0, le=1)] | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    error_code: str | None
    error_message: str | None

    @model_validator(mode="after")
    def validate_retry_lineage(self) -> Self:
        has_parent = self.retry_of_job_id is not None and self.retry_of_job_sha256 is not None
        if (self.attempt_number == 1) == has_parent:
            raise ValueError("Harbor Job retry lineage does not match attempt_number")
        return self


class ResearchEvaluationWorkspace(ContractModel):
    schema_version: Literal["sandowl-research-evaluation-workspace/v1"]
    project: ResearchEvaluationProjectRef
    run: ResearchEvaluationRunRef
    cohort: ResearchEvaluationCohortRef
    persona_quality: ResearchPersonaQualityReport
    task_bundles: Annotated[tuple[ResearchEvaluationTaskBundle, ...], Field(max_length=1)]
    targets: Annotated[tuple[ResearchEvaluationTarget, ...], Field(max_length=3)]
    jobs: Annotated[tuple[ResearchEvaluationJob, ...], Field(max_length=20)]
    capabilities: Annotated[tuple[ResearchEvaluationCapability, ...], Field(min_length=5)]
    runtime_boundaries: Annotated[
        tuple[ResearchEvaluationRuntimeBoundary, ...], Field(min_length=6)
    ]
    limitations: Annotated[tuple[EvaluationText, ...], Field(min_length=1)]
