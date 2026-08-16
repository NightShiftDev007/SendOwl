"""Strict report question and cited answer contracts."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.shared.contracts import ContractModel, Sha256Digest

type QuestionStatus = Literal["queued", "running", "succeeded", "failed"]
type QuestionText = Annotated[
    str, StringConstraints(min_length=2, max_length=1000, strip_whitespace=True)
]
type AnswerText = Annotated[str, StringConstraints(min_length=1, max_length=800)]


class ReportQuestionRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    question: QuestionText
    parent_question_id: UUID | None = None


class ReportAnswerCitation(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    article_id: UUID
    quote: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("citation offsets must span the exact quote")
        return self


class ReportQuestion(ContractModel):
    id: UUID
    report_id: UUID
    report_sha256: Sha256Digest
    graph_id: UUID
    graph_sha256: Sha256Digest
    question: QuestionText
    question_sha256: Sha256Digest
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["report-evidence-qa/v1", "report-evidence-qa/v2"]
    parent_question_id: UUID | None
    parent_question_sha256: Sha256Digest | None
    parent_answer_sha256: Sha256Digest | None
    conversation_depth: Annotated[int, Field(ge=0, le=4)]
    status: QuestionStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    answer_markdown: AnswerText | None
    citations: Annotated[tuple[ReportAnswerCitation, ...], Field(max_length=20)]
    answer_sha256: Sha256Digest | None
    error_code: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    error_message: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.conversation_depth == 0:
            lineage_valid = (
                self.parent_question_id is None
                and self.parent_question_sha256 is None
                and self.parent_answer_sha256 is None
                and self.prompt_schema_version == "report-evidence-qa/v1"
            )
        else:
            lineage_valid = (
                self.parent_question_id is not None
                and self.parent_question_sha256 is not None
                and self.parent_answer_sha256 is not None
                and self.prompt_schema_version == "report-evidence-qa/v2"
            )
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
        if self.status == "succeeded":
            valid = valid and self.answer_markdown is not None and bool(self.citations)
            valid = valid and self.answer_sha256 is not None and self.error_code is None
        elif self.status == "failed":
            valid = valid and self.answer_markdown is None and not self.citations
            valid = valid and self.answer_sha256 is None and self.error_code is not None
        else:
            valid = valid and self.answer_markdown is None and not self.citations
            valid = valid and self.answer_sha256 is None and self.error_code is None
        if not valid or not lineage_valid:
            raise ValueError(f"report question fields do not match status {self.status}")
        return self


class ReportQuestionsResponse(ContractModel):
    items: tuple[ReportQuestion, ...]
    total: Annotated[int, Field(ge=0)]


class ReportQuestionContext(ContractModel):
    current_question_id: UUID
    items: Annotated[tuple[ReportQuestion, ...], Field(min_length=1, max_length=5)]

    @model_validator(mode="after")
    def validate_chain(self) -> Self:
        if self.items[-1].id != self.current_question_id:
            raise ValueError("context must end at current_question_id")
        for position, item in enumerate(self.items):
            if item.status != "succeeded" or item.conversation_depth != position:
                raise ValueError(
                    "context must contain a contiguous succeeded root-to-current chain"
                )
            expected_parent = None if position == 0 else self.items[position - 1].id
            if item.parent_question_id != expected_parent:
                raise ValueError("context parent identities are not contiguous")
        return self
