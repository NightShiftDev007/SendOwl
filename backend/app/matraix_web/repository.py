"""Queue, verify, and project durable MatrAIx Playwright evaluations."""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_web.contracts import (
    MatraixWebEvaluationCreateRequest,
    MatraixWebEvaluationDetail,
    MatraixWebEvaluationsResponse,
    MatraixWebEvaluationSummary,
    MatraixWebReadiness,
    MatraixWebTasksResponse,
    MatraixWebTrial,
    MatraixWebTrialSummary,
    WebCohortRef,
    WebPageObservation,
    WebPersonaRef,
    WebQuoteObservation,
    WebTrialError,
    WebTrialResult,
)
from app.matraix_web.errors import (
    MatraixWebEvaluationNotFoundError,
    MatraixWebScreenshotNotFoundError,
    MatraixWebSelectionError,
    MatraixWebTrialNotFoundError,
    MatraixWebUnavailableError,
)
from app.matraix_web.hashing import (
    calculate_evaluation_sha256,
    calculate_result_sha256,
    calculate_trace_sha256,
    calculate_trial_sha256,
)
from app.matraix_web.models import (
    MatraixWebEvaluationRecord,
    MatraixWebPageRecord,
    MatraixWebQuoteRecord,
    MatraixWebTrialRecord,
)
from app.matraix_web.tasks import (
    EXECUTOR_SCHEMA_VERSION,
    EXECUTOR_SPEC_SHA256,
    PROMPT_SCHEMA_VERSION,
    RUNNER_VERSION,
    TASK_ID,
    TASK_VERSION,
    build_web_task,
)
from app.populations.contracts import CohortDetail, CohortMember
from app.populations.repository import get_cohort
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

READINESS_LIMITATIONS = (
    "Readiness requires a recent worker heartbeat after both the provider tool-call probe "
    "and the fixed Playwright executor identity probe.",
    "The executor can browse only the fixed Quotes to Scrape origin and writes screenshots "
    "to the SendOwl Web artifact volume.",
    "The selected quote and rating are synthetic Persona output, not a benchmark reward or "
    "human preference claim.",
)


class TrialIdentityRow(NamedTuple):
    evaluation_id: UUID
    id: UUID
    persona_position: int
    persona_id: UUID
    persona_external_id: str
    persona_display_name: str
    persona_profile_sha256: str
    trial_sha256: str
    status: str


def list_web_tasks() -> MatraixWebTasksResponse:
    task = build_web_task()
    return MatraixWebTasksResponse(items=(task,), total=1)


def _cohort_ref(cohort: CohortDetail) -> WebCohortRef:
    return WebCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
        persona_count=cohort.persona_count,
    )


def _persona_ref(member: CohortMember) -> WebPersonaRef:
    return WebPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
    )


def _status(statuses: tuple[str, ...]) -> str:
    if all(status == "queued" for status in statuses):
        return "queued"
    if any(status in {"queued", "running"} for status in statuses):
        return "running"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "failed"


async def _lock_content(session: AsyncSession, digest: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )


async def _live_config(session: AsyncSession) -> tuple[str, str]:
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
                    SimulationWorkerHeartbeatRecord.platform_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.web_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.web_executor_schema_version
                    == EXECUTOR_SCHEMA_VERSION,
                    SimulationWorkerHeartbeatRecord.web_executor_spec_sha256
                    == EXECUTOR_SPEC_SHA256,
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.web_model_name,
            heartbeat.web_config_sha256,
            heartbeat.web_prompt_schema_version,
        )
        for heartbeat in heartbeats
    }
    if not configs:
        raise MatraixWebUnavailableError(
            "MatrAIx Web execution is unavailable because no correctly pinned worker "
            "reported a complete browser/model configuration in the last 30 seconds"
        )
    if len(configs) != 1:
        raise MatraixWebUnavailableError(
            "live MatrAIx Web workers disagree on execution configuration"
        )
    model_name, config_sha256, prompt = next(iter(configs))
    if model_name is None or config_sha256 is None or prompt != PROMPT_SCHEMA_VERSION:
        raise RuntimeError("web-ready worker persisted an incomplete configuration")
    return model_name, config_sha256


