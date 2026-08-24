"""Transactional persistence for research projects and configured runs."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.repository import get_cohort
from app.research_projects.agenda_context import capture_project_agenda_context
from app.research_projects.context import (
    calculate_simulation_context_sha256,
    compile_simulation_context,
)
from app.research_projects.contracts import (
    LegacyResearchProjectDesign,
    ResearchProjectCohortRef,
    ResearchProjectCreateRequest,
    ResearchProjectDetail,
    ResearchProjectGraphRef,
    ResearchProjectSnapshotRef,
    ResearchProjectsResponse,
    ResearchRunEvent,
    ResearchRunEventsResponse,
    ResearchRunGraphMemoryResponse,
    ResearchRunGraphMemorySnapshot,
    ResearchRunGraphMemoryState,
    ResearchRunReport,
    ResearchRunReportsResponse,
    ResearchRunReportSummary,
    ResearchSimulationContext,
    ResearchSimulationPlan,
    ResearchSimulationRunCreateRequest,
    ResearchSimulationRunDetail,
    ResearchSimulationRunError,
    ResearchSimulationRunResult,
    ResearchSimulationRunsResponse,
)
from app.research_projects.errors import (
    ResearchProjectNotFoundError,
    ResearchSimulationRunNotFoundError,
)
from app.research_projects.hashing import (
    RUN_ENGINE,
    RUN_ENGINE_VERSION,
    calculate_graph_bound_research_project_sha256,
    calculate_planned_research_simulation_run_sha256,
    calculate_research_run_report_sha256,
)
from app.research_projects.memory import calculate_graph_memory_sha256
from app.research_projects.models import (
    ResearchProjectRecord,
    ResearchRunEventRecord,
    ResearchRunGraphMemoryRecord,
    ResearchRunReportRecord,
    ResearchSimulationRunRecord,
)
from app.research_projects.planning import (
    calculate_simulation_plan_sha256,
    compile_simulation_plan,
)
from app.semantic_experiments.repository import get_live_semantic_config
from app.world_graphs.repository import get_semantic_world_graph
from app.world_models.repository import get_world_snapshot


def _project_detail(record: ResearchProjectRecord) -> ResearchProjectDetail:
    legacy_design = None
    if record.schema_version == "sandowl-research-project/v1":
        if (
            record.cohort_id is None
            or record.cohort_sha256 is None
            or record.persona_count is None
            or record.simulation_requirement is None
        ):
            raise RuntimeError(f"legacy research project {record.id} has incomplete design fields")
        legacy_design = LegacyResearchProjectDesign(
            cohort=ResearchProjectCohortRef(
                cohort_id=record.cohort_id,
                cohort_sha256=record.cohort_sha256,
                persona_count=record.persona_count,
            ),
            simulation_requirement=record.simulation_requirement,
        )
    graph = None
    if record.schema_version == "sandowl-research-project/v3":
        if (
            record.world_graph_id is None
            or record.graph_sha256 is None
            or record.graph_node_count is None
            or record.graph_edge_count is None
        ):
            raise RuntimeError(f"research project {record.id} has incomplete graph fields")
        graph = ResearchProjectGraphRef(
            graph_id=record.world_graph_id,
            graph_sha256=record.graph_sha256,
            node_count=record.graph_node_count,
            edge_count=record.graph_edge_count,
        )
    return ResearchProjectDetail(
        id=record.id,
        title=record.title,
        research_question=record.research_question,
        snapshot=ResearchProjectSnapshotRef(
            world_model_id=record.world_model_id,
            world_snapshot_id=record.world_snapshot_id,
            snapshot_sha256=record.snapshot_sha256,
        ),
        graph=graph,
        schema_version=record.schema_version,
        legacy_design=legacy_design,
        project_sha256=record.project_sha256,
        created_at=record.created_at,
    )


def _run_detail(record: ResearchSimulationRunRecord) -> ResearchSimulationRunDetail:
    result = None
    error = None
    if record.status == "succeeded":
        values = (
            record.artifact_sha256,
            record.artifact_size_bytes,
            record.user_count,
            record.initial_post_count,
            record.generated_post_count,
            record.comment_count,
            record.reaction_count,
            record.do_nothing_count,
            record.observed_action_count,
            record.rounds_completed,
            record.limitations,
        )
        if any(value is None for value in values):
            raise RuntimeError(f"succeeded research run {record.id} has incomplete result fields")
        result = ResearchSimulationRunResult(
            artifact_sha256=record.artifact_sha256,
            artifact_size_bytes=record.artifact_size_bytes,
            user_count=record.user_count,
            initial_post_count=record.initial_post_count,
            generated_post_count=record.generated_post_count,
            comment_count=record.comment_count,
            reaction_count=record.reaction_count,
            do_nothing_count=record.do_nothing_count,
            observed_action_count=record.observed_action_count,
            rounds_completed=record.rounds_completed,
            limitations=tuple(record.limitations),
        )
    elif record.status == "failed":
        if record.error_code is None or record.error_message is None:
            raise RuntimeError(f"failed research run {record.id} has incomplete error fields")
        error = ResearchSimulationRunError(
            code=record.error_code,
            message=record.error_message,
        )
    simulation_context = None
    if record.schema_version in (
        "sandowl-research-simulation-run/v3",
        "sandowl-research-simulation-run/v4",
    ):
        if record.simulation_context is None or record.simulation_context_sha256 is None:
            raise RuntimeError(f"research run {record.id} has incomplete simulation context")
        simulation_context = ResearchSimulationContext.model_validate_json(
            json.dumps(record.simulation_context, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        actual_context_sha256 = calculate_simulation_context_sha256(simulation_context)
        if actual_context_sha256 != record.simulation_context_sha256:
            raise RuntimeError(f"research run {record.id} simulation context hash mismatch")
    simulation_plan = None
    if record.schema_version == "sandowl-research-simulation-run/v4":
        if record.simulation_plan is None or record.simulation_plan_sha256 is None:
            raise RuntimeError(f"research run {record.id} has incomplete simulation plan")
        simulation_plan = ResearchSimulationPlan.model_validate_json(
            json.dumps(record.simulation_plan, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        actual_plan_sha256 = calculate_simulation_plan_sha256(simulation_plan)
        if actual_plan_sha256 != record.simulation_plan_sha256:
            raise RuntimeError(f"research run {record.id} simulation plan hash mismatch")
    return ResearchSimulationRunDetail(
        id=record.id,
        research_project_id=record.research_project_id,
        project_sha256=record.project_sha256,
        schema_version=record.schema_version,
        cohort=ResearchProjectCohortRef(
            cohort_id=record.cohort_id,
            cohort_sha256=record.cohort_sha256,
            persona_count=record.persona_count,
        ),
        simulation_requirement=record.simulation_requirement,
        seed=record.seed,
        rounds=record.rounds,
        minutes_per_round=record.minutes_per_round,
        initial_post=record.initial_post,
        engine=record.engine,
        engine_version=record.engine_version,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        simulation_context=simulation_context,
        simulation_context_sha256=record.simulation_context_sha256,
        simulation_plan=simulation_plan,
        simulation_plan_sha256=record.simulation_plan_sha256,
        status=record.status,
        run_spec_sha256=record.run_spec_sha256,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        result=result,
        error=error,
    )


def _event_detail(record: ResearchRunEventRecord) -> ResearchRunEvent:
    return ResearchRunEvent(
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


async def create_research_project(
    session: AsyncSession,
    request: ResearchProjectCreateRequest,
) -> ResearchProjectDetail:
    """Validate existing triad resources and seal one content-addressed project."""
    snapshot = await get_world_snapshot(
        session,
        request.world_model_id,
        request.world_snapshot_id,
    )
    snapshot_ref = ResearchProjectSnapshotRef(
        world_model_id=snapshot.world_model_id,
        world_snapshot_id=snapshot.id,
        snapshot_sha256=snapshot.snapshot_sha256,
    )
    graph = await get_semantic_world_graph(session, request.world_graph_id)
    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise ValueError("research project requires a succeeded semantic world graph")
    if (
        graph.world_model_id != snapshot.world_model_id
        or graph.snapshot_id != snapshot.id
        or graph.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("semantic world graph does not belong to the selected WorldSnapshot")
    graph_ref = ResearchProjectGraphRef(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )
    project_sha256 = calculate_graph_bound_research_project_sha256(
        request.title,
        request.research_question,
        snapshot_ref,
        graph_ref,
    )
    existing = await session.scalar(
        select(ResearchProjectRecord).where(ResearchProjectRecord.project_sha256 == project_sha256)
    )
    if existing is not None:
        await capture_project_agenda_context(session, existing, commit=True)
        return _project_detail(existing)

    created_at = datetime.now(UTC)
    record = ResearchProjectRecord(
        id=uuid4(),
        title=request.title,
        research_question=request.research_question,
        world_model_id=snapshot_ref.world_model_id,
        world_snapshot_id=snapshot_ref.world_snapshot_id,
        snapshot_sha256=snapshot_ref.snapshot_sha256,
        world_graph_id=graph_ref.graph_id,
        graph_sha256=graph_ref.graph_sha256,
        graph_node_count=graph_ref.node_count,
        graph_edge_count=graph_ref.edge_count,
        schema_version="sandowl-research-project/v3",
        cohort_id=None,
        cohort_sha256=None,
        persona_count=None,
        simulation_requirement=None,
        project_sha256=project_sha256,
        created_at=created_at,
        sealed_at=created_at,
    )
    session.add(record)
    await session.flush()
    await capture_project_agenda_context(session, record, commit=False)
    await session.commit()
    return _project_detail(record)


async def get_research_project(
    session: AsyncSession,
    project_id: UUID,
) -> ResearchProjectDetail:
    record = await session.get(ResearchProjectRecord, project_id)
    if record is None:
        raise ResearchProjectNotFoundError(f"research project {project_id} was not found")
    return _project_detail(record)


async def list_research_projects(session: AsyncSession) -> ResearchProjectsResponse:
    records = tuple(
        (
            await session.execute(
                select(ResearchProjectRecord).order_by(
                    ResearchProjectRecord.created_at.desc(),
                    ResearchProjectRecord.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return ResearchProjectsResponse(
        items=tuple(_project_detail(record) for record in records),
        total=len(records),
    )


async def create_research_simulation_run(
    session: AsyncSession,
    project_id: UUID,
    request: ResearchSimulationRunCreateRequest,
) -> ResearchSimulationRunDetail:
    project = await session.get(ResearchProjectRecord, project_id)
    if project is None:
        raise ResearchProjectNotFoundError(f"research project {project_id} was not found")
    if project.schema_version != "sandowl-research-project/v3" or project.world_graph_id is None:
        raise ValueError(
            "this historical project has no bound semantic graph; create a new graph-bound project"
        )
    snapshot = await get_world_snapshot(session, project.world_model_id, project.world_snapshot_id)
    graph = await get_semantic_world_graph(session, project.world_graph_id)
    simulation_context = compile_simulation_context(snapshot, graph)
    simulation_context_sha256 = calculate_simulation_context_sha256(simulation_context)
    cohort = await get_cohort(session, request.cohort_id)
    if cohort.persona_count > 8:
        raise ValueError(
            f"selected cohort contains {cohort.persona_count} personas; "
            "OASIS research runs support at most 8"
        )
    cohort_ref = ResearchProjectCohortRef(
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        persona_count=cohort.persona_count,
    )
    simulation_plan = compile_simulation_plan(
        request,
        simulation_context.total_media_count
        + simulation_context.total_policy_count
        + simulation_context.total_node_count
        + simulation_context.total_edge_count,
        cohort.persona_count,
    )
    simulation_plan_sha256 = calculate_simulation_plan_sha256(simulation_plan)
    model_name, config_sha256 = await get_live_semantic_config(session)
    run_spec_sha256 = calculate_planned_research_simulation_run_sha256(
        project.project_sha256,
        cohort_ref,
        request.simulation_requirement,
        request.seed,
        model_name,
        config_sha256,
        simulation_context_sha256,
        simulation_plan_sha256,
    )
    existing = await session.scalar(
        select(ResearchSimulationRunRecord).where(
            ResearchSimulationRunRecord.run_spec_sha256 == run_spec_sha256
        )
    )
    if existing is not None:
        return _run_detail(existing)
    created_at = datetime.now(UTC)
    record = ResearchSimulationRunRecord(
        id=uuid4(),
        research_project_id=project.id,
        project_sha256=project.project_sha256,
        schema_version="sandowl-research-simulation-run/v4",
        cohort_id=cohort_ref.cohort_id,
        cohort_sha256=cohort_ref.cohort_sha256,
        persona_count=cohort_ref.persona_count,
        simulation_requirement=request.simulation_requirement,
        seed=request.seed,
        rounds=simulation_plan.rounds,
        minutes_per_round=simulation_plan.minutes_per_round,
        initial_post=request.initial_post,
        engine=RUN_ENGINE,
        engine_version=RUN_ENGINE_VERSION,
        model_name=model_name,
        semantic_config_sha256=config_sha256,
        prompt_schema_version="matraix-semantic-profile/v1",
        simulation_context=simulation_context.model_dump(mode="json"),
        simulation_context_sha256=simulation_context_sha256,
        simulation_plan=simulation_plan.model_dump(mode="json"),
        simulation_plan_sha256=simulation_plan_sha256,
        status="queued",
        run_spec_sha256=run_spec_sha256,
        created_at=created_at,
        claimed_by_worker_id=None,
        started_at=None,
        completed_at=None,
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
    session.add(record)
    await session.commit()
    return _run_detail(record)


async def preview_research_simulation_plan(
    session: AsyncSession,
    project_id: UUID,
    request: ResearchSimulationRunCreateRequest,
) -> ResearchSimulationPlan:
    """Compile the same context-aware plan used at enqueue time without creating a run."""
    project = await session.get(ResearchProjectRecord, project_id)
    if project is None:
        raise ResearchProjectNotFoundError(f"research project {project_id} was not found")
    if project.schema_version != "sandowl-research-project/v3" or project.world_graph_id is None:
        raise ValueError("this historical project cannot preview a graph-bound simulation plan")
    snapshot = await get_world_snapshot(session, project.world_model_id, project.world_snapshot_id)
    graph = await get_semantic_world_graph(session, project.world_graph_id)
    context = compile_simulation_context(snapshot, graph)
    cohort = await get_cohort(session, request.cohort_id)
    if cohort.persona_count > 8:
        raise ValueError(
            f"selected cohort contains {cohort.persona_count} personas; "
            "OASIS research runs support at most 8"
        )
    return compile_simulation_plan(
        request,
        context.total_media_count
        + context.total_policy_count
        + context.total_node_count
        + context.total_edge_count,
        cohort.persona_count,
    )


async def list_research_simulation_runs(
    session: AsyncSession,
    project_id: UUID,
) -> ResearchSimulationRunsResponse:
    if await session.get(ResearchProjectRecord, project_id) is None:
        raise ResearchProjectNotFoundError(f"research project {project_id} was not found")
    records = tuple(
        (
            await session.execute(
                select(ResearchSimulationRunRecord)
                .where(ResearchSimulationRunRecord.research_project_id == project_id)
                .order_by(
                    ResearchSimulationRunRecord.created_at.desc(),
                    ResearchSimulationRunRecord.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return ResearchSimulationRunsResponse(
        items=tuple(_run_detail(record) for record in records),
        total=len(records),
    )


async def get_research_simulation_run(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchSimulationRunDetail:
    record = await session.scalar(
        select(ResearchSimulationRunRecord).where(
            ResearchSimulationRunRecord.id == run_id,
            ResearchSimulationRunRecord.research_project_id == project_id,
        )
    )
    if record is None:
        raise ResearchSimulationRunNotFoundError(
            f"research simulation run {run_id} was not found for project {project_id}"
        )
    return _run_detail(record)


async def list_research_run_events(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchRunEventsResponse:
    await get_research_simulation_run(session, project_id, run_id)
    records = tuple(
        (
            await session.execute(
                select(ResearchRunEventRecord)
                .where(ResearchRunEventRecord.run_id == run_id)
                .order_by(ResearchRunEventRecord.sequence)
            )
        )
        .scalars()
        .all()
    )
    return ResearchRunEventsResponse(
        items=tuple(_event_detail(record) for record in records),
        total=len(records),
    )


async def list_research_run_graph_memory(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchRunGraphMemoryResponse:
    run = await get_research_simulation_run(session, project_id, run_id)
    records = tuple(
        (
            await session.scalars(
                select(ResearchRunGraphMemoryRecord)
                .where(ResearchRunGraphMemoryRecord.run_id == run_id)
                .order_by(ResearchRunGraphMemoryRecord.round)
            )
        ).all()
    )
    items: list[ResearchRunGraphMemorySnapshot] = []
    expected_previous = None
    for record in records:
        state = ResearchRunGraphMemoryState.model_validate_json(
            json.dumps(record.memory, ensure_ascii=False, allow_nan=False),
            strict=True,
        )
        if (
            state.run_spec_sha256 != run.run_spec_sha256
            or state.round != record.round
            or state.previous_sha256 != record.previous_sha256
            or state.previous_sha256 != expected_previous
        ):
            raise RuntimeError(
                f"research run graph memory {run_id}/{record.round} lineage mismatch"
            )
        actual_sha256 = calculate_graph_memory_sha256(state)
        if actual_sha256 != record.memory_sha256:
            raise RuntimeError(f"research run graph memory {run_id}/{record.round} hash mismatch")
        items.append(
            ResearchRunGraphMemorySnapshot(
                **state.model_dump(),
                memory_sha256=record.memory_sha256,
                created_at=record.created_at,
            )
        )
        expected_previous = record.memory_sha256
    return ResearchRunGraphMemoryResponse(items=tuple(items), total=len(items))


async def get_research_run_report(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchRunReport:
    project_record = await session.get(ResearchProjectRecord, project_id)
    if project_record is None:
        raise ResearchProjectNotFoundError(f"research project {project_id} was not found")
    run_record = await session.scalar(
        select(ResearchSimulationRunRecord).where(
            ResearchSimulationRunRecord.id == run_id,
            ResearchSimulationRunRecord.research_project_id == project_id,
        )
    )
    if run_record is None:
        raise ResearchSimulationRunNotFoundError(
            f"research simulation run {run_id} was not found for project {project_id}"
        )
    report_record = await session.scalar(
        select(ResearchRunReportRecord).where(ResearchRunReportRecord.run_id == run_id)
    )
    if report_record is None:
        raise ResearchSimulationRunNotFoundError(
            f"research run report for {run_id} is not available"
        )
    if run_record.artifact_sha256 is None:
        raise RuntimeError(f"research run report {report_record.id} has no completed artifact")
    expected_sha256 = calculate_research_run_report_sha256(
        run_record.run_spec_sha256,
        run_record.artifact_sha256,
    )
    if report_record.report_sha256 != expected_sha256:
        raise RuntimeError(f"research run report {report_record.id} content hash mismatch")
    events = await list_research_run_events(session, project_id, run_id)
    graph_memory = await list_research_run_graph_memory(session, project_id, run_id)
    return ResearchRunReport(
        id=report_record.id,
        research_project=_project_detail(project_record),
        run=_run_detail(run_record),
        events=events.items,
        graph_memory=graph_memory.items,
        report_sha256=report_record.report_sha256,
        created_at=report_record.created_at,
    )


async def list_research_run_reports(session: AsyncSession) -> ResearchRunReportsResponse:
    """List sealed native reports without loading their potentially large event streams."""
    rows = tuple(
        (
            await session.execute(
                select(
                    ResearchRunReportRecord,
                    ResearchProjectRecord,
                    ResearchSimulationRunRecord,
                )
                .join(
                    ResearchSimulationRunRecord,
                    ResearchSimulationRunRecord.id == ResearchRunReportRecord.run_id,
                )
                .join(
                    ResearchProjectRecord,
                    ResearchProjectRecord.id == ResearchSimulationRunRecord.research_project_id,
                )
                .order_by(
                    ResearchRunReportRecord.created_at.desc(),
                    ResearchRunReportRecord.id,
                )
            )
        ).all()
    )
    items: list[ResearchRunReportSummary] = []
    for report_record, project_record, run_record in rows:
        if run_record.artifact_sha256 is None:
            raise RuntimeError(f"research run report {report_record.id} has no completed artifact")
        expected_sha256 = calculate_research_run_report_sha256(
            run_record.run_spec_sha256,
            run_record.artifact_sha256,
        )
        if report_record.report_sha256 != expected_sha256:
            raise RuntimeError(f"research run report {report_record.id} content hash mismatch")
        items.append(
            ResearchRunReportSummary(
                id=report_record.id,
                research_project=_project_detail(project_record),
                run=_run_detail(run_record),
                report_sha256=report_record.report_sha256,
                created_at=report_record.created_at,
            )
        )
    return ResearchRunReportsResponse(items=tuple(items), total=len(items))
