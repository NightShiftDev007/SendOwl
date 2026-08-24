"""Transactional assembly and verified reads for MatrAIx survey experiments."""

from datetime import UTC, datetime, timedelta
from math import fsum
from typing import NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_surveys.contracts import (
    MatraixSurveyCreateRequest,
    MatraixSurveyExperimentDetail,
    MatraixSurveyExperimentsResponse,
    MatraixSurveyExperimentSummary,
    MatraixSurveyReadiness,
    MatraixSurveyTrial,
    SurveyAggregate,
    SurveyChoiceAnswer,
    SurveyChoiceCounts,
    SurveyCohortRef,
    SurveyFreeTextAnswer,
    SurveyFreeTextObservation,
    SurveyLikertAggregate,
    SurveyLikertAnswer,
    SurveyPersonaRef,
    SurveyScenarioRef,
    SurveyStatus,
    SurveyTrialError,
    SurveyTrialResult,
    SurveyVariantRef,
)
from app.matraix_surveys.errors import (
    MatraixSurveyExperimentNotFoundError,
    MatraixSurveySelectionError,
    MatraixSurveyTrialNotFoundError,
    MatraixSurveyUnavailableError,
)
from app.matraix_surveys.hashing import (
    calculate_survey_answers_sha256,
    calculate_survey_experiment_sha256,
    calculate_survey_trial_sha256,
)
from app.matraix_surveys.instrument import (
    INSTRUMENT_SCHEMA_VERSION,
    PROMPT_SCHEMA_VERSION,
    RUNNER_VERSION,
    build_survey_instrument,
)
from app.matraix_surveys.models import (
    MatraixSurveyAnswerRecord,
    MatraixSurveyExperimentRecord,
    MatraixSurveyTrialRecord,
)
from app.populations.repository import get_cohort
from app.scenarios.contracts import ScenarioDetail, ScenarioVariant
from app.scenarios.repository import get_scenario
from app.shared.progress import (
    ParentProgress,
    build_parent_progress,
    parse_parent_progress_statuses,
)
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

AGGREGATE_LIMITATIONS = (
    "Counts, ratings, and reasons are synthetic persona survey observations; they are not "
    "predictions of real people or a decision recommendation.",
    "Aggregation preserves only exact choice counts, bounded Likert statistics, and each "
    "successful persona's free-text reason; it performs no stance or sentiment inference.",
)
READINESS_LIMITATIONS = (
    "Readiness requires a recent worker heartbeat after successful provider semantic and "
    "scenario-preference tool-call probes.",
    "The Survey runner records bounded synthetic persona responses, not real-human research.",
)


def _advisory_lock_key(digest: str) -> int:
    unsigned_key = int(digest[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _lock_experiment_content(session: AsyncSession, digest: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_lock_key(digest)},
    )


def _scenario_ref(scenario: ScenarioDetail) -> SurveyScenarioRef:
    return SurveyScenarioRef(
        id=scenario.id,
        title=scenario.title,
        decision_question=scenario.decision_question,
        scenario_sha256=scenario.scenario_sha256,
    )


def _cohort_ref(cohort: object) -> SurveyCohortRef:
    return SurveyCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )


def _variant_ref(variant: ScenarioVariant, role: str) -> SurveyVariantRef:
    if role not in ("baseline", "alternative"):
        raise RuntimeError(f"unsupported survey variant role {role!r}")
    return SurveyVariantRef(
        id=variant.id,
        role=role,
        position=variant.position,
        name=variant.name,
        hypothesis=variant.hypothesis,
    )


def _select_alternative(scenario: ScenarioDetail, alternative_id: UUID) -> ScenarioVariant:
    selected = next(
        (alternative for alternative in scenario.alternatives if alternative.id == alternative_id),
        None,
    )
    if selected is None:
        raise MatraixSurveySelectionError(
            f"alternative_id {alternative_id} does not belong to sealed scenario {scenario.id}"
        )
    return selected


