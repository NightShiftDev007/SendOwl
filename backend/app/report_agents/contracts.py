"""Strict contracts for one sealed-snapshot bounded ReportAgent evidence scope."""

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

from app.evidence.contracts import (
    EvidenceBundleContent,
    EvidenceBundleDetail,
    EvidenceBundlePolicyContent,
)
from app.shared.contracts import ContractModel, Sha256Digest

type ReportAgentToolName = Literal[
    "list_evidence",
    "read_media",
    "read_policy",
    "read_world_snapshot",
    "read_world_graph",
    "read_simulation_run",
    "read_persona_interviews",
]
type ReportAgentDraftStatus = Literal["queued", "running", "succeeded", "failed"]
type Objective = Annotated[
    str,
    StringConstraints(min_length=2, max_length=1000, strip_whitespace=True),
]
type PlanText = Annotated[
    str,
    StringConstraints(min_length=2, max_length=500, strip_whitespace=True),
]
type PlanTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
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


def _request_outline(value: object) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"outline must be an array; received {type(value).__name__}")
    return tuple(value)


class ReportAgentPlanSection(ContractModel):
    position: Annotated[int, Field(ge=0, le=5)]
    title: PlanTitle
    focus: PlanText


class ReportAgentRunRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    world_model_id: UUID
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    objective: Objective
    outline: Annotated[tuple[ReportAgentPlanSection, ...], Field(min_length=2, max_length=6)]
    max_tool_calls: Annotated[int, Field(ge=1, le=20)]

    @field_validator("world_model_id", "world_snapshot_id", mode="before")
    @classmethod
    def parse_uuid_fields(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)

    @field_validator("outline", mode="before")
    @classmethod
    def parse_outline(cls, value: object) -> tuple[object, ...]:
        return _request_outline(value)

    @model_validator(mode="after")
    def validate_outline(self) -> Self:
        if tuple(section.position for section in self.outline) != tuple(range(len(self.outline))):
            raise ValueError("ReportAgent outline positions must be contiguous from zero")
        return self


class ReportAgentToolCall(ContractModel):
    id: UUID
    run_id: UUID
    position: Annotated[int, Field(ge=0, le=19)]
    tool_name: ReportAgentToolName
    target_id: UUID | None
    input_sha256: Sha256Digest
    result_sha256: Sha256Digest
    call_sha256: Sha256Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        target_valid = (self.tool_name == "list_evidence" and self.target_id is None) or (
            self.tool_name
            in (
                "read_media",
                "read_policy",
                "read_world_snapshot",
                "read_world_graph",
                "read_simulation_run",
                "read_persona_interviews",
            )
            and self.target_id is not None
        )
        if not target_valid:
            raise ValueError(f"ReportAgent tool target does not match {self.tool_name}")
        return self


class ReportAgentRun(ContractModel):
    id: UUID
    world_model_id: UUID
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    objective: Objective
    outline: Annotated[tuple[ReportAgentPlanSection, ...], Field(min_length=2, max_length=6)]
    max_tool_calls: Annotated[int, Field(ge=1, le=20)]
    schema_version: Literal[
        "bounded-report-agent-evidence/v1",
        "sandowl-research-run-report-agent/v1",
        "sandowl-research-run-report-agent/v2",
    ]
    research_simulation_run_id: UUID | None
    research_run_report_sha256: Sha256Digest | None
    run_sha256: Sha256Digest
    created_at: AwareDatetime
    tool_calls: Annotated[tuple[ReportAgentToolCall, ...], Field(max_length=20)]
    tool_call_count: Annotated[int, Field(ge=0, le=20)]
    remaining_tool_calls: Annotated[int, Field(ge=0, le=20)]

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        if tuple(section.position for section in self.outline) != tuple(range(len(self.outline))):
            raise ValueError("ReportAgent outline positions must be contiguous from zero")
        if tuple(call.position for call in self.tool_calls) != tuple(range(len(self.tool_calls))):
            raise ValueError("ReportAgent tool calls must be contiguous from zero")
        if any(call.run_id != self.id for call in self.tool_calls):
            raise ValueError("ReportAgent tool calls must belong to the projected run")
        if self.tool_call_count != len(self.tool_calls):
            raise ValueError("tool_call_count must equal the projected tool calls")
        if self.remaining_tool_calls != self.max_tool_calls - self.tool_call_count:
            raise ValueError("remaining_tool_calls must equal the unused explicit budget")
        is_research_run = self.schema_version in (
            "sandowl-research-run-report-agent/v1",
            "sandowl-research-run-report-agent/v2",
        )
        if is_research_run != (self.research_simulation_run_id is not None):
            raise ValueError("ReportAgent research-run scope must match its schema version")
        if is_research_run != (self.research_run_report_sha256 is not None):
            raise ValueError("ReportAgent research report digest must match its schema version")
        return self


