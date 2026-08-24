"""Transactional assembly and verified reads for semantic experiments."""

from datetime import UTC, datetime, timedelta
from math import fsum
from statistics import pstdev
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.errors import PopulationCohortNotFoundError
from app.populations.repository import get_cohort
from app.scenarios.contracts import ScenarioDetail, ScenarioVariant
from app.scenarios.errors import ScenarioNotFoundError
from app.scenarios.repository import get_scenario
from app.semantic_experiments.contracts import (
    FrozenSemanticVariant,
    SemanticCohortRef,
    SemanticExperimentComparison,
    SemanticExperimentCreateRequest,
    SemanticExperimentDetail,
    SemanticExperimentsResponse,
    SemanticExperimentSummary,
    SemanticMetricComparison,
    SemanticPairedDelta,
    SemanticReadiness,
    SemanticScenarioRef,
    SemanticStatus,
    SemanticTrial,
    SemanticTrialError,
    SemanticTrialEvent,
    SemanticTrialEventsResponse,
    SemanticTrialResult,
    SemanticVariantObservation,
)
from app.semantic_experiments.errors import (
    SemanticExperimentNotFoundError,
    SemanticExperimentSelectionError,
    SemanticExperimentUnavailableError,
    SemanticTrialNotFoundError,
)
from app.semantic_experiments.hashing import (
    PROMPT_SCHEMA_VERSION,
    calculate_semantic_experiment_sha256,
    calculate_semantic_trial_sha256,
)
from app.semantic_experiments.models import (
    SemanticExperimentRecord,
    SemanticExperimentVariantRecord,
    SemanticTrialEventRecord,
    SemanticTrialRecord,
)
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

COMPARISON_LIMITATIONS = (
    "Comparison contains only normalized actions observed by OASIS; it does not infer "
    "stance, reach, persuasion, business impact, or a decision verdict.",
    "Alternative deltas are paired only where both the baseline and alternative succeeded "
    "for the same recorded seed.",
)
READINESS_BASE_LIMITATIONS = (
    "Readiness requires a recent pinned OASIS 0.2.5 / CAMEL 0.2.78 heartbeat emitted after "
    "a successful provider tool-call startup probe, plus one unambiguous model configuration.",
    "The semantic engine produces bounded synthetic observations, not forecasts or decisions.",
)