async def _live_survey_config(session: AsyncSession) -> tuple[str, str]:
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
                    SimulationWorkerHeartbeatRecord.worker_domain == "evaluation",
                    SimulationWorkerHeartbeatRecord.survey_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.survey_prompt_schema_version
                    == PROMPT_SCHEMA_VERSION,
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.survey_model_name,
            heartbeat.survey_config_sha256,
            heartbeat.survey_prompt_schema_version,
        )
        for heartbeat in heartbeats
    }
    if not configs:
        raise MatraixSurveyUnavailableError(
            "MatrAIx Survey execution is unavailable because no correctly pinned worker "
            "reported a complete survey configuration in the last 30 seconds"
        )
    if len(configs) != 1:
        readable = ", ".join(
            sorted(
                f"model={name!r}, config_sha256={digest!r}, prompt={prompt!r}"
                for name, digest, prompt in configs
            )
        )
        raise MatraixSurveyUnavailableError(
            "live Survey workers disagree on execution configuration; resolve the conflict "
            f"before enqueueing experiments: {readable}"
        )
    model_name, config_sha256, prompt_schema = next(iter(configs))
    if model_name is None or config_sha256 is None or prompt_schema != PROMPT_SCHEMA_VERSION:
        raise RuntimeError("survey-ready worker persisted an incomplete configuration")
    return model_name, config_sha256


def _persona_ref(member: object) -> SurveyPersonaRef:
    return SurveyPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )


def _new_records(
    scenario: SurveyScenarioRef,
    cohort: SurveyCohortRef,
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
    personas: tuple[SurveyPersonaRef, ...],
    instrument_sha256: str,
    model_name: str,
    config_sha256: str,
    experiment_sha256: str,
    created_at: datetime,
    retry_of_experiment_id: UUID | None,
    retry_of_experiment_sha256: str | None,
    attempt_number: int,
) -> tuple[MatraixSurveyExperimentRecord, tuple[MatraixSurveyTrialRecord, ...]]:
    experiment = MatraixSurveyExperimentRecord(
        id=uuid4(),
        scenario_id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        scenario_title=scenario.title,
        decision_question=scenario.decision_question,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        cohort_title=cohort.title,
        dataset_sha256=cohort.dataset_sha256,
        persona_count=cohort.persona_count,
        baseline_id=baseline.id,
        baseline_position=baseline.position,
        baseline_name=baseline.name,
        baseline_hypothesis=baseline.hypothesis,
        alternative_id=alternative.id,
        alternative_position=alternative.position,
        alternative_name=alternative.name,
        alternative_hypothesis=alternative.hypothesis,
        instrument_schema_version=INSTRUMENT_SCHEMA_VERSION,
        instrument_sha256=instrument_sha256,
        model_name=model_name,
        survey_config_sha256=config_sha256,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        experiment_sha256=experiment_sha256,
        retry_of_experiment_id=retry_of_experiment_id,
        retry_of_experiment_sha256=retry_of_experiment_sha256,
        attempt_number=attempt_number,
        created_at=created_at,
        input_sealed_at=None,
    )
    trials = tuple(
        MatraixSurveyTrialRecord(
            id=uuid4(),
            experiment_id=experiment.id,
            persona_position=persona.position,
            persona_id=persona.id,
            persona_external_id=persona.persona_id,
            persona_display_name=persona.display_name,
            persona_profile_sha256=persona.profile_sha256,
            trial_sha256=calculate_survey_trial_sha256(experiment_sha256, persona),
            status="queued",
            created_at=created_at,
            claimed_by_worker_id=None,
            started_at=None,
            completed_at=None,
            runner_version=None,
            model_name=None,
            survey_config_sha256=None,
            prompt_schema_version=None,
            answers_sha256=None,
            error_code=None,
            error_message=None,
        )
        for persona in personas
    )
    return experiment, trials


def _scenario_from_record(record: MatraixSurveyExperimentRecord) -> SurveyScenarioRef:
    return SurveyScenarioRef(
        id=record.scenario_id,
        title=record.scenario_title,
        decision_question=record.decision_question,
        scenario_sha256=record.scenario_sha256,
    )


def _cohort_from_record(record: MatraixSurveyExperimentRecord) -> SurveyCohortRef:
    return SurveyCohortRef(
        id=record.cohort_id,
        title=record.cohort_title,
        cohort_sha256=record.cohort_sha256,
        dataset_sha256=record.dataset_sha256,
        persona_count=record.persona_count,
    )


def _baseline_from_record(record: MatraixSurveyExperimentRecord) -> SurveyVariantRef:
    return SurveyVariantRef(
        id=record.baseline_id,
        role="baseline",
        position=record.baseline_position,
        name=record.baseline_name,
        hypothesis=record.baseline_hypothesis,
    )


