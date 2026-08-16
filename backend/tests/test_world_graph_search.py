from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphNode,
    WorldGraphEvidenceReference,
)
from app.world_graphs.errors import WorldGraphNotReadyError
from app.world_graphs.search import search_semantic_world_graph


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _evidence(article: int, quote: str) -> WorldGraphEvidenceReference:
    return WorldGraphEvidenceReference(
        position=0,
        article_id=_uuid(article),
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )


def _graph() -> SemanticWorldGraphDetail:
    nodes = (
        SemanticWorldGraphNode(
            id=_uuid(1),
            position=0,
            entity_type="organization",
            name="Blue Harbor Council",
            summary="A regional policy council.",
            evidence=(_evidence(91, "Blue Harbor Council announced the clean port policy."),),
        ),
        SemanticWorldGraphNode(
            id=_uuid(2),
            position=1,
            entity_type="policy",
            name="Clean Port Policy",
            summary="A maritime emissions policy.",
            evidence=(_evidence(92, "The clean port policy starts next year."),),
        ),
    )
    edges = (
        SemanticWorldGraphEdge(
            id=_uuid(3),
            position=0,
            source_node_id=nodes[0].id,
            target_node_id=nodes[1].id,
            relation_type="announced",
            fact="Blue Harbor Council announced the Clean Port Policy.",
            evidence=(_evidence(91, "The council announced the clean port policy."),),
        ),
    )
    return SemanticWorldGraphDetail(
        id=_uuid(10),
        world_model_id=_uuid(11),
        snapshot_id=_uuid(12),
        snapshot_sha256="a" * 64,
        status="succeeded",
        model_name="qwen-test",
        semantic_config_sha256="b" * 64,
        extraction_config_sha256="c" * 64,
        prompt_schema_version="world-graph-extraction/v1",
        input_sha256="d" * 64,
        graph_sha256="e" * 64,
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
        started_at=datetime(2026, 8, 14, 0, 0, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 14, 0, 0, 2, tzinfo=UTC),
        nodes=nodes,
        edges=edges,
        error_code=None,
        error_message=None,
    )


def test_search_orders_exact_entities_before_fact_and_evidence_matches() -> None:
    result = search_semantic_world_graph(_graph(), "clean port policy", 20)

    assert result.total_match_count == 3
    assert tuple(item.kind for item in result.results) == ("node", "node", "edge")
    assert result.results[0].matched_fields == ("name", "evidence_quote")
    assert result.truncated is False
    assert result.search_semantics == "casefolded_lexical_substring"


def test_search_is_bounded_and_rejects_nonterminal_graphs() -> None:
    graph = _graph()
    bounded = search_semantic_world_graph(graph, "policy", 1)
    assert len(bounded.results) == 1
    assert bounded.total_match_count == 3
    assert bounded.truncated is True

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
    with pytest.raises(WorldGraphNotReadyError, match="cannot be searched"):
        search_semantic_world_graph(queued, "policy", 20)
