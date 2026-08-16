from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphNode,
    WorldGraphEvidenceReference,
)
from app.world_graphs.errors import WorldGraphEdgeNotFoundError, WorldGraphNotReadyError
from app.world_graphs.history import project_semantic_world_graph_edge_history
from app.world_models.contracts import SnapshotDetail, SnapshotEvidence


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _graph(version: int, fact: str, graph_id: int, edge_id: int) -> SemanticWorldGraphDetail:
    article_id = _uuid(100 + version)
    quote = f"Evidence for version {version}."
    evidence = WorldGraphEvidenceReference(
        position=0,
        article_id=article_id,
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )
    nodes = (
        SemanticWorldGraphNode(
            id=_uuid(graph_id + 1),
            position=0,
            entity_type="organization",
            name="Harbor Council",
            summary="A council.",
            evidence=(evidence,),
        ),
        SemanticWorldGraphNode(
            id=_uuid(graph_id + 2),
            position=1,
            entity_type="policy",
            name="Clean Port Policy",
            summary="A policy.",
            evidence=(evidence,),
        ),
    )
    edge = SemanticWorldGraphEdge(
        id=_uuid(edge_id),
        position=0,
        source_node_id=nodes[0].id,
        target_node_id=nodes[1].id,
        relation_type="announced",
        fact=fact,
        evidence=(evidence,),
    )
    created_at = datetime(2026, 8, 10 + version, tzinfo=UTC)
    return SemanticWorldGraphDetail(
        id=_uuid(graph_id),
        world_model_id=_uuid(1),
        snapshot_id=_uuid(10 + version),
        snapshot_sha256=f"{version:x}" * 64,
        status="succeeded",
        model_name="qwen-test",
        semantic_config_sha256="a" * 64,
        extraction_config_sha256="b" * 64,
        prompt_schema_version="world-graph-extraction/v1",
        input_sha256="c" * 64,
        graph_sha256=f"{version + 5:x}" * 64,
        created_at=created_at,
        started_at=created_at + timedelta(seconds=1),
        completed_at=created_at + timedelta(seconds=2),
        nodes=nodes,
        edges=(edge,),
        error_code=None,
        error_message=None,
    )


def _snapshot(graph: SemanticWorldGraphDetail, version: int) -> SnapshotDetail:
    article_id = graph.edges[0].evidence[0].article_id
    published_at = datetime(2026, 8, version, 8, tzinfo=UTC)
    return SnapshotDetail(
        id=graph.snapshot_id,
        world_model_id=graph.world_model_id,
        version=version,
        verification="human_confirmed",
        snapshot_sha256=graph.snapshot_sha256,
        created_at=graph.created_at - timedelta(hours=1),
        evidence=(
            SnapshotEvidence(
                article_id=article_id,
                source_name="Example News",
                original_url=f"https://example.com/{version}",
                title=f"Evidence {version}",
                published_at=published_at,
                captured_at=published_at + timedelta(minutes=5),
                country_code="CN",
                excerpt="Frozen evidence.",
                captured_text_sha256="d" * 64,
            ),
        ),
        policy_evidence=(),
    )


def test_edge_history_tracks_exact_signature_without_claiming_fact_validity() -> None:
    first = _graph(1, "Harbor Council announced the Clean Port Policy.", 20, 30)
    second = _graph(2, "harbor council announced the clean port policy.", 40, 50)
    paraphrase = _graph(3, "The council introduced a clean-port program.", 60, 70)

    result = project_semantic_world_graph_edge_history(
        second,
        second.edges[0].id,
        (
            (paraphrase, _snapshot(paraphrase, 3)),
            (first, _snapshot(first, 1)),
            (second, _snapshot(second, 2)),
        ),
        4,
    )

    assert tuple(item.snapshot_version for item in result.items) == (1, 2)
    assert result.items[1].edge_id == second.edges[0].id
    assert result.observation_semantics == "cross_snapshot_exact_signature_not_fact_validity"
    assert result.inspected_graph_count == 3
    assert result.total_succeeded_graph_count == 4
    assert result.truncated is True
    assert len(result.limitations) == 3


def test_edge_history_rejects_missing_edge_and_nonterminal_graph() -> None:
    graph = _graph(1, "Harbor Council announced the Clean Port Policy.", 20, 30)
    snapshot = _snapshot(graph, 1)
    with pytest.raises(WorldGraphEdgeNotFoundError):
        project_semantic_world_graph_edge_history(graph, _uuid(999), ((graph, snapshot),), 1)

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
    with pytest.raises(WorldGraphNotReadyError):
        project_semantic_world_graph_edge_history(queued, graph.edges[0].id, (), 1)
