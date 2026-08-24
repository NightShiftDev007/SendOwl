"""Deterministic compilation of evidence-backed simulation context."""

import json
from hashlib import sha256

from app.research_projects.contracts import (
    ResearchProjectGraphRef,
    ResearchSimulationContext,
    SimulationContextEdge,
    SimulationContextMediaItem,
    SimulationContextNode,
    SimulationContextPolicyItem,
)
from app.world_graphs.contracts import SemanticWorldGraphDetail
from app.world_models.contracts import SnapshotDetail

MAX_MEDIA_ITEMS = 5
MAX_POLICY_ITEMS = 5
MAX_NODES = 10
MAX_EDGES = 12


def _clip(value: str, length: int) -> str:
    return value if len(value) <= length else value[:length]


def compile_simulation_context(
    snapshot: SnapshotDetail,
    graph: SemanticWorldGraphDetail,
) -> ResearchSimulationContext:
    """Compile one bounded context without inventing facts or changing source order."""
    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise ValueError("simulation context requires a succeeded semantic world graph")
    if (
        graph.world_model_id != snapshot.world_model_id
        or graph.snapshot_id != snapshot.id
        or graph.snapshot_sha256 != snapshot.snapshot_sha256
    ):
        raise ValueError("semantic world graph does not match the selected WorldSnapshot")

    selected_nodes = graph.nodes[:MAX_NODES]
    selected_node_ids = {node.id for node in selected_nodes}
    selected_edges = tuple(
        edge
        for edge in graph.edges
        if edge.source_node_id in selected_node_ids and edge.target_node_id in selected_node_ids
    )[:MAX_EDGES]
    node_names = {node.id: node.name for node in selected_nodes}
    text_was_truncated = (
        any(
            (len(item.title) > 120 or len(item.source_name) > 80 or len(item.excerpt) > 240)
            for item in snapshot.evidence[:MAX_MEDIA_ITEMS]
        )
        or any(
            len(item.title) > 120 or len(item.authority_name) > 80
            for item in snapshot.policy_evidence[:MAX_POLICY_ITEMS]
        )
        or any(
            len(node.name) > 80 or len(node.summary) > 180 or len(node.evidence[0].quote) > 180
            for node in selected_nodes
        )
        or any(
            len(node_names[edge.source_node_id]) > 60
            or len(node_names[edge.target_node_id]) > 60
            or len(edge.fact) > 160
            or len(edge.evidence[0].quote) > 160
            for edge in selected_edges
        )
    )
    graph_ref = ResearchProjectGraphRef(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
    )
    return ResearchSimulationContext(
        schema_version="sandowl-simulation-context/v1",
        snapshot_sha256=snapshot.snapshot_sha256,
        graph=graph_ref,
        media_items=tuple(
            SimulationContextMediaItem(
                position=position,
                article_id=item.article_id,
                title=_clip(item.title, 120),
                source_name=_clip(item.source_name, 80),
                excerpt=_clip(item.excerpt, 240),
            )
            for position, item in enumerate(snapshot.evidence[:MAX_MEDIA_ITEMS])
        ),
        policy_items=tuple(
            SimulationContextPolicyItem(
                position=position,
                policy_version_id=item.policy_version_id,
                title=_clip(item.title, 120),
                authority_name=_clip(item.authority_name, 80),
                jurisdiction_code=item.jurisdiction_code,
            )
            for position, item in enumerate(snapshot.policy_evidence[:MAX_POLICY_ITEMS])
        ),
        nodes=tuple(
            SimulationContextNode(
                position=position,
                node_id=node.id,
                entity_type=node.entity_type,
                name=_clip(node.name, 80),
                summary=_clip(node.summary, 180),
                evidence_quote=_clip(node.evidence[0].quote, 180),
            )
            for position, node in enumerate(selected_nodes)
        ),
        edges=tuple(
            SimulationContextEdge(
                position=position,
                edge_id=edge.id,
                source_name=_clip(node_names[edge.source_node_id], 60),
                relation_type=edge.relation_type,
                target_name=_clip(node_names[edge.target_node_id], 60),
                fact=_clip(edge.fact, 160),
                evidence_quote=_clip(edge.evidence[0].quote, 160),
            )
            for position, edge in enumerate(selected_edges)
        ),
        total_media_count=len(snapshot.evidence),
        total_policy_count=len(snapshot.policy_evidence),
        total_node_count=len(graph.nodes),
        total_edge_count=len(graph.edges),
        truncated=(
            len(snapshot.evidence) > MAX_MEDIA_ITEMS
            or len(snapshot.policy_evidence) > MAX_POLICY_ITEMS
            or len(graph.nodes) > MAX_NODES
            or len(graph.edges) > len(selected_edges)
            or text_was_truncated
        ),
    )


def canonical_simulation_context_json(context: ResearchSimulationContext) -> str:
    return json.dumps(
        context.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_simulation_context_sha256(context: ResearchSimulationContext) -> str:
    return sha256(canonical_simulation_context_json(context).encode("utf-8")).hexdigest()


__all__ = [
    "calculate_simulation_context_sha256",
    "canonical_simulation_context_json",
    "compile_simulation_context",
]