def _advisory_lock_key(digest: str) -> int:
    unsigned_key = int(digest[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _lock_experiment_content(session: AsyncSession, digest: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_lock_key(digest)},
    )


def _frozen_variant(
    experiment_position: int,
    role: str,
    variant: ScenarioVariant,
) -> FrozenSemanticVariant:
    if role not in ("baseline", "alternative"):
        raise RuntimeError(f"unsupported semantic variant role {role!r}")
    return FrozenSemanticVariant(
        position=experiment_position,
        role=role,
        id=variant.id,
        scenario_position=variant.position,
        name=variant.name,
        hypothesis=variant.hypothesis,
        intervention_count=len(variant.interventions),
    )


def _select_variants(
    scenario: ScenarioDetail,
    alternative_ids: tuple[UUID, ...],
) -> tuple[FrozenSemanticVariant, ...]:
    alternatives_by_id = {alternative.id: alternative for alternative in scenario.alternatives}
    missing = tuple(item for item in alternative_ids if item not in alternatives_by_id)
    if missing:
        missing_text = ", ".join(str(item) for item in missing)
        raise SemanticExperimentSelectionError(
            f"alternative_ids contain variants that do not belong to sealed scenario "
            f"{scenario.id}: {missing_text}"
        )
    selected = tuple(
        sorted(
            (alternatives_by_id[item] for item in alternative_ids), key=lambda item: item.position
        )
    )
    return (_frozen_variant(0, "baseline", scenario.baseline),) + tuple(
        _frozen_variant(position, "alternative", variant)
        for position, variant in enumerate(selected, start=1)
    )


def _validate_execution_bounds(
    scenario: ScenarioDetail,
    variants: tuple[FrozenSemanticVariant, ...],
    persona_count: int,
    seeds: tuple[int, ...],
    rounds: int,
    minutes_per_round: int,
) -> None:
    if persona_count > 8:
        raise SemanticExperimentSelectionError(
            f"cohort contains {persona_count} personas; semantic experiments support at most 8"
        )
    budget = len(variants) * len(seeds) * rounds * persona_count
    if budget > 96:
        raise SemanticExperimentSelectionError(
            "semantic experiment budget exceeds 96 persona-rounds: "
            f"{len(variants)} variants × {len(seeds)} seeds × {rounds} rounds × "
            f"{persona_count} personas = {budget}; reduce alternatives, seeds, rounds, or cohort"
        )
    horizon = rounds * minutes_per_round
    selected_ids = {variant.id for variant in variants}
    for alternative in scenario.alternatives:
        if alternative.id not in selected_ids:
            continue
        for intervention in alternative.interventions:
            if intervention.offset_minutes > horizon:
                raise SemanticExperimentSelectionError(
                    f"alternative {alternative.id} intervention at offset_minutes "
                    f"{intervention.offset_minutes} exceeds the {horizon}-minute experiment horizon"
                )


async def get_live_semantic_config(session: AsyncSession) -> tuple[str, str]:
    await session.execute(text("LOCK TABLE simulation_worker_heartbeats IN SHARE MODE"))
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeats = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord)
                .where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
                    SimulationWorkerHeartbeatRecord.worker_domain == "semantic",
                    SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.semantic_model_name,
            heartbeat.semantic_config_sha256,
            heartbeat.semantic_prompt_schema_version,
        )
        for heartbeat in heartbeats
    }
    if not configs:
        raise SemanticExperimentUnavailableError(
            "OASIS semantic execution is unavailable because no correctly pinned worker "
            "reported a complete semantic configuration in the last 30 seconds"
        )
    if len(configs) != 1:
        readable = ", ".join(
            sorted(
                f"model={name!r}, config_sha256={digest!r}, prompt={prompt!r}"
                for name, digest, prompt in configs
            )
        )
        raise SemanticExperimentUnavailableError(
            "live semantic workers disagree on execution configuration; resolve the conflict "
            f"before enqueueing experiments: {readable}"
        )
    model_name, config_sha256, prompt_schema = next(iter(configs))
    if model_name is None or config_sha256 is None or prompt_schema != PROMPT_SCHEMA_VERSION:
        raise RuntimeError("semantic-ready worker persisted an incomplete configuration")
    return model_name, config_sha256


def _new_records(
    scenario: ScenarioDetail,
    cohort_id: UUID,
    cohort_title: str,
    cohort_sha256: str,
    dataset_sha256: str,
    persona_count: int,
    variants: tuple[FrozenSemanticVariant, ...],
    seeds: tuple[int, ...],
    rounds: int,
    minutes_per_round: int,
    model_name: str,
    config_sha256: str,
    experiment_sha256: str,
    created_at: datetime,
) -> tuple[
    SemanticExperimentRecord,
    tuple[SemanticExperimentVariantRecord, ...],
    tuple[SemanticTrialRecord, ...],
]:
    experiment = SemanticExperimentRecord(
        id=uuid4(),
        scenario_id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        scenario_title=scenario.title,
        decision_question=scenario.decision_question,
        cohort_id=cohort_id,
        cohort_sha256=cohort_sha256,
        cohort_title=cohort_title,
        dataset_sha256=dataset_sha256,
        persona_count=persona_count,
        rounds=rounds,
        minutes_per_round=minutes_per_round,
        model_name=model_name,
        semantic_config_sha256=config_sha256,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        experiment_sha256=experiment_sha256,
        created_at=created_at,
        input_sealed_at=None,
    )
    variant_records = tuple(
        SemanticExperimentVariantRecord(
            experiment_id=experiment.id,
            position=variant.position,
            role=variant.role,
            scenario_variant_id=variant.id,
            scenario_position=variant.scenario_position,
            name=variant.name,
            hypothesis=variant.hypothesis,
            intervention_count=variant.intervention_count,
        )
        for variant in variants
    )
    trials = tuple(
        SemanticTrialRecord(
            id=uuid4(),
            experiment_id=experiment.id,
            variant_position=variant.position,
            variant_role=variant.role,
            scenario_variant_id=variant.id,
            scenario_position=variant.scenario_position,
            variant_name=variant.name,
            variant_hypothesis=variant.hypothesis,
            seed=seed,
            trial_sha256=calculate_semantic_trial_sha256(experiment_sha256, variant, seed),
            status="queued",
            current_round=0,
            created_at=created_at,
            claimed_by_worker_id=None,
            started_at=None,
            completed_at=None,
            engine_version=None,
            camel_version=None,
            model_name=None,
            semantic_config_sha256=None,
            prompt_schema_version=None,
            artifact_sha256=None,
            artifact_size_bytes=None,
            user_count=None,
            initial_post_count=None,
            generated_post_count=None,
            comment_count=None,
            reaction_count=None,
            do_nothing_count=None,
            observed_action_count=None,
            rounds_completed=None,
            limitations=None,
            error_code=None,
            error_message=None,
        )
        for variant in variants
        for seed in seeds
    )
    return experiment, variant_records, trials


