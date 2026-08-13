from datetime import UTC, datetime
from uuid import UUID

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphNode,
    WorldGraphEvidenceReference,
)
from app.world_graphs.timeline import project_semantic_world_graph_timeline
from app.world_models.contracts import SnapshotDetail, SnapshotEvidence


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _snapshot() -> SnapshotDetail:
    evidence = tuple(
        SnapshotEvidence(
            article_id=_uuid(article),
            source_name=f"Source {article}",
            original_url=f"https://example.com/{article}",
            title=f"Article {article}",
            published_at=datetime(2026, 8, day, tzinfo=UTC),
            captured_at=datetime(2026, 8, 12, tzinfo=UTC),
            country_code="CN",
            excerpt=f"Article {article} excerpt",
            captured_text_sha256=f"{article % 10}" * 64,
        )
        for article, day in ((101, 11), (102, 10))
    )
    return SnapshotDetail(
        id=_uuid(90),
        world_model_id=_uuid(91),
        version=1,
        verification="human_confirmed",
        snapshot_sha256="a" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        evidence=evidence,
    )


def _reference(article: int, quote: str) -> WorldGraphEvidenceReference:
    return WorldGraphEvidenceReference(
        position=0,
        article_id=_uuid(article),
        quote=quote,
        start_offset=0,
        end_offset=len(quote),
    )


def _graph(snapshot: SnapshotDetail) -> SemanticWorldGraphDetail:
    first = SemanticWorldGraphNode(
        id=_uuid(1),
        position=0,
        entity_type="policy",
        name="Policy",
        summary="Policy summary",
        evidence=(_reference(101, "policy evidence"),),
    )
    second = SemanticWorldGraphNode(
        id=_uuid(2),
        position=1,
        entity_type="organization",
        name="Agency",
        summary="Agency summary",
        evidence=(_reference(102, "agency evidence"),),
    )
    edge = SemanticWorldGraphEdge(
        id=_uuid(3),
        position=0,
        source_node_id=second.id,
        target_node_id=first.id,
        relation_type="implements",
        fact="Agency implements policy",
        evidence=(_reference(102, "relation evidence"),),
    )
    return SemanticWorldGraphDetail(
        id=_uuid(80),
        world_model_id=snapshot.world_model_id,
        snapshot_id=snapshot.id,
        snapshot_sha256=snapshot.snapshot_sha256,
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
        nodes=(first, second),
        edges=(edge,),
        error_code=None,
        error_message=None,
    )


def test_timeline_orders_frozen_articles_and_groups_verified_objects() -> None:
    snapshot = _snapshot()
    graph = _graph(snapshot)

    result = project_semantic_world_graph_timeline(graph, snapshot)

    assert result.temporal_semantics == "evidence_publication_time_not_fact_validity"
    assert tuple(item.article_id for item in result.items) == (_uuid(102), _uuid(101))
    assert result.items[0].node_ids == (_uuid(2),)
    assert result.items[0].edge_ids == (_uuid(3),)
    assert result.items[0].evidence_reference_count == 2
    assert result.items[1].node_ids == (_uuid(1),)
    assert result.items[1].edge_ids == ()
