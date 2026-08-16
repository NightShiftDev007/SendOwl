"""NUL-delimited content addresses shared with PostgreSQL and the chat worker."""

from hashlib import sha256
from typing import Literal

from app.matraix_chat.contracts import (
    ChatCohortRef,
    ChatPersonaRef,
    ChatTranscriptMessage,
    ChatTrialFeedback,
)
from app.matraix_chat.tasks import PROMPT_SCHEMA_VERSION


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def calculate_task_spec_sha256(payload: dict[str, object]) -> str:
    source = payload["source"]
    if not isinstance(source, dict):
        raise TypeError("task source must be a dictionary")
    capabilities = payload["capabilities"]
    limitations = payload["limitations"]
    capabilities_valid = isinstance(capabilities, tuple) and all(
        isinstance(item, str) for item in capabilities
    )
    if not capabilities_valid:
        raise TypeError("task capabilities must be a tuple of strings")
    if not isinstance(limitations, tuple) or not all(isinstance(item, str) for item in limitations):
        raise TypeError("task limitations must be a tuple of strings")
    parts = (
        "matraix-chat-task-spec/v1",
        str(payload["task_id"]),
        str(payload["version"]),
        str(payload["schema_version"]),
        str(payload["title"]),
        str(payload["domain"]),
        str(source["kind"]),
        str(source["project"]),
        str(source["canonical_path"]),
        _bool_text(bool(source["production_sut"])),
        str(payload["application_id"]),
        str(payload["application_context"]),
        str(payload["transport"]),
        *capabilities,
        str(payload["instruction"]),
        str(payload["context"]),
        str(payload["minimum_customer_turns"]),
        str(payload["minimum_total_messages"]),
        str(payload["feedback_schema_version"]),
        str(payload["sut_spec_sha256"]),
        *limitations,
    )
    return _digest(parts)


def calculate_evaluation_sha256(
    task_spec_sha256: str,
    sut_spec_sha256: str,
    cohort: ChatCohortRef,
    model_name: str,
    chat_config_sha256: str,
    retry_of_evaluation_sha256: str | None,
    attempt_number: int,
) -> str:
    if attempt_number == 1 and retry_of_evaluation_sha256 is None:
        return _digest(
            (
                "matraix-chat-evaluation/v1",
                task_spec_sha256,
                sut_spec_sha256,
                str(cohort.id),
                cohort.cohort_sha256,
                cohort.dataset_sha256,
                str(cohort.persona_count),
                model_name,
                chat_config_sha256,
                PROMPT_SCHEMA_VERSION,
            )
        )
    if not 2 <= attempt_number <= 5 or retry_of_evaluation_sha256 is None:
        raise ValueError("retry evaluation requires a parent digest and attempt 2..5")
    return _digest(
        (
            "matraix-chat-evaluation-retry/v1",
            retry_of_evaluation_sha256,
            str(attempt_number),
            task_spec_sha256,
            sut_spec_sha256,
            str(cohort.id),
            cohort.cohort_sha256,
            cohort.dataset_sha256,
            str(cohort.persona_count),
            model_name,
            chat_config_sha256,
            PROMPT_SCHEMA_VERSION,
        )
    )


def calculate_trial_sha256(evaluation_sha256: str, persona: ChatPersonaRef) -> str:
    return _digest(
        (
            "matraix-chat-trial/v1",
            evaluation_sha256,
            str(persona.position),
            str(persona.id),
            persona.persona_id,
            persona.display_name,
            persona.profile_sha256,
        )
    )


def calculate_transcript_sha256(
    trial_sha256: str,
    messages: tuple[ChatTranscriptMessage, ...],
) -> str:
    parts = ["matraix-chat-transcript/v1", trial_sha256]
    for message in messages:
        parts.extend((str(message.position), message.role, message.content))
    return _digest(tuple(parts))


def calculate_feedback_sha256(trial_sha256: str, feedback: ChatTrialFeedback) -> str:
    return _digest(
        (
            "matraix-chat-feedback/v1",
            trial_sha256,
            feedback.schema_version,
            feedback.need_constraint_satisfaction,
            feedback.personal_preference_satisfaction,
            str(feedback.overall_experience_rating),
            feedback.reason,
            _bool_text(feedback.asked_useful_clarification_questions),
            feedback.clarifying_notes,
        )
    )


def calculate_result_sha256(
    trial_sha256: str,
    transcript_sha256: str,
    feedback_sha256: str,
    outcome_status: Literal["resolved", "partially_resolved", "unresolved"],
    next_step_owner: Literal["user", "support", "none"],
    conversation_path: Literal["clarify_then_resolve", "clarify_then_partial", "stalled"],
    resolution_progression: Literal["single_response", "looped", "advanced"],
    message_count: int,
    customer_turn_count: int,
    support_turn_count: int,
    clarification_question_count: int,
) -> str:
    return _digest(
        (
            "matraix-chat-result/v1",
            trial_sha256,
            transcript_sha256,
            feedback_sha256,
            outcome_status,
            next_step_owner,
            conversation_path,
            resolution_progression,
            str(message_count),
            str(customer_turn_count),
            str(support_turn_count),
            str(clarification_question_count),
        )
    )
