"""Transactional enqueue and fail-closed reads for semantic world graphs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION as SEMANTIC_PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord
from app.world_graphs.contracts import (
    GRAPH_PROMPT_SCHEMA_VERSION,
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphEvidenceTimeline,
    SemanticWorldGraphNode,
    SemanticWorldGraphSlice,
    SemanticWorldGraphsResponse,
    WorldGraphEvidenceReference,
    WorldGraphSliceDirection,
)
from app.world_graphs.errors import WorldGraphNotFoundError, WorldGraphUnavailableError
from app.world_graphs.hashing import (
    calculate_extraction_config_sha256,
    calculate_graph_input_sha256,
    calculate_semantic_graph_sha256,
)
from app.world_graphs.models import (
    SemanticWorldGraphEdgeRecord,
    SemanticWorldGraphEvidenceRecord,
    SemanticWorldGraphNodeRecord,
    SemanticWorldGraphRecord,
)
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
                    SimulationWorkerHeartbeatRecord.platform_runtime_ready.is_(True),
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
