"""Deterministic PostgreSQL-backed projection of frozen evidence into a graph."""

import json
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.world_models.contracts import SnapshotDetail, SnapshotEvidence
from app.world_models.graph_contracts import (
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceWorldGraph,
)
from app.world_models.repository import get_world_snapshot

GRAPH_SCHEMA_VERSION = "evidence-world-graph/v1"
GRAPH_PROVIDER = "postgres_projection"


def _stable_uuid(graph_id: UUID, kind: str, value: str) -> UUID:
    return uuid5(graph_id, f"{kind}\0{value}")


def _source_names(evidence: tuple[SnapshotEvidence, ...]) -> tuple[str, ...]:
    return tuple(
        sorted({item.source_name for item in evidence}, key=lambda value: (value.casefold(), value))
    )


def _country_codes(evidence: tuple[SnapshotEvidence, ...]) -> tuple[str, ...]:
    return tuple(sorted({item.country_code for item in evidence if item.country_code is not None}))


def _build_nodes(snapshot: SnapshotDetail, graph_id: UUID) -> tuple[EvidenceGraphNode, ...]:
    nodes: list[EvidenceGraphNode] = [
        EvidenceGraphNode(
            id=_stable_uuid(graph_id, "snapshot", str(snapshot.id)),
            position=0,
            kind="world_snapshot",
            label=f"Reality snapshot v{snapshot.version}",
            detail=f"{len(snapshot.evidence)} frozen evidence articles",
            article_id=None,
            country_code=None,
        )
    ]
    for item in snapshot.evidence:
        nodes.append(
            EvidenceGraphNode(
                id=_stable_uuid(graph_id, "article", str(item.article_id)),
                position=len(nodes),
                kind="article",
                label=item.title[:300],
                detail=item.excerpt,
                article_id=item.article_id,
                country_code=None,
            )
        )
    for source_name in _source_names(snapshot.evidence):
        nodes.append(
            EvidenceGraphNode(
                id=_stable_uuid(graph_id, "source", source_name),
                position=len(nodes),
                kind="source",
                label=source_name[:300],
                detail=None,
                article_id=None,
                country_code=None,
            )
        )
    for country_code in _country_codes(snapshot.evidence):
        nodes.append(
            EvidenceGraphNode(
                id=_stable_uuid(graph_id, "country", country_code),
                position=len(nodes),
                kind="country",
                label=country_code,
                detail=None,
                article_id=None,
                country_code=country_code,
            )
        )
    return tuple(nodes)


def _build_edges(
    snapshot: SnapshotDetail,
    graph_id: UUID,
    nodes: tuple[EvidenceGraphNode, ...],
) -> tuple[EvidenceGraphEdge, ...]:
    root_id = nodes[0].id
    source_id_by_name = {node.label: node.id for node in nodes if node.kind == "source"}
    country_id_by_code = {node.country_code: node.id for node in nodes if node.kind == "country"}
    edges: list[EvidenceGraphEdge] = []
    for item in snapshot.evidence:
        article_node_id = _stable_uuid(graph_id, "article", str(item.article_id))
        relationships = [
            ("contains_evidence", root_id, article_node_id),
            ("published_by", article_node_id, source_id_by_name[item.source_name]),
        ]
        if item.country_code is not None:
            relationships.append(
                ("located_in", article_node_id, country_id_by_code[item.country_code])
            )
        for kind, source_node_id, target_node_id in relationships:
            edge_position = len(edges)
            edges.append(
                EvidenceGraphEdge(
                    id=_stable_uuid(
                        graph_id,
                        "edge",
                        f"{edge_position}\0{kind}\0{source_node_id}\0{target_node_id}",
                    ),
                    position=edge_position,
                    kind=kind,
                    source_node_id=source_node_id,
                    target_node_id=target_node_id,
                    article_id=item.article_id,
                )
            )
    return tuple(edges)


def _canonical_graph_json(
    world_model_id: UUID,
    snapshot: SnapshotDetail,
    nodes: tuple[EvidenceGraphNode, ...],
    edges: tuple[EvidenceGraphEdge, ...],
) -> str:
    payload = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "provider": GRAPH_PROVIDER,
        "world_model_id": str(world_model_id),
        "snapshot_id": str(snapshot.id),
        "snapshot_sha256": snapshot.snapshot_sha256,
        "nodes": [node.model_dump(mode="json") for node in nodes],
        "edges": [edge.model_dump(mode="json") for edge in edges],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def project_evidence_world_graph(
    world_model_id: UUID,
    snapshot: SnapshotDetail,
) -> EvidenceWorldGraph:
    """Build a stable graph using direct frozen facts only; no inferred relationships."""
    graph_id = uuid5(NAMESPACE_URL, f"{GRAPH_SCHEMA_VERSION}\0{snapshot.id}")
    nodes = _build_nodes(snapshot, graph_id)
    edges = _build_edges(snapshot, graph_id, nodes)
    graph_sha256 = sha256(
        _canonical_graph_json(world_model_id, snapshot, nodes, edges).encode("utf-8")
    ).hexdigest()
    return EvidenceWorldGraph(
        id=graph_id,
        schema_version=GRAPH_SCHEMA_VERSION,
        provider=GRAPH_PROVIDER,
        world_model_id=world_model_id,
        snapshot_id=snapshot.id,
        snapshot_sha256=snapshot.snapshot_sha256,
        graph_sha256=graph_sha256,
        nodes=nodes,
        edges=edges,
    )


async def get_evidence_world_graph(
    session: AsyncSession,
    world_model_id: UUID,
    snapshot_id: UUID,
) -> EvidenceWorldGraph:
    snapshot = await get_world_snapshot(session, world_model_id, snapshot_id)
    return project_evidence_world_graph(world_model_id, snapshot)
