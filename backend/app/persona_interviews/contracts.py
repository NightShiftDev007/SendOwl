"""Strict contracts for report-grounded synthetic Persona interviews."""

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

type InterviewStatus = Literal["queued", "running", "succeeded", "failed"]
type InterviewQuestion = Annotated[
    str, StringConstraints(min_length=2, max_length=1000, strip_whitespace=True)
]
type InterviewAnswer = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class PersonaInterviewRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_id: UUID
    question: InterviewQuestion

    @field_validator("persona_id", mode="before")
    @classmethod
    def parse_persona_id(cls, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError("persona_id must be a UUID string")
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(
                f"persona_id must be a valid UUID string; received {value!r}"
            ) from error


class PersonaInterviewSessionRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_ids: Annotated[tuple[UUID, ...], Field(min_length=2, max_length=8)]
    question: InterviewQuestion

    @field_validator("persona_ids", mode="before")
    @classmethod
    def parse_persona_ids(cls, value: object) -> tuple[UUID, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("persona_ids must be an array")
        parsed: list[UUID] = []
        for position, item in enumerate(value):
            if not isinstance(item, str):
                raise ValueError(f"persona_ids[{position}] must be a UUID string")
            try:
                parsed.append(UUID(item))
            except ValueError as error:
                raise ValueError(
                    f"persona_ids[{position}] must be a valid UUID string; received {item!r}"
                ) from error
        return tuple(parsed)

    @model_validator(mode="after")
    def reject_duplicate_personas(self) -> Self:
        if len(set(self.persona_ids)) != len(self.persona_ids):
            raise ValueError("persona_ids must not contain duplicates")
        return self


class PersonaInterviewPersona(ContractModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=99)]
    persona_id: Identifier
    display_name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$"),
    ]
    profile_sha256: Sha256Digest


class PersonaInterview(ContractModel):
    id: UUID
    report_id: UUID
    report_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    persona: PersonaInterviewPersona
    question: InterviewQuestion
    interview_sha256: Sha256Digest
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["persona-report-interview/v1"]
    status: InterviewStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    answer_markdown: InterviewAnswer | None
    cited_section_positions: Annotated[tuple[int, ...], Field(max_length=4)]
    answer_sha256: Sha256Digest | None
    error_code: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None
    error_message: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if tuple(sorted(set(self.cited_section_positions))) != self.cited_section_positions:
            raise ValueError("cited section positions must be sorted and unique")
        if any(position < 0 or position > 3 for position in self.cited_section_positions):
            raise ValueError("cited section positions must be between zero and three")
        if self.status == "queued":
            valid = self.started_at is None and self.completed_at is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
        if self.status == "succeeded":
            valid = valid and self.answer_markdown is not None
            valid = valid and bool(self.cited_section_positions) and self.answer_sha256 is not None
            valid = valid and self.error_code is None and self.error_message is None
        elif self.status == "failed":
            valid = valid and self.answer_markdown is None and not self.cited_section_positions
            valid = valid and self.answer_sha256 is None and self.error_code is not None
        else:
            valid = valid and self.answer_markdown is None and not self.cited_section_positions
            valid = valid and self.answer_sha256 is None and self.error_code is None
        if not valid:
            raise ValueError(f"Persona interview fields do not match status {self.status}")
        return self


class PersonaInterviewsResponse(ContractModel):
    items: tuple[PersonaInterview, ...]
    total: Annotated[int, Field(ge=0)]


class PersonaInterviewSession(ContractModel):
    id: UUID
    report_id: UUID
    report_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    question: InterviewQuestion
    persona_count: Annotated[int, Field(ge=2, le=8)]
    session_sha256: Sha256Digest
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: Literal["persona-report-interview-session/v1"]
    status: InterviewStatus
    created_at: AwareDatetime
    interviews: Annotated[tuple[PersonaInterview, ...], Field(min_length=2, max_length=8)]

    @model_validator(mode="after")
    def validate_session(self) -> Self:
        if len(self.interviews) != self.persona_count:
            raise ValueError("session persona_count must equal the number of interviews")
        if len({item.persona.id for item in self.interviews}) != len(self.interviews):
            raise ValueError("session interviews must contain unique Personas")
        if any(
            item.report_id != self.report_id
            or item.report_sha256 != self.report_sha256
            or item.cohort_id != self.cohort_id
            or item.cohort_sha256 != self.cohort_sha256
            or item.question != self.question
            or item.model_name != self.model_name
            or item.semantic_config_sha256 != self.semantic_config_sha256
            for item in self.interviews
        ):
            raise ValueError("session interviews must match the frozen session context")
        statuses = tuple(item.status for item in self.interviews)
        expected: InterviewStatus
        if all(status == "queued" for status in statuses):
            expected = "queued"
        elif any(status in ("queued", "running") for status in statuses):
            expected = "running"
        elif all(status == "succeeded" for status in statuses):
            expected = "succeeded"
        else:
            expected = "failed"
        if self.status != expected:
            raise ValueError("session status must be derived from its interview statuses")
        return self


class PersonaInterviewSessionsResponse(ContractModel):
    items: tuple[PersonaInterviewSession, ...]
    total: Annotated[int, Field(ge=0)]
