"""Transactional persistence for stable decision identities and append-only context revisions."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision_threads.contracts import (
    DecisionThreadContextCreate,
    DecisionThreadCreateRequest,
    DecisionThreadDetail,
    DecisionThreadDraftCreateRequest,
    DecisionThreadRevision,
    DecisionThreadsResponse,
    DecisionThreadSummary,
)
from app.decision_threads.errors import DecisionThreadNotFoundError, DecisionThreadSelectionError
from app.decision_threads.models import DecisionThreadRecord, DecisionThreadRevisionRecord
from app.populations.repository import get_cohort
from app.scenarios.repository import get_scenario
from app.semantic_experiments.repository import get_semantic_experiment
from app.world_models.repository import get_world_snapshot


def _revision(record: DecisionThreadRevisionRecord) -> DecisionThreadRevision:
    return DecisionThreadRevision(
        id=record.id,
        version=record.version,
        world_model_id=record.world_model_id,
        world_snapshot_id=record.world_snapshot_id,
        snapshot_sha256=record.snapshot_sha256,
        scenario_id=record.scenario_id,
        scenario_sha256=record.scenario_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        semantic_experiment_id=record.semantic_experiment_id,
        experiment_sha256=record.experiment_sha256,
        created_at=record.created_at,
    )


async def _validated_revision_values(
    session: AsyncSession,
    decision_question: str,
    request: DecisionThreadContextCreate,
) -> tuple[str, str | None, str | None, str | None]:
    snapshot = await get_world_snapshot(
        session,
        request.world_model_id,
        request.world_snapshot_id,
    )
    scenario_sha256: str | None = None
    cohort_sha256: str | None = None
    experiment_sha256: str | None = None
    if request.scenario_id is not None:
        scenario = await get_scenario(session, request.scenario_id)
        if (
            scenario.snapshot.world_model_id != request.world_model_id
            or scenario.snapshot.world_snapshot_id != request.world_snapshot_id
            or scenario.snapshot.snapshot_sha256 != snapshot.snapshot_sha256
        ):
            raise DecisionThreadSelectionError(
                "selected scenario does not reference the decision thread world snapshot"
            )
        if scenario.decision_question != decision_question:
            raise DecisionThreadSelectionError(
                "selected scenario decision_question does not match the decision thread"
            )
        scenario_sha256 = scenario.scenario_sha256
    if request.cohort_id is not None:
        cohort = await get_cohort(session, request.cohort_id)
        cohort_sha256 = cohort.cohort_sha256
    if request.semantic_experiment_id is not None:
        experiment = await get_semantic_experiment(session, request.semantic_experiment_id)
        if experiment.scenario.id != request.scenario_id:
            raise DecisionThreadSelectionError(
                "selected semantic experiment does not reference the selected scenario"
            )
        if experiment.cohort.id != request.cohort_id:
            raise DecisionThreadSelectionError(
                "selected semantic experiment does not reference the selected cohort"
            )
        if experiment.scenario.scenario_sha256 != scenario_sha256:
            raise DecisionThreadSelectionError(
                "selected semantic experiment scenario digest does not match the selected scenario"
            )
        if experiment.cohort.cohort_sha256 != cohort_sha256:
            raise DecisionThreadSelectionError(
                "selected semantic experiment cohort digest does not match the selected cohort"
            )
        experiment_sha256 = experiment.experiment_sha256
    return snapshot.snapshot_sha256, scenario_sha256, cohort_sha256, experiment_sha256


async def _load_detail(
    session: AsyncSession,
    thread: DecisionThreadRecord,
) -> DecisionThreadDetail:
    records = tuple(
        (
            await session.execute(
                select(DecisionThreadRevisionRecord)
                .where(DecisionThreadRevisionRecord.thread_id == thread.id)
                .order_by(DecisionThreadRevisionRecord.version)
            )
        )
        .scalars()
        .all()
    )
    revisions = tuple(_revision(record) for record in records)
    return DecisionThreadDetail(
        id=thread.id,
        title=thread.title,
        decision_question=thread.decision_question,
        created_at=thread.created_at,
        latest_revision=revisions[-1] if revisions else None,
        revisions=revisions,
    )


async def create_decision_thread_draft(
    session: AsyncSession,
    request: DecisionThreadDraftCreateRequest,
) -> DecisionThreadDetail:
    thread = DecisionThreadRecord(
        id=uuid4(),
        title=request.title,
        decision_question=request.decision_question,
        created_at=datetime.now(UTC),
    )
    session.add(thread)
    await session.commit()
    return await _load_detail(session, thread)


async def create_decision_thread(
    session: AsyncSession,
    request: DecisionThreadCreateRequest,
) -> DecisionThreadDetail:
    digests = await _validated_revision_values(session, request.decision_question, request)
    created_at = datetime.now(UTC)
    thread = DecisionThreadRecord(
        id=uuid4(),
        title=request.title,
        decision_question=request.decision_question,
        created_at=created_at,
    )
    revision = DecisionThreadRevisionRecord(
        id=uuid4(),
        thread_id=thread.id,
        version=1,
        world_model_id=request.world_model_id,
        world_snapshot_id=request.world_snapshot_id,
        snapshot_sha256=digests[0],
        scenario_id=request.scenario_id,
        scenario_sha256=digests[1],
        cohort_id=request.cohort_id,
        cohort_sha256=digests[2],
        semantic_experiment_id=request.semantic_experiment_id,
        experiment_sha256=digests[3],
        created_at=created_at,
    )
    session.add_all((thread, revision))
    await session.commit()
    return await _load_detail(session, thread)


async def append_decision_thread_revision(
    session: AsyncSession,
    thread_id: UUID,
    request: DecisionThreadContextCreate,
) -> DecisionThreadDetail:
    thread = await session.scalar(
        select(DecisionThreadRecord).where(DecisionThreadRecord.id == thread_id).with_for_update()
    )
    if thread is None:
        raise DecisionThreadNotFoundError(f"decision thread {thread_id} was not found")
    latest_version = await session.scalar(
        select(DecisionThreadRevisionRecord.version)
        .where(DecisionThreadRevisionRecord.thread_id == thread_id)
        .order_by(DecisionThreadRevisionRecord.version.desc())
        .limit(1)
    )
    digests = await _validated_revision_values(session, thread.decision_question, request)
    revision = DecisionThreadRevisionRecord(
        id=uuid4(),
        thread_id=thread.id,
        version=(latest_version or 0) + 1,
        world_model_id=request.world_model_id,
        world_snapshot_id=request.world_snapshot_id,
        snapshot_sha256=digests[0],
        scenario_id=request.scenario_id,
        scenario_sha256=digests[1],
        cohort_id=request.cohort_id,
        cohort_sha256=digests[2],
        semantic_experiment_id=request.semantic_experiment_id,
        experiment_sha256=digests[3],
        created_at=datetime.now(UTC),
    )
    session.add(revision)
    await session.commit()
    return await _load_detail(session, thread)


async def get_decision_thread(session: AsyncSession, thread_id: UUID) -> DecisionThreadDetail:
    thread = await session.get(DecisionThreadRecord, thread_id)
    if thread is None:
        raise DecisionThreadNotFoundError(f"decision thread {thread_id} was not found")
    return await _load_detail(session, thread)


async def list_decision_threads(session: AsyncSession) -> DecisionThreadsResponse:
    threads = tuple(
        (
            await session.execute(
                select(DecisionThreadRecord).order_by(
                    DecisionThreadRecord.created_at.desc(), DecisionThreadRecord.id
                )
            )
        )
        .scalars()
        .all()
    )
    details = tuple([await _load_detail(session, thread) for thread in threads])
    return DecisionThreadsResponse(
        items=tuple(
            DecisionThreadSummary(
                id=detail.id,
                title=detail.title,
                decision_question=detail.decision_question,
                created_at=detail.created_at,
                latest_revision=detail.latest_revision,
            )
            for detail in details
        ),
        total=len(details),
    )
