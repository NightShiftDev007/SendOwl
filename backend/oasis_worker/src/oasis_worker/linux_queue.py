"""PostgreSQL queue operations for fixed MatrAIx Linux trials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.linux_contracts import (
    LINUX_PROMPT_SCHEMA_VERSION,
    LINUX_RUNNER_SCHEMA_VERSION,
    LINUX_RUNNER_SPEC_SHA256,
    LINUX_TASK_SPEC_SHA256,
    LinuxFrozenTrial,
    LinuxRuntimeConfig,
    LinuxSuccess,
)
from oasis_worker.linux_hashing import result_sha256, trial_sha256
from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import PersonaProfile, SemanticPersona
from oasis_worker.semantic_hashing import persona_profile_sha256


def linux_queue_head(
    connection: Connection[dict[str, object]],
    config: LinuxRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM matraix_linux_trials
            WHERE status='queued' AND model_name=%s AND linux_config_sha256=%s
              AND prompt_schema_version=%s AND runner_schema_version=%s
              AND runner_spec_sha256=%s
            ORDER BY created_at, id LIMIT 1
            """,
            (
                config.model_name,
                config.config_sha256,
                config.prompt_schema_version,
                config.runner_schema_version,
                config.runner_spec_sha256,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    trial_id, created_at = row["id"], row["created_at"]
    if not isinstance(trial_id, UUID) or not isinstance(created_at, datetime):
        raise RuntimeError("Linux queue head returned invalid PostgreSQL types")
    return trial_id, created_at


def _validate_claim(row: dict[str, object], config: LinuxRuntimeConfig) -> LinuxFrozenTrial:
    profile = PersonaProfile.model_validate(row["profile_json"])
    persona = SemanticPersona(
        id=row["persona_id"],
        position=row["persona_position"],
        persona_id=row["persona_external_id"],
        display_name=row["persona_display_name"],
        source=profile.source,
        profile=profile,
        profile_sha256=row["persona_profile_sha256"],
    )
    if persona_profile_sha256(profile) != persona.profile_sha256:
        raise RuntimeError("Linux Persona profile content digest mismatch")
    expected = trial_sha256(
        str(row["task_spec_sha256"]),
        str(row["runner_spec_sha256"]),
        str(row["cohort_id"]),
        str(row["cohort_sha256"]),
        str(row["dataset_sha256"]),
        str(row["persona_id"]),
        int(row["persona_position"]),
        str(row["persona_external_id"]),
        str(row["persona_profile_sha256"]),
        str(row["model_name"]),
        str(row["linux_config_sha256"]),
        str(row["prompt_schema_version"]),
        (str(row["retry_of_trial_sha256"]) if row["retry_of_trial_sha256"] is not None else None),
        int(row["attempt_number"]),
    )
    if (
        row["task_spec_sha256"] != LINUX_TASK_SPEC_SHA256
        or row["runner_schema_version"] != LINUX_RUNNER_SCHEMA_VERSION
        or row["runner_spec_sha256"] != LINUX_RUNNER_SPEC_SHA256
        or row["model_name"] != config.model_name
        or row["linux_config_sha256"] != config.config_sha256
        or row["prompt_schema_version"] != LINUX_PROMPT_SCHEMA_VERSION
        or row["trial_sha256"] != expected
        or row["cohort_title"] != row["actual_cohort_title"]
        or row["cohort_sha256"] != row["actual_cohort_sha256"]
        or row["dataset_sha256"] != row["actual_dataset_sha256"]
        or row["persona_position"] != row["actual_persona_position"]
        or row["persona_external_id"] != row["actual_persona_external_id"]
        or row["persona_display_name"] != row["actual_persona_display_name"]
        or row["persona_profile_sha256"] != row["actual_persona_profile_sha256"]
    ):
        raise RuntimeError("Linux trial frozen identity or content digest mismatch")
    return LinuxFrozenTrial(
        id=row["id"],
        status="running",
        created_at=row["created_at"],
        cohort_id=row["cohort_id"],
        cohort_title=row["cohort_title"],
        cohort_sha256=row["cohort_sha256"],
        dataset_sha256=row["dataset_sha256"],
        persona_position=row["persona_position"],
        persona_id=row["persona_id"],
        persona_external_id=row["persona_external_id"],
        persona_display_name=row["persona_display_name"],
        persona_profile_sha256=row["persona_profile_sha256"],
        task_spec_sha256=row["task_spec_sha256"],
        runner_spec_sha256=row["runner_spec_sha256"],
        model_name=row["model_name"],
        linux_config_sha256=row["linux_config_sha256"],
        prompt_schema_version=row["prompt_schema_version"],
        trial_sha256=row["trial_sha256"],
        persona=persona,
    )


def claim_linux_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    config: LinuxRuntimeConfig,
) -> LinuxFrozenTrial | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT trial.*, cohort.title AS actual_cohort_title,
                       cohort.cohort_sha256 AS actual_cohort_sha256,
                       dataset.dataset_sha256 AS actual_dataset_sha256,
                       member.position AS actual_persona_position,
                       persona.persona_id AS actual_persona_external_id,
                       persona.display_name AS actual_persona_display_name,
                       persona.profile_sha256 AS actual_persona_profile_sha256,
                       persona.profile_json
                FROM matraix_linux_trials trial
                JOIN cohorts cohort ON cohort.id=trial.cohort_id AND cohort.sealed_at IS NOT NULL
                JOIN persona_datasets dataset
                  ON dataset.id=cohort.dataset_id AND dataset.sealed_at IS NOT NULL
                JOIN cohort_members member
                  ON member.cohort_id=cohort.id AND member.persona_id=trial.persona_id
                JOIN personas persona ON persona.id=member.persona_id
                WHERE trial.id=%s AND trial.status='queued'
                  AND trial.model_name=%s AND trial.linux_config_sha256=%s
                  AND trial.prompt_schema_version=%s
                  AND trial.runner_schema_version=%s AND trial.runner_spec_sha256=%s
                FOR UPDATE OF trial SKIP LOCKED
                """,
                (
                    trial_id,
                    config.model_name,
                    config.config_sha256,
                    config.prompt_schema_version,
                    config.runner_schema_version,
                    config.runner_spec_sha256,
                ),
            )
            raw = cursor.fetchone()
            if raw is None:
                connection.commit()
                return None
            trial = _validate_claim(dict(raw), config)
            cursor.execute(
                """
                UPDATE matraix_linux_trials
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued Linux trial could not be claimed")
        connection.commit()
        return trial
    except (ValidationError, RuntimeError, KeyError, TypeError, ValueError) as error:
        connection.rollback()
        fail_linux_trial(
            connection,
            trial_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    f"Linux trial queue integrity validation failed with {type(error).__name__}."
                ),
            ),
            True,
        )
        return None


