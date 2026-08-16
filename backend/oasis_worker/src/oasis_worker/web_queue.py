"""PostgreSQL queue operations for immutable MatrAIx Playwright trials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import PersonaProfile, SemanticPersona
from oasis_worker.semantic_hashing import persona_profile_sha256
from oasis_worker.web_contracts import (
    WEB_EXECUTOR_SCHEMA_VERSION,
    WEB_EXECUTOR_SPEC_SHA256,
    WEB_PROMPT_SCHEMA_VERSION,
    WEB_TASK_ID,
    WEB_TASK_SCHEMA_VERSION,
    WEB_TASK_SPEC_SHA256,
    WEB_TASK_VERSION,
    ClaimedWebTrial,
    WebEvaluation,
    WebRuntimeConfig,
    WebSuccess,
)
from oasis_worker.web_hashing import (
    evaluation_sha256,
    result_sha256,
    trace_sha256,
    trial_sha256,
)


def web_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: WebRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.created_at
            FROM matraix_web_trials trial
            JOIN matraix_web_evaluations evaluation ON evaluation.id=trial.evaluation_id
            WHERE trial.status='queued' AND evaluation.input_sealed_at IS NOT NULL
              AND evaluation.model_name=%s AND evaluation.web_config_sha256=%s
              AND evaluation.prompt_schema_version=%s
              AND evaluation.executor_schema_version=%s
              AND evaluation.executor_spec_sha256=%s
            ORDER BY trial.created_at, trial.id LIMIT 1
            """,
            (
                runtime_config.model_name,
                runtime_config.config_sha256,
                runtime_config.prompt_schema_version,
                runtime_config.executor_schema_version,
                runtime_config.executor_spec_sha256,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    trial_id = row["id"]
    created_at = row["created_at"]
    if not isinstance(trial_id, UUID) or not isinstance(created_at, datetime):
        raise RuntimeError("Web queue head returned invalid PostgreSQL types")
    return trial_id, created_at


def _evaluation(row: dict[str, object]) -> WebEvaluation:
    return WebEvaluation.model_validate(
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
            "executor_schema_version": row["executor_schema_version"],
            "executor_spec_sha256": row["executor_spec_sha256"],
            "model_name": row["evaluation_model_name"],
            "web_config_sha256": row["evaluation_web_config_sha256"],
            "prompt_schema_version": row["evaluation_prompt_schema_version"],
            "evaluation_sha256": row["evaluation_sha256"],
            "created_at": row["evaluation_created_at"],
        }
    )


