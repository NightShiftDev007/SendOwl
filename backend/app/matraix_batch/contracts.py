"""Strict contracts for the registry-only MatrAIx batch projection."""

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

from app.shared.contracts import ContractModel, Sha256Digest

type MatraixBatchKind = Literal["survey", "chat", "web", "linux"]
type MatraixObservedTrialStatus = Literal["queued", "running", "succeeded", "failed"]
type BatchTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type SourceTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type ModelName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type SourceDetailPath = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^/api/v2/[A-Za-z0-9/_-]+$"),
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


class SurveyBatchRegistrySelection(ContractModel):
    kind: Literal["survey"]
    parent_id: UUID


class ChatBatchRegistrySelection(ContractModel):
    kind: Literal["chat"]
    parent_id: UUID


class WebBatchRegistrySelection(ContractModel):
    kind: Literal["web"]
    parent_id: UUID


class LinuxBatchRegistrySelection(ContractModel):
    kind: Literal["linux"]
    parent_id: UUID


type MatraixBatchRegistrySelection = Annotated[
    SurveyBatchRegistrySelection
    | ChatBatchRegistrySelection
    | WebBatchRegistrySelection
    | LinuxBatchRegistrySelection,
    Field(discriminator="kind"),
]


class MatraixBatchRegistryCreateRequest(ContractModel):
    """An ordered set of already sealed parent runs, never an execution request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: BatchTitle
    items: Annotated[tuple[MatraixBatchRegistrySelection, ...], Field(min_length=1, max_length=20)]

    @field_validator("items", mode="before")
    @classmethod
    def parse_parent_ids(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        parsed: list[object] = []
        for item in value:
            if not isinstance(item, dict):
                parsed.append(item)
                continue
            copied = dict(item)
            if "parent_id" in copied:
                copied["parent_id"] = _request_uuid(copied["parent_id"], "parent_id")
            parsed.append(copied)
        return tuple(parsed)

    @model_validator(mode="after")
    def validate_unique_sources(self) -> Self:
        references = tuple((item.kind, item.parent_id) for item in self.items)
        if len(set(references)) != len(references):
            raise ValueError("batch registry items must contain unique source references")
        return self


class MatraixNativeSurveyLaunchItem(ContractModel):
    kind: Literal["survey"]
    research_project_id: UUID
    research_simulation_run_id: UUID

    @field_validator("research_project_id", "research_simulation_run_id", mode="before")
    @classmethod
    def parse_resource_ids(cls, value: object, info: object) -> UUID:
        field_name = getattr(info, "field_name", "resource_id")
        return _request_uuid(value, field_name)


class MatraixNativeChatLaunchItem(ContractModel):
    kind: Literal["chat"]
    cohort_id: UUID
    task_id: Literal[
        "matraix/acme-support-order-4521",
        "matraix/acme-support-mcp-order-4521",
    ]
    task_version: Literal["1.0.0"]

    @field_validator("cohort_id", mode="before")
    @classmethod
    def parse_cohort_id(cls, value: object) -> UUID:
        return _request_uuid(value, "cohort_id")


type MatraixNativeBatchLaunchItem = Annotated[
    MatraixNativeSurveyLaunchItem | MatraixNativeChatLaunchItem,
    Field(discriminator="kind"),
]


class MatraixNativeBatchLaunchRequest(ContractModel):
    """An ordered, atomic native enqueue plan over supported SandOwl runtimes."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    title: BatchTitle
    items: Annotated[tuple[MatraixNativeBatchLaunchItem, ...], Field(min_length=1, max_length=20)]

    @field_validator("items", mode="before")
    @classmethod
    def parse_items(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_unique_specs(self) -> Self:
        specs = tuple(
            (item.kind, tuple(sorted(item.model_dump(mode="json").items()))) for item in self.items
        )
        if len(set(specs)) != len(specs):
            raise ValueError("native batch launch items must contain unique execution specs")
        return self


class SurveyBatchRegistryItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    kind: Literal["survey"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: SourceTitle
    version: Literal["scenario-preference/v1", "single-context-observation/v1"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal[
        "matraix-survey-scenario-preference/v1", "sandowl-research-survey/v1"
    ]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        expected_path = (
            f"/api/v2/research-surveys/{self.parent_id}"
            if self.version == "single-context-observation/v1"
            else f"/api/v2/matraix/survey-experiments/{self.parent_id}"
        )
        if self.source_detail_path != expected_path:
            raise ValueError("Survey source_detail_path must address the source parent")
        return self


class ChatBatchRegistryItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    kind: Literal["chat"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Acme support: late order #4521"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/chat-evaluations/{self.parent_id}":
            raise ValueError("Chat source_detail_path must address the source parent")
        return self


class WebBatchRegistryItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    kind: Literal["web"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Quote to save"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=4)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=4)]
    failed_trial_count: Annotated[int, Field(ge=0, le=4)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/web-evaluations/{self.parent_id}":
            raise ValueError("Web source_detail_path must address the source parent")
        return self


class LinuxBatchRegistryItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    kind: Literal["linux"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Note to CSV cleanup"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Literal[1]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=1)]
    failed_trial_count: Annotated[int, Field(ge=0, le=1)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/linux-evaluations/{self.parent_id}":
            raise ValueError("Linux source_detail_path must address the source parent")
        return self


type MatraixBatchRegistryItem = Annotated[
    SurveyBatchRegistryItem | ChatBatchRegistryItem | WebBatchRegistryItem | LinuxBatchRegistryItem,
    Field(discriminator="kind"),
]


class SurveyBatchRegistryCandidate(ContractModel):
    kind: Literal["survey"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: SourceTitle
    version: Literal["scenario-preference/v1", "single-context-observation/v1"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal[
        "matraix-survey-scenario-preference/v1", "sandowl-research-survey/v1"
    ]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        expected_path = (
            f"/api/v2/research-surveys/{self.parent_id}"
            if self.version == "single-context-observation/v1"
            else f"/api/v2/matraix/survey-experiments/{self.parent_id}"
        )
        if self.source_detail_path != expected_path:
            raise ValueError("Survey source_detail_path must address the source parent")
        return self


class ChatBatchRegistryCandidate(ContractModel):
    kind: Literal["chat"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Acme support: late order #4521"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/chat-evaluations/{self.parent_id}":
            raise ValueError("Chat source_detail_path must address the source parent")
        return self


class WebBatchRegistryCandidate(ContractModel):
    kind: Literal["web"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Quote to save"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Annotated[int, Field(ge=1, le=4)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=4)]
    failed_trial_count: Annotated[int, Field(ge=0, le=4)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/web-evaluations/{self.parent_id}":
            raise ValueError("Web source_detail_path must address the source parent")
        return self


class LinuxBatchRegistryCandidate(ContractModel):
    kind: Literal["linux"]
    parent_id: UUID
    parent_sha256: Sha256Digest
    title: Literal["Note to CSV cleanup"]
    version: Literal["1.0.0"]
    observed_status: MatraixObservedTrialStatus
    created_at: AwareDatetime
    trial_count: Literal[1]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=1)]
    failed_trial_count: Annotated[int, Field(ge=0, le=1)]
    model_name: ModelName
    parent_config_sha256: Sha256Digest
    prompt_schema_version: Literal["matraix-linux-note-to-csv/v1"]
    source_detail_path: SourceDetailPath

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_observed_counts(
            self.observed_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if self.source_detail_path != f"/api/v2/matraix/linux-evaluations/{self.parent_id}":
            raise ValueError("Linux source_detail_path must address the source parent")
        return self


type MatraixBatchRegistryCandidate = Annotated[
    SurveyBatchRegistryCandidate
    | ChatBatchRegistryCandidate
    | WebBatchRegistryCandidate
    | LinuxBatchRegistryCandidate,
    Field(discriminator="kind"),
]


def _validate_observed_counts(
    status: MatraixObservedTrialStatus,
    trial_count: int,
    succeeded_count: int,
    failed_count: int,
) -> None:
    terminal_count = succeeded_count + failed_count
    if terminal_count > trial_count:
        raise ValueError("terminal trial counts must not exceed trial_count")
    if status == "queued" and terminal_count != 0:
        raise ValueError("queued observation must not contain terminal trials")
    if status == "running" and terminal_count >= trial_count:
        raise ValueError("running observation requires at least one non-terminal trial")
    if status == "succeeded" and (succeeded_count != trial_count or failed_count != 0):
        raise ValueError("succeeded observation requires every trial to succeed")
    if status == "failed" and (terminal_count != trial_count or failed_count == 0):
        raise ValueError("failed observation requires terminal trials and at least one failure")


class MatraixBatchRegistrySummary(ContractModel):
    id: UUID
    title: BatchTitle
    registry_state: Literal["sealed"]
    execution_kind: Literal["registry_only"]
    observed_trial_status: MatraixObservedTrialStatus
    observed_at: AwareDatetime
    created_at: AwareDatetime
    sealed_at: AwareDatetime
    registry_sha256: Sha256Digest
    item_count: Annotated[int, Field(ge=1, le=20)]
    trial_count: Annotated[int, Field(ge=1, le=160)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=160)]
    failed_trial_count: Annotated[int, Field(ge=0, le=160)]

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.sealed_at < self.created_at:
            raise ValueError("sealed_at must not precede created_at")
        _validate_observed_counts(
            self.observed_trial_status,
            self.trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        return self


class MatraixBatchRegistryDetail(MatraixBatchRegistrySummary):
    items: Annotated[tuple[MatraixBatchRegistryItem, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_items(self) -> Self:
        if tuple(item.position for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("batch registry item positions must be contiguous from zero")
        if len(self.items) != self.item_count:
            raise ValueError("item_count must match items")
        if sum(item.trial_count for item in self.items) != self.trial_count:
            raise ValueError("trial_count must match items")
        if sum(item.succeeded_trial_count for item in self.items) != self.succeeded_trial_count:
            raise ValueError("succeeded_trial_count must match items")
        if sum(item.failed_trial_count for item in self.items) != self.failed_trial_count:
            raise ValueError("failed_trial_count must match items")
        return self


class MatraixNativeBatchLaunchResult(ContractModel):
    launch_mode: Literal["native_parent_enqueue"]
    registry: MatraixBatchRegistryDetail


class MatraixBatchRegistriesResponse(ContractModel):
    items: tuple[MatraixBatchRegistrySummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size or self.total < len(self.items):
            raise ValueError("batch registry page counts are inconsistent")
        if any(item.observed_at != self.observed_at for item in self.items):
            raise ValueError("batch registry summaries must share the response observation time")
        return self


class MatraixBatchRegistryCandidatesResponse(ContractModel):
    items: tuple[MatraixBatchRegistryCandidate, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size or self.total < len(self.items):
            raise ValueError("batch registry candidate page counts are inconsistent")
        return self


__all__ = [
    "ChatBatchRegistryItem",
    "ChatBatchRegistryCandidate",
    "LinuxBatchRegistryCandidate",
    "LinuxBatchRegistryItem",
    "MatraixBatchKind",
    "MatraixBatchRegistriesResponse",
    "MatraixBatchRegistryCandidatesResponse",
    "MatraixBatchRegistryCandidate",
    "MatraixBatchRegistryCreateRequest",
    "MatraixBatchRegistryDetail",
    "MatraixBatchRegistryItem",
    "MatraixBatchRegistrySummary",
    "MatraixNativeBatchLaunchItem",
    "MatraixNativeBatchLaunchRequest",
    "MatraixNativeBatchLaunchResult",
    "MatraixNativeChatLaunchItem",
    "MatraixNativeSurveyLaunchItem",
    "MatraixObservedTrialStatus",
    "SurveyBatchRegistryItem",
    "SurveyBatchRegistryCandidate",
    "WebBatchRegistryCandidate",
    "WebBatchRegistryItem",
]
