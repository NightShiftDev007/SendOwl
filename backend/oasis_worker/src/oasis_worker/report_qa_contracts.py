"""Strict worker contracts for evidence-bound report answers."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel


class ReportQACandidate(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    article_id: UUID
    object_label: Annotated[RequiredText, Field(max_length=500)]
    quote: Annotated[RequiredText, Field(max_length=500)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]


class ReportQAConversationTurn(StrictModel):
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=800, strict=True)]


class ClaimedReportQuestion(StrictModel):
    id: UUID
    report_id: UUID
    report_sha256: Sha256
    graph_id: UUID
    graph_sha256: Sha256
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    question_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Annotated[RequiredText, Field(max_length=64)]
    parent_question_sha256: Sha256 | None
    parent_answer_sha256: Sha256 | None
    conversation_depth: Annotated[int, Field(ge=0, le=4)]
    created_at: datetime
    report_title: Annotated[RequiredText, Field(max_length=300)]
    report_sections: Annotated[tuple[RequiredText, ...], Field(min_length=4, max_length=4)]
    candidates: Annotated[tuple[ReportQACandidate, ...], Field(min_length=1, max_length=20)]
    conversation_context: Annotated[tuple[ReportQAConversationTurn, ...], Field(max_length=4)]


class ExtractedReportAnswer(StrictModel):
    answer_markdown: Annotated[
        str,
        StringConstraints(min_length=1, max_length=800, strict=True),
        Field(
            description="A concise evidence-bound answer of no more than 400 Chinese characters."
        ),
    ]
    citation_positions: Annotated[tuple[int, ...], Field(min_length=1, max_length=20)]

    @field_validator("citation_positions")
    @classmethod
    def normalize_unique_positions(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) != len(set(value)):
            raise ValueError("citation_positions must be unique")
        return tuple(sorted(value))


class NormalizedReportAnswer(StrictModel):
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=800, strict=True)]
    citations: Annotated[tuple[ReportQACandidate, ...], Field(min_length=1, max_length=20)]
    answer_sha256: Sha256
