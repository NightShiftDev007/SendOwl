"""Transactional compilation and persistence for OASIS platform-smoke runs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scenarios.repository import get_scenario
from app.simulations.compiler import compile_platform_smoke_input
from app.simulations.constants import (
    OASIS_READINESS_LIMITATIONS,
    PLATFORM_SMOKE_LIMITATIONS,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.contracts import (
    CompiledPlatformSmokeInput,
    OasisReadiness,
    PlatformSmokeError,
    PlatformSmokePost,
    PlatformSmokeResult,
    PlatformSmokeRunDetail,
    PlatformSmokeRunsResponse,
    PlatformSmokeRunSummary,
    PlatformSmokeScenarioRef,
)
from app.simulations.errors import PlatformSmokeRunNotFoundError, PlatformSmokeUnavailableError
from app.simulations.hashing import calculate_platform_smoke_input_sha256
from app.simulations.models import (
    SimulationRunPostRecord,
    SimulationRunRecord,
    SimulationWorkerHeartbeatRecord,
)


def _input_advisory_lock_key(input_sha256: str) -> int:
    unsigned_key = int(input_sha256[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _lock_run_input(session: AsyncSession, input_sha256: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _input_advisory_lock_key(input_sha256)},
    )


def _scenario_ref_from_record(run: SimulationRunRecord) -> PlatformSmokeScenarioRef:
    return PlatformSmokeScenarioRef(
        id=run.scenario_id,
        scenario_sha256=run.scenario_sha256,
        variant_id=run.variant_id,
        variant_name=run.variant_name,
        world_snapshot_id=run.world_snapshot_id,
        snapshot_sha256=run.snapshot_sha256,
    )


def _posts_from_records(
    records: tuple[SimulationRunPostRecord, ...],
) -> tuple[PlatformSmokePost, ...]:
    return tuple(
        PlatformSmokePost(
            position=post.position,
            content=post.content,
            offset_minutes=post.offset_minutes,
        )
        for post in records
    )


def _compiled_input_from_records(
    run: SimulationRunRecord,
    posts: tuple[SimulationRunPostRecord, ...],
) -> CompiledPlatformSmokeInput:
    return CompiledPlatformSmokeInput(
        mode="reddit_manual_smoke",
        scenario=_scenario_ref_from_record(run),
        seed=run.seed,
        actor_user_name=run.actor_user_name,
        actor_name=run.actor_name,
        actor_bio=run.actor_bio,
        posts=_posts_from_records(posts),
    )


def _result_from_record(run: SimulationRunRecord) -> PlatformSmokeResult | None:
    if run.status != "succeeded":
        return None
    required = (
        run.engine_version,
        run.camel_version,
        run.artifact_sha256,
        run.artifact_size_bytes,
        run.user_count,
        run.post_count,
        run.trace_count,
    )
    if any(value is None for value in required):
        raise RuntimeError(f"succeeded simulation run {run.id} has incomplete result fields")
    return PlatformSmokeResult(
        engine_version=run.engine_version,
        camel_version=run.camel_version,
        artifact_sha256=run.artifact_sha256,
        artifact_size_bytes=run.artifact_size_bytes,
        user_count=run.user_count,
        post_count=run.post_count,
        trace_count=run.trace_count,
        limitations=PLATFORM_SMOKE_LIMITATIONS,
    )


def _error_from_record(run: SimulationRunRecord) -> PlatformSmokeError | None:
    if run.status != "failed":
        return None
    if run.error_code is None or run.error_message is None:
        raise RuntimeError(f"failed simulation run {run.id} has incomplete error fields")
    return PlatformSmokeError(code=run.error_code, message=run.error_message)


def _run_detail(
    run: SimulationRunRecord,
    posts: tuple[SimulationRunPostRecord, ...],
) -> PlatformSmokeRunDetail:
    """Reconstruct and content-verify one run solely from normalized tables."""
    if run.input_sealed_at is None:
        raise RuntimeError(f"simulation run {run.id} input is not sealed")
    if any(post.run_id != run.id for post in posts):
        raise RuntimeError(f"simulation run {run.id} received a post owned by another run")
    compiled = _compiled_input_from_records(run, posts)
    actual_sha256 = calculate_platform_smoke_input_sha256(compiled)
    if actual_sha256 != run.input_sha256:
        raise RuntimeError(f"simulation run {run.id} content does not match input_sha256")
    return PlatformSmokeRunDetail(
        id=run.id,
        mode="reddit_manual_smoke",
        status=run.status,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        scenario=compiled.scenario,
        seed=run.seed,
        input_sha256=run.input_sha256,
        posts=compiled.posts,
        result=_result_from_record(run),
        error=_error_from_record(run),
    )


def _run_summary(detail: PlatformSmokeRunDetail) -> PlatformSmokeRunSummary:
    return PlatformSmokeRunSummary(
        id=detail.id,
        mode=detail.mode,
        status=detail.status,
        created_at=detail.created_at,
        started_at=detail.started_at,
        completed_at=detail.completed_at,
        scenario=detail.scenario,
        seed=detail.seed,
        input_sha256=detail.input_sha256,
    )


def _new_records(
    run_id: UUID,
    compiled: CompiledPlatformSmokeInput,
    input_sha256: str,
    created_at: datetime,
) -> tuple[SimulationRunRecord, tuple[SimulationRunPostRecord, ...]]:
    scenario = compiled.scenario
    run = SimulationRunRecord(
        id=run_id,
        mode=compiled.mode,
        status="queued",
        scenario_id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        variant_id=scenario.variant_id,
        variant_name=scenario.variant_name,
        world_snapshot_id=scenario.world_snapshot_id,
        snapshot_sha256=scenario.snapshot_sha256,
        seed=compiled.seed,
        actor_user_name=compiled.actor_user_name,
        actor_name=compiled.actor_name,
        actor_bio=compiled.actor_bio,
        input_sha256=input_sha256,
        created_at=created_at,
        input_sealed_at=None,
        claimed_by_worker_id=None,
        started_at=None,
        completed_at=None,
        engine_version=None,
        camel_version=None,
        artifact_sha256=None,
        artifact_size_bytes=None,
        user_count=None,
        post_count=None,
        trace_count=None,
        error_code=None,
        error_message=None,
    )
    posts = tuple(
        SimulationRunPostRecord(
            run_id=run_id,
            position=post.position,
            content=post.content,
            offset_minutes=post.offset_minutes,
        )
        for post in compiled.posts
    )
    return run, posts


async def _load_run_details(
    session: AsyncSession,
    runs: tuple[SimulationRunRecord, ...],
) -> tuple[PlatformSmokeRunDetail, ...]:
    if not runs:
        return ()
    run_ids = tuple(run.id for run in runs)
    post_records = tuple(
        (
            await session.execute(
                select(SimulationRunPostRecord)
                .where(SimulationRunPostRecord.run_id.in_(run_ids))
                .order_by(SimulationRunPostRecord.run_id, SimulationRunPostRecord.position)
            )
        )
        .scalars()
        .all()
    )
    posts_by_run: dict[UUID, list[SimulationRunPostRecord]] = {run_id: [] for run_id in run_ids}
    for post in post_records:
        posts_by_run[post.run_id].append(post)
    return tuple(_run_detail(run, tuple(posts_by_run[run.id])) for run in runs)


async def create_platform_smoke_run(
    session: AsyncSession,
    scenario_id: UUID,
    variant_id: UUID,
    seed: int,
) -> PlatformSmokeRunDetail:
    """Compile one sealed alternative and idempotently enqueue its exact input."""
    scenario = await get_scenario(session, scenario_id)
    compiled = compile_platform_smoke_input(scenario, variant_id, seed)
    input_sha256 = calculate_platform_smoke_input_sha256(compiled)
    await _lock_run_input(session, input_sha256)
    existing = await session.scalar(
        select(SimulationRunRecord).where(SimulationRunRecord.input_sha256 == input_sha256)
    )
    if existing is not None:
        detail = (await _load_run_details(session, (existing,)))[0]
        await session.commit()
        return detail

    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    ready_worker_exists = await session.scalar(
        select(SimulationWorkerHeartbeatRecord.worker_id)
        .where(
            SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
            SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
            SimulationWorkerHeartbeatRecord.engine_version == "0.2.5",
            SimulationWorkerHeartbeatRecord.camel_version == "0.2.78",
            SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
            SimulationWorkerHeartbeatRecord.worker_domain == "semantic",
            SimulationWorkerHeartbeatRecord.platform_runtime_ready.is_(True),
        )
        .limit(1)
    )
    if ready_worker_exists is None:
        raise PlatformSmokeUnavailableError(
            "OASIS platform-smoke is unavailable because no correctly pinned worker "
            "reported readiness in the last 30 seconds"
        )

    created_at = datetime.now(UTC)
    run, posts = _new_records(uuid4(), compiled, input_sha256, created_at)
    session.add(run)
    await session.flush((run,))
    session.add_all(posts)
    await session.flush(posts)
    run.input_sealed_at = created_at
    await session.flush((run,))
    detail = _run_detail(run, posts)
    await session.commit()
    return detail


async def list_platform_smoke_runs(session: AsyncSession) -> PlatformSmokeRunsResponse:
    runs = tuple(
        (
            await session.execute(
                select(SimulationRunRecord)
                .where(SimulationRunRecord.input_sealed_at.is_not(None))
                .order_by(SimulationRunRecord.created_at.desc(), SimulationRunRecord.id.asc())
            )
        )
        .scalars()
        .all()
    )
    details = await _load_run_details(session, runs)
    return PlatformSmokeRunsResponse(
        items=tuple(_run_summary(detail) for detail in details),
        total=len(details),
    )


async def get_platform_smoke_run(
    session: AsyncSession,
    run_id: UUID,
) -> PlatformSmokeRunDetail:
    run = await session.scalar(
        select(SimulationRunRecord).where(
            SimulationRunRecord.id == run_id,
            SimulationRunRecord.input_sealed_at.is_not(None),
        )
    )
    if run is None:
        raise PlatformSmokeRunNotFoundError(f"platform-smoke run {run_id} was not found")
    return (await _load_run_details(session, (run,)))[0]


async def get_oasis_readiness(session: AsyncSession) -> OasisReadiness:
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    online_heartbeats = tuple(
        (
            await session.execute(
                select(SimulationWorkerHeartbeatRecord).where(
                    SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
                    SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
                    SimulationWorkerHeartbeatRecord.engine_version == "0.2.5",
                    SimulationWorkerHeartbeatRecord.camel_version == "0.2.78",
                    SimulationWorkerHeartbeatRecord.mode == "reddit_manual_smoke",
                    SimulationWorkerHeartbeatRecord.worker_domain == "semantic",
                )
            )
        )
        .scalars()
        .all()
    )
    return OasisReadiness(
        engine="camel-oasis",
        engine_version="0.2.5",
        mode="reddit_manual_smoke",
        worker_online=bool(online_heartbeats),
        platform_runtime_ready=any(
            heartbeat.platform_runtime_ready for heartbeat in online_heartbeats
        ),
        semantic_run_ready=False,
        limitations=OASIS_READINESS_LIMITATIONS,
    )
