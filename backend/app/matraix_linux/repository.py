"""Queue and verify the fixed MatrAIx Linux artifact task."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.matraix_linux.contracts import (
    LinuxArtifactHashes,
    LinuxCohortRef,
    LinuxPersonaRef,
    LinuxTrialError,
    LinuxTrialResult,
    MatraixLinuxEvaluation,
    MatraixLinuxEvaluationsResponse,
    MatraixLinuxReadiness,
    MatraixLinuxTask,
    MatraixLinuxTasksResponse,
    MatraixLinuxTrial,
    MatraixLinuxTrialCreateRequest,
    MatraixLinuxTrialsResponse,
)
from app.matraix_linux.errors import (
    MatraixLinuxEvaluationNotFoundError,
    MatraixLinuxSelectionError,
    MatraixLinuxTrialNotFoundError,
    MatraixLinuxUnavailableError,
)
from app.matraix_linux.hashing import (
    calculate_evaluation_sha256,
    calculate_result_sha256,
    calculate_trial_sha256,
)
from app.matraix_linux.models import MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord
from app.matraix_linux.tasks import (
    PROMPT_SCHEMA_VERSION,
    RUNNER_SCHEMA_VERSION,
    RUNNER_SPEC_SHA256,
    RUNNER_VERSION,
    TASK_ID,
    TASK_VERSION,
    build_linux_task,
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
    "Readiness requires a recent worker heartbeat after the provider tool-call probe and "
    "the fixed Linux artifact runner identity probe.",
    "The runner only writes four allowlisted files for the fixed source sample; it exposes "
    "no shell, arbitrary path, Docker socket, desktop Computer Use, or Harbor runtime.",
    "Persona feedback is synthetic model output, not human research or benchmark reward.",
)


def list_linux_tasks() -> MatraixLinuxTasksResponse:
    task = build_linux_task()
    return MatraixLinuxTasksResponse(items=(task,), total=1)


def _cohort_ref(cohort: CohortDetail) -> LinuxCohortRef:
    return LinuxCohortRef(
        id=cohort.id,
        title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset.dataset_sha256,
    )


def _persona_ref(member: CohortMember) -> LinuxPersonaRef:
    return LinuxPersonaRef(
        id=member.persona.id,
        position=member.position,
        persona_id=member.persona.persona_id,
        display_name=member.persona.display_name,
        profile_sha256=member.persona.profile_sha256,
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
                    SimulationWorkerHeartbeatRecord.linux_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.linux_runner_schema_version
                    == RUNNER_SCHEMA_VERSION,
                    SimulationWorkerHeartbeatRecord.linux_runner_spec_sha256 == RUNNER_SPEC_SHA256,
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (
            heartbeat.linux_model_name,
            heartbeat.linux_config_sha256,
            heartbeat.linux_prompt_schema_version,
        )
        for heartbeat in heartbeats
    }
    if not configs:
        raise MatraixLinuxUnavailableError(
            "MatrAIx Linux execution is unavailable because no correctly pinned worker "
            "reported a complete runner/model configuration in the last 30 seconds"
        )
    if len(configs) != 1:
        raise MatraixLinuxUnavailableError(
            "live MatrAIx Linux workers disagree on execution configuration"
        )
    model_name, config_sha256, prompt = next(iter(configs))
    if model_name is None or config_sha256 is None or prompt != PROMPT_SCHEMA_VERSION:
        raise RuntimeError("linux-ready worker persisted an incomplete configuration")
    return model_name, config_sha256


def verify_linux_trial_record(
    record: MatraixLinuxTrialRecord,
) -> tuple[MatraixLinuxTask, LinuxCohortRef, LinuxPersonaRef]:
    task = build_linux_task()
    cohort = LinuxCohortRef(
        id=record.cohort_id,
        title=record.cohort_title,
        cohort_sha256=record.cohort_sha256,
        dataset_sha256=record.dataset_sha256,
    )
    persona = LinuxPersonaRef(
        id=record.persona_id,
        position=record.persona_position,
        persona_id=record.persona_external_id,
        display_name=record.persona_display_name,
        profile_sha256=record.persona_profile_sha256,
    )
    if (
        record.task_id != task.task_id
        or record.task_version != task.version
        or record.task_schema_version != task.schema_version
        or record.task_spec_sha256 != task.task_spec_sha256
        or record.runner_schema_version != task.runner_schema_version
        or record.runner_spec_sha256 != task.runner_spec_sha256
        or record.prompt_schema_version != PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError(f"MatrAIx Linux trial {record.id} task integrity mismatch")
    expected = calculate_trial_sha256(
        record.task_spec_sha256,
        record.runner_spec_sha256,
        cohort,
        persona,
        record.model_name,
        record.linux_config_sha256,
        record.prompt_schema_version,
        record.retry_of_trial_sha256,
        record.attempt_number,
    )
    if record.trial_sha256 != expected:
        raise RuntimeError(f"MatrAIx Linux trial {record.id} integrity mismatch")
    return task, cohort, persona


def _result(record: MatraixLinuxTrialRecord) -> LinuxTrialResult | None:
    if record.status != "succeeded":
        return None
    required = (
        record.result_runner_version,
        record.result_artifact_sha256,
        record.result_cleaned_list_sha256,
        record.result_submission_sha256,
        record.result_feedback_sha256,
        record.result_verifier_sha256,
        record.result_sha256,
        record.result_reason,
        record.result_need_satisfaction,
        record.result_preference_satisfaction,
        record.result_rating,
        record.result_feedback_reason,
    )
    if any(value is None for value in required):
        raise RuntimeError(f"MatrAIx Linux trial {record.id} has an incomplete result")
    files = LinuxArtifactHashes(
        cleaned_list_csv=str(record.result_cleaned_list_sha256),
        submission_json=str(record.result_submission_sha256),
        user_feedback_json=str(record.result_feedback_sha256),
        verifier_json=str(record.result_verifier_sha256),
    )
    expected = calculate_result_sha256(
        record.trial_sha256,
        str(record.result_artifact_sha256),
        files,
        str(record.result_reason),
        str(record.result_need_satisfaction),
        str(record.result_preference_satisfaction),
        int(record.result_rating),
        str(record.result_feedback_reason),
    )
    if record.result_sha256 != expected:
        raise RuntimeError(f"MatrAIx Linux trial {record.id} result integrity mismatch")
    return LinuxTrialResult(
        runner_version="1.0.0",
        model_name=record.model_name,
        linux_config_sha256=record.linux_config_sha256,
        prompt_schema_version="matraix-linux-note-to-csv/v1",
        runner_schema_version="matraix-linux-artifact-runner/v1",
        runner_spec_sha256=record.runner_spec_sha256,
        verifier_passed=True,
        rows_written=3,
        artifact_sha256=str(record.result_artifact_sha256),
        file_sha256=files,
        result_sha256=expected,
        reason=str(record.result_reason),
        need_constraint_satisfaction=str(record.result_need_satisfaction),
        personal_preference_satisfaction=str(record.result_preference_satisfaction),
        overall_experience_rating=int(record.result_rating),
        feedback_reason=str(record.result_feedback_reason),
    )


def _trial(record: MatraixLinuxTrialRecord) -> MatraixLinuxTrial:
    task, cohort, persona = verify_linux_trial_record(record)
    error = None
    if record.status == "failed":
        if record.error_code is None or record.error_message is None:
            raise RuntimeError(f"MatrAIx Linux trial {record.id} has an incomplete error")
        error = LinuxTrialError(code=record.error_code, message=record.error_message)
    return MatraixLinuxTrial(
        id=record.id,
        status=record.status,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        task=task,
        cohort=cohort,
        persona=persona,
        trial_sha256=record.trial_sha256,
        retry_of_trial_id=record.retry_of_trial_id,
        retry_of_trial_sha256=record.retry_of_trial_sha256,
        attempt_number=record.attempt_number,
        result=_result(record),
        error=error,
    )


def verify_linux_evaluation_record(
    evaluation: MatraixLinuxEvaluationRecord,
    trial: MatraixLinuxTrialRecord,
) -> None:
    if evaluation.input_sealed_at is None:
        raise RuntimeError(f"MatrAIx Linux evaluation {evaluation.id} is not sealed")
    if evaluation.trial_id != trial.id or evaluation.trial_sha256 != trial.trial_sha256:
        raise RuntimeError(f"MatrAIx Linux evaluation {evaluation.id} trial identity mismatch")
    expected = calculate_evaluation_sha256(trial.id, trial.trial_sha256)
    if evaluation.evaluation_sha256 != expected:
        raise RuntimeError(f"MatrAIx Linux evaluation {evaluation.id} integrity mismatch")
    verify_linux_trial_record(trial)


def _evaluation(
    evaluation: MatraixLinuxEvaluationRecord,
    trial: MatraixLinuxTrialRecord,
) -> MatraixLinuxEvaluation:
    verify_linux_evaluation_record(evaluation, trial)
    if evaluation.input_sealed_at is None:
        raise RuntimeError(f"MatrAIx Linux evaluation {evaluation.id} is not sealed")
    public_trial = _trial(trial)
    return MatraixLinuxEvaluation(
        id=evaluation.id,
        status=public_trial.status,
        execution_kind="linux_artifact_runner",
        registry_eligibility="sealed_parent",
        created_at=evaluation.created_at,
        sealed_at=evaluation.input_sealed_at,
        evaluation_sha256=evaluation.evaluation_sha256,
        trial=public_trial,
    )


async def _create_linux_trial_attempt(
    session: AsyncSession,
    task: MatraixLinuxTask,
    cohort: LinuxCohortRef,
    persona: LinuxPersonaRef,
    model_name: str,
    config_sha256: str,
    retry_of_trial_id: UUID | None,
    retry_of_trial_sha256: str | None,
    attempt_number: int,
) -> MatraixLinuxTrialRecord:
    digest = calculate_trial_sha256(
        task.task_spec_sha256,
        task.runner_spec_sha256,
        cohort,
        persona,
        model_name,
        config_sha256,
        PROMPT_SCHEMA_VERSION,
        retry_of_trial_sha256,
        attempt_number,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(MatraixLinuxTrialRecord).where(MatraixLinuxTrialRecord.trial_sha256 == digest)
    )
    if existing is not None:
        verify_linux_trial_record(existing)
        return existing
    record = MatraixLinuxTrialRecord(
        id=uuid4(),
        cohort_id=cohort.id,
        cohort_title=cohort.title,
        cohort_sha256=cohort.cohort_sha256,
        dataset_sha256=cohort.dataset_sha256,
        persona_id=persona.id,
        persona_position=persona.position,
        persona_external_id=persona.persona_id,
        persona_display_name=persona.display_name,
        persona_profile_sha256=persona.profile_sha256,
        task_id=task.task_id,
        task_version=task.version,
        task_schema_version=task.schema_version,
        task_spec_sha256=task.task_spec_sha256,
        runner_schema_version=task.runner_schema_version,
        runner_spec_sha256=task.runner_spec_sha256,
        model_name=model_name,
        linux_config_sha256=config_sha256,
        prompt_schema_version=PROMPT_SCHEMA_VERSION,
        trial_sha256=digest,
        retry_of_trial_id=retry_of_trial_id,
        retry_of_trial_sha256=retry_of_trial_sha256,
        attempt_number=attempt_number,
        status="queued",
        created_at=datetime.now(UTC),
    )
    session.add(record)
    await session.flush()
    verify_linux_trial_record(record)
    return record


async def _ensure_linux_trial_record(
    session: AsyncSession,
    request: MatraixLinuxTrialCreateRequest,
) -> MatraixLinuxTrialRecord:
    if request.task_id != TASK_ID or request.task_version != TASK_VERSION:
        raise MatraixLinuxSelectionError("unsupported fixed MatrAIx Linux task")
    cohort_detail = await get_cohort(session, request.cohort_id)
    member = next(
        (item for item in cohort_detail.members if item.persona.id == request.persona_id),
        None,
    )
    if member is None:
        raise MatraixLinuxSelectionError(
            f"Persona {request.persona_id} is not a member of Cohort {request.cohort_id}"
        )
    model_name, config_sha256 = await _live_config(session)
    return await _create_linux_trial_attempt(
        session,
        build_linux_task(),
        _cohort_ref(cohort_detail),
        _persona_ref(member),
        model_name,
        config_sha256,
        None,
        None,
        1,
    )


async def create_linux_trial(
    session: AsyncSession,
    request: MatraixLinuxTrialCreateRequest,
) -> MatraixLinuxTrial:
    record = await _ensure_linux_trial_record(session, request)
    result = _trial(record)
    await session.commit()
    return result


async def _create_linux_evaluation_record(
    session: AsyncSession,
    trial: MatraixLinuxTrialRecord,
) -> MatraixLinuxEvaluationRecord:
    digest = calculate_evaluation_sha256(trial.id, trial.trial_sha256)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(MatraixLinuxEvaluationRecord).where(
            MatraixLinuxEvaluationRecord.evaluation_sha256 == digest
        )
    )
    if existing is not None:
        return existing
    created_at = datetime.now(UTC)
    evaluation = MatraixLinuxEvaluationRecord(
        id=uuid4(),
        trial_id=trial.id,
        trial_sha256=trial.trial_sha256,
        evaluation_sha256=digest,
        created_at=created_at,
        input_sealed_at=None,
    )
    session.add(evaluation)
    await session.flush()
    evaluation.input_sealed_at = created_at
    await session.flush()
    return evaluation


async def create_linux_evaluation(
    session: AsyncSession,
    request: MatraixLinuxTrialCreateRequest,
) -> MatraixLinuxEvaluation:
    trial = await _ensure_linux_trial_record(session, request)
    evaluation = await _create_linux_evaluation_record(session, trial)
    result = _evaluation(evaluation, trial)
    await session.commit()
    return result


async def retry_linux_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixLinuxEvaluation:
    row = (
        await session.execute(
            select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
            .join(
                MatraixLinuxTrialRecord,
                MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
            )
            .where(
                MatraixLinuxEvaluationRecord.id == evaluation_id,
                MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise MatraixLinuxEvaluationNotFoundError(
            f"MatrAIx Linux evaluation {evaluation_id} was not found"
        )
    parent_evaluation, parent_trial = row
    existing_row = (
        await session.execute(
            select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
            .join(
                MatraixLinuxTrialRecord,
                MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
            )
            .where(MatraixLinuxTrialRecord.retry_of_trial_id == parent_trial.id)
        )
    ).one_or_none()
    if existing_row is not None:
        existing_evaluation, existing_trial = existing_row
        return _evaluation(existing_evaluation, existing_trial)
    if parent_trial.status != "failed":
        raise MatraixLinuxSelectionError("only a failed Linux evaluation can be retried")
    if parent_trial.attempt_number >= 5:
        raise MatraixLinuxSelectionError("Linux evaluation retry limit of 5 attempts was reached")
    task, frozen_cohort, frozen_persona = verify_linux_trial_record(parent_trial)
    cohort_detail = await get_cohort(session, parent_trial.cohort_id)
    member = next(
        (item for item in cohort_detail.members if item.persona.id == parent_trial.persona_id),
        None,
    )
    if member is None:
        raise RuntimeError(f"MatrAIx Linux trial {parent_trial.id} Persona is no longer present")
    cohort = _cohort_ref(cohort_detail)
    persona = _persona_ref(member)
    if cohort != frozen_cohort or persona != frozen_persona:
        raise RuntimeError(f"MatrAIx Linux trial {parent_trial.id} frozen input mismatch")
    model_name, config_sha256 = await _live_config(session)
    trial = await _create_linux_trial_attempt(
        session,
        task,
        cohort,
        persona,
        model_name,
        config_sha256,
        parent_trial.id,
        parent_trial.trial_sha256,
        parent_trial.attempt_number + 1,
    )
    evaluation = await _create_linux_evaluation_record(session, trial)
    result = _evaluation(evaluation, trial)
    await session.commit()
    return result


async def list_linux_trials(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> MatraixLinuxTrialsResponse:
    total = int(
        await session.scalar(select(func.count()).select_from(MatraixLinuxTrialRecord)) or 0
    )
    if total == 0:
        return MatraixLinuxTrialsResponse(items=(), page=1, page_size=page_size, total=0)
    if (page - 1) * page_size >= total:
        raise MatraixLinuxSelectionError("requested Linux trial page starts beyond total")
    records = tuple(
        (
            await session.execute(
                select(MatraixLinuxTrialRecord)
                .order_by(
                    MatraixLinuxTrialRecord.created_at.desc(), MatraixLinuxTrialRecord.id.asc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return MatraixLinuxTrialsResponse(
        items=tuple(_trial(record) for record in records),
        page=page,
        page_size=page_size,
        total=total,
    )


async def list_linux_evaluations(
    session: AsyncSession,
    page: int,
    page_size: int,
) -> MatraixLinuxEvaluationsResponse:
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(MatraixLinuxEvaluationRecord)
            .where(MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None))
        )
        or 0
    )
    if total == 0:
        return MatraixLinuxEvaluationsResponse(items=(), page=1, page_size=page_size, total=0)
    if (page - 1) * page_size >= total:
        raise MatraixLinuxSelectionError("requested Linux evaluation page starts beyond total")
    rows = tuple(
        (
            await session.execute(
                select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
                .join(
                    MatraixLinuxTrialRecord,
                    MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
                )
                .where(MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None))
                .order_by(
                    MatraixLinuxEvaluationRecord.created_at.desc(),
                    MatraixLinuxEvaluationRecord.id.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return MatraixLinuxEvaluationsResponse(
        items=tuple(_evaluation(evaluation, trial) for evaluation, trial in rows),
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_linux_trial(session: AsyncSession, trial_id: UUID) -> MatraixLinuxTrial:
    record = await session.get(MatraixLinuxTrialRecord, trial_id)
    if record is None:
        raise MatraixLinuxTrialNotFoundError(f"MatrAIx Linux trial {trial_id} was not found")
    return _trial(record)


async def get_linux_evaluation(
    session: AsyncSession,
    evaluation_id: UUID,
) -> MatraixLinuxEvaluation:
    row = (
        await session.execute(
            select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
            .join(
                MatraixLinuxTrialRecord,
                MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
            )
            .where(
                MatraixLinuxEvaluationRecord.id == evaluation_id,
                MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise MatraixLinuxEvaluationNotFoundError(
            f"MatrAIx Linux evaluation {evaluation_id} was not found"
        )
    evaluation, trial = row
    return _evaluation(evaluation, trial)


async def get_linux_evaluation_progress(
    session: AsyncSession,
    evaluation_id: UUID,
) -> ParentProgress:
    row = (
        await session.execute(
            select(MatraixLinuxEvaluationRecord, MatraixLinuxTrialRecord)
            .join(
                MatraixLinuxTrialRecord,
                MatraixLinuxTrialRecord.id == MatraixLinuxEvaluationRecord.trial_id,
            )
            .where(
                MatraixLinuxEvaluationRecord.id == evaluation_id,
                MatraixLinuxEvaluationRecord.input_sealed_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise MatraixLinuxEvaluationNotFoundError(
            f"MatrAIx Linux evaluation {evaluation_id} was not found"
        )
    evaluation, trial = row
    event_count = 1 if trial.status in ("succeeded", "failed") else 0
    return build_parent_progress(
        evaluation.id,
        trial.attempt_number,
        parse_parent_progress_statuses((trial.status,)),
        event_count,
        datetime.now(UTC),
    )


async def get_linux_readiness(session: AsyncSession) -> MatraixLinuxReadiness:
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
            heartbeat.linux_model_name,
            heartbeat.linux_config_sha256,
            heartbeat.linux_prompt_schema_version,
            heartbeat.linux_runner_schema_version,
            heartbeat.linux_runner_spec_sha256,
        )
        for heartbeat in heartbeats
        if heartbeat.platform_runtime_ready
        and heartbeat.semantic_runtime_ready
        and heartbeat.linux_runtime_ready
    }
    conflict = len(configs) > 1
    complete = next(iter(configs)) if len(configs) == 1 else None
    ready = complete is not None and not conflict
    if ready and complete is not None:
        model_name, config_sha256, prompt, runner_schema, runner_sha = complete
        if (
            model_name is None
            or config_sha256 is None
            or prompt != PROMPT_SCHEMA_VERSION
            or runner_schema != RUNNER_SCHEMA_VERSION
            or runner_sha != RUNNER_SPEC_SHA256
        ):
            raise RuntimeError("linux-ready worker persisted incomplete configuration")
    else:
        model_name = None
        config_sha256 = None
        prompt = None
    limitations = READINESS_LIMITATIONS
    if conflict:
        limitations += ("Live Linux workers disagree on model or runner configuration.",)
    elif not ready:
        limitations += ("No live worker currently exposes a complete probed Linux configuration.",)
    return MatraixLinuxReadiness(
        engine="matraix-linux-artifact",
        runner_version=RUNNER_VERSION,
        worker_online=bool(heartbeats),
        live_worker_count=len(heartbeats),
        linux_runtime_ready=ready,
        configuration_conflict=conflict,
        model_name=model_name,
        linux_config_sha256=config_sha256,
        prompt_schema_version=prompt,
        task=build_linux_task(),
        limitations=limitations,
    )


async def get_linux_artifact(
    session: AsyncSession,
    artifact_root: Path,
    trial_id: UUID,
    artifact_name: str,
) -> tuple[Path, str]:
    trial = await get_linux_trial(session, trial_id)
    if trial.result is None:
        raise MatraixLinuxUnavailableError(
            f"MatrAIx Linux trial {trial_id} has no sealed artifacts"
        )
    expected = {
        "cleaned_list.csv": trial.result.file_sha256.cleaned_list_csv,
        "submission.json": trial.result.file_sha256.submission_json,
        "user_feedback.json": trial.result.file_sha256.user_feedback_json,
        "verifier.json": trial.result.file_sha256.verifier_json,
    }.get(artifact_name)
    if expected is None:
        raise MatraixLinuxSelectionError(f"unsupported Linux artifact {artifact_name!r}")
    path = artifact_root / str(trial_id) / artifact_name
    if not path.is_file():
        raise MatraixLinuxUnavailableError(
            f"MatrAIx Linux artifact {trial_id}/{artifact_name} is unavailable"
        )
    from hashlib import sha256

    actual = sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise MatraixLinuxUnavailableError(
            f"MatrAIx Linux artifact {trial_id}/{artifact_name} failed integrity verification"
        )
    return path, expected