def verify_web_evaluation_record(record: MatraixWebEvaluationRecord) -> WebCohortRef:
    task = build_web_task()
    if record.input_sealed_at is None:
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} is not sealed")
    if (
        record.task_id != task.task_id
        or record.task_version != task.version
        or record.task_schema_version != task.schema_version
        or record.task_spec_sha256 != task.task_spec_sha256
        or record.executor_schema_version != task.executor_schema_version
        or record.executor_spec_sha256 != task.executor_spec_sha256
        or record.prompt_schema_version != PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} task integrity mismatch")
    cohort = WebCohortRef(
        id=record.cohort_id,
        title=record.cohort_title,
        cohort_sha256=record.cohort_sha256,
        dataset_sha256=record.dataset_sha256,
        persona_count=record.persona_count,
    )
    expected = calculate_evaluation_sha256(
        record.task_spec_sha256,
        record.executor_spec_sha256,
        cohort,
        record.model_name,
        record.web_config_sha256,
        record.retry_of_evaluation_sha256,
        record.attempt_number,
    )
    if record.evaluation_sha256 != expected:
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} integrity mismatch")
    return cohort


def _persona_from_record(record: MatraixWebTrialRecord) -> WebPersonaRef:
    return WebPersonaRef(
        id=record.persona_id,
        position=record.persona_position,
        persona_id=record.persona_external_id,
        display_name=record.persona_display_name,
        profile_sha256=record.persona_profile_sha256,
    )


def _verify_trial_identity(
    record: MatraixWebTrialRecord,
    evaluation: MatraixWebEvaluationRecord,
) -> WebPersonaRef:
    persona = _persona_from_record(record)
    if calculate_trial_sha256(evaluation.evaluation_sha256, persona) != record.trial_sha256:
        raise RuntimeError(f"MatrAIx Web trial {record.id} integrity mismatch")
    return persona


def _page(
    trial_id: UUID,
    record: MatraixWebPageRecord,
    quotes: tuple[MatraixWebQuoteRecord, ...],
) -> WebPageObservation:
    return WebPageObservation(
        position=record.position,
        url=record.url,
        title=record.title,
        screenshot_sha256=record.screenshot_sha256,
        screenshot_path=(f"/api/v2/matraix/web-trials/{trial_id}/screenshots/{record.position}"),
        observed_at=record.observed_at,
        quotes=tuple(
            WebQuoteObservation(
                position=quote.position,
                quote_id=quote.quote_id,
                text=quote.text,
                author=quote.author,
                tags=tuple(quote.tags),
            )
            for quote in quotes
        ),
    )


def _trial(
    record: MatraixWebTrialRecord,
    evaluation: MatraixWebEvaluationRecord,
    pages: tuple[WebPageObservation, ...],
) -> MatraixWebTrial:
    persona = _verify_trial_identity(record, evaluation)
    result: WebTrialResult | None = None
    error: WebTrialError | None = None
    if record.status == "succeeded":
        required = (
            record.runner_version,
            record.model_name,
            record.web_config_sha256,
            record.prompt_schema_version,
            record.trace_sha256,
            record.result_sha256,
            record.decision_subject_id,
            record.decision_subject_label,
            record.basis_primary,
            record.reason,
            record.task_author,
            record.need_constraint_satisfaction,
            record.personal_preference_satisfaction,
            record.overall_experience_rating,
        )
        if any(value is None for value in required):
            raise RuntimeError(f"successful MatrAIx Web trial {record.id} is incomplete")
        expected_trace = calculate_trace_sha256(record.trial_sha256, pages)
        expected_result = calculate_result_sha256(
            record.trial_sha256,
            expected_trace,
            record.decision_subject_id,
            record.decision_subject_label,
            record.basis_primary,
            record.reason,
            record.task_author,
            record.need_constraint_satisfaction,
            record.personal_preference_satisfaction,
            record.overall_experience_rating,
        )
        if record.trace_sha256 != expected_trace or record.result_sha256 != expected_result:
            raise RuntimeError(f"MatrAIx Web trial {record.id} output integrity mismatch")
        if (
            record.model_name != evaluation.model_name
            or record.web_config_sha256 != evaluation.web_config_sha256
            or record.prompt_schema_version != evaluation.prompt_schema_version
        ):
            raise RuntimeError(f"MatrAIx Web trial {record.id} runtime integrity mismatch")
        result = WebTrialResult(
            runner_version=record.runner_version,
            model_name=record.model_name,
            web_config_sha256=record.web_config_sha256,
            prompt_schema_version=record.prompt_schema_version,
            trace_sha256=record.trace_sha256,
            result_sha256=record.result_sha256,
            decision_subject_id=record.decision_subject_id,
            decision_subject_label=record.decision_subject_label,
            decision_outcome="selected",
            basis_primary=record.basis_primary,
            exploration_style="compared_multiple",
            reason=record.reason,
            task_author=record.task_author,
            need_constraint_satisfaction=record.need_constraint_satisfaction,
            personal_preference_satisfaction=record.personal_preference_satisfaction,
            overall_experience_rating=record.overall_experience_rating,
        )
    elif record.status == "failed":
        if record.error_code is None or record.error_message is None:
            raise RuntimeError(f"failed MatrAIx Web trial {record.id} has no error")
        error = WebTrialError(code=record.error_code, message=record.error_message)
    return MatraixWebTrial(
        id=record.id,
        status=record.status,
        persona=persona,
        trial_sha256=record.trial_sha256,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        pages=pages,
        result=result,
        error=error,
    )


