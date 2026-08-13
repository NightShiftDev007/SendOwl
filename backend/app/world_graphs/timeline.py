"""Pure evidence-publication timeline projection for immutable semantic graphs."""

from collections import defaultdict
from uuid import UUID

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEvidenceTimeline,
    SemanticWorldGraphTimelineItem,
)
from app.world_graphs.errors import WorldGraphNotReadyError
from app.world_models.contracts import SnapshotDetail


def project_semantic_world_graph_timeline(
    graph: SemanticWorldGraphDetail,
    snapshot: SnapshotDetail,
) -> SemanticWorldGraphEvidenceTimeline:
    """Group verified graph references by frozen article publication time."""

    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise WorldGraphNotReadyError(
            f"semantic world graph {graph.id} is {graph.status!r}; "
            "only succeeded graphs have an evidence timeline"
        )
    if snapshot.id != graph.snapshot_id or snapshot.snapshot_sha256 != graph.snapshot_sha256:
        raise RuntimeError(f"semantic world graph {graph.id} snapshot identity mismatch")
    node_ids: defaultdict[UUID, set[UUID]] = defaultdict(set)
    edge_ids: defaultdict[UUID, set[UUID]] = defaultdict(set)
    reference_counts: defaultdict[UUID, int] = defaultdict(int)
    for node in graph.nodes:
        for reference in node.evidence:
            node_ids[reference.article_id].add(node.id)
            reference_counts[reference.article_id] += 1
    for edge in graph.edges:
        for reference in edge.evidence:
            edge_ids[reference.article_id].add(edge.id)
            reference_counts[reference.article_id] += 1
    node_order = {node.id: node.position for node in graph.nodes}
    edge_order = {edge.id: edge.position for edge in graph.edges}
    evidence_by_id = {item.article_id: item for item in snapshot.evidence}
    referenced_article_ids = set(reference_counts)
    missing = referenced_article_ids - set(evidence_by_id)
    if missing:
        values = ", ".join(
            str(article_id) for article_id in sorted(missing, key=lambda value: value.int)
        )
        raise RuntimeError(f"semantic world graph {graph.id} references unknown articles: {values}")
    ordered_evidence = sorted(
        (evidence_by_id[article_id] for article_id in referenced_article_ids),
        key=lambda item: (item.published_at, item.article_id.int),
    )
    items = tuple(
        SemanticWorldGraphTimelineItem(
            position=position,
            article_id=evidence.article_id,
            title=evidence.title,
            source_name=evidence.source_name,
            published_at=evidence.published_at,
            captured_at=evidence.captured_at,
            country_code=evidence.country_code,
            node_ids=tuple(sorted(node_ids[evidence.article_id], key=node_order.__getitem__)),
            edge_ids=tuple(sorted(edge_ids[evidence.article_id], key=edge_order.__getitem__)),
            evidence_reference_count=reference_counts[evidence.article_id],
        )
        for position, evidence in enumerate(ordered_evidence)
    )
    return SemanticWorldGraphEvidenceTimeline(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        temporal_semantics="evidence_publication_time_not_fact_validity",
        items=items,
    )
