"""Strict contracts for the self-hosted evidence world graph projection."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.media.contracts import CountryCode
from app.shared.contracts import ContractModel, Sha256Digest

type GraphSchemaVersion = Literal["evidence-world-graph/v1"]
type GraphProvider = Literal["postgres_projection"]
type GraphNodeKind = Literal["world_snapshot", "article", "source", "country"]
type GraphEdgeKind = Literal["contains_evidence", "published_by", "located_in"]
type GraphLabel = Annotated[str, StringConstraints(min_length=1, max_length=300)]
type GraphDetailText = Annotated[str, StringConstraints(min_length=1, max_length=280)]


class EvidenceGraphNode(ContractModel):
    """One deterministic node backed only by frozen snapshot evidence."""

    id: UUID
    position: Annotated[int, Field(ge=0)]
    kind: GraphNodeKind
    label: GraphLabel
    detail: GraphDetailText | None
    article_id: UUID | None
    country_code: CountryCode | None

    @model_validator(mode="after")
    def validate_kind_specific_reference(self) -> Self:
        if self.kind == "article" and self.article_id is None:
            raise ValueError("article graph nodes must reference one frozen article_id")
        if self.kind != "article" and self.article_id is not None:
            raise ValueError("only article graph nodes may reference article_id")
        if self.kind == "country" and self.country_code is None:
            raise ValueError("country graph nodes must include country_code")
        if self.kind != "country" and self.country_code is not None:
            raise ValueError("only country graph nodes may include country_code")
        return self


class EvidenceGraphEdge(ContractModel):
    """One direct, non-inferred relationship in the evidence graph."""

    id: UUID
    position: Annotated[int, Field(ge=0)]
    kind: GraphEdgeKind
    source_node_id: UUID
    target_node_id: UUID
    article_id: UUID


class EvidenceWorldGraph(ContractModel):
    """Content-addressed graph projection of one immutable WorldSnapshot."""

    id: UUID
    schema_version: GraphSchemaVersion
    provider: GraphProvider
    world_model_id: UUID
    snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    graph_sha256: Sha256Digest
    nodes: Annotated[tuple[EvidenceGraphNode, ...], Field(min_length=3)]
    edges: Annotated[tuple[EvidenceGraphEdge, ...], Field(min_length=2)]

    @model_validator(mode="after")
    def validate_graph_integrity(self) -> Self:
        node_ids = tuple(node.id for node in self.nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("evidence graph node IDs must be unique")
        if tuple(node.position for node in self.nodes) != tuple(range(len(self.nodes))):
            raise ValueError("evidence graph node positions must be contiguous from zero")
        if tuple(edge.position for edge in self.edges) != tuple(range(len(self.edges))):
            raise ValueError("evidence graph edge positions must be contiguous from zero")
        known_node_ids = set(node_ids)
        for edge in self.edges:
            if (
                edge.source_node_id not in known_node_ids
                or edge.target_node_id not in known_node_ids
            ):
                raise ValueError("evidence graph edges must reference nodes in the same graph")
        return self