def _variant_from_record(record: SemanticExperimentVariantRecord) -> FrozenSemanticVariant:
    return FrozenSemanticVariant(
        position=record.position,
        role=record.role,
        id=record.scenario_variant_id,
        scenario_position=record.scenario_position,
        name=record.name,
        hypothesis=record.hypothesis,
        intervention_count=record.intervention_count,
    )


def _event_from_record(record: SemanticTrialEventRecord) -> SemanticTrialEvent:
    return SemanticTrialEvent(
        sequence=record.sequence,
        round=record.round,
        phase=record.phase,
        actor_kind=record.actor_kind,
        persona_id=record.persona_id,
        agent_position=record.agent_position,
        action_type=record.action_type,
        content=record.content,
        post_id=record.post_id,
        comment_id=record.comment_id,
        target_post_id=record.target_post_id,
        observed_at_raw=record.observed_at_raw,
        recorded_at=record.recorded_at,
    )


def _verified_event_counts(
    events: tuple[SemanticTrialEventRecord, ...],
) -> tuple[int, int, int, int, int, int]:
    initial = sum(
        event.phase == "intervention" and event.action_type == "create_post" for event in events
    )
    generated = sum(
        event.phase == "audience" and event.action_type == "create_post" for event in events
    )
    comments = sum(event.action_type == "create_comment" for event in events)
    reactions = sum(event.action_type in ("like_post", "dislike_post") for event in events)
    idle = sum(event.action_type == "do_nothing" for event in events)
    return initial, generated, comments, reactions, idle, len(events)


def _trial_from_record(
    trial: SemanticTrialRecord,
    experiment: SemanticExperimentRecord,
    variant: FrozenSemanticVariant,
    events: tuple[SemanticTrialEventRecord, ...],
) -> SemanticTrial:
    expected_hash = calculate_semantic_trial_sha256(
        experiment.experiment_sha256, variant, trial.seed
    )
    if expected_hash != trial.trial_sha256:
        raise RuntimeError(f"semantic trial {trial.id} content does not match trial_sha256")
    result = None
    error = None
    if trial.status == "succeeded":
        values = (
            trial.engine_version,
            trial.camel_version,
            trial.model_name,
            trial.semantic_config_sha256,
            trial.prompt_schema_version,
            trial.artifact_sha256,
            trial.artifact_size_bytes,
            trial.user_count,
            trial.initial_post_count,
            trial.generated_post_count,
            trial.comment_count,
            trial.reaction_count,
            trial.do_nothing_count,
            trial.observed_action_count,
            trial.rounds_completed,
            trial.limitations,
        )
        if any(value is None for value in values):
            raise RuntimeError(f"succeeded semantic trial {trial.id} has incomplete result fields")
        event_counts = _verified_event_counts(events)
        if event_counts != (
            trial.initial_post_count,
            trial.generated_post_count,
            trial.comment_count,
            trial.reaction_count,
            trial.do_nothing_count,
            trial.observed_action_count,
        ):
            raise RuntimeError(f"semantic trial {trial.id} result counts do not match events")
        if trial.initial_post_count != variant.intervention_count:
            raise RuntimeError(f"semantic trial {trial.id} initial posts do not match its variant")
        if trial.user_count != experiment.persona_count + 1:
            raise RuntimeError(f"semantic trial {trial.id} user_count does not match its cohort")
        if trial.current_round != experiment.rounds or trial.rounds_completed != experiment.rounds:
            raise RuntimeError(f"semantic trial {trial.id} did not complete every configured round")
        if (
            trial.model_name != experiment.model_name
            or trial.semantic_config_sha256 != experiment.semantic_config_sha256
            or trial.prompt_schema_version != experiment.prompt_schema_version
        ):
            raise RuntimeError(f"semantic trial {trial.id} result config does not match experiment")
        result = SemanticTrialResult(
            engine_version=trial.engine_version,
            camel_version=trial.camel_version,
            model_name=trial.model_name,
            semantic_config_sha256=trial.semantic_config_sha256,
            prompt_schema_version=trial.prompt_schema_version,
            artifact_sha256=trial.artifact_sha256,
            artifact_size_bytes=trial.artifact_size_bytes,
            user_count=trial.user_count,
            initial_post_count=trial.initial_post_count,
            generated_post_count=trial.generated_post_count,
            comment_count=trial.comment_count,
            reaction_count=trial.reaction_count,
            do_nothing_count=trial.do_nothing_count,
            observed_action_count=trial.observed_action_count,
            authored_content_count=trial.generated_post_count + trial.comment_count,
            rounds_completed=trial.rounds_completed,
            limitations=tuple(trial.limitations),
        )
    elif trial.status == "failed":
        if trial.error_code is None or trial.error_message is None:
            raise RuntimeError(f"failed semantic trial {trial.id} has no explicit failure")
        error = SemanticTrialError(code=trial.error_code, message=trial.error_message)
    return SemanticTrial(
        id=trial.id,
        status=trial.status,
        seed=trial.seed,
        trial_sha256=trial.trial_sha256,
        current_round=trial.current_round,
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        result=result,
        error=error,
    )


