"""Strict API contracts for Qwen-extracted semantic world graphs."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.media.contracts import CountryCode
from app.populations.contracts import (
    CohortCreateRequest,
    CohortDatasetRef,
    CohortDetail,
    PersonaAttribute,
    PersonaSummary,
)
from app.shared.contracts import ContractModel, NonEmptyText, Sha256Digest

GRAPH_PROMPT_SCHEMA_VERSION = "world-graph-extraction/v1"

type WorldGraphStatus = Literal["queued", "running", "succeeded", "failed"]
type WorldGraphSliceDirection = Literal["both", "outbound", "inbound"]
type WorldGraphSearchMatchField = Literal[
    "name",
    "summary",
    "entity_type",
    "relation_type",
    "fact",
    "evidence_quote",
]
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


class SemanticWorldGraphEdgeSignature(ContractModel):
    """Exact normalized relationship identity used across immutable graph versions."""

    source_entity_type: WorldGraphEntityType
    source_name: EntityName
    relation_type: RelationType
    target_entity_type: WorldGraphEntityType
    target_name: EntityName
    fact: EntitySummary


class SemanticWorldGraphEdgeObservation(ContractModel):
    """One evidence-backed occurrence of an exact edge signature."""

    position: Annotated[int, Field(ge=0, le=49)]
    graph_id: UUID
    graph_sha256: Sha256Digest
    graph_created_at: AwareDatetime
    graph_completed_at: AwareDatetime
    snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    snapshot_version: Annotated[int, Field(ge=1)]
    edge_id: UUID
    evidence_article_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=20)]
    evidence_published_from: AwareDatetime
    evidence_published_through: AwareDatetime

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.graph_completed_at < self.graph_created_at:
            raise ValueError("edge observation graph completion cannot precede creation")
        if self.evidence_published_through < self.evidence_published_from:
            raise ValueError("edge observation evidence interval is reversed")
        if len(set(self.evidence_article_ids)) != len(self.evidence_article_ids):
            raise ValueError("edge observation article IDs must be unique")
        return self


class SemanticWorldGraphEdgeHistory(ContractModel):
    """Bounded cross-snapshot observation history for one exact edge signature."""

    graph_id: UUID
    graph_sha256: Sha256Digest
    edge_id: UUID
    observation_semantics: Literal["cross_snapshot_exact_signature_not_fact_validity"]
    signature: SemanticWorldGraphEdgeSignature
    inspected_graph_count: Annotated[int, Field(ge=1, le=12)]
    total_succeeded_graph_count: Annotated[int, Field(ge=1)]
    truncated: bool
    items: Annotated[
        tuple[SemanticWorldGraphEdgeObservation, ...], Field(min_length=1, max_length=50)
    ]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        if tuple(item.position for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("edge history positions must be contiguous from zero")
        identities = {(item.graph_id, item.edge_id) for item in self.items}
        if len(identities) != len(self.items):
            raise ValueError("edge history occurrences must be unique")
        ordering = tuple(
            (item.snapshot_version, item.graph_created_at, item.edge_id.int) for item in self.items
        )
        if ordering != tuple(sorted(ordering)):
            raise ValueError("edge history must be ordered by snapshot version and graph creation")
        current = tuple(
            item
            for item in self.items
            if item.graph_id == self.graph_id and item.edge_id == self.edge_id
        )
        if len(current) != 1 or current[0].graph_sha256 != self.graph_sha256:
            raise ValueError(
                "edge history must contain the requested graph occurrence exactly once"
            )
        if self.total_succeeded_graph_count < self.inspected_graph_count:
            raise ValueError("edge history inspected count exceeds available graph count")
        if self.truncated != (self.total_succeeded_graph_count > self.inspected_graph_count):
            raise ValueError("edge history truncation flag does not match graph counts")
        return self


class SemanticWorldGraphPersonaMatch(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    score: Annotated[int, Field(ge=1, le=20)]
    matched_terms: Annotated[tuple[NonEmptyText, ...], Field(min_length=1, max_length=20)]
    matched_attributes: Annotated[tuple[PersonaAttribute, ...], Field(min_length=1, max_length=20)]
    persona: PersonaSummary


class SemanticWorldGraphPersonaMatches(ContractModel):
    graph_id: UUID
    graph_sha256: Sha256Digest
    node_id: UUID
    dataset: CohortDatasetRef
    match_semantics: Literal["exact_token_overlap_non_low_information_attributes"]
    query_terms: Annotated[tuple[NonEmptyText, ...], Field(min_length=1, max_length=20)]
    inspected_persona_count: Annotated[int, Field(ge=0, le=200)]
    dataset_persona_count: Annotated[int, Field(ge=1)]
    scan_truncated: bool
    total_match_count_in_scan: Annotated[int, Field(ge=0, le=200)]
    matches: Annotated[tuple[SemanticWorldGraphPersonaMatch, ...], Field(max_length=20)]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=3, max_length=3)]

    @model_validator(mode="after")
    def validate_matches(self) -> Self:
        if tuple(item.position for item in self.matches) != tuple(range(len(self.matches))):
            raise ValueError("persona match positions must be contiguous from zero")
        if len({item.persona.id for item in self.matches}) != len(self.matches):
            raise ValueError("persona matches must be unique")
        if any(item.persona.dataset_id != self.dataset.id for item in self.matches):
            raise ValueError("persona matches must belong to the requested dataset")
        if self.total_match_count_in_scan < len(self.matches):
            raise ValueError("persona match count cannot be smaller than returned matches")
        if self.scan_truncated != (self.dataset_persona_count > self.inspected_persona_count):
            raise ValueError("persona scan truncation does not match dataset counts")
        return self


class GraphPersonaCohortCreateRequest(CohortCreateRequest):
    """Explicit bounded Persona selection from one graph-node match result."""

    persona_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=8)]


class GraphPersonaCohortOrigin(ContractModel):
    """Immutable audit link between a graph-node match and one cohort."""

    id: UUID
    graph_id: UUID
    graph_sha256: Sha256Digest
    node_id: UUID
    dataset: CohortDatasetRef
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    match_semantics: Literal["exact_token_overlap_non_low_information_attributes"]
    matcher_version: Literal["1.0.0"]
    selected_persona_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=8)]
    origin_sha256: Sha256Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if len(set(self.selected_persona_ids)) != len(self.selected_persona_ids):
            raise ValueError("graph Persona cohort origin must contain unique Personas")
        return self


class GraphPersonaCohortCreation(ContractModel):
    """New or existing cohort plus its durable graph-selection lineage."""

    origin: GraphPersonaCohortOrigin
    cohort: CohortDetail

    @model_validator(mode="after")
    def validate_resources(self) -> Self:
        member_ids = tuple(member.persona.id for member in self.cohort.members)
        if self.origin.cohort_id != self.cohort.id:
            raise ValueError("graph Persona origin must reference the returned cohort")
        if self.origin.cohort_sha256 != self.cohort.cohort_sha256:
            raise ValueError("graph Persona origin cohort digest does not match")
        if self.origin.dataset.id != self.cohort.dataset.id:
            raise ValueError("graph Persona origin dataset does not match")
        if self.origin.dataset.dataset_sha256 != self.cohort.dataset.dataset_sha256:
            raise ValueError("graph Persona origin dataset digest does not match")
        if self.origin.selected_persona_ids != member_ids:
            raise ValueError("graph Persona origin selection must equal cohort member order")
        return self


class GraphPersonaCohortOriginsResponse(ContractModel):
    """One bounded page of immutable graph-selection origins for a cohort."""

    items: tuple[GraphPersonaCohortOrigin, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("graph Persona origin page exceeds page_size")
        if len(self.items) > self.total:
            raise ValueError("graph Persona origin page exceeds total")
        cohort_ids = {item.cohort_id for item in self.items}
        if len(cohort_ids) > 1:
            raise ValueError("graph Persona origin page must belong to one cohort")
        ordering = tuple((item.created_at, item.id.int) for item in self.items)
        expected = tuple(sorted(ordering, key=lambda item: (-item[0].timestamp(), item[1])))
        if ordering != expected:
            raise ValueError("graph Persona origins must be ordered by creation time and ID")
        return self


class SemanticWorldGraphNodeSearchResult(ContractModel):
    kind: Literal["node"]
    rank: Annotated[int, Field(ge=0, le=49)]
    matched_fields: Annotated[
        tuple[WorldGraphSearchMatchField, ...],
        Field(min_length=1, max_length=4),
    ]
    node: SemanticWorldGraphNode


class SemanticWorldGraphEdgeSearchResult(ContractModel):
    kind: Literal["edge"]
    rank: Annotated[int, Field(ge=0, le=49)]
    matched_fields: Annotated[
        tuple[WorldGraphSearchMatchField, ...],
        Field(min_length=1, max_length=3),
    ]
    edge: SemanticWorldGraphEdge


type SemanticWorldGraphSearchResult = Annotated[
    SemanticWorldGraphNodeSearchResult | SemanticWorldGraphEdgeSearchResult,
    Field(discriminator="kind"),
]


class SemanticWorldGraphSearchResponse(ContractModel):
    """Bounded lexical matches over one already verified immutable graph."""

    graph_id: UUID
    graph_sha256: Sha256Digest
    query: Annotated[
        str,
        StringConstraints(
            min_length=2,
            max_length=100,
            pattern=r"^[^\r\n]+$",
            strip_whitespace=True,
        ),
    ]
    search_semantics: Literal["casefolded_lexical_substring"]
    total_match_count: Annotated[int, Field(ge=0, le=2500)]
    truncated: bool
    results: Annotated[tuple[SemanticWorldGraphSearchResult, ...], Field(max_length=50)]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=2, max_length=3)]

    @model_validator(mode="after")
    def validate_results(self) -> Self:
        if tuple(result.rank for result in self.results) != tuple(range(len(self.results))):
            raise ValueError("world graph search ranks must be contiguous from zero")
        if self.total_match_count < len(self.results):
            raise ValueError("world graph total matches cannot be smaller than results")
        if self.truncated != (self.total_match_count > len(self.results)):
            raise ValueError("world graph search truncated flag must match result counts")
        identities = tuple(
            (result.kind, result.node.id if result.kind == "node" else result.edge.id)
            for result in self.results
        )
        if len(set(identities)) != len(identities):
            raise ValueError("world graph search results must be unique")
        return self