def _persona(row: dict[str, object]) -> SemanticPersona:
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
    runtime_config: WebRuntimeConfig,
) -> ClaimedWebTrial:
    evaluation = _evaluation(row)
    persona = _persona(row)
    if (
        evaluation.task_id != WEB_TASK_ID
        or evaluation.task_version != WEB_TASK_VERSION
        or evaluation.task_schema_version != WEB_TASK_SCHEMA_VERSION
        or evaluation.task_spec_sha256 != WEB_TASK_SPEC_SHA256
        or evaluation.executor_schema_version != WEB_EXECUTOR_SCHEMA_VERSION
        or evaluation.executor_spec_sha256 != WEB_EXECUTOR_SPEC_SHA256
        or evaluation.model_name != runtime_config.model_name
        or evaluation.web_config_sha256 != runtime_config.config_sha256
        or evaluation.prompt_schema_version != WEB_PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError("Web evaluation does not match the live runtime identity")
    actual_evaluation_sha = evaluation_sha256(
        evaluation.task_spec_sha256,
        evaluation.executor_spec_sha256,
        evaluation.cohort_id,
        evaluation.cohort_sha256,
        evaluation.dataset_sha256,
        evaluation.persona_count,
        evaluation.model_name,
        evaluation.web_config_sha256,
    )
    if actual_evaluation_sha != evaluation.evaluation_sha256:
        raise RuntimeError("Web evaluation digest mismatch")
    if persona_profile_sha256(persona.profile) != persona.profile_sha256:
        raise RuntimeError("Web Persona profile content digest mismatch")
    actual_trial_sha = trial_sha256(
        evaluation.evaluation_sha256,
        persona.position,
        persona.id,
        persona.persona_id,
        persona.display_name,
        persona.profile_sha256,
    )
    if actual_trial_sha != row["trial_sha256"]:
        raise RuntimeError("Web trial digest mismatch")
    return ClaimedWebTrial(
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


def claim_web_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    runtime_config: WebRuntimeConfig,
) -> ClaimedWebTrial | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT trial.*, evaluation.cohort_id, evaluation.cohort_sha256,
                       evaluation.cohort_title, evaluation.dataset_sha256,
                       evaluation.persona_count, evaluation.task_id,
                       evaluation.task_version, evaluation.task_schema_version,
                       evaluation.task_spec_sha256, evaluation.executor_schema_version,
                       evaluation.executor_spec_sha256,
                       evaluation.model_name AS evaluation_model_name,
                       evaluation.web_config_sha256 AS evaluation_web_config_sha256,
                       evaluation.prompt_schema_version AS evaluation_prompt_schema_version,
                       evaluation.evaluation_sha256,
                       evaluation.created_at AS evaluation_created_at,
                       cohort.title AS actual_cohort_title,
                       cohort.persona_count AS actual_cohort_persona_count,
                       cohort.cohort_sha256 AS actual_cohort_sha256,
                       dataset.dataset_sha256 AS actual_dataset_sha256,
                       member.position AS actual_persona_position,
                       persona.persona_id AS actual_persona_external_id,
                       persona.display_name AS actual_persona_display_name,
                       persona.profile_sha256 AS actual_persona_profile_sha256,
                       persona.profile_json
                FROM matraix_web_trials trial
                JOIN matraix_web_evaluations evaluation
                  ON evaluation.id=trial.evaluation_id AND evaluation.input_sealed_at IS NOT NULL
                JOIN cohorts cohort
                  ON cohort.id=evaluation.cohort_id AND cohort.sealed_at IS NOT NULL
                JOIN persona_datasets dataset
                  ON dataset.id=cohort.dataset_id AND dataset.sealed_at IS NOT NULL
                JOIN cohort_members member
                  ON member.cohort_id=cohort.id AND member.persona_id=trial.persona_id
                JOIN personas persona ON persona.id=member.persona_id
                WHERE trial.id=%s AND trial.status='queued'
                  AND evaluation.model_name=%s AND evaluation.web_config_sha256=%s
                  AND evaluation.prompt_schema_version=%s
                  AND evaluation.executor_schema_version=%s
                  AND evaluation.executor_spec_sha256=%s
                FOR UPDATE OF trial SKIP LOCKED
                """,
                (
                    trial_id,
                    runtime_config.model_name,
                    runtime_config.config_sha256,
                    runtime_config.prompt_schema_version,
                    runtime_config.executor_schema_version,
                    runtime_config.executor_spec_sha256,
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
                or row["persona_position"] != row["actual_persona_position"]
                or row["persona_external_id"] != row["actual_persona_external_id"]
                or row["persona_display_name"] != row["actual_persona_display_name"]
                or row["persona_profile_sha256"] != row["actual_persona_profile_sha256"]
            ):
                raise RuntimeError("Web trial frozen Cohort or Persona binding mismatch")
            trial = _validate_claim(row, runtime_config)
            cursor.execute(
                """
                UPDATE matraix_web_trials
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued Web trial could not be claimed")
        connection.commit()
        return trial
    except (ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_web_trial(
            connection,
            trial_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    f"Web trial queue integrity validation failed with {type(error).__name__}."
                ),
            ),
            True,
        )
        return None


