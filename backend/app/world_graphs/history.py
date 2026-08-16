"""Pure cross-snapshot observation history for immutable semantic graph edges."""

from collections.abc import Sequence
from uuid import UUID

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphEdgeHistory,
    SemanticWorldGraphEdgeObservation,
    SemanticWorldGraphEdgeSignature,
    SemanticWorldGraphNode,
)
from app.world_graphs.errors import WorldGraphEdgeNotFoundError, WorldGraphNotReadyError
from app.world_models.contracts import SnapshotDetail

HISTORY_LIMITATIONS = (
    "Occurrences use exact case-folded entity, relation, and fact text; "
    "paraphrases are not merged.",
    "Evidence publication time shows when supporting articles appeared, "
    "not when a fact became valid.",
    "Missing occurrences can reflect extraction or snapshot coverage differences, "
    "not factual invalidation.",
)


def _nodes_by_id(graph: SemanticWorldGraphDetail) -> dict[UUID, SemanticWorldGraphNode]:
    return {node.id: node for node in graph.nodes}


def _signature(
    edge: SemanticWorldGraphEdge,
    nodes: dict[UUID, SemanticWorldGraphNode],
) -> SemanticWorldGraphEdgeSignature:
    source = nodes[edge.source_node_id]
    target = nodes[edge.target_node_id]
    return SemanticWorldGraphEdgeSignature(
        source_entity_type=source.entity_type,
        source_name=source.name,
        relation_type=edge.relation_type,
        target_entity_type=target.entity_type,
        target_name=target.name,
        fact=edge.fact,
    )


def _signature_key(signature: SemanticWorldGraphEdgeSignature) -> tuple[str, ...]:
    return (
        signature.source_entity_type,
        signature.source_name.casefold(),
        signature.relation_type,
        signature.target_entity_type,
        signature.target_name.casefold(),
        signature.fact.casefold(),
    )


def _matching_edges(
    graph: SemanticWorldGraphDetail,
    expected: SemanticWorldGraphEdgeSignature,
) -> tuple[SemanticWorldGraphEdge, ...]:
    nodes = _nodes_by_id(graph)
    expected_key = _signature_key(expected)
    return tuple(
        edge for edge in graph.edges if _signature_key(_signature(edge, nodes)) == expected_key
    )


def project_semantic_world_graph_edge_history(
    current_graph: SemanticWorldGraphDetail,
    edge_id: UUID,
    graph_snapshots: Sequence[tuple[SemanticWorldGraphDetail, SnapshotDetail]],
    total_succeeded_graph_count: int,
) -> SemanticWorldGraphEdgeHistory:
    if current_graph.status != "succeeded" or current_graph.graph_sha256 is None:
        raise WorldGraphNotReadyError(
            "only succeeded semantic graphs have edge observation history"
        )
    current_edge = next((edge for edge in current_graph.edges if edge.id == edge_id), None)
    if current_edge is None:
        raise WorldGraphEdgeNotFoundError(
            f"semantic world graph edge {edge_id} was not found in graph {current_graph.id}"
        )
    signature = _signature(current_edge, _nodes_by_id(current_graph))
    observations: list[SemanticWorldGraphEdgeObservation] = []
    for graph, snapshot in graph_snapshots:
        if graph.status != "succeeded" or graph.graph_sha256 is None or graph.completed_at is None:
            raise WorldGraphNotReadyError(
                "edge history candidates must be succeeded semantic graphs"
            )
        if graph.world_model_id != current_graph.world_model_id:
            raise ValueError("edge history candidates must belong to one world model")
        if snapshot.id != graph.snapshot_id or snapshot.snapshot_sha256 != graph.snapshot_sha256:
            raise ValueError("edge history graph and snapshot identities do not match")
        evidence_by_id = {item.article_id: item for item in snapshot.evidence}
        matching = _matching_edges(graph, signature)
        selected_edges = (
            tuple(edge for edge in matching if edge.id == edge_id)
            if graph.id == current_graph.id
            else matching[:1]
        )
        for edge in selected_edges:
            article_ids = tuple(dict.fromkeys(reference.article_id for reference in edge.evidence))
            try:
                publication_times = tuple(
                    evidence_by_id[article_id].published_at for article_id in article_ids
                )
            except KeyError as error:
                raise ValueError(
                    "edge history evidence is missing from its frozen snapshot"
                ) from error
            observations.append(
                SemanticWorldGraphEdgeObservation(
                    position=0,
                    graph_id=graph.id,
                    graph_sha256=graph.graph_sha256,
                    graph_created_at=graph.created_at,
                    graph_completed_at=graph.completed_at,
                    snapshot_id=snapshot.id,
                    snapshot_sha256=snapshot.snapshot_sha256,
                    snapshot_version=snapshot.version,
                    edge_id=edge.id,
                    evidence_article_ids=article_ids,
                    evidence_published_from=min(publication_times),
                    evidence_published_through=max(publication_times),
                )
            )
    ordered = sorted(
        observations,
        key=lambda item: (item.snapshot_version, item.graph_created_at, item.edge_id.int),
    )
    if not any(item.graph_id == current_graph.id and item.edge_id == edge_id for item in ordered):
        raise ValueError("edge history candidates do not contain the requested graph")
    positioned = tuple(
        item.model_copy(update={"position": position}) for position, item in enumerate(ordered)
    )
    return SemanticWorldGraphEdgeHistory(
        graph_id=current_graph.id,
        graph_sha256=current_graph.graph_sha256,
        edge_id=edge_id,
        observation_semantics="cross_snapshot_exact_signature_not_fact_validity",
        signature=signature,
        inspected_graph_count=len(graph_snapshots),
        total_succeeded_graph_count=total_succeeded_graph_count,
        truncated=total_succeeded_graph_count > len(graph_snapshots),
        items=positioned,
        limitations=HISTORY_LIMITATIONS,
    )
