"""Strict API contracts for Qwen-extracted semantic world graphs."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.media.contracts import CountryCode
from app.shared.contracts import ContractModel, NonEmptyText, Sha256Digest

GRAPH_PROMPT_SCHEMA_VERSION = "world-graph-extraction/v1"

type WorldGraphStatus = Literal["queued", "running", "succeeded", "failed"]
type WorldGraphSliceDirection = Literal["both", "outbound", "inbound"]
type WorldGraphEntityType = Literal[
    "organization",
    "person",
    "location",
    "policy",
    "event",
    "concept",
]
type EntityName = Annotated[str, StringConstraints(min_length=1, max_length=200)]
type EntitySummary = Annotated[str, StringConstraints(min_length=1, max_length=500)]
type RelationType = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
type EvidenceQuote = Annotated[str, StringConstraints(min_length=1, max_length=500)]
type SafeErrorCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]
type SafeErrorMessage = Annotated[str, StringConstraints(min_length=1, max_length=500)]


class WorldGraphEvidenceReference(ContractModel):
    """Exact verbatim evidence supporting one node or edge."""

    position: Annotated[int, Field(ge=0)]
    article_id: UUID
    quote: EvidenceQuote
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end_offset <= self.start_offset:
            raise ValueError("evidence end_offset must be greater than start_offset")
        if self.end_offset - self.start_offset != len(self.quote):
            raise ValueError("evidence offsets must span the exact quote length")
        return self


class SemanticWorldGraphNode(ContractModel):
    """One normalized entity with at least one frozen evidence reference."""

    id: UUID
    position: Annotated[int, Field(ge=0)]
    entity_type: WorldGraphEntityType
    name: EntityName
    summary: EntitySummary
    evidence: Annotated[tuple[WorldGraphEvidenceReference, ...], Field(min_length=1, max_length=20)]


class SemanticWorldGraphEdge(ContractModel):
    """One directed, evidence-backed relationship between graph nodes."""

    id: UUID
    position: Annotated[int, Field(ge=0)]
    source_node_id: UUID
    target_node_id: UUID
    relation_type: RelationType
    fact: EntitySummary
    evidence: Annotated[tuple[WorldGraphEvidenceReference, ...], Field(min_length=1, max_length=20)]


class SemanticWorldGraphDetail(ContractModel):
    """Durable extraction job and its immutable terminal graph."""

    id: UUID
    world_model_id: UUID
    snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    status: WorldGraphStatus
    model_name: EntityName
    semantic_config_sha256: Sha256Digest
    extraction_config_sha256: Sha256Digest
    prompt_schema_version: Literal["world-graph-extraction/v1"]
    input_sha256: Sha256Digest
    graph_sha256: Sha256Digest | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    nodes: Annotated[tuple[SemanticWorldGraphNode, ...], Field(max_length=500)]
    edges: Annotated[tuple[SemanticWorldGraphEdge, ...], Field(max_length=2000)]
    error_code: SafeErrorCode | None
    error_message: SafeErrorMessage | None

    @model_validator(mode="after")
    def validate_state_and_graph(self) -> Self:
        node_positions = tuple(node.position for node in self.nodes)
        edge_positions = tuple(edge.position for edge in self.edges)
        if node_positions != tuple(range(len(self.nodes))):
            raise ValueError("semantic graph node positions must be contiguous from zero")
        if edge_positions != tuple(range(len(self.edges))):
            raise ValueError("semantic graph edge positions must be contiguous from zero")
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("semantic graph node IDs must be unique")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("semantic graph edges must reference nodes in the same graph")
        if self.status == "queued":
            valid = (
                self.started_at is None
                and self.completed_at is None
                and self.graph_sha256 is None
                and not self.nodes
                and not self.edges
                and self.error_code is None
                and self.error_message is None
            )
        elif self.status == "running":
            valid = (
                self.started_at is not None
                and self.completed_at is None
                and self.graph_sha256 is None
                and not self.nodes
                and not self.edges
                and self.error_code is None
                and self.error_message is None
            )
        elif self.status == "succeeded":
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.graph_sha256 is not None
                and bool(self.nodes)
                and self.error_code is None
                and self.error_message is None
            )
        else:
            valid = (
                self.started_at is not None
                and self.completed_at is not None
                and self.graph_sha256 is None
                and not self.nodes
                and not self.edges
                and self.error_code is not None
                and self.error_message is not None
            )
        if not valid:
            raise ValueError(f"semantic graph fields do not match {self.status!r} state")
        return self


class SemanticWorldGraphsResponse(ContractModel):
    items: tuple[SemanticWorldGraphDetail, ...]
    total: Annotated[int, Field(ge=0)]


class SemanticWorldGraphSlice(ContractModel):
    """Bounded, deterministic neighborhood view over one immutable graph."""

    graph_id: UUID
    graph_sha256: Sha256Digest
    root_node_id: UUID
    direction: WorldGraphSliceDirection
    hops: Annotated[int, Field(ge=1, le=3)]
    max_nodes: Annotated[int, Field(ge=2, le=100)]
    truncated: bool
    total_graph_node_count: Annotated[int, Field(ge=1, le=500)]
    total_graph_edge_count: Annotated[int, Field(ge=0, le=2000)]
    nodes: Annotated[tuple[SemanticWorldGraphNode, ...], Field(min_length=1, max_length=100)]
    edges: Annotated[tuple[SemanticWorldGraphEdge, ...], Field(max_length=2000)]

    @model_validator(mode="after")
    def validate_slice(self) -> Self:
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("world graph slice node IDs must be unique")
        if self.root_node_id not in node_ids:
            raise ValueError("world graph slice must contain its root node")
        if any(
            edge.source_node_id not in node_ids or edge.target_node_id not in node_ids
            for edge in self.edges
        ):
            raise ValueError("world graph slice edges must remain inside the selected nodes")
        if len({edge.id for edge in self.edges}) != len(self.edges):
            raise ValueError("world graph slice edge IDs must be unique")
        if len(self.nodes) > self.total_graph_node_count:
            raise ValueError("world graph slice cannot contain more nodes than its graph")
        if len(self.edges) > self.total_graph_edge_count:
            raise ValueError("world graph slice cannot contain more edges than its graph")
        return self


class SemanticWorldGraphTimelineItem(ContractModel):
    """Graph objects supported by one frozen article, ordered by publication time."""

    position: Annotated[int, Field(ge=0, le=49)]
    article_id: UUID
    title: NonEmptyText
    source_name: NonEmptyText
    published_at: AwareDatetime
    captured_at: AwareDatetime
    country_code: CountryCode | None
    node_ids: Annotated[tuple[UUID, ...], Field(max_length=500)]
    edge_ids: Annotated[tuple[UUID, ...], Field(max_length=2000)]
    evidence_reference_count: Annotated[int, Field(ge=1, le=50000)]

    @model_validator(mode="after")
    def validate_objects(self) -> Self:
        if not self.node_ids and not self.edge_ids:
            raise ValueError("world graph timeline item must reference a node or edge")
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("world graph timeline node IDs must be unique")
        if len(set(self.edge_ids)) != len(self.edge_ids):
            raise ValueError("world graph timeline edge IDs must be unique")
        return self


class SemanticWorldGraphEvidenceTimeline(ContractModel):
    """Publication-time lens over evidence, not a claim-validity timeline."""

    graph_id: UUID
    graph_sha256: Sha256Digest
    temporal_semantics: Literal["evidence_publication_time_not_fact_validity"]
    items: Annotated[tuple[SemanticWorldGraphTimelineItem, ...], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def validate_timeline(self) -> Self:
        if tuple(item.position for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("world graph timeline positions must be contiguous from zero")
        if len({item.article_id for item in self.items}) != len(self.items):
            raise ValueError("world graph timeline article IDs must be unique")
        ordering = tuple((item.published_at, item.article_id.int) for item in self.items)
        if ordering != tuple(sorted(ordering)):
            raise ValueError(
                "world graph timeline must be ordered by publication time and article ID"
            )
        return self
