"""Strict contracts for cited interaction with one single-run ReportAgent report."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.shared.contracts import ContractModel, Sha256Digest

type AgentInteractionStatus = Literal["queued", "running", "succeeded", "failed"]


class AgentInteractionRequest(ContractModel):
    question: Annotated[
        str,
        StringConstraints(min_length=2, max_length=1000, strip_whitespace=True),
    ]
    parent_interaction_id: UUID | None


class AgentInteractionCitation(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    source_kind: Literal["simulation_run"]
    target_id: UUID
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
            raise ValueError("Agent Interaction citation offsets must span the exact quote")
        return self


class AgentInteraction(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    report_agent_run_id: UUID
    report_agent_run_sha256: Sha256Digest
    report_agent_draft_id: UUID
    report_agent_draft_sha256: Sha256Digest
    source_sha256: Sha256Digest
    question: Annotated[
        str,
        StringConstraints(min_length=2, max_length=1000, strip_whitespace=True),
    ]
    interaction_sha256: Sha256Digest
    model_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, strip_whitespace=True),
    ]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal[
        "sandowl-agent-interaction/v1",
        "sandowl-agent-interaction/v2",
    ]
    parent_interaction_id: UUID | None
    parent_interaction_sha256: Sha256Digest | None
    parent_answer_sha256: Sha256Digest | None
    conversation_depth: Annotated[int, Field(ge=0, le=4)]
    status: AgentInteractionStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    answer_markdown: (
        Annotated[
            str,
            StringConstraints(min_length=1, max_length=1200, strip_whitespace=True),
        ]
        | None
    )
    citations: Annotated[tuple[AgentInteractionCitation, ...], Field(max_length=20)]
    answer_sha256: Sha256Digest | None
    error_code: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    error_message: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        root = self.parent_interaction_id is None
        if root != (self.conversation_depth == 0):
            raise ValueError("Agent Interaction parent must match conversation depth")
        if root != (self.parent_interaction_sha256 is None):
            raise ValueError("Agent Interaction parent digest must match lineage")
        if root != (self.parent_answer_sha256 is None):
            raise ValueError("Agent Interaction parent answer must match lineage")
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
        if self.status == "succeeded":
            valid = (
                valid
                and self.answer_markdown is not None
                and bool(self.citations)
                and self.answer_sha256 is not None
                and self.error_code is None
                and self.error_message is None
            )
        elif self.status == "failed":
            valid = (
                valid
                and self.answer_markdown is None
                and not self.citations
                and self.answer_sha256 is None
                and self.error_code is not None
                and self.error_message is not None
            )
        else:
            valid = (
                valid
                and self.answer_markdown is None
                and not self.citations
                and self.answer_sha256 is None
                and self.error_code is None
                and self.error_message is None
            )
        if not valid:
            raise ValueError(f"Agent Interaction fields do not match status {self.status}")
        if self.citations and tuple(item.position for item in self.citations) != tuple(
            range(len(self.citations))
        ):
            raise ValueError("Agent Interaction citation positions must be contiguous")
        return self


class AgentInteractionsResponse(ContractModel):
    items: tuple[AgentInteraction, ...]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total != len(self.items):
            raise ValueError("Agent Interaction total must match items")
        return self


class AgentInteractionContext(ContractModel):
    root_interaction_id: UUID
    items: Annotated[tuple[AgentInteraction, ...], Field(min_length=1, max_length=5)]
