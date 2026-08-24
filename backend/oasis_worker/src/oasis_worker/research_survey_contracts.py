"""Worker contracts for native single-context research surveys."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SemanticPersona

RESEARCH_SURVEY_PROMPT_VERSION = "sandowl-research-survey/v1"
RESEARCH_SURVEY_RUNNER_VERSION = "1.0.0"
RESEARCH_SURVEY_TOOL_NAME = "submit_research_observation"


class ResearchSurveyRuntimeConfig(StrictModel):
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)] = Field(
        repr=False
    )
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["sandowl-research-survey/v1"]


class ResearchSurveyContext(StrictModel):
    id: UUID
    project_id: UUID
    run_id: UUID
    project_title: Annotated[RequiredText, Field(max_length=300)]
    research_question: Annotated[RequiredText, Field(max_length=2000)]
    simulation_requirement: Annotated[RequiredText, Field(max_length=4000)]
    initial_post: Annotated[RequiredText, Field(max_length=4000)]
    project_sha256: Sha256
    run_spec_sha256: Sha256
    cohort_id: UUID
    cohort_sha256: Sha256
    persona_count: Annotated[int, Field(ge=1, le=8)]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    survey_config_sha256: Sha256
    survey_sha256: Sha256


class ClaimedResearchSurveyTrial(StrictModel):
    id: UUID
    created_at: datetime
    persona_position: Annotated[int, Field(ge=0, le=7)]
    persona_id: UUID
    persona_external_id: Annotated[
        str, StringConstraints(min_length=1, max_length=128, strict=True)
    ]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile_sha256: Sha256
    trial_sha256: Sha256
    survey: ResearchSurveyContext
    persona: SemanticPersona


class ContextClarityAnswer(StrictModel):
    position: Literal[0]
    question_id: Literal["context_clarity"]
    type: Literal["likert"]
    value: Annotated[int, Field(strict=True, ge=1, le=5)]


class AttentionPriorityAnswer(StrictModel):
    position: Literal[1]
    question_id: Literal["attention_priority"]
    type: Literal["single_choice"]
    value: Literal["evidence", "process", "timing", "impact"]


class UnansweredQuestionAnswer(StrictModel):
    position: Literal[2]
    question_id: Literal["unanswered_question"]
    type: Literal["free_text"]
    value: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True, strict=True)
    ]


class ExtractedResearchSurveyResponse(StrictModel):
    answers: tuple[ContextClarityAnswer, AttentionPriorityAnswer, UnansweredQuestionAnswer]


class ResearchSurveySuccess(StrictModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    survey_config_sha256: Sha256
    prompt_schema_version: Literal["sandowl-research-survey/v1"]
    answers: tuple[ContextClarityAnswer, AttentionPriorityAnswer, UnansweredQuestionAnswer]
    answers_sha256: Sha256