def _alternative_from_record(record: MatraixSurveyExperimentRecord) -> SurveyVariantRef:
    return SurveyVariantRef(
        id=record.alternative_id,
        role="alternative",
        position=record.alternative_position,
        name=record.alternative_name,
        hypothesis=record.alternative_hypothesis,
    )


def verify_survey_experiment_record(
    record: MatraixSurveyExperimentRecord,
) -> tuple[
    SurveyScenarioRef,
    SurveyCohortRef,
    SurveyVariantRef,
    SurveyVariantRef,
]:
    if record.input_sealed_at is None:
        raise RuntimeError(f"MatrAIx Survey experiment {record.id} is not sealed")
    scenario = _scenario_from_record(record)
    cohort = _cohort_from_record(record)
    baseline = _baseline_from_record(record)
    alternative = _alternative_from_record(record)
    instrument = build_survey_instrument(baseline, alternative)
    if instrument.instrument_sha256 != record.instrument_sha256:
        raise RuntimeError(f"Survey experiment {record.id} instrument hash is inconsistent")
    expected = calculate_survey_experiment_sha256(
        scenario,
        cohort,
        baseline,
        alternative,
        record.instrument_sha256,
        record.model_name,
        record.survey_config_sha256,
        record.retry_of_experiment_sha256,
        record.attempt_number,
    )
    if expected != record.experiment_sha256:
        raise RuntimeError(
            f"Survey experiment {record.id} content does not match experiment_sha256"
        )
    return scenario, cohort, baseline, alternative


def _persona_from_trial(trial: MatraixSurveyTrialRecord) -> SurveyPersonaRef:
    return SurveyPersonaRef(
        id=trial.persona_id,
        position=trial.persona_position,
        persona_id=trial.persona_external_id,
        display_name=trial.persona_display_name,
        profile_sha256=trial.persona_profile_sha256,
    )


def _answer_from_record(record: MatraixSurveyAnswerRecord) -> object:
    if record.question_position == 0:
        if record.choice_value not in ("baseline", "alternative"):
            raise RuntimeError(f"Survey answer {record.trial_id}/0 has invalid choice storage")
        return SurveyChoiceAnswer(
            position=0,
            question_id="preferred_variant",
            type="single_choice",
            value=record.choice_value,
        )
    if record.question_position == 1:
        if record.likert_value is None:
            raise RuntimeError(f"Survey answer {record.trial_id}/1 has no Likert value")
        return SurveyLikertAnswer(
            position=1,
            question_id="alternative_support",
            type="likert",
            value=record.likert_value,
        )
    if record.question_position == 2:
        if record.free_text_value is None:
            raise RuntimeError(f"Survey answer {record.trial_id}/2 has no free-text value")
        return SurveyFreeTextAnswer(
            position=2,
            question_id="primary_reason",
            type="free_text",
            value=record.free_text_value,
        )
    raise RuntimeError(
        f"Survey answer {record.trial_id}/{record.question_position} has unknown position"
    )


