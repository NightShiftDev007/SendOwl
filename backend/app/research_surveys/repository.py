"""Transactional assembly and verified reads for native research surveys."""

from datetime import UTC, datetime, timedelta
from math import fsum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.repository import get_cohort
from app.research_projects.models import ResearchProjectRecord, ResearchSimulationRunRecord
from app.research_surveys.contracts import (
    ResearchSurveyAggregate,
    ResearchSurveyCohortRef,
    ResearchSurveyCreateRequest,
    ResearchSurveyDetail,
    ResearchSurveyFocusAnswer,
    ResearchSurveyFocusCounts,
    ResearchSurveyInstrument,
    ResearchSurveyLikertAnswer,
    ResearchSurveyPersonaRef,
    ResearchSurveyProjectRef,
    ResearchSurveyQuestionAnswer,
    ResearchSurveyReadiness,
    ResearchSurveyRunRef,
    ResearchSurveysResponse,
    ResearchSurveySummary,
    ResearchSurveyTrial,
    ResearchSurveyTrialError,
    ResearchSurveyTrialResult,
)
from app.research_surveys.errors import (
    ResearchSurveyNotFoundError,
    ResearchSurveySelectionError,
    ResearchSurveyUnavailableError,
)
from app.research_surveys.hashing import instrument_sha256, survey_sha256, trial_sha256
from app.research_surveys.models import (
    ResearchSurveyAnswerRecord,
    ResearchSurveyRecord,
    ResearchSurveyTrialRecord,
)
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

LIMITATIONS = (
    "这些回答是冻结 Persona 在单一合成研究上下文中的模拟观察，不是真人调研。",
    "Survey 不比较、排序或推荐方案，也不验证 Simulation Run 的现实有效性。",
)


def _instrument() -> ResearchSurveyInstrument:
    return ResearchSurveyInstrument(
        schema_version="single-context-observation/v1",
        instrument_sha256=instrument_sha256(),
        title="Single-context observation",
        description="记录每个合成 Persona 对同一研究上下文的清晰度、关注重点与一个未解问题。",
    )


async def _live_config(session: AsyncSession) -> tuple[str, str, int]:
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    rows = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord).where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
                    SimulationWorkerHeartbeatRecord.worker_domain == "evaluation",
                    SimulationWorkerHeartbeatRecord.survey_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.survey_prompt_schema_version
                    == "sandowl-research-survey/v1",
                )
            )
        )
        .scalars()
        .all()
    )
    configs = {(row.survey_model_name, row.survey_config_sha256) for row in rows}
    if len(configs) != 1:
        raise ResearchSurveyUnavailableError(
            "native Survey requires one consistent live evaluation-worker configuration"
        )
    model, config = next(iter(configs))
    if model is None or config is None:
        raise RuntimeError("ready Survey worker persisted an incomplete configuration")
    return model, config, len(rows)


def _refs(
    record: ResearchSurveyRecord,
) -> tuple[ResearchSurveyProjectRef, ResearchSurveyRunRef, ResearchSurveyCohortRef]:
    return (
        ResearchSurveyProjectRef(
            id=record.research_project_id,
            title=record.project_title,
            research_question=record.research_question,
            project_sha256=record.project_sha256,
        ),
        ResearchSurveyRunRef(
            id=record.research_simulation_run_id,
            simulation_requirement=record.simulation_requirement,
            initial_post=record.initial_post,
            run_spec_sha256=record.run_spec_sha256,
        ),
        ResearchSurveyCohortRef(
            id=record.cohort_id,
            title=record.cohort_title,
            cohort_sha256=record.cohort_sha256,
            dataset_sha256=record.dataset_sha256,
            persona_count=record.persona_count,
        ),
    )


def _status(statuses: tuple[str, ...]) -> str:
    if all(item == "queued" for item in statuses):
        return "queued"
    if any(item in ("queued", "running") for item in statuses):
        return "running"
    if all(item == "succeeded" for item in statuses):
        return "succeeded"
    return "failed"


def _persona(record: ResearchSurveyTrialRecord) -> ResearchSurveyPersonaRef:
    return ResearchSurveyPersonaRef(
        id=record.persona_id,
        position=record.persona_position,
        persona_id=record.persona_external_id,
        display_name=record.persona_display_name,
        profile_sha256=record.persona_profile_sha256,
    )


