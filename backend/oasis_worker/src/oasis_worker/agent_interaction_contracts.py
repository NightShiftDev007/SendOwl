"""Strict worker contracts for native Agent Interaction."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel


class AgentInteractionConversationTurn(StrictModel):
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=1200, strict=True)]


class ClaimedAgentInteraction(StrictModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    report_agent_run_id: UUID
    report_agent_run_sha256: Sha256
    report_agent_draft_id: UUID
    report_agent_draft_sha256: Sha256
    source_sha256: Sha256
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    interaction_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal[
        "sandowl-agent-interaction/v1",
        "sandowl-agent-interaction/v2",
    ]
    parent_interaction_sha256: Sha256 | None
    parent_answer_sha256: Sha256 | None
    conversation_depth: Annotated[int, Field(ge=0, le=4)]
    created_at: datetime
    report_title: Annotated[RequiredText, Field(max_length=200)]
    report_markdown: Annotated[str, StringConstraints(min_length=1, max_length=40000, strict=True)]
    source_text: Annotated[str, StringConstraints(min_length=1, max_length=80000, strict=True)]
    conversation_context: Annotated[
        tuple[AgentInteractionConversationTurn, ...], Field(max_length=4)
    ]


class ExtractedAgentInteractionAnswer(StrictModel):
    answer_markdown: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1200, strict=True),
        Field(description="A concise answer of no more than 600 Chinese characters."),
    ]
    citation_quotes: Annotated[
        tuple[Annotated[str, StringConstraints(min_length=1, max_length=500, strict=True)], ...],
        Field(min_length=1, max_length=20),
    ]

    @field_validator("citation_quotes")
    @classmethod
    def require_unique_quotes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("citation_quotes must be unique")
        return value


class AgentInteractionCitation(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    source_kind: Literal["simulation_run"]
    target_id: UUID
    source_label: Annotated[RequiredText, Field(max_length=500)]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=500, strict=True)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]


class NormalizedAgentInteractionAnswer(StrictModel):
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=1200, strict=True)]
    citations: Annotated[tuple[AgentInteractionCitation, ...], Field(min_length=1, max_length=20)]
    answer_sha256: Sha256
