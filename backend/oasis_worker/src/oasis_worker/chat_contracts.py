"""Strict worker contracts for the MatrAIx Acme Support chatbot evaluation."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SemanticPersona

CHAT_RUNNER_VERSION = "1.0.0"
CHAT_PROMPT_SCHEMA_VERSION = "matraix-chat-acme-support/v1"
CHAT_REST_TASK_ID = "matraix/acme-support-order-4521"
CHAT_MCP_TASK_ID = "matraix/acme-support-mcp-order-4521"
CHAT_TASK_VERSION = "1.0.0"
CHAT_TASK_SCHEMA_VERSION = "matraix-chat-task/acme-support-v1"
CHAT_FEEDBACK_SCHEMA_VERSION = "matraix-chat-feedback/acme-support-v1"
CHAT_TASK_SPEC_SHA256 = "4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1"
CHAT_SUT_SPEC_SHA256 = "b3609ac5ab58a4994c497f276d4689b8272150a9251676ddef84ebe9e8bdc980"
CHAT_MCP_TASK_SPEC_SHA256 = "cd92b749ac08d0a229c3ea6191c52f03c096b03aff1689f5da04e7ec2daabd98"
CHAT_MCP_SUT_SPEC_SHA256 = "5fbc2623be9df873de0c025edd1f2dcbf9d0b24672d627f1e063002c9e9587e1"
CHAT_SUITE_ID = "sendowl/matraix-acme-rest-mcp-suite"
CHAT_SUITE_VERSION = "1.0.0"
CHAT_SUITE_SHA256 = "0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"
CHAT_MIN_CUSTOMER_TURNS = 2
CHAT_MAX_CUSTOMER_TURNS = 4
CHAT_CUSTOMER_TOOL_NAME = "send_customer_message"
CHAT_FEEDBACK_TOOL_NAME = "submit_chat_feedback"


class ChatRuntimeConfig(StrictModel):
    """Non-persisted provider/SUT credentials plus their public runtime identity."""

    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    provider_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    rest_sut_base_url: Annotated[
        str, StringConstraints(min_length=1, max_length=2000, strict=True)
    ] = Field(repr=False)
    mcp_sut_url: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)] = (
        Field(repr=False)
    )
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    sut_task_id: Literal["sendowl/matraix-acme-rest-mcp-suite"]
    sut_task_version: Literal["1.0.0"]
    sut_spec_sha256: Literal["0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"]


class ChatEvaluation(StrictModel):
    id: UUID
    cohort_id: UUID
    cohort_sha256: Sha256
    cohort_title: Annotated[RequiredText, Field(max_length=200)]
    dataset_sha256: Sha256
    persona_count: Annotated[int, Field(ge=1, le=8)]
    task_id: Literal["matraix/acme-support-order-4521", "matraix/acme-support-mcp-order-4521"]
    task_version: Literal["1.0.0"]
    task_schema_version: Literal["matraix-chat-task/acme-support-v1"]
    task_spec_sha256: Sha256
    sut_spec_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    chat_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    evaluation_sha256: Sha256
    retry_of_evaluation_id: UUID | None
    retry_of_evaluation_sha256: Sha256 | None
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    created_at: datetime

    @model_validator(mode="after")
    def validate_task_identity(self) -> Self:
        expected = (
            (CHAT_MCP_TASK_SPEC_SHA256, CHAT_MCP_SUT_SPEC_SHA256)
            if self.task_id == CHAT_MCP_TASK_ID
            else (CHAT_TASK_SPEC_SHA256, CHAT_SUT_SPEC_SHA256)
        )
        if (self.task_spec_sha256, self.sut_spec_sha256) != expected:
            raise ValueError("chat evaluation task hashes do not match its fixed transport")
        is_root = self.attempt_number == 1
        has_parent = (
            self.retry_of_evaluation_id is not None and self.retry_of_evaluation_sha256 is not None
        )
        if is_root == has_parent:
            raise ValueError("chat retry lineage does not match attempt number")
        return self


class ClaimedChatTrial(StrictModel):
    id: UUID
    status: Literal["running"]
    created_at: datetime
    persona_position: Annotated[int, Field(ge=0, le=7)]
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
    evaluation: ChatEvaluation
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
            raise ValueError("chat trial persona does not match its frozen Persona binding")
        if self.persona_position >= self.evaluation.persona_count:
            raise ValueError("chat trial Persona position is outside the frozen cohort")
        return self


class CustomerMessageSubmission(StrictModel):
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=2, max_length=2000, strict=True),
    ]

    @field_validator("message")
    @classmethod
    def reject_nul_message(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("customer message must not contain a NUL byte")
        return value


class ChatFeedback(StrictModel):
    schema_version: Literal["matraix-chat-feedback/acme-support-v1"]
    need_constraint_satisfaction: Literal["yes", "partially", "no"]
    personal_preference_satisfaction: Literal["yes", "partially", "no"]
    overall_experience_rating: Annotated[int, Field(strict=True, ge=1, le=10)]
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000, strict=True),
    ]
    asked_useful_clarification_questions: bool
    clarifying_notes: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000, strict=True),
    ]

    @field_validator("reason", "clarifying_notes")
    @classmethod
    def reject_nul_feedback_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("chat feedback text must not contain a NUL byte")
        return value


class ChatMessage(StrictModel):
    position: Annotated[int, Field(ge=0, le=39)]
    role: Literal["customer", "support"]
    content: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=8000, strict=True),
    ]

    @field_validator("content")
    @classmethod
    def reject_nul_content(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("chat message content must not contain a NUL byte")
        return value


class ChatResult(StrictModel):
    outcome_status: Literal["resolved", "partially_resolved", "unresolved"]
    next_step_owner: Literal["user", "support", "none"]
    conversation_path: Literal["clarify_then_resolve", "clarify_then_partial", "stalled"]
    resolution_progression: Literal["single_response", "looped", "advanced"]
    message_count: Annotated[int, Field(ge=4, le=40)]
    customer_turn_count: Annotated[int, Field(ge=2, le=20)]
    support_turn_count: Annotated[int, Field(ge=2, le=20)]
    clarification_question_count: Annotated[int, Field(ge=0, le=20)]


class ChatSuccess(StrictModel):
    runner_version: Literal["1.0.0"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    chat_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-chat-acme-support/v1"]
    messages: Annotated[tuple[ChatMessage, ...], Field(min_length=4, max_length=40)]
    transcript_sha256: Sha256
    feedback: ChatFeedback
    feedback_sha256: Sha256
    result: ChatResult
    result_sha256: Sha256

    @model_validator(mode="after")
    def validate_success_shape(self) -> Self:
        positions = tuple(message.position for message in self.messages)
        if positions != tuple(range(len(self.messages))):
            raise ValueError("chat transcript positions must be contiguous from zero")
        roles = tuple(message.role for message in self.messages)
        expected_roles = tuple(
            "customer" if position % 2 == 0 else "support" for position in positions
        )
        if roles != expected_roles or roles[-1] != "support":
            raise ValueError("chat transcript must alternate customer/support and end in support")
        customer_count = sum(role == "customer" for role in roles)
        support_count = sum(role == "support" for role in roles)
        if customer_count != support_count or not (
            CHAT_MIN_CUSTOMER_TURNS <= customer_count <= CHAT_MAX_CUSTOMER_TURNS
        ):
            raise ValueError("chat success must contain two through four complete turns")
        if (
            self.result.message_count != len(self.messages)
            or self.result.customer_turn_count != customer_count
            or self.result.support_turn_count != support_count
        ):
            raise ValueError("chat result counts do not match the transcript")
        return self
