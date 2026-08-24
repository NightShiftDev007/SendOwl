"""Transactional enqueue and fail-closed reads for semantic world graphs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.contracts import CohortDatasetRef
from app.populations.repository import ensure_cohort, get_cohort, load_persona_match_scan
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION as SEMANTIC_PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord
from app.world_graphs.cohort_origins import (
    GRAPH_PERSONA_MATCH_SEMANTICS,
    GRAPH_PERSONA_MATCHER_VERSION,
    calculate_graph_persona_cohort_origin_sha256,
)
from app.world_graphs.contracts import (
    GRAPH_PROMPT_SCHEMA_VERSION,
    GraphPersonaCohortCreateRequest,
    GraphPersonaCohortCreation,
    GraphPersonaCohortOrigin,
    GraphPersonaCohortOriginsResponse,
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphEdgeHistory,
    SemanticWorldGraphEvidenceTimeline,
    SemanticWorldGraphNode,
    SemanticWorldGraphPersonaMatches,
    SemanticWorldGraphSearchResponse,
    SemanticWorldGraphSlice,
    SemanticWorldGraphsResponse,
    WorldGraphEvidenceReference,
    WorldGraphSliceDirection,
)
from app.world_graphs.errors import (
    WorldGraphNotFoundError,
    WorldGraphPersonaOriginPageOutOfRangeError,
    WorldGraphPersonaSelectionError,
    WorldGraphUnavailableError,
)
from app.world_graphs.hashing import (
    calculate_extraction_config_sha256,
    calculate_graph_input_sha256,
    calculate_semantic_graph_sha256,
)
from app.world_graphs.history import project_semantic_world_graph_edge_history
from app.world_graphs.models import (
    SemanticWorldGraphCohortOriginRecord,
    SemanticWorldGraphEdgeRecord,
    SemanticWorldGraphEvidenceRecord,
    SemanticWorldGraphNodeRecord,
    SemanticWorldGraphRecord,
)
from app.world_graphs.persona_matching import match_graph_node_to_personas
from app.world_graphs.search import search_semantic_world_graph
from app.world_graphs.slicing import slice_semantic_world_graph
from app.world_graphs.timeline import project_semantic_world_graph_timeline
from app.world_models.repository import get_world_snapshot


def _advisory_lock_key(digest: str) -> int:
    unsigned_key = int(digest[:16], 16)
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _live_graph_model_config(session: AsyncSession) -> tuple[str, str]:
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
                    SimulationWorkerHeartbeatRecord.worker_domain == "report",
                    SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
                    SimulationWorkerHeartbeatRecord.semantic_prompt_schema_version
                    == SEMANTIC_PROMPT_SCHEMA_VERSION,
                )
                .with_for_update(read=True)
            )
        )
        .scalars()
        .all()
    )
    configs = {
        (heartbeat.semantic_model_name, heartbeat.semantic_config_sha256)
        for heartbeat in heartbeats
    }
    if not configs:
        raise WorldGraphUnavailableError(
            "semantic world graph extraction is unavailable because no model worker passed "
            "the provider tool-call probe in the last 30 seconds"
        )
    if len(configs) != 1:
        raise WorldGraphUnavailableError(
            "semantic world graph extraction is unavailable because live workers disagree "
            "on model configuration"
        )
    model_name, semantic_config_sha256 = next(iter(configs))
    if model_name is None or semantic_config_sha256 is None:
        raise RuntimeError("semantic-ready worker persisted incomplete model configuration")
    return model_name, semantic_config_sha256


def _references_by_object(
    records: tuple[SemanticWorldGraphEvidenceRecord, ...],
) -> dict[tuple[str, UUID], tuple[WorldGraphEvidenceReference, ...]]:
    grouped: dict[tuple[str, UUID], list[WorldGraphEvidenceReference]] = {}
    for record in records:
        grouped.setdefault((record.object_kind, record.object_id), []).append(
            WorldGraphEvidenceReference(
                position=record.position,
                article_id=record.article_id,
                quote=record.quote,
                start_offset=record.start_offset,
                end_offset=record.end_offset,
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


async def _load_graph_detail(
    session: AsyncSession,
    record: SemanticWorldGraphRecord,
) -> SemanticWorldGraphDetail:
    node_records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphNodeRecord)
                .where(SemanticWorldGraphNodeRecord.graph_id == record.id)
                .order_by(SemanticWorldGraphNodeRecord.position)
            )
        )
        .scalars()
        .all()
    )
    edge_records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphEdgeRecord)
                .where(SemanticWorldGraphEdgeRecord.graph_id == record.id)
                .order_by(SemanticWorldGraphEdgeRecord.position)
            )
        )
        .scalars()
        .all()
    )
    evidence_records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphEvidenceRecord)
                .where(SemanticWorldGraphEvidenceRecord.graph_id == record.id)
                .order_by(
                    SemanticWorldGraphEvidenceRecord.object_kind,
                    SemanticWorldGraphEvidenceRecord.object_id,
                    SemanticWorldGraphEvidenceRecord.position,
                )
            )
        )
        .scalars()
        .all()
    )
    references = _references_by_object(evidence_records)
    nodes = tuple(
        SemanticWorldGraphNode(
            id=node.id,
            position=node.position,
            entity_type=node.entity_type,
            name=node.name,
            summary=node.summary,
            evidence=references.get(("node", node.id), ()),
        )
        for node in node_records
    )
    edges = tuple(
        SemanticWorldGraphEdge(
            id=edge.id,
            position=edge.position,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            relation_type=edge.relation_type,
            fact=edge.fact,
            evidence=references.get(("edge", edge.id), ()),
        )
        for edge in edge_records
    )
    if record.status == "succeeded":
        if record.node_count != len(nodes) or record.edge_count != len(edges):
            raise RuntimeError(f"semantic world graph {record.id} stored count mismatch")
        expected_digest = calculate_semantic_graph_sha256(record.input_sha256, nodes, edges)
        if record.graph_sha256 != expected_digest:
            raise RuntimeError(f"semantic world graph {record.id} content hash mismatch")
    elif nodes or edges or evidence_records:
        raise RuntimeError(f"non-succeeded semantic world graph {record.id} contains graph records")
    return SemanticWorldGraphDetail(
        id=record.id,
        world_model_id=record.world_model_id,
        snapshot_id=record.snapshot_id,
        snapshot_sha256=record.snapshot_sha256,
        status=record.status,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        extraction_config_sha256=record.extraction_config_sha256,
        prompt_schema_version=GRAPH_PROMPT_SCHEMA_VERSION,
        input_sha256=record.input_sha256,
        graph_sha256=record.graph_sha256,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        nodes=nodes,
        edges=edges,
        error_code=record.error_code,
        error_message=record.error_message,
    )


async def enqueue_semantic_world_graph(
    session: AsyncSession,
    world_model_id: UUID,
    snapshot_id: UUID,
) -> SemanticWorldGraphDetail:
    snapshot = await get_world_snapshot(session, world_model_id, snapshot_id)
    model_name, semantic_config_sha256 = await _live_graph_model_config(session)
    extraction_config_sha256 = calculate_extraction_config_sha256(semantic_config_sha256)
    input_sha256 = calculate_graph_input_sha256(
        world_model_id,
        snapshot_id,
        snapshot.snapshot_sha256,
        model_name,
        semantic_config_sha256,
        extraction_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _advisory_lock_key(input_sha256)},
    )
    existing = (
        await session.execute(
            select(SemanticWorldGraphRecord).where(
                SemanticWorldGraphRecord.input_sha256 == input_sha256
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await session.commit()
        return await _load_graph_detail(session, existing)
    record = SemanticWorldGraphRecord(
        id=uuid4(),
        world_model_id=world_model_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot.snapshot_sha256,
        status="queued",
        model_name=model_name,
        semantic_config_sha256=semantic_config_sha256,
        extraction_config_sha256=extraction_config_sha256,
        prompt_schema_version=GRAPH_PROMPT_SCHEMA_VERSION,
        input_sha256=input_sha256,
        graph_sha256=None,
        created_at=datetime.now(UTC),
        claimed_by_worker_id=None,
        started_at=None,
        completed_at=None,
        node_count=None,
        edge_count=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return await _load_graph_detail(session, record)


async def get_semantic_world_graph(
    session: AsyncSession,
    graph_id: UUID,
) -> SemanticWorldGraphDetail:
    record = await session.get(SemanticWorldGraphRecord, graph_id)
    if record is None:
        raise WorldGraphNotFoundError(f"semantic world graph {graph_id} was not found")
    return await _load_graph_detail(session, record)


async def get_semantic_world_graph_slice(
    session: AsyncSession,
    graph_id: UUID,
    root_node_id: UUID,
    direction: WorldGraphSliceDirection,
    hops: int,
    max_nodes: int,
) -> SemanticWorldGraphSlice:
    graph = await get_semantic_world_graph(session, graph_id)
    return slice_semantic_world_graph(graph, root_node_id, direction, hops, max_nodes)


async def get_semantic_world_graph_timeline(
    session: AsyncSession,
    graph_id: UUID,
) -> SemanticWorldGraphEvidenceTimeline:
    graph = await get_semantic_world_graph(session, graph_id)
    snapshot = await get_world_snapshot(session, graph.world_model_id, graph.snapshot_id)
    return project_semantic_world_graph_timeline(graph, snapshot)


async def search_world_graph(
    session: AsyncSession,
    graph_id: UUID,
    query: str,
    limit: int,
) -> SemanticWorldGraphSearchResponse:
    graph = await get_semantic_world_graph(session, graph_id)
    return search_semantic_world_graph(graph, query, limit)


async def get_semantic_world_graph_edge_history(
    session: AsyncSession,
    graph_id: UUID,
    edge_id: UUID,
) -> SemanticWorldGraphEdgeHistory:
    current_record = await session.get(SemanticWorldGraphRecord, graph_id)
    if current_record is None:
        raise WorldGraphNotFoundError(f"semantic world graph {graph_id} was not found")
    current_graph = await _load_graph_detail(session, current_record)
    total_succeeded_graph_count = int(
        (
            await session.execute(
                select(func.count(SemanticWorldGraphRecord.id)).where(
                    SemanticWorldGraphRecord.world_model_id == current_record.world_model_id,
                    SemanticWorldGraphRecord.status == "succeeded",
                )
            )
        ).scalar_one()
    )
    recent_records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphRecord)
                .where(
                    SemanticWorldGraphRecord.world_model_id == current_record.world_model_id,
                    SemanticWorldGraphRecord.status == "succeeded",
                    SemanticWorldGraphRecord.id != current_record.id,
                )
                .order_by(SemanticWorldGraphRecord.created_at.desc(), SemanticWorldGraphRecord.id)
                .limit(11)
            )
        )
        .scalars()
        .all()
    )
    records = (current_record, *recent_records)
    graph_snapshots = []
    for record in records:
        graph = (
            current_graph
            if record.id == current_record.id
            else await _load_graph_detail(session, record)
        )
        snapshot = await get_world_snapshot(session, graph.world_model_id, graph.snapshot_id)
        graph_snapshots.append((graph, snapshot))
    return project_semantic_world_graph_edge_history(
        current_graph,
        edge_id,
        graph_snapshots,
        total_succeeded_graph_count,
    )


async def get_semantic_world_graph_persona_matches(
    session: AsyncSession,
    graph_id: UUID,
    node_id: UUID,
    dataset_id: UUID,
    limit: int,
) -> SemanticWorldGraphPersonaMatches:
    graph = await get_semantic_world_graph(session, graph_id)
    dataset, persona_count, personas = await load_persona_match_scan(session, dataset_id, 200)
    return match_graph_node_to_personas(
        graph,
        node_id,
        dataset,
        persona_count,
        personas,
        limit,
    )


def _graph_persona_cohort_origin(
    record: SemanticWorldGraphCohortOriginRecord,
    dataset: CohortDatasetRef,
) -> GraphPersonaCohortOrigin:
    selected_persona_ids = tuple(record.selected_persona_ids)
    actual_digest = calculate_graph_persona_cohort_origin_sha256(
        record.graph_id,
        record.graph_sha256,
        record.node_id,
        record.dataset_id,
        record.dataset_sha256,
        record.cohort_id,
        record.cohort_sha256,
        selected_persona_ids,
    )
    if actual_digest != record.origin_sha256:
        raise RuntimeError(f"graph Persona cohort origin {record.id} does not match origin_sha256")
    if record.dataset_id != dataset.id or record.dataset_sha256 != dataset.dataset_sha256:
        raise RuntimeError(f"graph Persona cohort origin {record.id} dataset is inconsistent")
    return GraphPersonaCohortOrigin(
        id=record.id,
        graph_id=record.graph_id,
        graph_sha256=record.graph_sha256,
        node_id=record.node_id,
        dataset=dataset,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        match_semantics=record.match_semantics,
        matcher_version=record.matcher_version,
        selected_persona_ids=selected_persona_ids,
        origin_sha256=record.origin_sha256,
        created_at=record.created_at,
    )


async def create_graph_persona_cohort(
    session: AsyncSession,
    graph_id: UUID,
    node_id: UUID,
    request: GraphPersonaCohortCreateRequest,
) -> GraphPersonaCohortCreation:
    """Atomically seal a cohort and its graph-guided selection lineage."""
    graph = await get_semantic_world_graph(session, graph_id)
    dataset, persona_count, personas = await load_persona_match_scan(
        session,
        request.dataset_id,
        200,
    )
    matches = match_graph_node_to_personas(
        graph,
        node_id,
        dataset,
        persona_count,
        personas,
        20,
    )
    candidate_ids = {match.persona.id for match in matches.matches}
    rejected_ids = tuple(
        persona_id for persona_id in request.persona_ids if persona_id not in candidate_ids
    )
    if rejected_ids:
        raise WorldGraphPersonaSelectionError(
            "cohort selection contains Personas outside the verified top-20 match result: "
            + ", ".join(str(persona_id) for persona_id in rejected_ids)
        )
    cohort = await ensure_cohort(session, request)
    if graph.graph_sha256 is None:
        raise RuntimeError("succeeded graph is missing graph_sha256")
    origin_sha256 = calculate_graph_persona_cohort_origin_sha256(
        graph.id,
        graph.graph_sha256,
        node_id,
        dataset.id,
        dataset.dataset_sha256,
        cohort.id,
        cohort.cohort_sha256,
        request.persona_ids,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_lock_key(origin_sha256)},
    )
    record = await session.scalar(
        select(SemanticWorldGraphCohortOriginRecord).where(
            SemanticWorldGraphCohortOriginRecord.origin_sha256 == origin_sha256
        )
    )
    if record is None:
        record = SemanticWorldGraphCohortOriginRecord(
            id=uuid4(),
            graph_id=graph.id,
            graph_sha256=graph.graph_sha256,
            node_id=node_id,
            dataset_id=dataset.id,
            dataset_sha256=dataset.dataset_sha256,
            cohort_id=cohort.id,
            cohort_sha256=cohort.cohort_sha256,
            match_semantics=GRAPH_PERSONA_MATCH_SEMANTICS,
            matcher_version=GRAPH_PERSONA_MATCHER_VERSION,
            selected_persona_ids=list(request.persona_ids),
            origin_sha256=origin_sha256,
            created_at=datetime.now(UTC),
        )
        session.add(record)
        await session.flush((record,))
    origin = _graph_persona_cohort_origin(record, dataset)
    result = GraphPersonaCohortCreation(origin=origin, cohort=cohort)
    await session.commit()
    return result


async def list_graph_persona_cohort_origins(
    session: AsyncSession,
    cohort_id: UUID,
    page: int,
    page_size: int,
) -> GraphPersonaCohortOriginsResponse:
    """Return one integrity-checked page of durable graph selection lineage."""
    cohort = await get_cohort(session, cohort_id)
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(SemanticWorldGraphCohortOriginRecord)
            .where(SemanticWorldGraphCohortOriginRecord.cohort_id == cohort_id)
        )
        or 0
    )
    offset = (page - 1) * page_size
    if total > 0 and offset >= total:
        raise WorldGraphPersonaOriginPageOutOfRangeError(
            f"graph Persona origin page {page} is beyond cohort {cohort_id} total {total}"
        )
    records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphCohortOriginRecord)
                .where(SemanticWorldGraphCohortOriginRecord.cohort_id == cohort_id)
                .order_by(
                    SemanticWorldGraphCohortOriginRecord.created_at.desc(),
                    SemanticWorldGraphCohortOriginRecord.id.asc(),
                )
                .offset(offset)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = tuple(_graph_persona_cohort_origin(record, cohort.dataset) for record in records)
    if any(
        item.cohort_id != cohort.id or item.cohort_sha256 != cohort.cohort_sha256 for item in items
    ):
        raise RuntimeError(f"graph Persona origins for cohort {cohort_id} are inconsistent")
    return GraphPersonaCohortOriginsResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


async def list_snapshot_semantic_world_graphs(
    session: AsyncSession,
    world_model_id: UUID,
    snapshot_id: UUID,
) -> SemanticWorldGraphsResponse:
    await get_world_snapshot(session, world_model_id, snapshot_id)
    records = tuple(
        (
            await session.execute(
                select(SemanticWorldGraphRecord)
                .where(
                    SemanticWorldGraphRecord.world_model_id == world_model_id,
                    SemanticWorldGraphRecord.snapshot_id == snapshot_id,
                )
                .order_by(SemanticWorldGraphRecord.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    items = tuple([await _load_graph_detail(session, record) for record in records])
    return SemanticWorldGraphsResponse(items=items, total=len(items))
