"""Strict storage, provider-output, and terminal contracts for world graph extraction."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel

GRAPH_PROMPT_SCHEMA_VERSION = "world-graph-extraction/v1"
GRAPH_MAX_INPUT_CHARACTERS = 80_000

EntityType = Literal["organization", "person", "location", "policy", "event", "concept"]
LocalId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*$",
        strict=True,
    ),
]
RelationType = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        strict=True,
    ),
]


class FrozenGraphEvidence(StrictModel):
    article_id: UUID
    position: Annotated[int, Field(ge=0, le=49)]
    title: Annotated[RequiredText, Field(max_length=20_000)]
    captured_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2_100_000, strict=True),
    ]
    captured_text_sha256: Sha256


class ClaimedWorldGraph(StrictModel):
    id: UUID
    world_model_id: UUID
    snapshot_id: UUID
    snapshot_sha256: Sha256
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    extraction_config_sha256: Sha256
    prompt_schema_version: Literal["world-graph-extraction/v1"]
    input_sha256: Sha256
    created_at: datetime
    evidence: Annotated[tuple[FrozenGraphEvidence, ...], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def validate_evidence_order(self) -> Self:
        if tuple(item.position for item in self.evidence) != tuple(range(len(self.evidence))):
            raise ValueError("world graph evidence positions must be contiguous from zero")
        if len({item.article_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("world graph evidence article IDs must be unique")
        return self


class ExtractedEvidence(StrictModel):
    article_id: UUID
    quote: Annotated[RequiredText, Field(max_length=500)]


class ExtractedEntity(StrictModel):
    local_id: LocalId
    entity_type: EntityType
    name: Annotated[RequiredText, Field(max_length=200)]
    summary: Annotated[RequiredText, Field(max_length=500)]
    evidence: Annotated[tuple[ExtractedEvidence, ...], Field(min_length=1, max_length=20)]


class ExtractedRelationship(StrictModel):
    source_local_id: LocalId
    target_local_id: LocalId
    relation_type: RelationType
    fact: Annotated[RequiredText, Field(max_length=500)]
    evidence: Annotated[tuple[ExtractedEvidence, ...], Field(min_length=1, max_length=20)]


class ExtractedWorldGraph(StrictModel):
    entities: Annotated[tuple[ExtractedEntity, ...], Field(min_length=1, max_length=500)]
    relationships: Annotated[tuple[ExtractedRelationship, ...], Field(max_length=2000)]

    @field_validator("entities")
    @classmethod
    def require_unique_local_ids(
        cls,
        entities: tuple[ExtractedEntity, ...],
    ) -> tuple[ExtractedEntity, ...]:
        if len({entity.local_id for entity in entities}) != len(entities):
            raise ValueError("extracted entity local_id values must be unique")
        return entities

    @model_validator(mode="after")
    def validate_relationship_references(self) -> Self:
        local_ids = {entity.local_id for entity in self.entities}
        for relationship in self.relationships:
            if (
                relationship.source_local_id not in local_ids
                or relationship.target_local_id not in local_ids
            ):
                raise ValueError("extracted relationship references an unknown entity local_id")
            if relationship.source_local_id == relationship.target_local_id:
                raise ValueError("extracted relationship cannot be a self-loop")
        return self


class NormalizedGraphEvidence(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    article_id: UUID
    quote: Annotated[RequiredText, Field(max_length=500)]
    start_offset: Annotated[int, Field(ge=0)]
    end_offset: Annotated[int, Field(ge=1)]


class NormalizedGraphNode(StrictModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=499)]
    entity_type: EntityType
    name: Annotated[RequiredText, Field(max_length=200)]
    summary: Annotated[RequiredText, Field(max_length=500)]
    evidence: Annotated[tuple[NormalizedGraphEvidence, ...], Field(min_length=1, max_length=20)]


class NormalizedGraphEdge(StrictModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=1999)]
    source_node_id: UUID
    target_node_id: UUID
    relation_type: RelationType
    fact: Annotated[RequiredText, Field(max_length=500)]
    evidence: Annotated[tuple[NormalizedGraphEvidence, ...], Field(min_length=1, max_length=20)]


class NormalizedWorldGraph(StrictModel):
    graph_sha256: Sha256
    nodes: Annotated[tuple[NormalizedGraphNode, ...], Field(min_length=1, max_length=500)]
    edges: Annotated[tuple[NormalizedGraphEdge, ...], Field(max_length=2000)]
