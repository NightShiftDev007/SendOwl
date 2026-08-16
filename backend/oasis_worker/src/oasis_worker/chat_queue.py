"""PostgreSQL queue operations for durable MatrAIx chatbot evaluations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.chat_contracts import (
    CHAT_MCP_SUT_SPEC_SHA256,
    CHAT_MCP_TASK_ID,
    CHAT_MCP_TASK_SPEC_SHA256,
    CHAT_PROMPT_SCHEMA_VERSION,
    CHAT_REST_TASK_ID,
    CHAT_SUT_SPEC_SHA256,
    CHAT_TASK_SCHEMA_VERSION,
    CHAT_TASK_SPEC_SHA256,
    CHAT_TASK_VERSION,
    ChatEvaluation,
    ChatMessage,
    ChatRuntimeConfig,
    ChatSuccess,
    ClaimedChatTrial,
)
from oasis_worker.chat_hashing import (
    evaluation_sha256,
    feedback_sha256,
    result_sha256,
    transcript_sha256,
    trial_sha256,
)
from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import PersonaProfile, SemanticPersona
from oasis_worker.semantic_hashing import persona_profile_sha256


def chat_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: ChatRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.created_at
            FROM matraix_chat_trials trial
            JOIN matraix_chat_evaluations evaluation ON evaluation.id=trial.evaluation_id
            WHERE trial.status='queued' AND evaluation.input_sealed_at IS NOT NULL
              AND evaluation.model_name=%s AND evaluation.chat_config_sha256=%s
              AND evaluation.prompt_schema_version=%s
            ORDER BY trial.created_at, trial.id LIMIT 1
            """,
            (
                runtime_config.model_name,
                runtime_config.config_sha256,
                runtime_config.prompt_schema_version,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    trial_id = row["id"]
    created_at = row["created_at"]
    if not isinstance(trial_id, UUID) or not isinstance(created_at, datetime):
        raise RuntimeError("chat queue head returned invalid PostgreSQL types")
    return trial_id, created_at


def _chat_evaluation(row: dict[str, object]) -> ChatEvaluation:
    return ChatEvaluation.model_validate(
        {
            "id": row["evaluation_id"],
            "cohort_id": row["cohort_id"],
            "cohort_sha256": row["cohort_sha256"],
            "cohort_title": row["cohort_title"],
            "dataset_sha256": row["dataset_sha256"],
            "persona_count": row["persona_count"],
            "task_id": row["task_id"],
            "task_version": row["task_version"],
            "task_schema_version": row["task_schema_version"],
            "task_spec_sha256": row["task_spec_sha256"],
            "sut_spec_sha256": row["sut_spec_sha256"],
            "model_name": row["evaluation_model_name"],
            "chat_config_sha256": row["evaluation_chat_config_sha256"],
            "prompt_schema_version": row["evaluation_prompt_schema_version"],
            "evaluation_sha256": row["evaluation_sha256"],
            "retry_of_evaluation_id": row["retry_of_evaluation_id"],
            "retry_of_evaluation_sha256": row["retry_of_evaluation_sha256"],
            "attempt_number": row["attempt_number"],
            "created_at": row["evaluation_created_at"],
        }
    )


def _chat_persona(row: dict[str, object]) -> SemanticPersona:
    profile = PersonaProfile.model_validate(row["profile_json"])
    return SemanticPersona(
        id=row["persona_id"],
        position=row["persona_position"],
        persona_id=row["persona_external_id"],
        display_name=row["persona_display_name"],
        source=profile.source,
        profile=profile,
        profile_sha256=row["persona_profile_sha256"],
    )


def _validate_claim(
    row: dict[str, object],
    runtime_config: ChatRuntimeConfig,
) -> ClaimedChatTrial:
    evaluation = _chat_evaluation(row)
    persona = _chat_persona(row)
    expected_hashes = (
        (CHAT_MCP_TASK_SPEC_SHA256, CHAT_MCP_SUT_SPEC_SHA256)
        if evaluation.task_id == CHAT_MCP_TASK_ID
        else (CHAT_TASK_SPEC_SHA256, CHAT_SUT_SPEC_SHA256)
    )
    if (
        evaluation.task_id not in {CHAT_REST_TASK_ID, CHAT_MCP_TASK_ID}
        or evaluation.task_version != CHAT_TASK_VERSION
        or evaluation.task_schema_version != CHAT_TASK_SCHEMA_VERSION
        or (evaluation.task_spec_sha256, evaluation.sut_spec_sha256) != expected_hashes
        or evaluation.model_name != runtime_config.model_name
        or evaluation.chat_config_sha256 != runtime_config.config_sha256
        or evaluation.prompt_schema_version != CHAT_PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError("chat evaluation does not match the live runtime identity")
    if evaluation_sha256(evaluation) != evaluation.evaluation_sha256:
        raise RuntimeError("chat evaluation digest mismatch")
    if persona_profile_sha256(persona.profile) != persona.profile_sha256:
        raise RuntimeError("chat Persona profile content digest mismatch")
    expected_trial = trial_sha256(
        evaluation.evaluation_sha256,
        persona.position,
        persona.id,
        persona.persona_id,
        persona.display_name,
        persona.profile_sha256,
    )
    if expected_trial != row["trial_sha256"]:
        raise RuntimeError("chat trial digest mismatch")
    return ClaimedChatTrial(
        id=row["id"],
        status="running",
        created_at=row["created_at"],
        persona_position=row["persona_position"],
        persona_id=row["persona_id"],
        persona_external_id=row["persona_external_id"],
        persona_display_name=row["persona_display_name"],
        persona_profile_sha256=row["persona_profile_sha256"],
        trial_sha256=row["trial_sha256"],
        evaluation=evaluation,
        persona=persona,
    )


def claim_chat_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    runtime_config: ChatRuntimeConfig,
) -> ClaimedChatTrial | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT trial.*, evaluation.cohort_id, evaluation.cohort_sha256,
                       evaluation.cohort_title, evaluation.dataset_sha256,
                       evaluation.persona_count, evaluation.task_id,
                       evaluation.task_version, evaluation.task_schema_version,
                       evaluation.task_spec_sha256, evaluation.sut_spec_sha256,
                       evaluation.model_name AS evaluation_model_name,
                       evaluation.chat_config_sha256 AS evaluation_chat_config_sha256,
                       evaluation.prompt_schema_version AS evaluation_prompt_schema_version,
                       evaluation.evaluation_sha256,
                       evaluation.retry_of_evaluation_id,
                       evaluation.retry_of_evaluation_sha256,
                       evaluation.attempt_number,
                       evaluation.created_at AS evaluation_created_at,
                       cohort.id AS actual_cohort_id,
                       cohort.title AS actual_cohort_title,
                       cohort.persona_count AS actual_cohort_persona_count,
                       cohort.cohort_sha256 AS actual_cohort_sha256,
                       dataset.dataset_sha256 AS actual_dataset_sha256,
                       member.position AS actual_persona_position,
                       persona.persona_id AS actual_persona_external_id,
                       persona.display_name AS actual_persona_display_name,
                       persona.profile_sha256 AS actual_persona_profile_sha256,
                       persona.profile_json
                FROM matraix_chat_trials trial
                JOIN matraix_chat_evaluations evaluation
                  ON evaluation.id=trial.evaluation_id AND evaluation.input_sealed_at IS NOT NULL
                JOIN cohorts cohort
                  ON cohort.id=evaluation.cohort_id AND cohort.sealed_at IS NOT NULL
                JOIN persona_datasets dataset
                  ON dataset.id=cohort.dataset_id AND dataset.sealed_at IS NOT NULL
                JOIN cohort_members member
                  ON member.cohort_id=cohort.id AND member.persona_id=trial.persona_id
                JOIN personas persona ON persona.id=member.persona_id
                WHERE trial.id=%s AND trial.status='queued'
                  AND evaluation.model_name=%s AND evaluation.chat_config_sha256=%s
                  AND evaluation.prompt_schema_version=%s
                FOR UPDATE OF trial SKIP LOCKED
                """,
                (
                    trial_id,
                    runtime_config.model_name,
                    runtime_config.config_sha256,
                    runtime_config.prompt_schema_version,
                ),
            )
            raw = cursor.fetchone()
            if raw is None:
                connection.commit()
                return None
            row = dict(raw)
            if (
                row["cohort_sha256"] != row["actual_cohort_sha256"]
                or row["cohort_title"] != row["actual_cohort_title"]
                or row["persona_count"] != row["actual_cohort_persona_count"]
                or row["dataset_sha256"] != row["actual_dataset_sha256"]
                or row["cohort_id"] != row["actual_cohort_id"]
                or row["persona_position"] != row["actual_persona_position"]
                or row["persona_external_id"] != row["actual_persona_external_id"]
                or row["persona_display_name"] != row["actual_persona_display_name"]
                or row["persona_profile_sha256"] != row["actual_persona_profile_sha256"]
            ):
                raise RuntimeError("chat trial frozen Cohort or Persona binding mismatch")
            job = _validate_claim(row, runtime_config)
            cursor.execute(
                """
                UPDATE matraix_chat_trials
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued chat trial could not be claimed")
        connection.commit()
        return job
    except (ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        if isinstance(error, ValidationError):
            issue = error.errors(include_url=False, include_input=False)[0]
            location = ".".join(str(part) for part in issue["loc"]) or "claim"
            detail = f"validation failed at {location}: {issue['type']}"
        else:
            detail = f"validation failed with {type(error).__name__}"
        fail_chat_trial(
            connection,
            trial_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=f"Chat trial queue integrity {detail}."[:500],
            ),
            True,
        )
        return None


def append_chat_message(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    message: ChatMessage,
) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM matraix_chat_trials
                WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
                FOR UPDATE
                """,
                (trial_id, worker_id),
            )
            if cursor.fetchone() is None:
                raise RuntimeError("chat trial is no longer owned and running")
            cursor.execute(
                """
                SELECT count(*) AS count FROM matraix_chat_messages WHERE trial_id=%s
                """,
                (trial_id,),
            )
            count_row = cursor.fetchone()
            if count_row is None or count_row["count"] != message.position:
                raise RuntimeError("chat message position is not the next append-only position")
            cursor.execute(
                """
                INSERT INTO matraix_chat_messages
                    (trial_id, position, role, content, recorded_at)
                VALUES (%s, %s, %s, %s, now())
                """,
                (trial_id, message.position, message.role, message.content),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _verify_success(trial_sha: str, result: ChatSuccess) -> None:
    actual_transcript = transcript_sha256(trial_sha, result.messages)
    actual_feedback = feedback_sha256(trial_sha, result.feedback)
    actual_result = result_sha256(
        trial_sha,
        actual_transcript,
        actual_feedback,
        result.result,
    )
    if (
        result.transcript_sha256 != actual_transcript
        or result.feedback_sha256 != actual_feedback
        or result.result_sha256 != actual_result
    ):
        raise RuntimeError("chat result content digests do not match the completed artifacts")


def complete_chat_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    result: ChatSuccess,
) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT trial_sha256 FROM matraix_chat_trials
                WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE
                """,
                (trial_id, worker_id),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("chat trial is no longer owned and running")
            _verify_success(row["trial_sha256"], result)
            cursor.execute(
                """
                SELECT position, role, content FROM matraix_chat_messages
                WHERE trial_id=%s ORDER BY position
                """,
                (trial_id,),
            )
            persisted = tuple(ChatMessage.model_validate(item) for item in cursor.fetchall())
            if persisted != result.messages:
                raise RuntimeError("persisted chat transcript differs from the verified result")
            feedback = result.feedback
            cursor.execute(
                """
                INSERT INTO matraix_chat_feedback (
                    trial_id, schema_version, need_constraint_satisfaction,
                    personal_preference_satisfaction, overall_experience_rating,
                    reason, asked_useful_clarification_questions, clarifying_notes, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                """,
                (
                    trial_id,
                    feedback.schema_version,
                    feedback.need_constraint_satisfaction,
                    feedback.personal_preference_satisfaction,
                    feedback.overall_experience_rating,
                    feedback.reason,
                    feedback.asked_useful_clarification_questions,
                    feedback.clarifying_notes,
                ),
            )
            outcome = result.result
            cursor.execute(
                """
                UPDATE matraix_chat_trials SET
                    status='succeeded', completed_at=now(), runner_version=%s,
                    model_name=%s, chat_config_sha256=%s, prompt_schema_version=%s,
                    transcript_sha256=%s, feedback_sha256=%s, result_sha256=%s,
                    outcome_status=%s, next_step_owner=%s, conversation_path=%s,
                    resolution_progression=%s, message_count=%s,
                    customer_turn_count=%s, support_turn_count=%s,
                    clarification_question_count=%s
                WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
                """,
                (
                    result.runner_version,
                    result.model_name,
                    result.chat_config_sha256,
                    result.prompt_schema_version,
                    result.transcript_sha256,
                    result.feedback_sha256,
                    result.result_sha256,
                    outcome.outcome_status,
                    outcome.next_step_owner,
                    outcome.conversation_path,
                    outcome.resolution_progression,
                    outcome.message_count,
                    outcome.customer_turn_count,
                    outcome.support_turn_count,
                    outcome.clarification_question_count,
                    trial_id,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("running chat trial could not be completed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def fail_chat_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_first: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_first:
            cursor.execute(
                """
                UPDATE matraix_chat_trials
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
        cursor.execute(
            """
            UPDATE matraix_chat_trials
            SET status='failed', completed_at=now(), error_code=%s, error_message=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (failure.code, failure.message, trial_id, worker_id),
        )
    connection.commit()


def fail_chat_trials_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_chat_trials
            SET status='failed', completed_at=now(), error_code='worker_process_restarted',
                error_message='The model worker restarted before completing this chat trial.'
            WHERE status='running' AND claimed_by_worker_id=%s
            """,
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_chat_trials(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("chat trial orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_chat_trials trial
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The model worker heartbeat expired during this chat trial.'
            WHERE trial.status='running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats heartbeat
                WHERE heartbeat.worker_id=trial.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


__all__ = [
    "append_chat_message",
    "chat_queue_head",
    "claim_chat_trial",
    "complete_chat_trial",
    "fail_chat_trial",
    "fail_chat_trials_owned_by_worker",
    "fail_orphaned_chat_trials",
]