def complete_linux_trial(
    connection: Connection[dict[str, object]],
    trial: LinuxFrozenTrial,
    worker_id: str,
    result: LinuxSuccess,
) -> None:
    actual = result_sha256(
        trial.trial_sha256,
        result.artifact_sha256,
        result.file_sha256,
        result.reason,
        result.need_constraint_satisfaction,
        result.personal_preference_satisfaction,
        result.overall_experience_rating,
        result.feedback_reason,
    )
    if (
        result.model_name != trial.model_name
        or result.linux_config_sha256 != trial.linux_config_sha256
        or result.prompt_schema_version != trial.prompt_schema_version
        or result.runner_spec_sha256 != trial.runner_spec_sha256
        or result.result_sha256 != actual
    ):
        raise RuntimeError("Linux result identity or content digest mismatch")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_linux_trials SET status='succeeded', completed_at=now(),
                result_runner_version=%s, result_artifact_sha256=%s,
                result_cleaned_list_sha256=%s, result_submission_sha256=%s,
                result_feedback_sha256=%s, result_verifier_sha256=%s,
                result_sha256=%s, result_reason=%s, result_need_satisfaction=%s,
                result_preference_satisfaction=%s, result_rating=%s,
                result_feedback_reason=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (
                result.runner_version,
                result.artifact_sha256,
                result.file_sha256.cleaned_list_csv,
                result.file_sha256.submission_json,
                result.file_sha256.user_feedback_json,
                result.file_sha256.verifier_json,
                result.result_sha256,
                result.reason,
                result.need_constraint_satisfaction,
                result.personal_preference_satisfaction,
                result.overall_experience_rating,
                result.feedback_reason,
                trial.id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("running Linux trial could not be completed")
    connection.commit()


def fail_linux_trial(
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
                UPDATE matraix_linux_trials SET status='running', started_at=now(),
                    claimed_by_worker_id=%s WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
        cursor.execute(
            """
            UPDATE matraix_linux_trials SET status='failed', completed_at=now(),
                error_code=%s, error_message=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (failure.code, failure.message, trial_id, worker_id),
        )
    connection.commit()


def fail_linux_trials_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_linux_trials SET status='failed', completed_at=now(),
                error_code='worker_process_restarted',
                error_message='The model worker restarted before completing this Linux trial.'
            WHERE status='running' AND claimed_by_worker_id=%s
            """,
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_linux_trials(connection: Connection[dict[str, object]], cutoff: datetime) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_linux_trials trial
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_lost',
                error_message='The model worker stopped before completing this Linux trial.'
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