class ReportAgentEvidenceDirectoryResult(ContractModel):
    run: ReportAgentRun
    bundle: EvidenceBundleDetail


class ReportAgentMediaReadResult(ContractModel):
    run: ReportAgentRun
    content: EvidenceBundleContent


class ReportAgentPolicyReadResult(ContractModel):
    run: ReportAgentRun
    content: EvidenceBundlePolicyContent


class ReportAgentDraftCitation(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    evidence_kind: Literal[
        "media_article",
        "policy_document",
        "world_snapshot",
        "world_graph",
        "simulation_run",
        "persona_interviews",
    ]
    target_id: UUID
    tool_call_position: Annotated[int, Field(ge=0, le=19)]
    source_label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=500, strip_whitespace=True),
    ]
    quote: Annotated[
        str,
        StringConstraints(min_length=1, max_length=500, strip_whitespace=False),
    ]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("ReportAgent citation offsets must span the exact quote")
        return self


class ReportAgentDraftSection(ContractModel):
    position: Annotated[int, Field(ge=0, le=5)]
    title: PlanTitle
    body_markdown: Annotated[
        str,
        StringConstraints(min_length=1, max_length=5000, strip_whitespace=True),
    ]
    citations: Annotated[
        tuple[ReportAgentDraftCitation, ...],
        Field(min_length=1, max_length=20),
    ]

    @model_validator(mode="after")
    def validate_citation_positions(self) -> Self:
        if tuple(item.position for item in self.citations) != tuple(range(len(self.citations))):
            raise ValueError("ReportAgent section citation positions must be contiguous")
        return self


class ReportAgentCitedDraft(ContractModel):
    id: UUID
    run_id: UUID
    run_sha256: Sha256Digest
    evidence_call_count: Annotated[int, Field(ge=1, le=20)]
    evidence_calls_sha256: Sha256Digest
    input_sha256: Sha256Digest
    retry_of_draft_id: UUID | None
    retry_of_input_sha256: Sha256Digest | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    model_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, strip_whitespace=True),
    ]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["bounded-report-agent-cited-draft/v1"]
    status: ReportAgentDraftStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    title: PlanTitle | None
    sections: Annotated[tuple[ReportAgentDraftSection, ...], Field(max_length=6)]
    draft_sha256: Sha256Digest | None
    error_code: (
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=128, strip_whitespace=True),
        ]
        | None
    )
    error_message: (
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=500, strip_whitespace=True),
        ]
        | None
    )

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        has_retry_parent = (
            self.retry_of_draft_id is not None and self.retry_of_input_sha256 is not None
        )
        if (self.attempt_number == 1) == has_retry_parent:
            raise ValueError("ReportAgent draft retry lineage does not match attempt number")
        if has_retry_parent and self.retry_of_input_sha256 != self.input_sha256:
            raise ValueError("ReportAgent retry must preserve the frozen input digest")
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
        if self.status == "succeeded":
            valid = (
                valid
                and self.title is not None
                and bool(self.sections)
                and self.draft_sha256 is not None
                and self.error_code is None
                and self.error_message is None
            )
        elif self.status == "failed":
            valid = (
                valid
                and self.title is None
                and not self.sections
                and self.draft_sha256 is None
                and self.error_code is not None
                and self.error_message is not None
            )
        else:
            valid = (
                valid
                and self.title is None
                and not self.sections
                and self.draft_sha256 is None
                and self.error_code is None
                and self.error_message is None
            )
        if not valid:
            raise ValueError(f"ReportAgent cited draft fields do not match status {self.status}")
        if self.sections and tuple(section.position for section in self.sections) != tuple(
            range(len(self.sections))
        ):
            raise ValueError("ReportAgent draft section positions must be contiguous")
        return self


class ReportAgentDraftsResponse(ContractModel):
    items: tuple[ReportAgentCitedDraft, ...]
    total: Annotated[int, Field(ge=0)]


__all__ = [
    "ReportAgentEvidenceDirectoryResult",
    "ReportAgentCitedDraft",
    "ReportAgentDraftCitation",
    "ReportAgentDraftSection",
    "ReportAgentDraftsResponse",
    "ReportAgentMediaReadResult",
    "ReportAgentPlanSection",
    "ReportAgentPolicyReadResult",
    "ReportAgentRun",
    "ReportAgentRunRequest",
    "ReportAgentToolCall",
    "ReportAgentToolName",
]
