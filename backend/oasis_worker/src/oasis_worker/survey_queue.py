"""PostgreSQL queue operations for immutable MatrAIx scenario-preference trials."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from psycopg import Connection, Cursor
from psycopg import Error as PsycopgError
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import PersonaProfile, SemanticPersona
from oasis_worker.semantic_hashing import persona_profile_sha256
from oasis_worker.survey_contracts import (
    ClaimedSurveyTrial,
    PositionedAlternativeSupportAnswer,
    PositionedPreferredVariantAnswer,
    PositionedPrimaryReasonAnswer,
    PositionedSurveyAnswer,
    SurveyCohortMember,
    SurveyExperiment,
    SurveyRuntimeConfig,
    SurveySuccess,
)
from oasis_worker.survey_hashing import (
    answers_sha256,
    build_survey_instrument,
    experiment_sha256,
    instrument_sha256,
    trial_sha256,
)


def _uuid(value: object, location: str) -> UUID:
    if not isinstance(value, UUID):
        raise RuntimeError(f"expected PostgreSQL UUID at {location}")
    return value


def _json_object(value: object, location: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(f"expected JSON object at {location}")
    return {str(key): item for key, item in value.items()}


def _text(value: object, location: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"expected PostgreSQL text at {location}")
    return value


def _queue_failure(error: BaseException) -> NormalizedFailure:
    if isinstance(error, ValidationError):
        issue = error.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in issue["loc"]) or "input"
        detail = f"validation failed at {location} ({issue['type']})"
    elif isinstance(error, (RuntimeError, ValueError)):
        detail = str(error)
    elif isinstance(error, KeyError):
        detail = f"required storage field {error!s} is missing"
    else:
        detail = f"validation failed with {type(error).__name__}"
    return NormalizedFailure(
        code="queue_integrity",
        message=("Survey queue integrity check failed: " + " ".join(detail.split()))[:500],
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _cohort_sha256(
    title: str,
    dataset_sha256: str,
    members: tuple[SurveyCohortMember, ...],
) -> str:
    payload = {
        "schema": "matraix-cohort/v1",
        "title": title,
        "dataset_sha256": dataset_sha256,
        "persona_count": len(members),
        "members": [
            {"persona_id": item.persona_id, "profile_sha256": item.profile_sha256}
            for item in members
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def survey_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SurveyRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.created_at
            FROM matraix_survey_trials AS trial
            JOIN matraix_survey_experiments AS experiment
              ON experiment.id = trial.experiment_id
            WHERE trial.status = 'queued' AND experiment.input_sealed_at IS NOT NULL
              AND experiment.model_name = %s
              AND experiment.survey_config_sha256 = %s
              AND experiment.prompt_schema_version = %s
            ORDER BY trial.created_at, trial.id
            LIMIT 1
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
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("queued survey trial created_at is not a PostgreSQL timestamp")
    return _uuid(row["id"], "matraix_survey_trials.id"), created_at


def _load_experiment(
    cursor: Cursor[dict[str, object]],
    experiment_id: UUID,
) -> SurveyExperiment:
    cursor.execute(
        """
        SELECT id, scenario_id, scenario_sha256, scenario_title, decision_question,
               cohort_id, cohort_sha256, cohort_title, dataset_sha256, persona_count,
               baseline_id, baseline_position, baseline_name, baseline_hypothesis,
               alternative_id, alternative_position, alternative_name,
               alternative_hypothesis, instrument_schema_version, instrument_sha256,
               model_name, survey_config_sha256, prompt_schema_version,
               experiment_sha256, created_at
               ,retry_of_experiment_id, retry_of_experiment_sha256, attempt_number
        FROM matraix_survey_experiments
        WHERE id = %s AND input_sealed_at IS NOT NULL
        """,
        (experiment_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"survey trial references missing sealed experiment {experiment_id}")
    instrument = build_survey_instrument(
        _text(row["baseline_name"], "matraix_survey_experiments.baseline_name"),
        _text(
            row["baseline_hypothesis"],
            "matraix_survey_experiments.baseline_hypothesis",
        ),
        _text(row["alternative_name"], "matraix_survey_experiments.alternative_name"),
        _text(
            row["alternative_hypothesis"],
            "matraix_survey_experiments.alternative_hypothesis",
        ),
    )
    return SurveyExperiment.model_validate(
        {
            **row,
            "instrument": instrument,
        }
    )


def _load_cohort_members(
    cursor: Cursor[dict[str, object]],
    cohort_id: UUID,
) -> tuple[SurveyCohortMember, ...]:
    cursor.execute(
        """
        SELECT member.position, persona.persona_id, persona.profile_sha256
        FROM cohort_members AS member
        JOIN personas AS persona
          ON persona.dataset_id = member.dataset_id AND persona.id = member.persona_id
        WHERE member.cohort_id = %s
        ORDER BY member.position
        """,
        (cohort_id,),
    )
    return tuple(SurveyCohortMember.model_validate(row) for row in cursor.fetchall())


def _load_persona(
    cursor: Cursor[dict[str, object]],
    cohort_id: UUID,
    persona_position: int,
) -> SemanticPersona:
    cursor.execute(
        """
        SELECT persona.id, member.position, persona.persona_id, persona.display_name,
               persona.source, persona.profile_json, persona.profile_sha256
        FROM cohort_members AS member
        JOIN personas AS persona
          ON persona.dataset_id = member.dataset_id AND persona.id = member.persona_id
        WHERE member.cohort_id = %s AND member.position = %s
        """,
        (cohort_id, persona_position),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("survey trial persona is absent from its sealed cohort position")
    return SemanticPersona.model_validate(
        {
            "id": row["id"],
            "position": row["position"],
            "persona_id": row["persona_id"],
            "display_name": row["display_name"],
            "source": row["source"],
            "profile": PersonaProfile.model_validate(
                _json_object(row["profile_json"], "personas.profile_json")
            ),
            "profile_sha256": row["profile_sha256"],
        }
    )


def _validate_source_bindings(
    cursor: Cursor[dict[str, object]],
    experiment: SurveyExperiment,
    persona: SemanticPersona,
    members: tuple[SurveyCohortMember, ...],
    runtime_config: SurveyRuntimeConfig,
) -> None:
    cursor.execute(
        """
        SELECT scenario.title, scenario.decision_question, scenario.scenario_sha256,
               baseline.position AS baseline_position, baseline.name AS baseline_name,
               baseline.hypothesis AS baseline_hypothesis,
               alternative.position AS alternative_position,
               alternative.name AS alternative_name,
               alternative.hypothesis AS alternative_hypothesis
        FROM scenarios AS scenario
        JOIN scenario_variants AS baseline
          ON baseline.scenario_id = scenario.id AND baseline.id = %s
        JOIN scenario_variants AS alternative
          ON alternative.scenario_id = scenario.id AND alternative.id = %s
        WHERE scenario.id = %s AND scenario.sealed_at IS NOT NULL
        """,
        (experiment.baseline_id, experiment.alternative_id, experiment.scenario_id),
    )
    scenario = cursor.fetchone()
    if scenario is None:
        raise RuntimeError("survey experiment references a missing sealed scenario or variant")
    frozen_scenario = (
        experiment.scenario_title,
        experiment.decision_question,
        experiment.scenario_sha256,
        experiment.baseline_position,
        experiment.baseline_name,
        experiment.baseline_hypothesis,
        experiment.alternative_position,
        experiment.alternative_name,
        experiment.alternative_hypothesis,
    )
    observed_scenario = (
        scenario["title"],
        scenario["decision_question"],
        scenario["scenario_sha256"],
        scenario["baseline_position"],
        scenario["baseline_name"],
        scenario["baseline_hypothesis"],
        scenario["alternative_position"],
        scenario["alternative_name"],
        scenario["alternative_hypothesis"],
    )
    if observed_scenario != frozen_scenario:
        raise RuntimeError("survey experiment frozen scenario fields differ from sealed sources")
    cursor.execute(
        """
        SELECT cohort.title, cohort.persona_count, cohort.cohort_sha256,
               dataset.dataset_sha256
        FROM cohorts AS cohort
        JOIN persona_datasets AS dataset ON dataset.id = cohort.dataset_id
        WHERE cohort.id = %s AND cohort.sealed_at IS NOT NULL AND dataset.sealed_at IS NOT NULL
        """,
        (experiment.cohort_id,),
    )
    cohort = cursor.fetchone()
    if cohort is None:
        raise RuntimeError("survey experiment references a missing sealed cohort")
    if (
        cohort["title"] != experiment.cohort_title
        or cohort["persona_count"] != experiment.persona_count
        or cohort["cohort_sha256"] != experiment.cohort_sha256
        or cohort["dataset_sha256"] != experiment.dataset_sha256
        or len(members) != experiment.persona_count
        or _cohort_sha256(experiment.cohort_title, experiment.dataset_sha256, members)
        != experiment.cohort_sha256
    ):
        raise RuntimeError("survey experiment frozen cohort fields differ from sealed sources")
    if (
        persona.profile.persona_id != persona.persona_id
        or persona.profile.display_name != persona.display_name
        or persona.profile.source != persona.source
        or persona_profile_sha256(persona.profile) != persona.profile_sha256
    ):
        raise RuntimeError("survey persona profile digest or identity mismatch")
    if instrument_sha256(experiment.instrument) != experiment.instrument_sha256:
        raise RuntimeError("survey experiment instrument digest mismatch")
    if experiment_sha256(experiment) != experiment.experiment_sha256:
        raise RuntimeError("survey experiment content digest mismatch")
    if (
        experiment.model_name != runtime_config.model_name
        or experiment.survey_config_sha256 != runtime_config.config_sha256
        or experiment.prompt_schema_version != runtime_config.prompt_schema_version
    ):
        raise RuntimeError("survey experiment does not match worker runtime configuration")


def _claim_failure(
    cursor: Cursor[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    cursor.execute(
        """
        UPDATE matraix_survey_trials
        SET status = 'running', started_at = now(), claimed_by_worker_id = %s
        WHERE id = %s AND status = 'queued'
        """,
        (worker_id, trial_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"invalid queued survey trial {trial_id} could not be claimed")
    cursor.execute(
        """
        UPDATE matraix_survey_trials
        SET status = 'failed', completed_at = now(), error_code = %s, error_message = %s
        WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
        """,
        (failure.code, failure.message, trial_id, worker_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"invalid survey trial {trial_id} could not be failed")


def _answer_row(
    trial_id: UUID,
    answer: PositionedSurveyAnswer,
) -> tuple[UUID, int, str, str, str | None, int | None, str | None]:
    if isinstance(answer, PositionedPreferredVariantAnswer):
        return trial_id, 0, answer.question_id, answer.type, answer.value, None, None
    if isinstance(answer, PositionedAlternativeSupportAnswer):
        return trial_id, 1, answer.question_id, answer.type, None, answer.value, None
    if isinstance(answer, PositionedPrimaryReasonAnswer):
        return trial_id, 2, answer.question_id, answer.type, None, None, answer.value
    raise TypeError(f"unsupported typed survey answer {type(answer).__name__}")


def _claimed_survey_trial_from_row(
    row: dict[str, object],
    experiment: SurveyExperiment,
    persona: SemanticPersona,
    members: tuple[SurveyCohortMember, ...],
) -> ClaimedSurveyTrial:
    return ClaimedSurveyTrial.model_validate(
        {
            "id": row["id"],
            "status": "running",
            "created_at": row["created_at"],
            "persona_position": row["persona_position"],
            "persona_id": row["persona_id"],
            "persona_external_id": row["persona_external_id"],
            "persona_display_name": row["persona_display_name"],
            "persona_profile_sha256": row["persona_profile_sha256"],
            "trial_sha256": row["trial_sha256"],
            "experiment": experiment,
            "persona": persona,
            "cohort_members": members,
        }
    )


def claim_survey_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    runtime_config: SurveyRuntimeConfig,
) -> ClaimedSurveyTrial | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.experiment_id, trial.persona_position, trial.persona_id,
                   trial.persona_external_id, trial.persona_display_name,
                   trial.persona_profile_sha256, trial.trial_sha256, trial.created_at
            FROM matraix_survey_trials AS trial
            JOIN matraix_survey_experiments AS experiment
              ON experiment.id = trial.experiment_id
            WHERE trial.id = %s AND trial.status = 'queued'
              AND experiment.input_sealed_at IS NOT NULL
              AND experiment.model_name = %s
              AND experiment.survey_config_sha256 = %s
              AND experiment.prompt_schema_version = %s
            FOR UPDATE OF trial SKIP LOCKED
            """,
            (
                trial_id,
                runtime_config.model_name,
                runtime_config.config_sha256,
                runtime_config.prompt_schema_version,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            connection.commit()
            return None
        try:
            experiment = _load_experiment(
                cursor,
                _uuid(row["experiment_id"], "matraix_survey_trials.experiment_id"),
            )
            persona = _load_persona(cursor, experiment.cohort_id, int(row["persona_position"]))
            members = _load_cohort_members(cursor, experiment.cohort_id)
            trial = _claimed_survey_trial_from_row(row, experiment, persona, members)
            _validate_source_bindings(cursor, experiment, persona, members, runtime_config)
            if (
                trial_sha256(
                    experiment.experiment_sha256,
                    trial.persona_position,
                    trial.persona_id,
                    trial.persona_external_id,
                    trial.persona_display_name,
                    trial.persona_profile_sha256,
                )
                != trial.trial_sha256
            ):
                raise RuntimeError("survey trial content digest mismatch")
        except (ValidationError, RuntimeError, ValueError, KeyError, TypeError) as error:
            _claim_failure(cursor, trial_id, worker_id, _queue_failure(error))
            connection.commit()
            return None
        cursor.execute(
            """
            UPDATE matraix_survey_trials
            SET status = 'running', started_at = now(), claimed_by_worker_id = %s
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, trial_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(f"queued survey trial {trial_id} could not be claimed")
    connection.commit()
    return trial


def complete_survey_trial(
    connection: Connection[dict[str, object]],
    trial: ClaimedSurveyTrial,
    worker_id: str,
    result: SurveySuccess,
) -> None:
    if (
        result.runner_version != "1.0.0"
        or result.model_name != trial.experiment.model_name
        or result.survey_config_sha256 != trial.experiment.survey_config_sha256
        or result.prompt_schema_version != trial.experiment.prompt_schema_version
        or result.answers_sha256 != answers_sha256(trial.trial_sha256, result.answers)
    ):
        raise RuntimeError("survey result identity or content digest mismatch")
    rows = [_answer_row(trial.id, answer) for answer in result.answers]
    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO matraix_survey_answers (
                    trial_id, question_position, question_id, answer_type,
                    choice_value, likert_value, free_text_value, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                """,
                rows,
            )
            cursor.execute(
                """
                UPDATE matraix_survey_trials
                SET status = 'succeeded', completed_at = now(), runner_version = %s,
                    model_name = %s, survey_config_sha256 = %s,
                    prompt_schema_version = %s, answers_sha256 = %s
                WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
                """,
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
                raise RuntimeError(f"survey trial {trial.id} is no longer running")
        connection.commit()
    except (PsycopgError, RuntimeError):
        connection.rollback()
        raise


def fail_survey_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_survey_trials
            SET status = 'failed', completed_at = now(), error_code = %s, error_message = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (failure.code, failure.message, trial_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"survey trial {trial_id} is no longer running")
    connection.commit()


def fail_survey_trials_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_survey_trials
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_process_restarted',
                error_message = 'The model worker restarted before completing this survey trial.'
            WHERE status = 'running' AND claimed_by_worker_id = %s
            """,
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_survey_trials(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("survey orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE matraix_survey_trials AS trial
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_heartbeat_lost',
                error_message = 'The model worker stopped before completing this survey trial.'
            WHERE trial.status = 'running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats AS heartbeat
                WHERE heartbeat.worker_id = trial.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


__all__ = [
    "claim_survey_trial",
    "complete_survey_trial",
    "fail_orphaned_survey_trials",
    "fail_survey_trial",
    "fail_survey_trials_owned_by_worker",
    "survey_queue_head",
]
