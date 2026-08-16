"""Canonical identities for the MatrAIx Acme Support chatbot runtime and results."""

from __future__ import annotations

import hashlib

from oasis_worker.chat_contracts import (
    CHAT_CUSTOMER_TOOL_NAME,
    CHAT_FEEDBACK_TOOL_NAME,
    CHAT_MAX_CUSTOMER_TURNS,
    CHAT_MCP_SUT_SPEC_SHA256,
    CHAT_MCP_TASK_ID,
    CHAT_MIN_CUSTOMER_TURNS,
    CHAT_PROMPT_SCHEMA_VERSION,
    CHAT_REST_TASK_ID,
    CHAT_RUNNER_VERSION,
    CHAT_SUT_SPEC_SHA256,
    ChatEvaluation,
    ChatFeedback,
    ChatMessage,
    ChatResult,
)
from oasis_worker.semantic_contracts import LOW_INFORMATION_VALUES, MAX_PROFILE_ATTRIBUTES

CHAT_CONTEXT_TOKEN_LIMIT = 32_768
CHAT_OUTPUT_MAX_TOKENS = 1024
CHAT_TOOL_CHOICE = "required"
CHAT_ENABLE_THINKING = False
CHAT_PROFILE_SCHEMA_VERSION = "matraix-chat-profile/v1"


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def chat_config_sha256(provider_base_url: str, model_name: str) -> str:
    """Hash output-affecting provider, prompt, profile, protocol, and SUT behavior."""
    return _digest(
        (
            "matraix-chat-runtime-config/v1",
            "openai_compatible",
            provider_base_url,
            model_name,
            CHAT_RUNNER_VERSION,
            CHAT_PROMPT_SCHEMA_VERSION,
            str(CHAT_CONTEXT_TOKEN_LIMIT),
            str(CHAT_OUTPUT_MAX_TOKENS),
            CHAT_TOOL_CHOICE,
            _bool_text(CHAT_ENABLE_THINKING),
            CHAT_CUSTOMER_TOOL_NAME,
            CHAT_FEEDBACK_TOOL_NAME,
            str(CHAT_MIN_CUSTOMER_TURNS),
            str(CHAT_MAX_CUSTOMER_TURNS),
            "customer_first_strict_alternation_support_last",
            CHAT_PROFILE_SCHEMA_VERSION,
            *sorted(LOW_INFORMATION_VALUES),
            str(MAX_PROFILE_ATTRIBUTES),
            CHAT_REST_TASK_ID,
            CHAT_SUT_SPEC_SHA256,
            CHAT_MCP_TASK_ID,
            CHAT_MCP_SUT_SPEC_SHA256,
        )
    )


def evaluation_sha256(evaluation: ChatEvaluation) -> str:
    if evaluation.attempt_number > 1:
        if evaluation.retry_of_evaluation_sha256 is None:
            raise ValueError("chat retry evaluation has no parent digest")
        return _digest(
            (
                "matraix-chat-evaluation-retry/v1",
                evaluation.retry_of_evaluation_sha256,
                str(evaluation.attempt_number),
                evaluation.task_spec_sha256,
                evaluation.sut_spec_sha256,
                str(evaluation.cohort_id),
                evaluation.cohort_sha256,
                evaluation.dataset_sha256,
                str(evaluation.persona_count),
                evaluation.model_name,
                evaluation.chat_config_sha256,
                CHAT_PROMPT_SCHEMA_VERSION,
            )
        )
    return _digest(
        (
            "matraix-chat-evaluation/v1",
            evaluation.task_spec_sha256,
            evaluation.sut_spec_sha256,
            str(evaluation.cohort_id),
            evaluation.cohort_sha256,
            evaluation.dataset_sha256,
            str(evaluation.persona_count),
            evaluation.model_name,
            evaluation.chat_config_sha256,
            CHAT_PROMPT_SCHEMA_VERSION,
        )
    )


def trial_sha256(
    frozen_evaluation_sha256: str,
    persona_position: int,
    persona_id: object,
    persona_external_id: str,
    persona_display_name: str,
    persona_profile_sha256: str,
) -> str:
    return _digest(
        (
            "matraix-chat-trial/v1",
            frozen_evaluation_sha256,
            str(persona_position),
            str(persona_id),
            persona_external_id,
            persona_display_name,
            persona_profile_sha256,
        )
    )


def transcript_sha256(
    frozen_trial_sha256: str,
    messages: tuple[ChatMessage, ...],
) -> str:
    parts = ["matraix-chat-transcript/v1", frozen_trial_sha256]
    for message in messages:
        parts.extend((str(message.position), message.role, message.content))
    return _digest(tuple(parts))


def feedback_sha256(
    frozen_trial_sha256: str,
    feedback: ChatFeedback,
) -> str:
    return _digest(
        (
            "matraix-chat-feedback/v1",
            frozen_trial_sha256,
            feedback.schema_version,
            feedback.need_constraint_satisfaction,
            feedback.personal_preference_satisfaction,
            str(feedback.overall_experience_rating),
            feedback.reason,
            _bool_text(feedback.asked_useful_clarification_questions),
            feedback.clarifying_notes,
        )
    )


def result_sha256(
    frozen_trial_sha256: str,
    frozen_transcript_sha256: str,
    frozen_feedback_sha256: str,
    result: ChatResult,
) -> str:
    return _digest(
        (
            "matraix-chat-result/v1",
            frozen_trial_sha256,
            frozen_transcript_sha256,
            frozen_feedback_sha256,
            result.outcome_status,
            result.next_step_owner,
            result.conversation_path,
            result.resolution_progression,
            str(result.message_count),
            str(result.customer_turn_count),
            str(result.support_turn_count),
            str(result.clarification_question_count),
        )
    )