async def _load_trial_records(
    session: AsyncSession,
    evaluation_ids: tuple[UUID, ...],
) -> tuple[MatraixWebTrialRecord, ...]:
    if not evaluation_ids:
        return ()
    return tuple(
        (
            await session.execute(
                select(MatraixWebTrialRecord)
                .where(MatraixWebTrialRecord.evaluation_id.in_(evaluation_ids))
                .order_by(
                    MatraixWebTrialRecord.evaluation_id,
                    MatraixWebTrialRecord.persona_position,
                )
            )
        )
        .scalars()
        .all()
    )


def _verify_trial_rows(
    record: MatraixWebEvaluationRecord,
    trials: tuple[MatraixWebTrialRecord, ...],
) -> None:
    if len(trials) != record.persona_count:
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} has incomplete trials")
    if tuple(trial.persona_position for trial in trials) != tuple(range(record.persona_count)):
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} trial positions are incomplete")
    if len({trial.persona_id for trial in trials}) != len(trials):
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} contains duplicate Personas")
    for trial in trials:
        _verify_trial_identity(trial, record)


def _summary(
    record: MatraixWebEvaluationRecord,
    trials: tuple[MatraixWebTrialRecord, ...],
) -> MatraixWebEvaluationSummary:
    cohort = verify_web_evaluation_record(record)
    _verify_trial_rows(record, trials)
    statuses = tuple(trial.status for trial in trials)
    return MatraixWebEvaluationSummary(
        id=record.id,
        status=_status(statuses),
        created_at=record.created_at,
        task=build_web_task(),
        cohort=cohort,
        trial_count=len(trials),
        succeeded_trial_count=sum(status == "succeeded" for status in statuses),
        failed_trial_count=sum(status == "failed" for status in statuses),
        model_name=record.model_name,
        web_config_sha256=record.web_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        evaluation_sha256=record.evaluation_sha256,
        retry_of_evaluation_id=record.retry_of_evaluation_id,
        retry_of_evaluation_sha256=record.retry_of_evaluation_sha256,
        attempt_number=record.attempt_number,
    )


async def _load_pages(
    session: AsyncSession,
    trial_ids: tuple[UUID, ...],
) -> dict[UUID, tuple[WebPageObservation, ...]]:
    if not trial_ids:
        return {}
    page_records = tuple(
        (
            await session.execute(
                select(MatraixWebPageRecord)
                .where(MatraixWebPageRecord.trial_id.in_(trial_ids))
                .order_by(MatraixWebPageRecord.trial_id, MatraixWebPageRecord.position)
            )
        )
        .scalars()
        .all()
    )
    quote_records = tuple(
        (
            await session.execute(
                select(MatraixWebQuoteRecord)
                .where(MatraixWebQuoteRecord.trial_id.in_(trial_ids))
                .order_by(MatraixWebQuoteRecord.trial_id, MatraixWebQuoteRecord.position)
            )
        )
        .scalars()
        .all()
    )
    quotes_by_page: dict[tuple[UUID, int], list[MatraixWebQuoteRecord]] = defaultdict(list)
    for quote in quote_records:
        quotes_by_page[(quote.trial_id, quote.page_position)].append(quote)
    pages_by_trial: dict[UUID, list[WebPageObservation]] = defaultdict(list)
    for page_record in page_records:
        pages_by_trial[page_record.trial_id].append(
            _page(
                page_record.trial_id,
                page_record,
                tuple(quotes_by_page[(page_record.trial_id, page_record.position)]),
            )
        )
    return {trial_id: tuple(pages_by_trial[trial_id]) for trial_id in trial_ids}


