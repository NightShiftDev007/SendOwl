"""Strict contracts for interviews over one frozen research run."""

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

from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type ResearchInterviewStatus = Literal["queued", "running", "succeeded", "failed"]
type ResearchInterviewQuestion = Annotated[
    str, StringConstraints(min_length=2, max_length=1000, strip_whitespace=True)
]


class ResearchInterviewRequestModel(ContractModel):
    model_config = ConfigDict(extra="forbid")


class ResearchPersonaInterviewRequest(ResearchInterviewRequestModel):
    persona_id: UUID
    question: ResearchInterviewQuestion

    @field_validator("persona_id", mode="before")
    @classmethod
    def parse_persona_id(cls, value: object) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))


class ResearchPersonaInterviewSessionRequest(ResearchInterviewRequestModel):
    persona_ids: Annotated[tuple[UUID, ...], Field(min_length=2, max_length=8)]
    question: ResearchInterviewQuestion

    @field_validator("persona_ids", mode="before")
    @classmethod
    def parse_persona_ids(cls, value: object) -> tuple[UUID, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("persona_ids must be an array")
        return tuple(item if isinstance(item, UUID) else UUID(str(item)) for item in value)

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        if len(set(self.persona_ids)) != len(self.persona_ids):
            raise ValueError("persona_ids must not contain duplicates")
        return self


class ResearchInterviewPersona(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Identifier
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    profile_sha256: Sha256Digest


class ResearchInterviewCitation(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    source_kind: Literal["research_run"]
    target_id: UUID
    source_label: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    quote: Annotated[
        str,
        StringConstraints(min_length=1, max_length=500, strip_whitespace=False),
    ]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("research interview citation offsets must span the exact quote")
        return self


class ResearchPersonaInterview(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    run_spec_sha256: Sha256Digest
    graph_memory_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    persona: ResearchInterviewPersona
    question: ResearchInterviewQuestion
    source_sha256: Sha256Digest
    interview_sha256: Sha256Digest
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["sandowl-run-persona-interview/v1"]
    status: ResearchInterviewStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None
    citations: Annotated[tuple[ResearchInterviewCitation, ...], Field(max_length=20)]
    answer_sha256: Sha256Digest | None
    error_code: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    error_message: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if tuple(item.position for item in self.citations) != tuple(range(len(self.citations))):
            raise ValueError("research interview citation positions must be contiguous")
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
            raise ValueError(f"research interview fields do not match status {self.status}")
        return self


class ResearchPersonaInterviewsResponse(ContractModel):
    items: tuple[ResearchPersonaInterview, ...]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total != len(self.items):
            raise ValueError("research interview total must match items")
        return self


class ResearchPersonaInterviewSession(ContractModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    run_spec_sha256: Sha256Digest
    graph_memory_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    question: ResearchInterviewQuestion
    persona_count: Annotated[int, Field(ge=2, le=8)]
    session_sha256: Sha256Digest
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["sandowl-run-persona-interview-session/v1"]
    status: ResearchInterviewStatus
    created_at: AwareDatetime
    interviews: Annotated[tuple[ResearchPersonaInterview, ...], Field(min_length=2, max_length=8)]

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if len(self.interviews) != self.persona_count:
            raise ValueError("research interview session count must match interviews")
        if len({item.persona.id for item in self.interviews}) != len(self.interviews):
            raise ValueError("research interview session Personas must be unique")
        if any(
            item.research_project_id != self.research_project_id
            or item.research_simulation_run_id != self.research_simulation_run_id
            or item.run_spec_sha256 != self.run_spec_sha256
            or item.graph_memory_sha256 != self.graph_memory_sha256
            or item.cohort_id != self.cohort_id
            or item.cohort_sha256 != self.cohort_sha256
            or item.question != self.question
            or item.model_name != self.model_name
            or item.semantic_config_sha256 != self.semantic_config_sha256
            for item in self.interviews
        ):
            raise ValueError("research interview session inputs must share one frozen run")
        statuses = tuple(item.status for item in self.interviews)
        expected: ResearchInterviewStatus
        if all(item == "queued" for item in statuses):
            expected = "queued"
        elif any(item in ("queued", "running") for item in statuses):
            expected = "running"
        elif all(item == "succeeded" for item in statuses):
            expected = "succeeded"
        else:
            expected = "failed"
        if self.status != expected:
            raise ValueError("research interview session status must derive from interviews")
        return self


class ResearchPersonaInterviewSessionsResponse(ContractModel):
    items: tuple[ResearchPersonaInterviewSession, ...]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total != len(self.items):
            raise ValueError("research interview session total must match items")
        return self
