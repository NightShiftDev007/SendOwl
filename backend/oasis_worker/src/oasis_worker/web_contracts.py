"""Strict worker contracts for the bounded MatrAIx Playwright quote-choice task."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SemanticPersona

WEB_TASK_ID = "matraix/quotes-playwright-choice"
WEB_TASK_VERSION = "1.0.0"
WEB_TASK_SCHEMA_VERSION = "matraix-web-task/quote-choice-v1"
WEB_TASK_SPEC_SHA256 = "f5be8a4a377764ac77f80e3178720e914b4b069875dc5b8f3bbd6ff3508525ad"
WEB_EXECUTOR_SCHEMA_VERSION = "matraix-web-browser-executor/v1"
WEB_EXECUTOR_SPEC_SHA256 = "36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7"
WEB_PROMPT_SCHEMA_VERSION = "matraix-web-quotes-choice/v1"
WEB_RUNNER_VERSION = "1.0.0"
WEB_TOOL_NAME = "submit_quote_choice"


class WebRuntimeConfig(StrictModel):
    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    provider_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    browser_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    executor_schema_version: Literal["matraix-web-browser-executor/v1"]
    executor_spec_sha256: Literal[
        "36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7"
    ]


class WebEvaluation(StrictModel):
    id: UUID
    cohort_id: UUID
    cohort_sha256: Sha256
    cohort_title: Annotated[RequiredText, Field(max_length=200)]
    dataset_sha256: Sha256
    persona_count: Annotated[int, Field(ge=1, le=4)]
    task_id: Literal["matraix/quotes-playwright-choice"]
    task_version: Literal["1.0.0"]
    task_schema_version: Literal["matraix-web-task/quote-choice-v1"]
    task_spec_sha256: Literal["f5be8a4a377764ac77f80e3178720e914b4b069875dc5b8f3bbd6ff3508525ad"]
    executor_schema_version: Literal["matraix-web-browser-executor/v1"]
    executor_spec_sha256: Literal[
        "36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7"
    ]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    web_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    evaluation_sha256: Sha256
    retry_of_evaluation_id: UUID | None
    retry_of_evaluation_sha256: Sha256 | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    created_at: datetime

    @model_validator(mode="after")
    def validate_retry_lineage(self) -> Self:
        has_parent = (
            self.retry_of_evaluation_id is not None and self.retry_of_evaluation_sha256 is not None
        )
        if (self.attempt_number == 1) == has_parent:
            raise ValueError("root Web attempts have no parent; later attempts require one")
        return self


class ClaimedWebTrial(StrictModel):
    id: UUID
    status: Literal["running"]
    created_at: datetime
    persona_position: Annotated[int, Field(ge=0, le=3)]
    persona_id: UUID
    persona_external_id: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
            strict=True,
        ),
    ]
    persona_display_name: Annotated[RequiredText, Field(max_length=200)]
    persona_profile_sha256: Sha256
    trial_sha256: Sha256
    evaluation: WebEvaluation
    persona: SemanticPersona

    @model_validator(mode="after")
    def validate_persona_binding(self) -> Self:
        if (
            self.persona.position != self.persona_position
            or self.persona.id != self.persona_id
            or self.persona.persona_id != self.persona_external_id
            or self.persona.display_name != self.persona_display_name
            or self.persona.profile_sha256 != self.persona_profile_sha256
        ):
            raise ValueError("Web trial Persona does not match its frozen binding")
        if self.persona_position >= self.evaluation.persona_count:
            raise ValueError("Web trial Persona position is outside the frozen Cohort")
        return self


class BrowserQuote(StrictModel):
    position: Annotated[int, Field(ge=0, le=59)]
    quote_id: Sha256
    text: Annotated[RequiredText, Field(max_length=2000)]
    author: Annotated[RequiredText, Field(max_length=200)]
    tags: Annotated[tuple[str, ...], Field(max_length=20)]

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or len(value) > 128 for value in values):
            raise ValueError("Web quote tags must contain bounded non-empty values")
        return values


class BrowserPage(StrictModel):
    position: Annotated[int, Field(ge=0, le=2)]
    url: Annotated[
        str,
        StringConstraints(
            min_length=28,
            max_length=200,
            pattern=r"^https://quotes\.toscrape\.com/(?:page/[1-9][0-9]*/)?$",
            strict=True,
        ),
    ]
    title: Annotated[RequiredText, Field(max_length=200)]
    screenshot_sha256: Sha256
    quotes: Annotated[tuple[BrowserQuote, ...], Field(min_length=1, max_length=20)]


class BrowserObservation(StrictModel):
    task_id: Literal["matraix/quotes-playwright-choice"]
    task_version: Literal["1.0.0"]
    executor_schema_version: Literal["matraix-web-browser-executor/v1"]
    executor_spec_sha256: Literal[
        "36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7"
    ]
    pages: Annotated[tuple[BrowserPage, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if tuple(page.position for page in self.pages) != (0, 1, 2):
            raise ValueError("Web pages must occupy positions zero through two")
        quote_positions = tuple(quote.position for page in self.pages for quote in page.quotes)
        if quote_positions != tuple(range(len(quote_positions))):
            raise ValueError("Web quote positions must be contiguous from zero")
        if len({quote.quote_id for page in self.pages for quote in page.quotes}) != len(
            quote_positions
        ):
            raise ValueError("Web quote identities must be unique")
        return self


class WebChoiceSubmission(StrictModel):
    decision_subject_id: Sha256
    basis_primary: Literal[
        "price",
        "quality",
        "features",
        "convenience",
        "taste",
        "trust",
        "familiarity",
        "novelty",
        "fit",
        "other",
    ]
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=20, max_length=2000, strict=True),
    ]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(strict=True, ge=1, le=10)]


class WebSuccess(StrictModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    web_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-web-quotes-choice/v1"]
    pages: tuple[BrowserPage, BrowserPage, BrowserPage]
    trace_sha256: Sha256
    result_sha256: Sha256
    decision_subject_id: Sha256
    decision_subject_label: Annotated[RequiredText, Field(max_length=2000)]
    basis_primary: Literal[
        "price",
        "quality",
        "features",
        "convenience",
        "taste",
        "trust",
        "familiarity",
        "novelty",
        "fit",
        "other",
    ]
    reason: Annotated[RequiredText, Field(min_length=20, max_length=2000)]
    task_author: Annotated[RequiredText, Field(max_length=200)]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(ge=1, le=10)]
