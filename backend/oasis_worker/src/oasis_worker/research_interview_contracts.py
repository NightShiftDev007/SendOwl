"""Strict worker contracts for interviews over a frozen research run."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import PersonaProfile


class ClaimedResearchPersonaInterview(StrictModel):
    id: UUID
    research_project_id: UUID
    research_simulation_run_id: UUID
    run_spec_sha256: Sha256
    graph_memory_sha256: Sha256
    cohort_id: UUID
    cohort_sha256: Sha256
    persona_id: UUID
    persona_position: Annotated[int, Field(ge=0, le=7)]
    persona_external_id: Annotated[RequiredText, Field(max_length=128)]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile: PersonaProfile
    persona_profile_sha256: Sha256
    question: Annotated[str, StringConstraints(min_length=2, max_length=1000, strict=True)]
    source_text: Annotated[str, StringConstraints(min_length=1, max_length=80000, strict=True)]
    source_sha256: Sha256
    interview_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["sandowl-run-persona-interview/v1"]
    created_at: datetime


class ExtractedResearchPersonaInterviewAnswer(StrictModel):
    answer_markdown: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2000, strict=True),
        Field(description="A bounded first-person synthetic perspective."),
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


class ResearchInterviewCitation(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    source_kind: Literal["research_run"]
    target_id: UUID
    source_label: Annotated[RequiredText, Field(max_length=500)]
    quote: Annotated[str, StringConstraints(min_length=1, max_length=500, strict=True)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]


class NormalizedResearchPersonaInterviewAnswer(StrictModel):
    answer_markdown: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)]
    citations: Annotated[tuple[ResearchInterviewCitation, ...], Field(min_length=1, max_length=20)]
    answer_sha256: Sha256
