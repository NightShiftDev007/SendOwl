"""PostgreSQL claim and transition operations for semantic OASIS trials."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from psycopg import Connection, Cursor
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import (
    ClaimedSemanticTrial,
    CohortIntegrityInput,
    DatasetIntegrityInput,
    PersonaProfile,
    ScenarioIntegrityInput,
    ScenarioVariantIntegrity,
    SemanticEvent,
    SemanticExperiment,
    SemanticIntervention,
    SemanticPersona,
    SemanticRuntimeConfig,
    SemanticSuccess,
    SemanticVariant,
)
from oasis_worker.semantic_hashing import (
    cohort_sha256,
    experiment_sha256,
    persona_profile_sha256,
    scenario_sha256,
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


def _queue_integrity_failure(error: BaseException) -> NormalizedFailure:
    if isinstance(error, ValidationError):
        first = error.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "input"
        detail = f"validation failed at {location} ({first['type']})"
    elif isinstance(error, RuntimeError):
        detail = str(error)
    elif isinstance(error, KeyError):
        detail = f"required storage field {error!s} is missing"
    else:
        detail = f"validation failed with {type(error).__name__}"
    message = " ".join(detail.split())[:500]
    return NormalizedFailure(
        code="queue_integrity",
        message=f"Semantic queue integrity check failed: {message}",
    )


def _semantic_persona_from_row(row: dict[str, object]) -> SemanticPersona:
    """Project one PostgreSQL persona row without leaking storage-only columns."""
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


def _claimed_semantic_trial_from_row(
    row: dict[str, object],
    experiment: SemanticExperiment,
    scenario: ScenarioIntegrityInput,
    dataset: DatasetIntegrityInput,
    cohort: CohortIntegrityInput,
) -> ClaimedSemanticTrial:
    """Project one claimed trial row without its storage-only experiment_id."""
    return ClaimedSemanticTrial.model_validate(
        {
            "id": row["id"],
            "status": "running",
            "created_at": row["created_at"],
            "experiment": experiment,
            "variant_position": row["variant_position"],
            "variant_role": row["variant_role"],
            "scenario_variant_id": row["scenario_variant_id"],
            "scenario_position": row["scenario_position"],
            "variant_name": row["variant_name"],
            "variant_hypothesis": row["variant_hypothesis"],
            "seed": row["seed"],
            "trial_sha256": row["trial_sha256"],
            "scenario": scenario,
            "dataset": dataset,
            "cohort": cohort,
        }
    )


def semantic_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.created_at
            FROM semantic_trials AS trial
            JOIN semantic_experiments AS experiment ON experiment.id = trial.experiment_id
            WHERE trial.status = 'queued' AND experiment.input_sealed_at IS NOT NULL
              AND experiment.model_name = %s
              AND experiment.semantic_config_sha256 = %s
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
        raise RuntimeError("queued semantic trial created_at is not a PostgreSQL timestamp")
    return _uuid(row["id"], "semantic_trials.id"), created_at


def _load_interventions(
    cursor: Cursor[dict[str, object]],
    scenario_id: UUID,
    variant_id: UUID,
) -> tuple[SemanticIntervention, ...]:
    cursor.execute(
        """
        SELECT id, position, kind, actor, channel, content, offset_minutes
        FROM scenario_interventions
        WHERE scenario_id = %s AND variant_id = %s
        ORDER BY position
        """,
        (scenario_id, variant_id),
    )
    return tuple(
        SemanticIntervention.model_validate(
            {
                "id": row["id"],
                "position": row["position"],
                "kind": row["kind"],
                "actor": row["actor"],
                "channel": row["channel"],
                "content": row["content"],
                "offset_minutes": row["offset_minutes"],
            }
        )
        for row in cursor.fetchall()
    )


def _load_full_scenario(
    cursor: Cursor[dict[str, object]], row: dict[str, object]
) -> ScenarioIntegrityInput:
    scenario_id = _uuid(row["scenario_id"], "semantic_experiments.scenario_id")
    cursor.execute(
        """
        SELECT id, title, decision_question, world_model_id, world_snapshot_id,
               snapshot_version, snapshot_sha256, snapshot_evidence_count, scenario_sha256
        FROM scenarios
        WHERE id = %s AND sealed_at IS NOT NULL
        """,
        (scenario_id,),
    )
    scenario_row = cursor.fetchone()
    if scenario_row is None:
        raise RuntimeError(f"semantic experiment references missing sealed scenario {scenario_id}")
    cursor.execute(
        """
        SELECT id, role, position, name, hypothesis
        FROM scenario_variants
        WHERE scenario_id = %s
        ORDER BY position
        """,
        (scenario_id,),
    )
    variant_rows = cursor.fetchall()
    variants = tuple(
        ScenarioVariantIntegrity.model_validate(
            {
                "id": variant_row["id"],
                "role": variant_row["role"],
                "position": variant_row["position"],
                "name": variant_row["name"],
                "hypothesis": variant_row["hypothesis"],
                "interventions": _load_interventions(
                    cursor,
                    scenario_id,
                    _uuid(variant_row["id"], "scenario_variants.id"),
                ),
            }
        )
        for variant_row in variant_rows
    )
    return ScenarioIntegrityInput.model_validate(
        {
            "id": scenario_row["id"],
            "title": scenario_row["title"],
            "decision_question": scenario_row["decision_question"],
            "world_model_id": scenario_row["world_model_id"],
            "world_snapshot_id": scenario_row["world_snapshot_id"],
            "snapshot_version": scenario_row["snapshot_version"],
            "snapshot_sha256": scenario_row["snapshot_sha256"],
            "snapshot_evidence_count": scenario_row["snapshot_evidence_count"],
            "scenario_sha256": scenario_row["scenario_sha256"],
            "variants": variants,
        }
    )


def load_dataset_and_cohort(
    cursor: Cursor[dict[str, object]],
    row: dict[str, object],
) -> tuple[DatasetIntegrityInput, CohortIntegrityInput]:
    cohort_id = _uuid(row["cohort_id"], "semantic_experiments.cohort_id")
    cursor.execute(
        """
        SELECT dataset.id, dataset.slug, dataset.display_name, dataset.schema_version,
               dataset.parent_pool, dataset.source_repository, dataset.persona_count,
               dataset.manifest_sha256, dataset.dataset_sha256
        FROM cohorts AS cohort
        JOIN persona_datasets AS dataset ON dataset.id = cohort.dataset_id
        WHERE cohort.id = %s AND cohort.sealed_at IS NOT NULL AND dataset.sealed_at IS NOT NULL
        """,
        (cohort_id,),
    )
    dataset_row = cursor.fetchone()
    if dataset_row is None:
        raise RuntimeError(f"semantic experiment references missing sealed cohort {cohort_id}")
    dataset = DatasetIntegrityInput.model_validate(
        {
            "id": dataset_row["id"],
            "slug": dataset_row["slug"],
            "display_name": dataset_row["display_name"],
            "schema_version": dataset_row["schema_version"],
            "parent_pool": dataset_row["parent_pool"],
            "source_repository": dataset_row["source_repository"],
            "persona_count": dataset_row["persona_count"],
            "manifest_sha256": dataset_row["manifest_sha256"],
            "dataset_sha256": dataset_row["dataset_sha256"],
        }
    )
    cursor.execute(
        """
        SELECT cohort.id, cohort.dataset_id, cohort.title, cohort.persona_count,
               cohort.cohort_sha256
        FROM cohorts AS cohort
        WHERE cohort.id = %s AND cohort.sealed_at IS NOT NULL
        """,
        (cohort_id,),
    )
    cohort_row = cursor.fetchone()
    if cohort_row is None:
        raise RuntimeError(f"semantic experiment references missing sealed cohort {cohort_id}")
    cursor.execute(
        """
        SELECT member.position, persona.id, persona.persona_id, persona.display_name,
               persona.source, persona.profile_json, persona.profile_sha256
        FROM cohort_members AS member
        JOIN personas AS persona
          ON persona.dataset_id = member.dataset_id AND persona.id = member.persona_id
        WHERE member.cohort_id = %s
        ORDER BY member.position
        """,
        (cohort_id,),
    )
    persona_rows = cursor.fetchall()
    personas = tuple(_semantic_persona_from_row(persona_row) for persona_row in persona_rows)
    cohort = CohortIntegrityInput.model_validate(
        {
            "id": cohort_row["id"],
            "dataset_id": cohort_row["dataset_id"],
            "title": cohort_row["title"],
            "persona_count": cohort_row["persona_count"],
            "cohort_sha256": cohort_row["cohort_sha256"],
            "personas": personas,
        }
    )
    return dataset, cohort


def _load_experiment(
    cursor: Cursor[dict[str, object]],
    row: dict[str, object],
) -> SemanticExperiment:
    experiment_id = _uuid(row["experiment_id"], "semantic_trials.experiment_id")
    cursor.execute(
        """
        SELECT id, scenario_id, scenario_sha256, scenario_title, decision_question,
               cohort_id, cohort_sha256, cohort_title, dataset_sha256, persona_count,
               rounds, minutes_per_round, model_name, semantic_config_sha256,
               prompt_schema_version, experiment_sha256
        FROM semantic_experiments
        WHERE id = %s AND input_sealed_at IS NOT NULL
        """,
        (experiment_id,),
    )
    experiment_row = cursor.fetchone()
    if experiment_row is None:
        raise RuntimeError(f"semantic trial references missing sealed experiment {experiment_id}")
    cursor.execute(
        """
        SELECT position AS experiment_position, role, scenario_variant_id AS id,
               scenario_position, name, hypothesis, intervention_count
        FROM semantic_experiment_variants
        WHERE experiment_id = %s
        ORDER BY position
        """,
        (experiment_id,),
    )
    variant_rows = cursor.fetchall()
    variants = tuple(
        SemanticVariant.model_validate(
            {
                "experiment_position": variant_row["experiment_position"],
                "role": variant_row["role"],
                "id": variant_row["id"],
                "scenario_position": variant_row["scenario_position"],
                "name": variant_row["name"],
                "hypothesis": variant_row["hypothesis"],
                "intervention_count": variant_row["intervention_count"],
                "interventions": _load_interventions(
                    cursor,
                    _uuid(experiment_row["scenario_id"], "semantic_experiments.scenario_id"),
                    _uuid(variant_row["id"], "semantic_experiment_variants.scenario_variant_id"),
                ),
            }
        )
        for variant_row in variant_rows
    )
    cursor.execute(
        """
        SELECT DISTINCT seed
        FROM semantic_trials
        WHERE experiment_id = %s
        ORDER BY seed
        """,
        (experiment_id,),
    )
    seeds = tuple(item["seed"] for item in cursor.fetchall())
    return SemanticExperiment.model_validate(
        {
            "id": experiment_row["id"],
            "scenario_id": experiment_row["scenario_id"],
            "scenario_sha256": experiment_row["scenario_sha256"],
            "scenario_title": experiment_row["scenario_title"],
            "decision_question": experiment_row["decision_question"],
            "cohort_id": experiment_row["cohort_id"],
            "cohort_sha256": experiment_row["cohort_sha256"],
            "cohort_title": experiment_row["cohort_title"],
            "dataset_sha256": experiment_row["dataset_sha256"],
            "persona_count": experiment_row["persona_count"],
            "rounds": experiment_row["rounds"],
            "minutes_per_round": experiment_row["minutes_per_round"],
            "model_name": experiment_row["model_name"],
            "semantic_config_sha256": experiment_row["semantic_config_sha256"],
            "prompt_schema_version": experiment_row["prompt_schema_version"],
            "experiment_sha256": experiment_row["experiment_sha256"],
            "variants": variants,
            "seeds": seeds,
        }
    )


def _validate_claim_integrity(
    trial: ClaimedSemanticTrial, runtime_config: SemanticRuntimeConfig
) -> None:
    experiment = trial.experiment
    if scenario_sha256(trial.scenario) != trial.scenario.scenario_sha256:
        raise RuntimeError(f"semantic trial {trial.id} scenario content hash mismatch")
    if trial.scenario.id != experiment.scenario_id:
        raise RuntimeError(f"semantic trial {trial.id} scenario identity mismatch")
    if trial.scenario.scenario_sha256 != experiment.scenario_sha256:
        raise RuntimeError(f"semantic trial {trial.id} frozen scenario digest mismatch")
    if (
        trial.scenario.title != experiment.scenario_title
        or trial.scenario.decision_question != experiment.decision_question
    ):
        raise RuntimeError(f"semantic trial {trial.id} frozen scenario text mismatch")
    scenario_variants = {item.id: item for item in trial.scenario.variants}
    for experiment_variant in experiment.variants:
        scenario_variant = scenario_variants.get(experiment_variant.id)
        if scenario_variant is None or (
            scenario_variant.role != experiment_variant.role
            or scenario_variant.position != experiment_variant.scenario_position
            or scenario_variant.name != experiment_variant.name
            or scenario_variant.hypothesis != experiment_variant.hypothesis
            or scenario_variant.interventions != experiment_variant.interventions
        ):
            raise RuntimeError(f"semantic trial {trial.id} experiment variant mismatch")
    if trial.dataset.dataset_sha256 != experiment.dataset_sha256:
        raise RuntimeError(f"semantic trial {trial.id} frozen dataset digest mismatch")
    if trial.cohort.dataset_id != trial.dataset.id:
        raise RuntimeError(f"semantic trial {trial.id} cohort dataset identity mismatch")
    for persona in trial.cohort.personas:
        if persona.profile.persona_id != persona.persona_id:
            raise RuntimeError(f"semantic trial {trial.id} persona identity mismatch")
        if persona.profile.display_name != persona.display_name:
            raise RuntimeError(f"semantic trial {trial.id} persona display name mismatch")
        if persona.profile.source != persona.source:
            raise RuntimeError(f"semantic trial {trial.id} persona source mismatch")
        if persona_profile_sha256(persona.profile) != persona.profile_sha256:
            raise RuntimeError(f"semantic trial {trial.id} persona profile digest mismatch")
    if cohort_sha256(trial.cohort, trial.dataset.dataset_sha256) != trial.cohort.cohort_sha256:
        raise RuntimeError(f"semantic trial {trial.id} cohort content hash mismatch")
    if trial.cohort.id != experiment.cohort_id:
        raise RuntimeError(f"semantic trial {trial.id} cohort identity mismatch")
    if trial.cohort.cohort_sha256 != experiment.cohort_sha256:
        raise RuntimeError(f"semantic trial {trial.id} frozen cohort digest mismatch")
    if trial.cohort.title != experiment.cohort_title:
        raise RuntimeError(f"semantic trial {trial.id} frozen cohort title mismatch")
    if trial.cohort.persona_count != experiment.persona_count:
        raise RuntimeError(f"semantic trial {trial.id} frozen persona count mismatch")
    if experiment_sha256(experiment) != experiment.experiment_sha256:
        raise RuntimeError(f"semantic trial {trial.id} experiment content hash mismatch")
    if trial_sha256(experiment, trial.variant_position, trial.seed) != trial.trial_sha256:
        raise RuntimeError(f"semantic trial {trial.id} content hash mismatch")
    if (
        experiment.model_name != runtime_config.model_name
        or experiment.semantic_config_sha256 != runtime_config.config_sha256
        or experiment.prompt_schema_version != runtime_config.prompt_schema_version
    ):
        raise RuntimeError(f"semantic trial {trial.id} does not match worker model configuration")


def claim_semantic_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedSemanticTrial | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT trial.id, trial.experiment_id, trial.variant_position, trial.variant_role,
                   trial.scenario_variant_id, trial.scenario_position, trial.variant_name,
                   trial.variant_hypothesis, trial.seed, trial.trial_sha256,
                   trial.created_at
            FROM semantic_trials AS trial
            JOIN semantic_experiments AS experiment ON experiment.id = trial.experiment_id
            WHERE trial.id = %s AND trial.status = 'queued'
              AND experiment.input_sealed_at IS NOT NULL
              AND experiment.model_name = %s
              AND experiment.semantic_config_sha256 = %s
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
        selected = cursor.fetchone()
        if selected is None:
            connection.commit()
            return None
        try:
            experiment = _load_experiment(cursor, selected)
            scenario = _load_full_scenario(cursor, experiment.model_dump(mode="python"))
            dataset, cohort = load_dataset_and_cohort(cursor, experiment.model_dump(mode="python"))
            trial = _claimed_semantic_trial_from_row(
                selected,
                experiment,
                scenario,
                dataset,
                cohort,
            )
            _validate_claim_integrity(trial, runtime_config)
        except (ValidationError, RuntimeError, ValueError, KeyError) as error:
            failure = _queue_integrity_failure(error)
            cursor.execute(
                """
                UPDATE semantic_trials
                SET status = 'running', current_round = 0, started_at = now(),
                    claimed_by_worker_id = %s
                WHERE id = %s AND status = 'queued'
                """,
                (worker_id, trial_id),
            )
            cursor.execute(
                """
                UPDATE semantic_trials
                SET status = 'failed', completed_at = now(),
                    error_code = %s,
                    error_message = %s
                WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
                """,
                (
                    failure.code,
                    failure.message,
                    trial_id,
                    worker_id,
                ),
            )
            connection.commit()
            return None
        cursor.execute(
            """
            UPDATE semantic_trials
            SET status = 'running', current_round = 0, started_at = now(),
                claimed_by_worker_id = %s
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, trial_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(f"queued semantic trial {trial_id} could not be claimed")
    connection.commit()
    return trial