async def _detail(
    session: AsyncSession,
    record: MatraixWebEvaluationRecord,
) -> MatraixWebEvaluationDetail:
    trials = await _load_trial_records(session, (record.id,))
    summary = _summary(record, trials)
    pages = await _load_pages(session, tuple(trial.id for trial in trials))
    full_trials = tuple(_trial(trial, record, pages[trial.id]) for trial in trials)
    trial_summaries = tuple(
        MatraixWebTrialSummary(
            id=trial.id,
            status=trial.status,
            persona=trial.persona,
            trial_sha256=trial.trial_sha256,
            created_at=trial.created_at,
            started_at=trial.started_at,
            completed_at=trial.completed_at,
            observed_page_count=len(trial.pages),
            observed_quote_count=sum(len(page.quotes) for page in trial.pages),
            selected_quote_id=(
                trial.result.decision_subject_id if trial.result is not None else None
            ),
            error=trial.error,
        )
        for trial in full_trials
    )
    return MatraixWebEvaluationDetail(
        **summary.model_dump(mode="python"),
        trials=trial_summaries,
    )


async def _create_web_evaluation_attempt(
    session: AsyncSession,
    cohort_detail: CohortDetail,
    model_name: str,
    config_sha256: str,
    retry_of_evaluation_id: UUID | None,
    retry_of_evaluation_sha256: str | None,
    attempt_number: int,
) -> MatraixWebEvaluationRecord:
    task = build_web_task()
    cohort = _cohort_ref(cohort_detail)
    digest = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.executor_spec_sha256,
        cohort,
        model_name,
        config_sha256,
        retry_of_evaluation_sha256,
        attempt_number,
    )
    await _lock_content(session, digest)
    existing = await session.scalar(
        select(MatraixWebEvaluationRecord).where(
            MatraixWebEvaluationRecord.evaluation_sha256 == digest
        )
    )
    if existing is not None:
        return existing
    created_at = datetime.now(UTC)
    evaluation = MatraixWebEvaluationRecord(
        id=uuid4(),
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        cohort_title=cohort.title,
        dataset_sha256=cohort.dataset_sha256,
        persona_count=cohort.persona_count,
        task_id=task.task_id,
        task_version=task.version,
        task_schema_version=task.schema_version,
        task_spec_sha256=task.task_spec_sha256,
        executor_schema_version=task.executor_schema_version,
        executor_spec_sha256=task.executor_spec_sha256,
        model_name=model_name,
        web_config_sha256=config_sha256,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        evaluation_sha256=digest,
        retry_of_evaluation_id=retry_of_evaluation_id,
        retry_of_evaluation_sha256=retry_of_evaluation_sha256,
        attempt_number=attempt_number,
        created_at=created_at,
        input_sealed_at=None,
    )
    session.add(evaluation)
    await session.flush()
    for member in cohort_detail.members:
        persona = _persona_ref(member)
        session.add(
            MatraixWebTrialRecord(
                id=uuid4(),
                evaluation_id=evaluation.id,
                persona_position=persona.position,
                persona_id=persona.id,
                persona_external_id=persona.persona_id,
                persona_display_name=persona.display_name,
                persona_profile_sha256=persona.profile_sha256,
                trial_sha256=calculate_trial_sha256(digest, persona),
                status="queued",
                created_at=created_at,
            )
        )
    await session.flush()
    evaluation.input_sealed_at = created_at
    await session.flush()
    return evaluation


async def create_web_evaluation(
    session: AsyncSession,
    request: MatraixWebEvaluationCreateRequest,
) -> MatraixWebEvaluationDetail:
    if request.task_id != TASK_ID or request.task_version != TASK_VERSION:
        raise MatraixWebSelectionError("unsupported fixed MatrAIx Web task")
    cohort_detail = await get_cohort(session, request.cohort_id)
    if cohort_detail.persona_count > 4:
        raise MatraixWebSelectionError(
            f"cohort contains {cohort_detail.persona_count} personas; Web supports at most 4"
        )
    model_name, config_sha256 = await _live_config(session)
    evaluation = await _create_web_evaluation_attempt(
        session,
        cohort_detail,
        model_name,
        config_sha256,
        None,
        None,
        1,
    )
    detail = await _detail(session, evaluation)
    await session.commit()
    return detail


async def retry_web_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixWebEvaluationDetail:
    parent = await session.get(MatraixWebEvaluationRecord, evaluation_id)
    if parent is None or parent.input_sealed_at is None:
        raise MatraixWebEvaluationNotFoundError(
            f"MatrAIx Web evaluation {evaluation_id} was not found"
        )
    existing = await session.scalar(
        select(MatraixWebEvaluationRecord).where(
            MatraixWebEvaluationRecord.retry_of_evaluation_id == parent.id
        )
    )
    if existing is not None:
        return await _detail(session, existing)
    trials = await _load_trial_records(session, (parent.id,))
    statuses = tuple(trial.status for trial in trials)
    if any(status in ("queued", "running") for status in statuses) or not any(
        status == "failed" for status in statuses
    ):
        raise MatraixWebSelectionError(
            "only a terminal Web evaluation containing a failed trial can be retried"
        )
    if parent.attempt_number >= 5:
        raise MatraixWebSelectionError("Web evaluation retry limit of 5 attempts was reached")
    frozen_cohort = verify_web_evaluation_record(parent)
    cohort_detail = await get_cohort(session, parent.cohort_id)
    if _cohort_ref(cohort_detail) != frozen_cohort:
        raise RuntimeError(f"MatrAIx Web evaluation {parent.id} Cohort integrity mismatch")
    model_name, config_sha256 = await _live_config(session)
    evaluation = await _create_web_evaluation_attempt(
        session,
        cohort_detail,
        model_name,
        config_sha256,
        parent.id,
        parent.evaluation_sha256,
        parent.attempt_number + 1,
    )
    detail = await _detail(session, evaluation)
    await session.commit()
    return detail


async def list_web_evaluations(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> MatraixWebEvaluationsResponse:
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(MatraixWebEvaluationRecord)
            .where(MatraixWebEvaluationRecord.input_sealed_at.is_not(None))
        )
        or 0
    )
    if total == 0:
        return MatraixWebEvaluationsResponse(items=(), page=1, page_size=page_size, total=0)
    if (page - 1) * page_size >= total:
        raise MatraixWebSelectionError("requested Web evaluation page starts beyond total")
    records = tuple(
        (
            await session.execute(
                select(MatraixWebEvaluationRecord)
                .where(MatraixWebEvaluationRecord.input_sealed_at.is_not(None))
                .order_by(
                    MatraixWebEvaluationRecord.created_at.desc(),
                    MatraixWebEvaluationRecord.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    trial_records = await _load_trial_records(session, tuple(record.id for record in records))
    by_evaluation: dict[UUID, list[MatraixWebTrialRecord]] = defaultdict(list)
    for trial in trial_records:
        by_evaluation[trial.evaluation_id].append(trial)
    return MatraixWebEvaluationsResponse(
        items=tuple(_summary(record, tuple(by_evaluation[record.id])) for record in records),
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_web_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixWebEvaluationDetail:
    record = await session.scalar(
        select(MatraixWebEvaluationRecord).where(
            MatraixWebEvaluationRecord.id == evaluation_id,
            MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixWebEvaluationNotFoundError(
            f"MatrAIx Web evaluation {evaluation_id} was not found"
        )
    return await _detail(session, record)


async def get_web_evaluation_progress(
    session: AsyncSession,
    evaluation_id: UUID,
) -> ParentProgress:
    record = await session.scalar(
        select(MatraixWebEvaluationRecord).where(
            MatraixWebEvaluationRecord.id == evaluation_id,
            MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
        )
    )
    if record is None:
        raise MatraixWebEvaluationNotFoundError(
            f"MatrAIx Web evaluation {evaluation_id} was not found"
        )
    trial_records = await _load_trial_records(session, (record.id,))
    trial_ids = tuple(trial.id for trial in trial_records)
    page_count = await session.scalar(
        select(func.count())
        .select_from(MatraixWebPageRecord)
        .where(MatraixWebPageRecord.trial_id.in_(trial_ids))
    )
    quote_count = await session.scalar(
        select(func.count())
        .select_from(MatraixWebQuoteRecord)
        .where(MatraixWebQuoteRecord.trial_id.in_(trial_ids))
    )
    if page_count is None or quote_count is None:
        raise RuntimeError(f"MatrAIx Web evaluation {record.id} event count is unavailable")
    return build_parent_progress(
        record.id,
        record.attempt_number,
        parse_parent_progress_statuses(tuple(trial.status for trial in trial_records)),
        page_count + quote_count,
        datetime.now(UTC),
    )


async def get_web_trial(session: AsyncSession, trial_id: UUID) -> MatraixWebTrial:
    record = await session.get(MatraixWebTrialRecord, trial_id)
    if record is None:
        raise MatraixWebTrialNotFoundError(f"MatrAIx Web trial {trial_id} was not found")
    evaluation = await session.scalar(
        select(MatraixWebEvaluationRecord).where(
            MatraixWebEvaluationRecord.id == record.evaluation_id,
            MatraixWebEvaluationRecord.input_sealed_at.is_not(None),
        )
    )
    if evaluation is None:
        raise RuntimeError(f"MatrAIx Web trial {trial_id} references a missing sealed parent")
    pages = await _load_pages(session, (trial_id,))
    return _trial(record, evaluation, pages[trial_id])


async def get_web_screenshot(
    session: AsyncSession,
    artifact_root: Path,
    trial_id: UUID,
    page_position: int,
) -> tuple[Path, str]:
    page = await session.get(
        MatraixWebPageRecord,
        {"trial_id": trial_id, "position": page_position},
    )
    if page is None:
        raise MatraixWebScreenshotNotFoundError(
            f"MatrAIx Web screenshot {trial_id}/{page_position} was not found"
        )
    path = artifact_root / str(trial_id) / f"page-{page_position}.png"
    if not path.is_file():
        raise MatraixWebUnavailableError(
            f"MatrAIx Web screenshot artifact {trial_id}/{page_position} is unavailable"
        )
    digest = await asyncio.to_thread(lambda: sha256(path.read_bytes()).hexdigest())
    if digest != page.screenshot_sha256:
        raise MatraixWebUnavailableError(
            "MatrAIx Web screenshot artifact "
            f"{trial_id}/{page_position} failed integrity verification"
        )
    return path, page.screenshot_sha256


async def get_web_readiness(session: AsyncSession) -> MatraixWebReadiness:
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
                )
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.web_model_name,
            heartbeat.web_config_sha256,
            heartbeat.web_prompt_schema_version,
            heartbeat.web_executor_schema_version,
            heartbeat.web_executor_spec_sha256,
        )
        for heartbeat in heartbeats
        if heartbeat.platform_runtime_ready
        and heartbeat.semantic_runtime_ready
        and heartbeat.web_runtime_ready
    }
    conflict = len(configs) > 1
    complete = next(iter(configs)) if len(configs) == 1 else None
    ready = bool(heartbeats) and complete is not None and not conflict
    if ready and complete is not None:
        model_name, config_sha256, prompt, executor_schema, executor_sha = complete
        if (
            model_name is None
            or config_sha256 is None
            or prompt != PROMPT_SCHEMA_VERSION
            or executor_schema != EXECUTOR_SCHEMA_VERSION
            or executor_sha != EXECUTOR_SPEC_SHA256
        ):
            raise RuntimeError("web-ready worker persisted incomplete configuration")
    else:
        model_name = None
        config_sha256 = None
        prompt = None
    limitations = READINESS_LIMITATIONS
    if conflict:
        limitations += ("Live Web workers disagree on model or executor configuration.",)
    elif not ready:
        limitations += (
            "No live worker currently exposes a complete probed Web execution configuration.",
        )
    return MatraixWebReadiness(
        engine="matraix-web-playwright",
        runner_version=RUNNER_VERSION,
        worker_online=bool(heartbeats),
        live_worker_count=len(heartbeats),
        web_runtime_ready=ready,
        configuration_conflict=conflict,
        model_name=model_name,
        web_config_sha256=config_sha256,
        prompt_schema_version=prompt,
        task=build_web_task(),
        limitations=limitations,
    )
