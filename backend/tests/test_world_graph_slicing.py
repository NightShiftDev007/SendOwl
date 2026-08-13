from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphNode,
    WorldGraphEvidenceReference,
)
from app.world_graphs.errors import WorldGraphNodeNotFoundError, WorldGraphNotReadyError
from app.world_graphs.slicing import slice_semantic_world_graph


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _evidence(position: int) -> WorldGraphEvidenceReference:
    return WorldGraphEvidenceReference(
        position=0,
        article_id=_uuid(90 + position),
        quote=f"evidence {position}",
        start_offset=position * 20,
        end_offset=position * 20 + len(f"evidence {position}"),
    )


def _succeeded_graph() -> SemanticWorldGraphDetail:
    nodes = tuple(
        SemanticWorldGraphNode(
            id=_uuid(index + 1),
            position=index,
            entity_type="concept",
            name=f"node-{index}",
            summary=f"node {index} summary",
            evidence=(_evidence(index),),
        )
        for index in range(5)
    )
    endpoints = ((0, 1), (0, 2), (1, 3), (2, 3), (4, 0))
    edges = tuple(
        SemanticWorldGraphEdge(
            id=_uuid(20 + position),
            position=position,
            source_node_id=nodes[source].id,
            target_node_id=nodes[target].id,
            relation_type="relates_to",
            fact=f"{source} relates to {target}",
            evidence=(_evidence(position + 10),),
        )
        for position, (source, target) in enumerate(endpoints)
    )
    return SemanticWorldGraphDetail(
        id=_uuid(50),
        world_model_id=_uuid(51),
        snapshot_id=_uuid(52),
        snapshot_sha256="a" * 64,
        status="succeeded",
        model_name="qwen-test",
        semantic_config_sha256="b" * 64,
        extraction_config_sha256="c" * 64,
        prompt_schema_version="world-graph-extraction/v1",
        input_sha256="d" * 64,
        graph_sha256="e" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        started_at=datetime(2026, 8, 12, 0, 0, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 12, 0, 0, 2, tzinfo=UTC),
        nodes=nodes,
        edges=edges,
        error_code=None,
        error_message=None,
    )


def test_slice_respects_direction_hops_and_original_order() -> None:
    graph = _succeeded_graph()

    outbound = slice_semantic_world_graph(graph, _uuid(1), "outbound", 2, 100)
    inbound = slice_semantic_world_graph(graph, _uuid(1), "inbound", 1, 100)

    assert tuple(node.position for node in outbound.nodes) == (0, 1, 2, 3)
    assert tuple(edge.position for edge in outbound.edges) == (0, 1, 2, 3)
    assert tuple(node.position for node in inbound.nodes) == (0, 4)
    assert tuple(edge.position for edge in inbound.edges) == (4,)
    assert outbound.truncated is False


def test_slice_is_deterministically_bounded_and_marks_truncation() -> None:
    graph = _succeeded_graph()

    result = slice_semantic_world_graph(graph, _uuid(1), "both", 3, 2)

    assert tuple(node.position for node in result.nodes) == (0, 1)
    assert tuple(edge.position for edge in result.edges) == (0,)
    assert result.truncated is True
    assert result.total_graph_node_count == 5
    assert result.total_graph_edge_count == 5


def test_slice_rejects_unknown_roots_and_non_terminal_graphs() -> None:
    graph = _succeeded_graph()

    with pytest.raises(WorldGraphNodeNotFoundError, match="does not belong"):
        slice_semantic_world_graph(graph, _uuid(999), "both", 1, 20)

    queued = graph.model_copy(
        update={
            "status": "queued",
            "started_at": None,
            "completed_at": None,
            "graph_sha256": None,
            "nodes": (),
            "edges": (),
        }
    )
    with pytest.raises(WorldGraphNotReadyError, match="only succeeded graphs"):
        slice_semantic_world_graph(queued, _uuid(1), "both", 1, 20)