def _status_from_values(status_values: tuple[str, ...]) -> SemanticStatus:
    statuses = set(status_values)
    if not statuses or not statuses <= {"queued", "running", "succeeded", "failed"}:
        raise RuntimeError(f"semantic experiment contains invalid trial statuses: {statuses}")
    if statuses == {"queued"}:
        return "queued"
    if statuses & {"queued", "running"}:
        return "running"
    if statuses == {"succeeded"}:
        return "succeeded"
    return "failed"


def _experiment_status(trials: tuple[SemanticTrial, ...]) -> SemanticStatus:
    return _status_from_values(tuple(trial.status for trial in trials))


def _summary_from_state(
    experiment: SemanticExperimentRecord,
    variants: tuple[FrozenSemanticVariant, ...],
    seeds: tuple[int, ...],
    trial_count: int,
    status: SemanticStatus,
) -> SemanticExperimentSummary:
    return SemanticExperimentSummary(
        id=experiment.id,
        status=status,
        created_at=experiment.created_at,
        scenario=SemanticScenarioRef(
            id=experiment.scenario_id,
            title=experiment.scenario_title,
            decision_question=experiment.decision_question,
            scenario_sha256=experiment.scenario_sha256,
        ),
        cohort=SemanticCohortRef(
            id=experiment.cohort_id,
            title=experiment.cohort_title,
            cohort_sha256=experiment.cohort_sha256,
            dataset_sha256=experiment.dataset_sha256,
            persona_count=experiment.persona_count,
        ),
        variant_count=len(variants),
        trial_count=trial_count,
        rounds=experiment.rounds,
        minutes_per_round=experiment.minutes_per_round,
        seeds=seeds,
        model_name=experiment.model_name,
        semantic_config_sha256=experiment.semantic_config_sha256,
        prompt_schema_version=experiment.prompt_schema_version,
        experiment_sha256=experiment.experiment_sha256,
    )


def _summary(
    experiment: SemanticExperimentRecord,
    variants: tuple[FrozenSemanticVariant, ...],
    trials: tuple[SemanticTrial, ...],
) -> SemanticExperimentSummary:
    return _summary_from_state(
        experiment,
        variants,
        tuple(sorted({trial.seed for trial in trials})),
        len(trials),
        _experiment_status(trials),
    )