def _trial_from_record(
    trial: MatraixSurveyTrialRecord,
    experiment: MatraixSurveyExperimentRecord,
    answer_records: tuple[MatraixSurveyAnswerRecord, ...],
) -> MatraixSurveyTrial:
    persona = _persona_from_trial(trial)
    expected_trial_sha = calculate_survey_trial_sha256(experiment.experiment_sha256, persona)
    if expected_trial_sha != trial.trial_sha256:
        raise RuntimeError(f"Survey trial {trial.id} content does not match trial_sha256")
    answers = tuple(_answer_from_record(record) for record in answer_records)
    result = None
    error = None
    if trial.status == "succeeded":
        if len(answers) != 3:
            raise RuntimeError(f"succeeded Survey trial {trial.id} must contain exactly 3 answers")
        values = (
            trial.runner_version,
            trial.model_name,
            trial.survey_config_sha256,
            trial.prompt_schema_version,
            trial.answers_sha256,
        )
        if any(value is None for value in values):
            raise RuntimeError(f"succeeded Survey trial {trial.id} has incomplete provenance")
        expected_answers_sha = calculate_survey_answers_sha256(trial.trial_sha256, answers)
        if expected_answers_sha != trial.answers_sha256:
            raise RuntimeError(f"Survey trial {trial.id} answers do not match answers_sha256")
        if (
            trial.runner_version != RUNNER_VERSION
            or trial.model_name != experiment.model_name
            or trial.survey_config_sha256 != experiment.survey_config_sha256
            or trial.prompt_schema_version != experiment.prompt_schema_version
        ):
            raise RuntimeError(f"Survey trial {trial.id} provenance does not match experiment")
        result = SurveyTrialResult(
            runner_version=trial.runner_version,
            model_name=trial.model_name,
            survey_config_sha256=trial.survey_config_sha256,
            prompt_schema_version=trial.prompt_schema_version,
            answers_sha256=trial.answers_sha256,
            answers=answers,
        )
    elif answer_records:
        raise RuntimeError(f"non-successful Survey trial {trial.id} must not contain answers")
    if trial.status == "failed":
        if trial.error_code is None or trial.error_message is None:
            raise RuntimeError(f"failed Survey trial {trial.id} has incomplete error fields")
        error = SurveyTrialError(code=trial.error_code, message=trial.error_message)
    return MatraixSurveyTrial(
        id=trial.id,
        status=trial.status,
        persona=persona,
        trial_sha256=trial.trial_sha256,
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        result=result,
        error=error,
    )


def _experiment_status_values(status_values: tuple[str, ...]) -> SurveyStatus:
    statuses = set(status_values)
    unknown = statuses - {"queued", "running", "succeeded", "failed"}
    if unknown:
        raise RuntimeError(f"Survey trials contain unknown statuses: {sorted(unknown)}")
    if statuses == {"queued"}:
        return "queued"
    if statuses & {"queued", "running"}:
        return "running"
    if statuses == {"succeeded"}:
        return "succeeded"
    return "failed"


def _experiment_status(trials: tuple[MatraixSurveyTrial, ...]) -> SurveyStatus:
    return _experiment_status_values(tuple(trial.status for trial in trials))


def _aggregate(trials: tuple[MatraixSurveyTrial, ...]) -> SurveyAggregate:
    succeeded = tuple(trial for trial in trials if trial.result is not None)
    failed_count = sum(trial.status == "failed" for trial in trials)
    choice_values = tuple(trial.result.answers[0].value for trial in succeeded)
    likert_values = tuple(int(trial.result.answers[1].value) for trial in succeeded)
    reasons = tuple(
        SurveyFreeTextObservation(
            trial_id=trial.id,
            persona=trial.persona,
            text=str(trial.result.answers[2].value),
        )
        for trial in succeeded
    )
    return SurveyAggregate(
        succeeded_trial_count=len(succeeded),
        failed_trial_count=failed_count,
        preferred_variant=SurveyChoiceCounts(
            baseline_count=choice_values.count("baseline"),
            alternative_count=choice_values.count("alternative"),
        ),
        alternative_support=SurveyLikertAggregate(
            n=len(likert_values),
            min=min(likert_values) if likert_values else None,
            max=max(likert_values) if likert_values else None,
            mean=fsum(likert_values) / len(likert_values) if likert_values else None,
        ),
        primary_reasons=reasons,
        limitations=AGGREGATE_LIMITATIONS,
    )


def _summary(
    record: MatraixSurveyExperimentRecord,
    trials: tuple[MatraixSurveyTrial, ...],
) -> MatraixSurveyExperimentSummary:
    scenario, cohort, baseline, alternative = verify_survey_experiment_record(record)
    if len(trials) != record.persona_count:
        raise RuntimeError(f"Survey experiment {record.id} trial count does not match cohort")
    return MatraixSurveyExperimentSummary(
        id=record.id,
        status=_experiment_status(trials),
        created_at=record.created_at,
        scenario=scenario,
        cohort=cohort,
        baseline=baseline,
        alternative=alternative,
        trial_count=len(trials),
        succeeded_trial_count=sum(trial.status == "succeeded" for trial in trials),
        failed_trial_count=sum(trial.status == "failed" for trial in trials),
        model_name=record.model_name,
        survey_config_sha256=record.survey_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        instrument_schema_version=record.instrument_schema_version,
        instrument_sha256=record.instrument_sha256,
        experiment_sha256=record.experiment_sha256,
        retry_of_experiment_id=record.retry_of_experiment_id,
        retry_of_experiment_sha256=record.retry_of_experiment_sha256,
        attempt_number=record.attempt_number,
    )


