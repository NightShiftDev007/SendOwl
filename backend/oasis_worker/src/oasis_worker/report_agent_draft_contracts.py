"""Strict worker contracts for bounded, evidence-cited ReportAgent drafts."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel

DRAFT_PROMPT_SCHEMA_VERSION = "bounded-report-agent-cited-draft/v1"
EvidenceKind = Literal[
    "media_article",
    "policy_document",
    "world_snapshot",
    "world_graph",
    "simulation_run",
    "persona_interviews",
]


class ReportAgentDraftPlanSection(StrictModel):
    position: Annotated[int, Field(ge=0, le=5)]
    title: Annotated[RequiredText, Field(max_length=200)]
    focus: Annotated[RequiredText, Field(max_length=500)]


class ReportAgentDraftEvidence(StrictModel):
    evidence_position: Annotated[int, Field(ge=0, le=19)]
    tool_call_position: Annotated[int, Field(ge=0, le=19)]
    evidence_kind: EvidenceKind
    target_id: UUID
    source_label: Annotated[RequiredText, Field(max_length=500)]
    captured_text: Annotated[str, StringConstraints(min_length=1, max_length=80000, strict=True)]
    content_sha256: Sha256


class ClaimedReportAgentDraft(StrictModel):
    id: UUID
    run_id: UUID
    run_sha256: Sha256
    evidence_call_count: Annotated[int, Field(ge=1, le=20)]
    evidence_calls_sha256: Sha256
    input_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["bounded-report-agent-cited-draft/v1"]
    created_at: datetime
    objective: Annotated[RequiredText, Field(max_length=1000)]
    outline: Annotated[tuple[ReportAgentDraftPlanSection, ...], Field(min_length=2, max_length=6)]
    evidence: Annotated[tuple[ReportAgentDraftEvidence, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        if tuple(item.position for item in self.outline) != tuple(range(len(self.outline))):
            raise ValueError("ReportAgent draft outline positions must be contiguous")
        if tuple(item.evidence_position for item in self.evidence) != tuple(
            range(len(self.evidence))
        ):
            raise ValueError("ReportAgent draft evidence positions must be contiguous")
        if self.evidence_call_count != len(self.evidence):
            raise ValueError("ReportAgent draft evidence count must match the frozen evidence")
        return self


class ExtractedReportAgentDraftCitation(StrictModel):
    evidence_position: Annotated[int, Field(ge=0, le=19)]
    quote_position: Annotated[int, Field(ge=0, le=19)]


class ExtractedReportAgentDraftSection(StrictModel):
    position: Annotated[int, Field(ge=0, le=5)]
    title: Annotated[RequiredText, Field(max_length=200)]
    body_markdown: Annotated[str, StringConstraints(min_length=1, max_length=5000, strict=True)]
    citations: Annotated[
        tuple[ExtractedReportAgentDraftCitation, ...], Field(min_length=1, max_length=20)
    ]

    @field_validator("citations")
    @classmethod
    def require_unique_quotes(
        cls, value: tuple[ExtractedReportAgentDraftCitation, ...]
    ) -> tuple[ExtractedReportAgentDraftCitation, ...]:
        keys = tuple((item.evidence_position, item.quote_position) for item in value)
        if len(keys) != len(set(keys)):
            raise ValueError("ReportAgent section citations must be unique")
        return value


class ExtractedReportAgentDraft(StrictModel):
    title: Annotated[RequiredText, Field(max_length=200)]
    sections: Annotated[
        tuple[ExtractedReportAgentDraftSection, ...], Field(min_length=2, max_length=6)
    ]


class NormalizedReportAgentDraftCitation(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    evidence_kind: EvidenceKind
    target_id: UUID
    tool_call_position: Annotated[int, Field(ge=0, le=19)]
    source_label: Annotated[RequiredText, Field(max_length=500)]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=500, strict=True)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]


class NormalizedReportAgentDraftSection(StrictModel):
    position: Annotated[int, Field(ge=0, le=5)]
    title: Annotated[RequiredText, Field(max_length=200)]
    body_markdown: Annotated[str, StringConstraints(min_length=1, max_length=5000, strict=True)]
    citations: Annotated[
        tuple[NormalizedReportAgentDraftCitation, ...], Field(min_length=1, max_length=20)
    ]


class NormalizedReportAgentDraft(StrictModel):
    title: Annotated[RequiredText, Field(max_length=200)]
    sections: Annotated[
        tuple[NormalizedReportAgentDraftSection, ...], Field(min_length=2, max_length=6)
    ]
    draft_sha256: Sha256