async def _load_details(
    session: AsyncSession,
    experiments: tuple[SemanticExperimentRecord, ...],
) -> tuple[SemanticExperimentDetail, ...]:
    if not experiments:
        return ()
    experiment_ids = tuple(experiment.id for experiment in experiments)
    variant_records = tuple(
        (
            await session.execute(
                select(SemanticExperimentVariantRecord)
                .where(SemanticExperimentVariantRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    SemanticExperimentVariantRecord.experiment_id,
                    SemanticExperimentVariantRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    trial_records = tuple(
        (
            await session.execute(
                select(SemanticTrialRecord)
                .where(SemanticTrialRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    SemanticTrialRecord.experiment_id,
                    SemanticTrialRecord.variant_position,
                    SemanticTrialRecord.seed,
                )
            )
        )
        .scalars()
        .all()
    )
    trial_ids = tuple(trial.id for trial in trial_records)
    event_records = (
        tuple(
            (
                await session.execute(
                    select(SemanticTrialEventRecord)
                    .where(SemanticTrialEventRecord.trial_id.in_(trial_ids))
                    .order_by(
                        SemanticTrialEventRecord.trial_id,
                        SemanticTrialEventRecord.sequence,
                    )
                )
            )
            .scalars()
            .all()
        )
        if trial_ids
        else ()
    )
    variants_by_experiment: dict[UUID, list[SemanticExperimentVariantRecord]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    trials_by_experiment: dict[UUID, list[SemanticTrialRecord]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    events_by_trial: dict[UUID, list[SemanticTrialEventRecord]] = {
        trial_id: [] for trial_id in trial_ids
    }
    for variant in variant_records:
        variants_by_experiment[variant.experiment_id].append(variant)
    for trial in trial_records:
        trials_by_experiment[trial.experiment_id].append(trial)
    for event in event_records:
        events_by_trial[event.trial_id].append(event)

    details: list[SemanticExperimentDetail] = []
    for experiment in experiments:
        if experiment.input_sealed_at is None:
            raise RuntimeError(f"semantic experiment {experiment.id} is not sealed")
        frozen_variants = tuple(
            _variant_from_record(record) for record in variants_by_experiment[experiment.id]
        )
        records = tuple(trials_by_experiment[experiment.id])
        variant_by_position = {variant.position: variant for variant in frozen_variants}
        trials = tuple(
            _trial_from_record(
                trial,
                experiment,
                variant_by_position[trial.variant_position],
                tuple(events_by_trial[trial.id]),
            )
            for trial in records
        )
        seeds = tuple(sorted({trial.seed for trial in trials}))
        actual_hash = calculate_semantic_experiment_sha256(
            str(experiment.scenario_id),
            experiment.scenario_sha256,
            str(experiment.cohort_id),
            experiment.cohort_sha256,
            frozen_variants,
            seeds,
            experiment.rounds,
            experiment.minutes_per_round,
            experiment.model_name,
            experiment.semantic_config_sha256,
        )
        if actual_hash != experiment.experiment_sha256:
            raise RuntimeError(
                f"semantic experiment {experiment.id} content does not match experiment_sha256"
            )
        summary = _summary(experiment, frozen_variants, trials)
        public_variants = tuple(
            {
                **variant.model_dump(),
                "trials": tuple(
                    trial
                    for record, trial in zip(records, trials, strict=True)
                    if record.variant_position == variant.position
                ),
            }
            for variant in frozen_variants
        )
        details.append(
            SemanticExperimentDetail(
                **summary.model_dump(),
                variants=public_variants,
            )
        )
    return tuple(details)


async def _load_summaries(
    session: AsyncSession,
    experiments: tuple[SemanticExperimentRecord, ...],
) -> tuple[SemanticExperimentSummary, ...]:
    """Verify summary inputs without loading the unbounded event history."""
    if not experiments:
        return ()
    experiment_ids = tuple(experiment.id for experiment in experiments)
    variant_records = tuple(
        (
            await session.execute(
                select(SemanticExperimentVariantRecord)
                .where(SemanticExperimentVariantRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    SemanticExperimentVariantRecord.experiment_id,
                    SemanticExperimentVariantRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    trial_dimensions = tuple(
        (
            await session.execute(
                select(
                    SemanticTrialRecord.experiment_id,
                    SemanticTrialRecord.variant_position,
                    SemanticTrialRecord.seed,
                    SemanticTrialRecord.status,
                    SemanticTrialRecord.trial_sha256,
                )
                .where(SemanticTrialRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    SemanticTrialRecord.experiment_id,
                    SemanticTrialRecord.variant_position,
                    SemanticTrialRecord.seed,
                )
            )
        )
        .tuples()
        .all()
    )
    variants_by_experiment: dict[UUID, list[SemanticExperimentVariantRecord]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    trials_by_experiment: dict[UUID, list[tuple[int, int, str, str]]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    for variant in variant_records:
        variants_by_experiment[variant.experiment_id].append(variant)
    for experiment_id, variant_position, seed, status, trial_sha256 in trial_dimensions:
        trials_by_experiment[experiment_id].append((variant_position, seed, status, trial_sha256))

    summaries: list[SemanticExperimentSummary] = []
    for experiment in experiments:
        if experiment.input_sealed_at is None:
            raise RuntimeError(f"semantic experiment {experiment.id} is not sealed")
        variants = tuple(
            _variant_from_record(record) for record in variants_by_experiment[experiment.id]
        )
        if tuple(variant.position for variant in variants) != tuple(range(len(variants))):
            raise RuntimeError(
                f"semantic experiment {experiment.id} has non-contiguous variant positions"
            )
        trial_rows = tuple(trials_by_experiment[experiment.id])
        seeds = tuple(sorted({seed for _, seed, _, _ in trial_rows}))
        expected_matrix = {(variant.position, seed) for variant in variants for seed in seeds}
        actual_matrix = {(position, seed) for position, seed, _, _ in trial_rows}
        if len(trial_rows) != len(expected_matrix) or actual_matrix != expected_matrix:
            raise RuntimeError(
                f"semantic experiment {experiment.id} has an incomplete trial matrix"
            )
        variants_by_position = {variant.position: variant for variant in variants}
        for variant_position, seed, _, trial_sha256 in trial_rows:
            variant = variants_by_position.get(variant_position)
            if variant is None:
                raise RuntimeError(
                    f"semantic experiment {experiment.id} trial references an unknown variant"
                )
            expected_trial_sha256 = calculate_semantic_trial_sha256(
                experiment.experiment_sha256,
                variant,
                seed,
            )
            if trial_sha256 != expected_trial_sha256:
                raise RuntimeError(
                    f"semantic experiment {experiment.id} contains an invalid trial hash"
                )
        expected_experiment_sha256 = calculate_semantic_experiment_sha256(
            str(experiment.scenario_id),
            experiment.scenario_sha256,
            str(experiment.cohort_id),
            experiment.cohort_sha256,
            variants,
            seeds,
            experiment.rounds,
            experiment.minutes_per_round,
            experiment.model_name,
            experiment.semantic_config_sha256,
        )
        if experiment.experiment_sha256 != expected_experiment_sha256:
            raise RuntimeError(
                f"semantic experiment {experiment.id} content does not match experiment_sha256"
            )
        summaries.append(
            _summary_from_state(
                experiment,
                variants,
                seeds,
                len(trial_rows),
                _status_from_values(tuple(status for _, _, status, _ in trial_rows)),
            )
        )
    return tuple(summaries)


async def create_semantic_experiment(
    session: AsyncSession,
    request: SemanticExperimentCreateRequest,
) -> SemanticExperimentDetail:
    scenario = await get_scenario(session, request.scenario_id)
    cohort = await get_cohort(session, request.cohort_id)
    variants = _select_variants(scenario, request.alternative_ids)
    seeds = tuple(sorted(request.seeds))
    _validate_execution_bounds(
        scenario,
        variants,
        cohort.persona_count,
        seeds,
        request.rounds,
        request.minutes_per_round,
    )
    model_name, config_sha256 = await get_live_semantic_config(session)
    experiment_sha256 = calculate_semantic_experiment_sha256(
        str(scenario.id),
        scenario.scenario_sha256,
        str(cohort.id),
        cohort.cohort_sha256,
        variants,
        seeds,
        request.rounds,
        request.minutes_per_round,
        model_name,
        config_sha256,
    )
    await _lock_experiment_content(session, experiment_sha256)
    existing = await session.scalar(
        select(SemanticExperimentRecord).where(
            SemanticExperimentRecord.experiment_sha256 == experiment_sha256
        )
    )
    if existing is not None:
        detail = (await _load_details(session, (existing,)))[0]
        await session.commit()
        return detail
    created_at = datetime.now(UTC)
    experiment, variant_records, trials = _new_records(
        scenario,
        cohort.id,
        cohort.title,
        cohort.cohort_sha256,
        cohort.dataset.dataset_sha256,
        cohort.persona_count,
        variants,
        seeds,
        request.rounds,
        request.minutes_per_round,
        model_name,
        config_sha256,
        experiment_sha256,
        created_at,
    )
    session.add(experiment)
    await session.flush((experiment,))
    session.add_all(variant_records)
    await session.flush(variant_records)
    session.add_all(trials)
    await session.flush(trials)
    experiment.input_sealed_at = created_at
    await session.flush((experiment,))
    detail = (await _load_details(session, (experiment,)))[0]
    await session.commit()
    return detail


async def list_semantic_experiments(session: AsyncSession) -> SemanticExperimentsResponse:
    records = tuple(
        (
            await session.execute(
                select(SemanticExperimentRecord)
                .where(SemanticExperimentRecord.input_sealed_at.is_not(None))
                .order_by(
                    SemanticExperimentRecord.created_at.desc(),
                    SemanticExperimentRecord.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    summaries = await _load_summaries(session, records)
    return SemanticExperimentsResponse(
        items=summaries,
        total=len(summaries),
    )


async def get_semantic_experiment(
    session: AsyncSession,
    experiment_id: UUID,
) -> SemanticExperimentDetail:
    record = await session.scalar(
        select(SemanticExperimentRecord).where(
            SemanticExperimentRecord.id == experiment_id,
            SemanticExperimentRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise SemanticExperimentNotFoundError(f"semantic experiment {experiment_id} was not found")
    return (await _load_details(session, (record,)))[0]


async def list_semantic_trial_events(
    session: AsyncSession,
    trial_id: UUID,
    after_sequence: int,
    limit: int,
) -> SemanticTrialEventsResponse:
    exists = await session.scalar(
        select(SemanticTrialRecord.id).where(SemanticTrialRecord.id == trial_id)
    )
    if exists is None:
        raise SemanticTrialNotFoundError(f"semantic trial {trial_id} was not found")
    records = tuple(
        (
            await session.execute(
                select(SemanticTrialEventRecord)
                .where(
                    SemanticTrialEventRecord.trial_id == trial_id,
                    SemanticTrialEventRecord.sequence > after_sequence,
                )
                .order_by(SemanticTrialEventRecord.sequence)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    page = records[:limit]
    return SemanticTrialEventsResponse(
        trial_id=trial_id,
        after_sequence=after_sequence,
        next_after_sequence=page[-1].sequence if page else after_sequence,
        has_more=len(records) > limit,
        items=tuple(_event_from_record(record) for record in page),
    )


def _mean_stddev(values: tuple[float, ...]) -> tuple[float, float]:
    return fsum(values) / len(values), pstdev(values) if len(values) > 1 else 0.0


def _metric_value(result: SemanticTrialResult, metric: str) -> float:
    if metric == "observed_action_count":
        return float(result.observed_action_count)
    if metric == "authored_content_count":
        return float(result.authored_content_count)
    if metric == "reaction_count":
        return float(result.reaction_count)
    if metric == "do_nothing_count":
        return float(result.do_nothing_count)
    raise RuntimeError(f"unsupported comparison metric {metric!r}")


def _comparison_metric(
    detail: SemanticExperimentDetail,
    metric: str,
) -> SemanticMetricComparison:
    observations: list[SemanticVariantObservation] = []
    successful_by_variant: dict[int, dict[int, SemanticTrialResult]] = {}
    for variant in detail.variants:
        successful = {
            trial.seed: trial.result
            for trial in variant.trials
            if trial.status == "succeeded" and trial.result is not None
        }
        successful_by_variant[variant.position] = successful
        values = tuple(_metric_value(result, metric) for result in successful.values())
        if values:
            mean, stddev = _mean_stddev(values)
            observations.append(
                SemanticVariantObservation(
                    position=variant.position,
                    role=variant.role,
                    id=variant.id,
                    name=variant.name,
                    n=len(values),
                    mean=mean,
                    stddev=stddev,
                )
            )
    baseline = successful_by_variant.get(0, {})
    deltas: list[SemanticPairedDelta] = []
    for alternative in detail.variants[1:]:
        alternative_results = successful_by_variant[alternative.position]
        common_seeds = tuple(sorted(set(baseline) & set(alternative_results)))
        if not common_seeds:
            continue
        values = tuple(
            _metric_value(alternative_results[seed], metric) - _metric_value(baseline[seed], metric)
            for seed in common_seeds
        )
        mean_delta, stddev_delta = _mean_stddev(values)
        deltas.append(
            SemanticPairedDelta(
                alternative_position=alternative.position,
                alternative_id=alternative.id,
                alternative_name=alternative.name,
                n=len(values),
                mean_delta=mean_delta,
                stddev_delta=stddev_delta,
            )
        )
    return SemanticMetricComparison(
        metric=metric,
        variants=tuple(observations),
        paired_deltas=tuple(deltas),
    )


async def compare_semantic_experiment(
    session: AsyncSession,
    experiment_id: UUID,
) -> SemanticExperimentComparison:
    detail = await get_semantic_experiment(session, experiment_id)
    trials = tuple(trial for variant in detail.variants for trial in variant.trials)
    statuses = {trial.status for trial in trials}
    complete = statuses == {"succeeded"}
    if complete:
        state = "complete"
    elif statuses <= {"succeeded", "failed"} and "failed" in statuses:
        state = "failed"
    elif not any(trial.status == "succeeded" for trial in trials) and "failed" not in statuses:
        state = "pending"
    else:
        state = "partial"
    metric_names = (
        "observed_action_count",
        "authored_content_count",
        "reaction_count",
        "do_nothing_count",
    )
    return SemanticExperimentComparison(
        experiment_id=detail.id,
        complete=complete,
        state=state,
        metrics=tuple(_comparison_metric(detail, metric) for metric in metric_names),
        limitations=COMPARISON_LIMITATIONS,
    )


async def get_semantic_readiness(session: AsyncSession) -> SemanticReadiness:
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeats = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord).where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
                    SimulationWorkerHeartbeatRecord.worker_domain == "semantic",
                )
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.semantic_model_name,
            heartbeat.semantic_config_sha256,
            heartbeat.semantic_prompt_schema_version,
        )
        for heartbeat in heartbeats
        if heartbeat.semantic_runtime_ready and heartbeat.worker_domain == "semantic"
    }
    conflict = len(configs) > 1
    complete_config = next(iter(configs)) if len(configs) == 1 else None
    ready = bool(heartbeats) and complete_config is not None and not conflict
    if ready and complete_config is not None:
        model_name, config_sha256, prompt_schema = complete_config
        if model_name is None or config_sha256 is None or prompt_schema != PROMPT_SCHEMA_VERSION:
            raise RuntimeError("semantic-ready worker persisted an incomplete configuration")
    else:
        model_name = None
        config_sha256 = None
        prompt_schema = None
    limitations = READINESS_BASE_LIMITATIONS
    if conflict:
        limitations += (
            "Live semantic workers disagree on model or configuration identity; "
            "enqueueing is blocked.",
        )
    elif not ready:
        limitations += (
            "No live worker currently exposes a complete semantic execution configuration.",
        )
    return SemanticReadiness(
        engine="camel-oasis",
        engine_version=OASIS_ENGINE_VERSION,
        camel_version=CAMEL_ENGINE_VERSION,
        worker_online=bool(heartbeats),
        live_worker_count=len(heartbeats),
        semantic_runtime_ready=ready,
        configuration_conflict=conflict,
        model_name=model_name,
        semantic_config_sha256=config_sha256,
        prompt_schema_version=prompt_schema,
        limitations=limitations,
    )


__all__ = [
    "PopulationCohortNotFoundError",
    "ScenarioNotFoundError",
    "compare_semantic_experiment",
    "create_semantic_experiment",
    "get_semantic_experiment",
    "get_semantic_readiness",
    "list_semantic_experiments",
    "list_semantic_trial_events",
]
