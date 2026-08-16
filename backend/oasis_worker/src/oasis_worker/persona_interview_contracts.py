"""Strict worker contracts for report-grounded synthetic Persona interviews."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import PersonaProfile


class InterviewReportSection(StrictModel):
    position: Annotated[int, Field(ge=0, le=3)]
    kind: Annotated[RequiredText, Field(max_length=32)]
    title: Annotated[RequiredText, Field(max_length=300)]
    body_markdown: Annotated[RequiredText, Field(max_length=40_000)]


class ClaimedPersonaInterview(StrictModel):
    id: UUID
    report_id: UUID
    report_sha256: Sha256
    cohort_id: UUID
    cohort_sha256: Sha256
    persona_id: UUID
    persona_position: Annotated[int, Field(ge=0, le=99)]
    persona_external_id: Annotated[RequiredText, Field(max_length=128)]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile: PersonaProfile
    persona_profile_sha256: Sha256
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    interview_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["persona-report-interview/v1"]
    created_at: datetime
    report_title: Annotated[RequiredText, Field(max_length=300)]
    report_sections: Annotated[
        tuple[InterviewReportSection, ...], Field(min_length=4, max_length=4)
    ]

    @model_validator(mode="after")
    def validate_report_outline(self) -> "ClaimedPersonaInterview":
        if tuple(section.position for section in self.report_sections) != (0, 1, 2, 3):
            raise ValueError("report section positions must be contiguous from zero")
        if tuple(section.kind for section in self.report_sections) != (
            "scope",
            "comparison",
            "limitations",
            "provenance",
        ):
            raise ValueError("report sections must use the fixed findings outline")
        return self


class ExtractedPersonaInterviewAnswer(StrictModel):
    answer_markdown: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2000, strict=True),
    ]
    cited_section_positions: Annotated[tuple[int, ...], Field(min_length=1, max_length=4)]

    @field_validator("cited_section_positions")
    @classmethod
    def normalize_positions(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(position < 0 or position > 3 for position in value):
            raise ValueError("section positions must be between zero and three")
        if len(value) != len(set(value)):
            raise ValueError("section positions must be unique")
        return tuple(sorted(value))


class NormalizedPersonaInterviewAnswer(StrictModel):
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)]
    cited_section_positions: Annotated[tuple[int, ...], Field(min_length=1, max_length=4)]
    answer_sha256: Sha256