def complete_web_trial(
    connection: Connection[dict[str, object]],
    trial: ClaimedWebTrial,
    worker_id: str,
    result: WebSuccess,
) -> None:
    actual_trace = trace_sha256(trial.trial_sha256, result.pages)
    actual_result = result_sha256(
        trial.trial_sha256,
        actual_trace,
        result.decision_subject_id,
        result.decision_subject_label,
        result.basis_primary,
        result.reason,
        result.task_author,
        result.need_constraint_satisfaction,
        result.personal_preference_satisfaction,
        result.overall_experience_rating,
    )
    if (
        result.model_name != trial.evaluation.model_name
        or result.web_config_sha256 != trial.evaluation.web_config_sha256
        or result.prompt_schema_version != trial.evaluation.prompt_schema_version
        or result.trace_sha256 != actual_trace
        or result.result_sha256 != actual_result
    ):
        raise RuntimeError("Web result identity or content digest mismatch")
    selected = next(
        (
            quote
            for page in result.pages
            for quote in page.quotes
            if quote.quote_id == result.decision_subject_id
        ),
        None,
    )
    if (
        selected is None
        or selected.text != result.decision_subject_label
        or selected.author != result.task_author
    ):
        raise RuntimeError("Web result selected quote is absent from observations")
    try:
        with connection.cursor() as cursor:
            for page in result.pages:
                cursor.execute(
                    """
                    INSERT INTO matraix_web_pages (
                        trial_id, position, url, title, screenshot_sha256, observed_at
                    ) VALUES (%s, %s, %s, %s, %s, now())
                    """,
                    (
                        trial.id,
                        page.position,
                        page.url,
                        page.title,
                        page.screenshot_sha256,
                    ),
                )
                for quote in page.quotes:
                    cursor.execute(
                        """
                        INSERT INTO matraix_web_quotes (
                            trial_id, position, page_position, quote_id, text, author, tags
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            trial.id,
                            quote.position,
                            page.position,
                            quote.quote_id,
                            quote.text,
                            quote.author,
                            list(quote.tags),
                        ),
                    )
            cursor.execute(
                """
                UPDATE matraix_web_trials SET
                    status='succeeded', completed_at=now(), runner_version=%s,
                    model_name=%s, web_config_sha256=%s, prompt_schema_version=%s,
                    trace_sha256=%s, result_sha256=%s, decision_subject_id=%s,
                    decision_subject_label=%s, basis_primary=%s, reason=%s,
                    task_author=%s, need_constraint_satisfaction=%s,
                    personal_preference_satisfaction=%s, overall_experience_rating=%s
                WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
                """,
                (
                    result.runner_version,
                    result.model_name,
                    result.web_config_sha256,
                    result.prompt_schema_version,
                    result.trace_sha256,
                    result.result_sha256,
                    result.decision_subject_id,
                    result.decision_subject_label,
                    result.basis_primary,
                    result.reason,
                    result.task_author,
                    result.need_constraint_satisfaction,
                    result.personal_preference_satisfaction,
                    result.overall_experience_rating,
                    trial.id,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("running Web trial could not be completed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def fail_web_trial(
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
                UPDATE matraix_web_trials
                SET status='running', started_at=now(), claimed_by_worker_id=%s
                WHERE id=%s AND status='queued'
                """,
                (worker_id, trial_id),
            )
        cursor.execute(
            """
            UPDATE matraix_web_trials
            SET status='failed', completed_at=now(), error_code=%s, error_message=%s
            WHERE id=%s AND status='running' AND claimed_by_worker_id=%s
            """,
            (failure.code, failure.message, trial_id, worker_id),
        )
    connection.commit()


def fail_web_trials_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_web_trials
            SET status='failed', completed_at=now(), error_code='worker_process_restarted',
                error_message='The model worker restarted before completing this Web trial.'
            WHERE status='running' AND claimed_by_worker_id=%s
            """,
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_web_trials(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Web orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_web_trials trial
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_lost',
                error_message='The model worker stopped before completing this Web trial.'
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
    "claim_web_trial",
    "complete_web_trial",
    "fail_orphaned_web_trials",
    "fail_web_trial",
    "fail_web_trials_owned_by_worker",
    "web_queue_head",
]
