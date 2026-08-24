"""PostgreSQL queue operations for native research Survey trials."""

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.research_survey_contracts import (
    ClaimedResearchSurveyTrial,
    ResearchSurveyContext,
    ResearchSurveyRuntimeConfig,
    ResearchSurveySuccess,
)
from oasis_worker.research_survey_hashing import research_survey_answers_sha256
from oasis_worker.semantic_contracts import PersonaProfile, SemanticPersona


def research_survey_queue_head(
    connection: Connection[dict[str, object]], config: ResearchSurveyRuntimeConfig
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.created_at
            FROM research_survey_trials trial
            JOIN research_surveys survey ON survey.id=trial.survey_id
            WHERE trial.status='queued' AND survey.sealed_at IS NOT NULL
              AND survey.model_name=%s AND survey.survey_config_sha256=%s
              AND survey.prompt_schema_version=%s
            ORDER BY trial.created_at, trial.id LIMIT 1
            """,
            (config.model_name, config.config_sha256, config.prompt_schema_version),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    if not isinstance(row["id"], UUID) or not isinstance(row["created_at"], datetime):
        raise RuntimeError("native Survey queue head has invalid storage types")
    return row["id"], row["created_at"]


def claim_research_survey_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    config: ResearchSurveyRuntimeConfig,
) -> ClaimedResearchSurveyTrial | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.*, survey.research_project_id,
                   survey.research_simulation_run_id, survey.project_title,
                   survey.research_question, survey.project_sha256,
                   survey.simulation_requirement, survey.initial_post,
                   survey.run_spec_sha256, survey.cohort_id, survey.cohort_sha256,
                   survey.persona_count, survey.model_name AS frozen_model_name,
                   survey.survey_config_sha256 AS frozen_config_sha256,
                   survey.survey_sha256, persona.source, persona.profile_json
            FROM research_survey_trials trial
            JOIN research_surveys survey ON survey.id=trial.survey_id
            JOIN personas persona ON persona.id=trial.persona_id
            WHERE trial.id=%s AND trial.status='queued'
              AND survey.sealed_at IS NOT NULL AND survey.model_name=%s
              AND survey.survey_config_sha256=%s
              AND survey.prompt_schema_version=%s
            FOR UPDATE OF trial SKIP LOCKED
            """,
            (trial_id, config.model_name, config.config_sha256, config.prompt_schema_version),
        )
        row = cursor.fetchone()
        if row is None:
            connection.commit()
            return None
        try:
            persona = SemanticPersona.model_validate(
                {
                    "id": row["persona_id"],
                    "position": row["persona_position"],
                    "persona_id": row["persona_external_id"],
                    "display_name": row["persona_display_name"],
                    "source": row["source"],
                    "profile": PersonaProfile.model_validate(row["profile_json"]),
                    "profile_sha256": row["persona_profile_sha256"],
                }
            )
            survey = ResearchSurveyContext.model_validate(
                {
                    "id": row["survey_id"],
                    "project_id": row["research_project_id"],
                    "run_id": row["research_simulation_run_id"],
                    "project_title": row["project_title"],
                    "research_question": row["research_question"],
                    "simulation_requirement": row["simulation_requirement"],
                    "initial_post": row["initial_post"],
                    "project_sha256": row["project_sha256"],
                    "run_spec_sha256": row["run_spec_sha256"],
                    "cohort_id": row["cohort_id"],
                    "cohort_sha256": row["cohort_sha256"],
                    "persona_count": row["persona_count"],
                    "model_name": row["frozen_model_name"],
                    "survey_config_sha256": row["frozen_config_sha256"],
                    "survey_sha256": row["survey_sha256"],
                }
            )
            trial = ClaimedResearchSurveyTrial.model_validate(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "persona_position": row["persona_position"],
                    "persona_id": row["persona_id"],
                    "persona_external_id": row["persona_external_id"],
                    "persona_display_name": row["persona_display_name"],
                    "persona_profile_sha256": row["persona_profile_sha256"],
                    "trial_sha256": row["trial_sha256"],
                    "survey": survey,
                    "persona": persona,
                }
            )
        except (ValidationError, ValueError, TypeError) as error:
            cursor.execute(
                "UPDATE research_survey_trials SET status='running', started_at=now(), "
                "claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, trial_id),
            )
            cursor.execute(
                "UPDATE research_survey_trials SET status='failed', completed_at=now(), "
                "error_code='queue_integrity', error_message=%s "
                "WHERE id=%s AND status='running'",
                (f"Native Survey queue validation failed: {type(error).__name__}", trial_id),
            )
            connection.commit()
            return None
        cursor.execute(
            "UPDATE research_survey_trials SET status='running', started_at=now(), "
            "claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
            (worker_id, trial_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
    connection.commit()
    return trial


def complete_research_survey_trial(
    connection: Connection[dict[str, object]],
    trial: ClaimedResearchSurveyTrial,
    worker_id: str,
    result: ResearchSurveySuccess,
) -> None:
    if (
        result.model_name != trial.survey.model_name
        or result.survey_config_sha256 != trial.survey.survey_config_sha256
        or result.answers_sha256
        != research_survey_answers_sha256(trial.trial_sha256, result.answers)
    ):
        raise RuntimeError("native Survey result identity mismatch")
    clarity, focus, question = result.answers
    rows = [
        (trial.id, 0, clarity.question_id, clarity.type, None, clarity.value, None),
        (trial.id, 1, focus.question_id, focus.type, focus.value, None, None),
        (trial.id, 2, question.question_id, question.type, None, None, question.value),
    ]
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO research_survey_answers "
            "(trial_id, question_position, question_id, answer_type, choice_value, "
            "likert_value, free_text_value, recorded_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,now())",
            rows,
        )
        cursor.execute(
            "UPDATE research_survey_trials SET status='succeeded', completed_at=now(), "
            "runner_version=%s, model_name=%s, survey_config_sha256=%s, "
            "prompt_schema_version=%s, answers_sha256=%s "
            "WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (
                result.runner_version,
                result.model_name,
                result.survey_config_sha256,
                result.prompt_schema_version,
                result.answers_sha256,
                trial.id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError("native Survey trial is no longer running")
    connection.commit()


def fail_research_survey_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_survey_trials SET status='failed', completed_at=now(), "
            "error_code=%s, error_message=%s "
            "WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (failure.code, failure.message, trial_id, worker_id),
        )
    connection.commit()


def fail_research_survey_trials_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE research_survey_trials SET status='failed', completed_at=now(), "
            "error_code='worker_process_restarted', "
            "error_message='The evaluation worker restarted before completing this native "
            "Survey trial.' WHERE status='running' AND claimed_by_worker_id=%s",
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_research_survey_trials(
    connection: Connection[dict[str, object]], cutoff: datetime
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE research_survey_trials trial
            SET status='failed', completed_at=now(),
                error_code='worker_heartbeat_lost',
                error_message='The evaluation worker stopped before completing this '
                              'native Survey trial.'
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