def append_round_events(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    round_number: int,
    events: Sequence[SemanticEvent],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT current_round
            FROM semantic_trials
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            FOR UPDATE
            """,
            (trial_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or row["current_round"] != round_number - 1:
            connection.rollback()
            raise RuntimeError(
                f"semantic trial {trial_id} is not ready to append round {round_number}"
            )
        cursor.execute(
            "SELECT coalesce(max(sequence), -1) AS last_sequence "
            "FROM semantic_trial_events WHERE trial_id = %s",
            (trial_id,),
        )
        last_row = cursor.fetchone()
        if last_row is None:
            raise RuntimeError(f"cannot read semantic trial {trial_id} event sequence")
        first_sequence = int(last_row["last_sequence"]) + 1
        if first_sequence == 0:
            first_sequence = 1
        cursor.executemany(
            """
            INSERT INTO semantic_trial_events (
                trial_id, sequence, round, phase, actor_kind, persona_id,
                agent_position, action_type, content, post_id, comment_id,
                target_post_id, observed_at_raw, recorded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
            )
            """,
            [
                (
                    trial_id,
                    first_sequence + offset,
                    event.round,
                    event.phase,
                    event.actor_kind,
                    event.persona_id,
                    event.agent_position,
                    event.action_type,
                    event.content,
                    event.post_id,
                    event.comment_id,
                    event.target_post_id,
                    event.observed_at_raw,
                )
                for offset, event in enumerate(events)
            ],
        )
        cursor.execute(
            """
            UPDATE semantic_trials
            SET current_round = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
              AND current_round = %s
            """,
            (round_number, trial_id, worker_id, round_number - 1),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"semantic trial {trial_id} round update was rejected")
    connection.commit()


def complete_semantic_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    result: SemanticSuccess,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_trials
            SET status = 'succeeded', completed_at = now(),
                engine_version = %s, camel_version = %s, model_name = %s,
                semantic_config_sha256 = %s, prompt_schema_version = %s,
                artifact_sha256 = %s, artifact_size_bytes = %s, user_count = %s,
                initial_post_count = %s, generated_post_count = %s, comment_count = %s,
                reaction_count = %s, do_nothing_count = %s, observed_action_count = %s,
                rounds_completed = %s, limitations = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (
                result.engine_version,
                result.camel_version,
                result.model_name,
                result.semantic_config_sha256,
                result.prompt_schema_version,
                result.artifact_sha256,
                result.artifact_size_bytes,
                result.user_count,
                result.initial_post_count,
                result.generated_post_count,
                result.comment_count,
                result.reaction_count,
                result.do_nothing_count,
                result.observed_action_count,
                result.rounds_completed,
                list(result.limitations),
                trial_id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"semantic trial {trial_id} is no longer running")
    connection.commit()


def fail_semantic_trial(
    connection: Connection[dict[str, object]],
    trial_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_trials
            SET status = 'failed', completed_at = now(), error_code = %s, error_message = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (failure.code, failure.message, trial_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"semantic trial {trial_id} is no longer running")
    connection.commit()


def fail_orphaned_semantic_trials(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_trials AS trial
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_heartbeat_lost',
                error_message = 'The OASIS worker stopped before completing this semantic trial.'
            WHERE trial.status = 'running'
              AND NOT EXISTS (
                  SELECT 1 FROM simulation_worker_heartbeats AS heartbeat
                  WHERE heartbeat.worker_id = trial.claimed_by_worker_id
                    AND heartbeat.last_seen_at >= %s
              )
            """,
            (cutoff,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated


def fail_semantic_trials_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_trials
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_process_restarted',
                error_message = 'The owning OASIS worker restarted before completing this trial.'
            WHERE status = 'running' AND claimed_by_worker_id = %s
            """,
            (worker_id,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated
