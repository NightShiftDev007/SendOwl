"""Durable Harbor job lifecycle for Project-bound Chat/Web/App evaluations."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research_evaluations.bundles import verified_research_evaluation_scope
from app.research_evaluations.contracts import (
    ResearchEvaluationJob,
    ResearchEvaluationJobCreateRequest,
)
from app.research_evaluations.errors import (
    ResearchEvaluationRetryError,
    ResearchEvaluationScopeError,
)
from app.research_evaluations.hashing import calculate_evaluation_job_sha256
from app.research_evaluations.models import (
    ResearchEvaluationJobRecord,
    ResearchEvaluationTargetRecord,
)


def _detail(record: ResearchEvaluationJobRecord) -> ResearchEvaluationJob:
    return ResearchEvaluationJob(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        cohort_id=record.cohort_id,
        target_id=record.target_id,
        kind=record.kind,
        status=record.status,
        job_sha256=record.job_sha256,
        retry_of_job_id=record.retry_of_job_id,
        retry_of_job_sha256=record.retry_of_job_sha256,
        attempt_number=record.attempt_number,
        remote_run_id=record.remote_run_id,
        trajectory_sha256=record.trajectory_sha256,
        artifact_sha256=record.artifact_sha256,
        verifier_sha256=record.verifier_sha256,
        reward_sha256=record.reward_sha256,
        reward_value=record.reward_value,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_code=record.error_code,
        error_message=record.error_message,
    )


async def create_research_evaluation_job(
    session: AsyncSession,
    request: ResearchEvaluationJobCreateRequest,
) -> ResearchEvaluationJob:
    project, run, cohort = await verified_research_evaluation_scope(
        session, request.research_project_id, request.research_simulation_run_id
    )
    target = await session.get(ResearchEvaluationTargetRecord, request.target_id)
    if (
        target is None
        or target.research_project_id != project.id
        or target.research_simulation_run_id != run.id
        or target.cohort_id != cohort.id
    ):
        raise ResearchEvaluationScopeError(
            "Harbor job target must belong to the selected Project / Run / Cohort"
        )
    digest = calculate_evaluation_job_sha256(
        target.target_sha256,
        project.project_sha256,
        run.run_spec_sha256,
        cohort.cohort_sha256,
        None,
        1,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(ResearchEvaluationJobRecord).where(ResearchEvaluationJobRecord.job_sha256 == digest)
    )
    if existing is not None:
        return _detail(existing)
    now = datetime.now(UTC)
    record = ResearchEvaluationJobRecord(
        id=uuid4(),
        research_project_id=project.id,
        research_simulation_run_id=run.id,
        cohort_id=cohort.id,
        target_id=target.id,
        kind=target.kind,
        status="queued",
        job_sha256=digest,
        retry_of_job_id=None,
        retry_of_job_sha256=None,
        attempt_number=1,
        remote_run_id=None,
        trajectory_json=None,
        trajectory_sha256=None,
        artifact_json=None,
        artifact_sha256=None,
        verifier_json=None,
        verifier_sha256=None,
        reward_json=None,
        reward_sha256=None,
        reward_value=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return _detail(record)


async def retry_research_evaluation_job(
    session: AsyncSession,
    job_id: UUID,
) -> ResearchEvaluationJob:
    parent = (
        await session.execute(
            select(ResearchEvaluationJobRecord)
            .where(ResearchEvaluationJobRecord.id == job_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if parent is None:
        raise ResearchEvaluationScopeError(f"research evaluation job {job_id} was not found")
    existing = await session.scalar(
        select(ResearchEvaluationJobRecord).where(
            ResearchEvaluationJobRecord.retry_of_job_id == parent.id
        )
    )
    if existing is not None:
        return _detail(existing)
    if parent.status != "failed":
        raise ResearchEvaluationRetryError("only a failed Harbor Job can be retried")
    if parent.attempt_number >= 5:
        raise ResearchEvaluationRetryError("Harbor Job retry limit is five attempts")

    project, run, cohort = await verified_research_evaluation_scope(
        session,
        parent.research_project_id,
        parent.research_simulation_run_id,
    )
    target = await session.get(ResearchEvaluationTargetRecord, parent.target_id)
    if (
        target is None
        or target.research_project_id != project.id
        or target.research_simulation_run_id != run.id
        or target.cohort_id != cohort.id
        or parent.cohort_id != cohort.id
    ):
        raise ResearchEvaluationScopeError(
            "Harbor retry target no longer matches the frozen Project / Run / Cohort"
        )
    attempt_number = parent.attempt_number + 1
    digest = calculate_evaluation_job_sha256(
        target.target_sha256,
        project.project_sha256,
        run.run_spec_sha256,
        cohort.cohort_sha256,
        parent.job_sha256,
        attempt_number,
    )
    now = datetime.now(UTC)
    record = ResearchEvaluationJobRecord(
        id=uuid4(),
        research_project_id=project.id,
        research_simulation_run_id=run.id,
        cohort_id=cohort.id,
        target_id=target.id,
        kind=target.kind,
        status="queued",
        job_sha256=digest,
        retry_of_job_id=parent.id,
        retry_of_job_sha256=parent.job_sha256,
        attempt_number=attempt_number,
        remote_run_id=None,
        trajectory_json=None,
        trajectory_sha256=None,
        artifact_json=None,
        artifact_sha256=None,
        verifier_json=None,
        verifier_sha256=None,
        reward_json=None,
        reward_sha256=None,
        reward_value=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return _detail(record)


async def get_research_evaluation_job(session: AsyncSession, job_id: UUID) -> ResearchEvaluationJob:
    record = await session.get(ResearchEvaluationJobRecord, job_id)
    if record is None:
        raise ResearchEvaluationScopeError(f"research evaluation job {job_id} was not found")
    return _detail(record)


async def list_research_evaluation_jobs(
    session: AsyncSession, project_id: UUID, run_id: UUID
) -> tuple[ResearchEvaluationJob, ...]:
    records = tuple(
        (
            await session.execute(
                select(ResearchEvaluationJobRecord)
                .where(
                    ResearchEvaluationJobRecord.research_project_id == project_id,
                    ResearchEvaluationJobRecord.research_simulation_run_id == run_id,
                )
                .order_by(ResearchEvaluationJobRecord.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return tuple(_detail(record) for record in records)


async def claim_research_evaluation_job(
    session: AsyncSession,
) -> ResearchEvaluationJobRecord | None:
    record = (
        await session.execute(
            select(ResearchEvaluationJobRecord)
            .where(ResearchEvaluationJobRecord.status == "queued")
            .order_by(ResearchEvaluationJobRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
    ).scalar_one_or_none()
    if record is None:
        return None
    record.status = "dispatching"
    record.started_at = datetime.now(UTC)
    await session.commit()
    return record


def _digest(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def complete_research_evaluation_job(
    session: AsyncSession,
    job_id: UUID,
    *,
    remote_run_id: str,
    trajectory: dict[str, object],
    artifact: dict[str, object],
    verifier: dict[str, object],
    reward: dict[str, object],
    reward_value: float,
) -> None:
    record = await session.get(ResearchEvaluationJobRecord, job_id)
    if record is None or record.status not in {"dispatching", "running"}:
        raise RuntimeError(f"research evaluation job {job_id} is not active")
    record.status = "succeeded"
    record.remote_run_id = remote_run_id
    record.trajectory_json = trajectory
    record.trajectory_sha256 = _digest(trajectory)
    record.artifact_json = artifact
    record.artifact_sha256 = _digest(artifact)
    record.verifier_json = verifier
    record.verifier_sha256 = _digest(verifier)
    record.reward_json = reward
    record.reward_sha256 = _digest(reward)
    record.reward_value = reward_value
    record.completed_at = datetime.now(UTC)
    await session.commit()


async def fail_research_evaluation_job(
    session: AsyncSession, job_id: UUID, error: Exception
) -> None:
    record = await session.get(ResearchEvaluationJobRecord, job_id)
    if record is None:
        raise RuntimeError(f"research evaluation job {job_id} disappeared")
    record.status = "failed"
    record.completed_at = datetime.now(UTC)
    record.error_code = type(error).__name__.casefold()[:128]
    record.error_message = (str(error) or type(error).__name__)[:2000]
    await session.commit()


async def fail_active_research_evaluation_jobs(
    session: AsyncSession,
    error: Exception,
) -> None:
    records = tuple(
        (
            await session.execute(
                select(ResearchEvaluationJobRecord).where(
                    ResearchEvaluationJobRecord.status.in_(("dispatching", "running"))
                )
            )
        )
        .scalars()
        .all()
    )
    if not records:
        return
    completed_at = datetime.now(UTC)
    error_code = type(error).__name__.casefold()[:128]
    error_message = (str(error) or type(error).__name__)[:2000]
    for record in records:
        record.status = "failed"
        record.completed_at = completed_at
        record.error_code = error_code
        record.error_message = error_message
    await session.commit()