async def _load_trials(
    session: AsyncSession,
    experiments: tuple[MatraixSurveyExperimentRecord, ...],
) -> dict[UUID, tuple[MatraixSurveyTrial, ...]]:
    if not experiments:
        return {}
    experiment_ids = tuple(record.id for record in experiments)
    trial_records = tuple(
        (
            await session.execute(
                select(MatraixSurveyTrialRecord)
                .where(MatraixSurveyTrialRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    MatraixSurveyTrialRecord.experiment_id,
                    MatraixSurveyTrialRecord.persona_position,
                )
            )
        )
        .scalars()
        .all()
    )
    trial_ids = tuple(trial.id for trial in trial_records)
    answer_records = (
        tuple(
            (
                await session.execute(
                    select(MatraixSurveyAnswerRecord)
                    .where(MatraixSurveyAnswerRecord.trial_id.in_(trial_ids))
                    .order_by(
                        MatraixSurveyAnswerRecord.trial_id,
                        MatraixSurveyAnswerRecord.question_position,
                    )
                )
            )
            .scalars()
            .all()
        )
        if trial_ids
        else ()
    )
    answers_by_trial: dict[UUID, list[MatraixSurveyAnswerRecord]] = {
        trial_id: [] for trial_id in trial_ids
    }
    for answer in answer_records:
        answers_by_trial[answer.trial_id].append(answer)
    experiments_by_id = {record.id: record for record in experiments}
    trials_by_experiment: dict[UUID, list[MatraixSurveyTrial]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    for trial in trial_records:
        trials_by_experiment[trial.experiment_id].append(
            _trial_from_record(
                trial,
                experiments_by_id[trial.experiment_id],
                tuple(answers_by_trial[trial.id]),
            )
        )
    return {
        experiment_id: tuple(trials_by_experiment[experiment_id])
        for experiment_id in experiment_ids
    }


class SurveyTrialSummaryRow(NamedTuple):
    experiment_id: UUID
    persona_position: int
    persona_id: UUID
    persona_external_id: str
    persona_display_name: str
    persona_profile_sha256: str
    trial_sha256: str
    status: str


async def _load_trial_summaries(
    session: AsyncSession,
    experiments: tuple[MatraixSurveyExperimentRecord, ...],
) -> dict[UUID, tuple[SurveyTrialSummaryRow, ...]]:
    """Load only bounded trial identity/status rows, never Survey answers."""
    if not experiments:
        return {}
    experiment_ids = tuple(record.id for record in experiments)
    rows = tuple(
        SurveyTrialSummaryRow(*row)
        for row in (
            await session.execute(
                select(
                    MatraixSurveyTrialRecord.experiment_id,
                    MatraixSurveyTrialRecord.persona_position,
                    MatraixSurveyTrialRecord.persona_id,
                    MatraixSurveyTrialRecord.persona_external_id,
                    MatraixSurveyTrialRecord.persona_display_name,
                    MatraixSurveyTrialRecord.persona_profile_sha256,
                    MatraixSurveyTrialRecord.trial_sha256,
                    MatraixSurveyTrialRecord.status,
                )
                .where(MatraixSurveyTrialRecord.experiment_id.in_(experiment_ids))
                .order_by(
                    MatraixSurveyTrialRecord.experiment_id,
                    MatraixSurveyTrialRecord.persona_position,
                )
            )
        ).tuples()
    )
    grouped: dict[UUID, list[SurveyTrialSummaryRow]] = {
        experiment_id: [] for experiment_id in experiment_ids
    }
    for row in rows:
        grouped[row.experiment_id].append(row)
    return {experiment_id: tuple(grouped[experiment_id]) for experiment_id in experiment_ids}


def _summary_without_answers(
    record: MatraixSurveyExperimentRecord,
    rows: tuple[SurveyTrialSummaryRow, ...],
) -> MatraixSurveyExperimentSummary:
    scenario, cohort, baseline, alternative = verify_survey_experiment_record(record)
    if len(rows) != record.persona_count:
        raise RuntimeError(f"Survey experiment {record.id} trial count does not match cohort")
    if tuple(row.persona_position for row in rows) != tuple(range(record.persona_count)):
        raise RuntimeError(f"Survey experiment {record.id} trial positions are incomplete")
    if len({row.persona_id for row in rows}) != len(rows):
        raise RuntimeError(f"Survey experiment {record.id} contains duplicate Personas")
    for row in rows:
        persona = SurveyPersonaRef(
            id=row.persona_id,
            position=row.persona_position,
            persona_id=row.persona_external_id,
            display_name=row.persona_display_name,
            profile_sha256=row.persona_profile_sha256,
        )
        expected_sha256 = calculate_survey_trial_sha256(record.experiment_sha256, persona)
        if expected_sha256 != row.trial_sha256:
            raise RuntimeError(f"Survey trial {row.trial_sha256} integrity mismatch")
    statuses = tuple(row.status for row in rows)
    return MatraixSurveyExperimentSummary(
        id=record.id,
        status=_experiment_status_values(statuses),
        created_at=record.created_at,
        scenario=scenario,
        cohort=cohort,
        baseline=baseline,
        alternative=alternative,
        trial_count=len(rows),
        succeeded_trial_count=sum(status == "succeeded" for status in statuses),
        failed_trial_count=sum(status == "failed" for status in statuses),
        model_name=record.model_name,
        survey_config_sha256=record.survey_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        instrument_schema_version=record.instrument_schema_version,
        instrument_sha256=record.instrument_sha256,
        experiment_sha256=record.experiment_sha256,
        retry_of_experiment_id=record.retry_of_experiment_id,
        retry_of_experiment_sha256=record.retry_of_experiment_sha256,
        attempt_number=record.attempt_number,
    )


async def _detail(
    session: AsyncSession,
    record: MatraixSurveyExperimentRecord,
) -> MatraixSurveyExperimentDetail:
    trials = (await _load_trials(session, (record,)))[record.id]
    summary = _summary(record, trials)
    baseline = summary.baseline
    alternative = summary.alternative
    return MatraixSurveyExperimentDetail(
        **summary.model_dump(mode="python"),
        instrument=build_survey_instrument(baseline, alternative),
        trials=trials,
        aggregate=_aggregate(trials),
    )


async def ensure_matraix_survey_experiment_record(
    session: AsyncSession,
    request: MatraixSurveyCreateRequest,
) -> MatraixSurveyExperimentRecord:
    """Validate and stage one content-addressed Survey without committing."""
    scenario_detail = await get_scenario(session, request.scenario_id)
    cohort_detail = await get_cohort(session, request.cohort_id)
    if cohort_detail.persona_count > 8:
        raise MatraixSurveySelectionError(
            f"cohort contains {cohort_detail.persona_count} personas; Survey supports at most 8"
        )
    selected_alternative = _select_alternative(scenario_detail, request.alternative_id)
    scenario = _scenario_ref(scenario_detail)
    cohort = _cohort_ref(cohort_detail)
    baseline = _variant_ref(scenario_detail.baseline, "baseline")
    alternative = _variant_ref(selected_alternative, "alternative")
    personas = tuple(_persona_ref(member) for member in cohort_detail.members)
    instrument = build_survey_instrument(baseline, alternative)
    model_name, config_sha256 = await _live_survey_config(session)
    experiment_sha256 = calculate_survey_experiment_sha256(
        scenario,
        cohort,
        baseline,
        alternative,
        instrument.instrument_sha256,
        model_name,
        config_sha256,
        None,
        1,
    )
    await _lock_experiment_content(session, experiment_sha256)
    existing = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.experiment_sha256 == experiment_sha256
        )
    )
    if existing is not None:
        return existing
    created_at = datetime.now(UTC)
    experiment, trials = _new_records(
        scenario,
        cohort,
        baseline,
        alternative,
        personas,
        instrument.instrument_sha256,
        model_name,
        config_sha256,
        experiment_sha256,
        created_at,
        None,
        None,
        1,
    )
    session.add(experiment)
    await session.flush((experiment,))
    session.add_all(trials)
    await session.flush(trials)
    experiment.input_sealed_at = created_at
    await session.flush((experiment,))
    return experiment