async def _records(
    session: AsyncSession, survey_id: UUID
) -> tuple[
    ResearchSurveyRecord,
    tuple[ResearchSurveyTrialRecord, ...],
    dict[UUID, tuple[ResearchSurveyAnswerRecord, ...]],
]:
    survey = await session.get(ResearchSurveyRecord, survey_id)
    if survey is None:
        raise ResearchSurveyNotFoundError(f"research survey {survey_id} was not found")
    trials = tuple(
        (
            await session.execute(
                select(ResearchSurveyTrialRecord)
                .where(ResearchSurveyTrialRecord.survey_id == survey_id)
                .order_by(ResearchSurveyTrialRecord.persona_position)
            )
        )
        .scalars()
        .all()
    )
    answers: dict[UUID, tuple[ResearchSurveyAnswerRecord, ...]] = {}
    for trial in trials:
        answers[trial.id] = tuple(
            (
                await session.execute(
                    select(ResearchSurveyAnswerRecord)
                    .where(ResearchSurveyAnswerRecord.trial_id == trial.id)
                    .order_by(ResearchSurveyAnswerRecord.question_position)
                )
            )
            .scalars()
            .all()
        )
    return survey, trials, answers


def _summary(
    record: ResearchSurveyRecord, trials: tuple[ResearchSurveyTrialRecord, ...]
) -> ResearchSurveySummary:
    statuses = tuple(item.status for item in trials)
    project, run, cohort = _refs(record)
    return ResearchSurveySummary(
        id=record.id,
        status=_status(statuses),
        project=project,
        run=run,
        cohort=cohort,
        trial_count=len(trials),
        succeeded_trial_count=statuses.count("succeeded"),
        failed_trial_count=statuses.count("failed"),
        model_name=record.model_name,
        survey_config_sha256=record.survey_config_sha256,
        prompt_schema_version="sandowl-research-survey/v1",
        instrument_schema_version="single-context-observation/v1",
        instrument_sha256=record.instrument_sha256,
        survey_sha256=record.survey_sha256,
        created_at=record.created_at,
    )


def _trial(
    record: ResearchSurveyTrialRecord, answers: tuple[ResearchSurveyAnswerRecord, ...]
) -> ResearchSurveyTrial:
    result = None
    error = None
    if record.status == "succeeded":
        if (
            len(answers) != 3
            or record.runner_version != "1.0.0"
            or record.model_name is None
            or record.survey_config_sha256 is None
            or record.answers_sha256 is None
        ):
            raise RuntimeError(
                f"research survey trial {record.id} has incomplete successful output"
            )
        result = ResearchSurveyTrialResult(
            runner_version="1.0.0",
            model_name=record.model_name,
            survey_config_sha256=record.survey_config_sha256,
            prompt_schema_version="sandowl-research-survey/v1",
            answers_sha256=record.answers_sha256,
            answers=(
                ResearchSurveyLikertAnswer(
                    position=0,
                    question_id="context_clarity",
                    type="likert",
                    value=int(answers[0].likert_value),
                ),
                ResearchSurveyFocusAnswer(
                    position=1,
                    question_id="attention_priority",
                    type="single_choice",
                    value=str(answers[1].choice_value),
                ),
                ResearchSurveyQuestionAnswer(
                    position=2,
                    question_id="unanswered_question",
                    type="free_text",
                    value=str(answers[2].free_text_value),
                ),
            ),
        )
    elif record.status == "failed":
        if record.error_code is None or record.error_message is None:
            raise RuntimeError(f"research survey trial {record.id} has incomplete failure")
        error = ResearchSurveyTrialError(code=record.error_code, message=record.error_message)
    return ResearchSurveyTrial(
        id=record.id,
        status=record.status,
        persona=_persona(record),
        trial_sha256=record.trial_sha256,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        result=result,
        error=error,
    )


async def ensure_research_survey_record(
    session: AsyncSession, request: ResearchSurveyCreateRequest
) -> ResearchSurveyRecord:
    project = await session.get(ResearchProjectRecord, request.research_project_id)
    run = await session.get(ResearchSimulationRunRecord, request.research_simulation_run_id)
    if project is None or run is None or run.research_project_id != request.research_project_id:
        raise ResearchSurveySelectionError(
            "the selected project and simulation run do not form one native research scope"
        )
    if run.status != "succeeded" or run.initial_post is None:
        raise ResearchSurveySelectionError(
            "a native Survey can only bind a succeeded v2 Simulation Run"
        )
    cohort = await get_cohort(session, run.cohort_id)
    if cohort.cohort_sha256 != run.cohort_sha256 or cohort.persona_count != run.persona_count:
        raise RuntimeError("run cohort identity differs from the sealed Cohort")
    from app.research_evaluations.bundles import ensure_research_evaluation_task_bundle
    from app.research_evaluations.contracts import ResearchEvaluationTaskBundleCreateRequest

    await ensure_research_evaluation_task_bundle(
        session,
        ResearchEvaluationTaskBundleCreateRequest(
            research_project_id=project.id,
            research_simulation_run_id=run.id,
            kind="survey",
        ),
        commit=False,
    )
    existing = await session.scalar(
        select(ResearchSurveyRecord).where(
            ResearchSurveyRecord.research_simulation_run_id == run.id
        )
    )
    if existing is not None:
        return existing
    model, config, _ = await _live_config(session)
    frozen_sha = survey_sha256(
        project.project_sha256, run.run_spec_sha256, cohort.cohort_sha256, model, config
    )
    now = datetime.now(UTC)
    survey = ResearchSurveyRecord(
        id=uuid4(),
        research_project_id=project.id,
        research_simulation_run_id=run.id,
        project_title=project.title,
        research_question=project.research_question,
        project_sha256=project.project_sha256,
        simulation_requirement=run.simulation_requirement,
        initial_post=run.initial_post,
        run_spec_sha256=run.run_spec_sha256,
        cohort_id=cohort.id,
        cohort_title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
        instrument_schema_version="single-context-observation/v1",
        instrument_sha256=instrument_sha256(),
        model_name=model,
        survey_config_sha256=config,
        prompt_schema_version="sandowl-research-survey/v1",
        survey_sha256=frozen_sha,
        created_at=now,
        sealed_at=now,
    )
    session.add(survey)
    await session.flush((survey,))
    trials = tuple(
        ResearchSurveyTrialRecord(
            id=uuid4(),
            survey_id=survey.id,
            persona_position=member.position,
            persona_id=member.persona.id,
            persona_external_id=member.persona.persona_id,
            persona_display_name=member.persona.display_name,
            persona_profile_sha256=member.persona.profile_sha256,
            trial_sha256=trial_sha256(
                frozen_sha, member.position, member.persona.id, member.persona.profile_sha256
            ),
            status="queued",
            created_at=now,
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
        for member in cohort.members
    )
    session.add_all(trials)
    await session.flush(trials)
    return survey


async def create_research_survey(
    session: AsyncSession, request: ResearchSurveyCreateRequest
) -> ResearchSurveyDetail:
    survey = await ensure_research_survey_record(session, request)
    await session.commit()
    return await get_research_survey(session, survey.id)


async def get_research_survey(session: AsyncSession, survey_id: UUID) -> ResearchSurveyDetail:
    record, trial_records, answer_records = await _records(session, survey_id)
    trials = tuple(_trial(item, answer_records[item.id]) for item in trial_records)
    summary = _summary(record, trial_records)
    succeeded = tuple(item for item in trials if item.result is not None)
    clarity = tuple(
        float(item.result.answers[0].value) for item in succeeded if item.result is not None
    )
    focuses = tuple(
        str(item.result.answers[1].value) for item in succeeded if item.result is not None
    )
    questions = tuple(
        str(item.result.answers[2].value) for item in succeeded if item.result is not None
    )
    aggregate = ResearchSurveyAggregate(
        succeeded_trial_count=len(succeeded),
        failed_trial_count=sum(item.status == "failed" for item in trials),
        context_clarity_mean=None if not clarity else fsum(clarity) / len(clarity),
        attention_priority=ResearchSurveyFocusCounts(
            evidence=focuses.count("evidence"),
            process=focuses.count("process"),
            timing=focuses.count("timing"),
            impact=focuses.count("impact"),
        ),
        unanswered_questions=questions,
        limitations=LIMITATIONS,
    )
    return ResearchSurveyDetail(
        **summary.model_dump(), instrument=_instrument(), trials=trials, aggregate=aggregate
    )


async def list_research_surveys(session: AsyncSession) -> ResearchSurveysResponse:
    ids = tuple(
        (
            await session.execute(
                select(ResearchSurveyRecord.id).order_by(
                    ResearchSurveyRecord.created_at.desc(), ResearchSurveyRecord.id
                )
            )
        )
        .scalars()
        .all()
    )
    details = tuple([await get_research_survey(session, item) for item in ids])
    return ResearchSurveysResponse(
        items=tuple(ResearchSurveySummary.model_validate(item.model_dump()) for item in details),
        total=len(details),
    )


async def get_research_survey_progress(session: AsyncSession, survey_id: UUID) -> ParentProgress:
    record, trials, answers = await _records(session, survey_id)
    return build_parent_progress(
        record.id,
        1,
        parse_parent_progress_statuses(tuple(item.status for item in trials)),
        sum(len(items) for items in answers.values()),
        datetime.now(UTC),
    )


async def get_research_survey_readiness(session: AsyncSession) -> ResearchSurveyReadiness:
    try:
        model, config, count = await _live_config(session)
        ready = True
    except ResearchSurveyUnavailableError:
        model = config = None
        ready = False
        count = 0
    return ResearchSurveyReadiness(
        engine="matraix-survey",
        runner_version="1.0.0",
        survey_runtime_ready=ready,
        live_worker_count=count,
        model_name=model,
        survey_config_sha256=config,
        prompt_schema_version="sandowl-research-survey/v1" if ready else None,
        instrument_schema_version="single-context-observation/v1",
        limitations=LIMITATIONS,
    )