async def create_matraix_survey_experiment(
    session: AsyncSession,
    request: MatraixSurveyCreateRequest,
) -> MatraixSurveyExperimentDetail:
    """Validate, content-address, persist, and enqueue one survey per persona."""
    record = await ensure_matraix_survey_experiment_record(session, request)
    detail = await _detail(session, record)
    await session.commit()
    return detail


async def retry_matraix_survey_experiment(
    session: AsyncSession,
    experiment_id: UUID,
) -> MatraixSurveyExperimentDetail:
    parent = await session.get(MatraixSurveyExperimentRecord, experiment_id)
    if parent is None or parent.input_sealed_at is None:
        raise MatraixSurveyExperimentNotFoundError(
            f"MatrAIx Survey experiment {experiment_id} was not found"
        )
    existing = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.retry_of_experiment_id == parent.id
        )
    )
    if existing is not None:
        return await _detail(session, existing)
    rows = (await _load_trial_summaries(session, (parent,)))[parent.id]
    statuses = tuple(row.status for row in rows)
    if any(status in ("queued", "running") for status in statuses) or not any(
        status == "failed" for status in statuses
    ):
        raise MatraixSurveySelectionError(
            "only a terminal Survey experiment containing a failed trial can be retried"
        )
    if parent.attempt_number >= 5:
        raise MatraixSurveySelectionError("Survey retry limit of 5 attempts was reached")
    scenario, cohort, baseline, alternative = verify_survey_experiment_record(parent)
    cohort_detail = await get_cohort(session, parent.cohort_id)
    if _cohort_ref(cohort_detail) != cohort:
        raise RuntimeError(f"Survey experiment {parent.id} Cohort integrity mismatch")
    model_name, config_sha256 = await _live_survey_config(session)
    digest = calculate_survey_experiment_sha256(
        scenario,
        cohort,
        baseline,
        alternative,
        parent.instrument_sha256,
        model_name,
        config_sha256,
        parent.experiment_sha256,
        parent.attempt_number + 1,
    )
    await _lock_experiment_content(session, digest)
    existing_after_lock = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.retry_of_experiment_id == parent.id
        )
    )
    if existing_after_lock is not None:
        detail = await _detail(session, existing_after_lock)
        await session.commit()
        return detail
    created_at = datetime.now(UTC)
    experiment, trials = _new_records(
        scenario,
        cohort,
        baseline,
        alternative,
        tuple(_persona_ref(member) for member in cohort_detail.members),
        parent.instrument_sha256,
        model_name,
        config_sha256,
        digest,
        created_at,
        parent.id,
        parent.experiment_sha256,
        parent.attempt_number + 1,
    )
    session.add(experiment)
    await session.flush((experiment,))
    session.add_all(trials)
    await session.flush(trials)
    experiment.input_sealed_at = created_at
    await session.flush((experiment,))
    detail = await _detail(session, experiment)
    await session.commit()
    return detail


async def list_matraix_survey_experiments(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> MatraixSurveyExperimentsResponse:
    total = await session.scalar(
        select(func.count())
        .select_from(MatraixSurveyExperimentRecord)
        .where(MatraixSurveyExperimentRecord.input_sealed_at.is_not(None))
    )
    if total is None:
        raise RuntimeError("MatrAIx Survey experiment count is unavailable")
    if total == 0:
        return MatraixSurveyExperimentsResponse(items=(), page=1, page_size=page_size, total=0)
    if (page - 1) * page_size >= total:
        raise MatraixSurveySelectionError("requested Survey experiment page starts beyond total")
    records = tuple(
        (
            await session.execute(
                select(MatraixSurveyExperimentRecord)
                .where(MatraixSurveyExperimentRecord.input_sealed_at.is_not(None))
                .order_by(
                    MatraixSurveyExperimentRecord.created_at.desc(),
                    MatraixSurveyExperimentRecord.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    trials = await _load_trial_summaries(session, records)
    items = tuple(_summary_without_answers(record, trials[record.id]) for record in records)
    return MatraixSurveyExperimentsResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_matraix_survey_experiment(
    session: AsyncSession,
    experiment_id: UUID,
) -> MatraixSurveyExperimentDetail:
    record = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.id == experiment_id,
            MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixSurveyExperimentNotFoundError(
            f"MatrAIx Survey experiment {experiment_id} was not found"
        )
    return await _detail(session, record)


async def get_matraix_survey_experiment_progress(
    session: AsyncSession,
    experiment_id: UUID,
) -> ParentProgress:
    record = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.id == experiment_id,
            MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixSurveyExperimentNotFoundError(
            f"MatrAIx Survey experiment {experiment_id} was not found"
        )
    rows = (await _load_trial_summaries(session, (record,)))[record.id]
    answer_count = await session.scalar(
        select(func.count())
        .select_from(MatraixSurveyAnswerRecord)
        .join(
            MatraixSurveyTrialRecord,
            MatraixSurveyTrialRecord.id == MatraixSurveyAnswerRecord.trial_id,
        )
        .where(MatraixSurveyTrialRecord.experiment_id == record.id)
    )
    if answer_count is None:
        raise RuntimeError(f"MatrAIx Survey experiment {record.id} answer count is unavailable")
    return build_parent_progress(
        record.id,
        record.attempt_number,
        parse_parent_progress_statuses(tuple(row.status for row in rows)),
        answer_count,
        datetime.now(UTC),
    )


async def get_matraix_survey_trial(
    session: AsyncSession,
    trial_id: UUID,
) -> MatraixSurveyTrial:
    trial = await session.scalar(
        select(MatraixSurveyTrialRecord).where(MatraixSurveyTrialRecord.id == trial_id)
    )
    if trial is None:
        raise MatraixSurveyTrialNotFoundError(f"MatrAIx Survey trial {trial_id} was not found")
    experiment = await session.scalar(
        select(MatraixSurveyExperimentRecord).where(
            MatraixSurveyExperimentRecord.id == trial.experiment_id,
            MatraixSurveyExperimentRecord.input_sealed_at.is_not(None),
        )
    )
    if experiment is None:
        raise RuntimeError(f"Survey trial {trial.id} references a missing sealed experiment")
    verify_survey_experiment_record(experiment)
    answers = tuple(
        (
            await session.execute(
                select(MatraixSurveyAnswerRecord)
                .where(MatraixSurveyAnswerRecord.trial_id == trial.id)
                .order_by(MatraixSurveyAnswerRecord.question_position)
            )
        )
        .scalars()
        .all()
    )
    return _trial_from_record(trial, experiment, answers)


async def get_matraix_survey_readiness(session: AsyncSession) -> MatraixSurveyReadiness:
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
                    SimulationWorkerHeartbeatRecord.worker_domain == "evaluation",
                )
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.survey_model_name,
            heartbeat.survey_config_sha256,
            heartbeat.survey_prompt_schema_version,
        )
        for heartbeat in heartbeats
        if (
            heartbeat.worker_domain == "evaluation"
            and heartbeat.survey_runtime_ready
            and heartbeat.survey_prompt_schema_version == PROMPT_SCHEMA_VERSION
        )
    }
    conflict = len(configs) > 1
    complete_config = next(iter(configs)) if len(configs) == 1 else None
    ready = bool(heartbeats) and complete_config is not None and not conflict
    if ready and complete_config is not None:
        model_name, config_sha256, prompt_schema = complete_config
        if model_name is None or config_sha256 is None or prompt_schema != PROMPT_SCHEMA_VERSION:
            raise RuntimeError("survey-ready worker persisted an incomplete configuration")
    else:
        model_name = None
        config_sha256 = None
        prompt_schema = None
    limitations = READINESS_LIMITATIONS
    if conflict:
        limitations += (
            "Live Survey workers disagree on model or configuration identity; "
            "enqueueing is blocked.",
        )
    elif not ready:
        limitations += (
            "No live worker currently exposes a complete Survey execution configuration.",
        )
    return MatraixSurveyReadiness(
        engine="matraix-survey",
        runner_version=RUNNER_VERSION,
        worker_online=bool(heartbeats),
        live_worker_count=len(heartbeats),
        survey_runtime_ready=ready,
        configuration_conflict=conflict,
        model_name=model_name,
        survey_config_sha256=config_sha256,
        prompt_schema_version=prompt_schema,
        instrument_schema_version=INSTRUMENT_SCHEMA_VERSION,
        limitations=limitations,
    )


__all__ = [
    "create_matraix_survey_experiment",
    "ensure_matraix_survey_experiment_record",
    "get_matraix_survey_experiment",
    "get_matraix_survey_readiness",
    "get_matraix_survey_trial",
    "list_matraix_survey_experiments",
    "verify_survey_experiment_record",
]
