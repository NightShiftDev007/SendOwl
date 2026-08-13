"""Strict contracts for immutable decision scenarios."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Sha256Digest

type ScenarioTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type VariantName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type DecisionQuestion = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type VariantHypothesis = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type InterventionContent = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type VariantPosition = Annotated[int, Field(ge=0, le=5)]
type InterventionPosition = Annotated[int, Field(ge=0, le=19)]
type OffsetMinutes = Annotated[int, Field(ge=0, le=1440)]
type InterventionKind = Literal["initial_post"]
type InterventionActor = Literal["scenario_actor"]
type InterventionChannel = Literal["reddit"]


def _request_uuid(value: object, field_name: str) -> UUID:
    """Parse one UUID transport string without weakening response validation."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


def _request_tuple(value: object, field_name: str) -> tuple[object, ...]:
    """Convert one JSON array before strict immutable tuple validation."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array; received {type(value).__name__}")
    return tuple(value)


class ScenarioRequestModel(ContractModel):
    """Request boundary that rejects every unspecified input field."""

    model_config = ConfigDict(extra="forbid")


class ScenarioInterventionCreate(ScenarioRequestModel):
    """One explicitly supported action in an alternative scenario path."""

    kind: InterventionKind
    actor: InterventionActor
    channel: InterventionChannel
    content: InterventionContent
    offset_minutes: OffsetMinutes


class ScenarioBaselineCreate(ScenarioRequestModel):
    """No-action comparator captured alongside the alternatives."""

    name: VariantName
    hypothesis: VariantHypothesis


class ScenarioAlternativeCreate(ScenarioRequestModel):
    """One proposed decision path and its ordered initial posts."""

    name: VariantName
    hypothesis: VariantHypothesis
    interventions: Annotated[
        tuple[ScenarioInterventionCreate, ...],
        Field(min_length=1, max_length=20),
    ]

    @field_validator("interventions", mode="before")
    @classmethod
    def parse_interventions(cls, value: object) -> tuple[object, ...]:
        """Convert the intervention JSON array before strict item validation."""
        return _request_tuple(value, "interventions")


class ScenarioCreateRequest(ScenarioRequestModel):
    """Create one immutable experiment definition against an exact world snapshot."""

    title: ScenarioTitle
    decision_question: DecisionQuestion
    world_model_id: UUID
    world_snapshot_id: UUID
    baseline: ScenarioBaselineCreate
    alternatives: Annotated[
        tuple[ScenarioAlternativeCreate, ...],
        Field(min_length=1, max_length=5),
    ]

    @field_validator("world_model_id", mode="before")
    @classmethod
    def parse_world_model_id(cls, value: object) -> UUID:
        """Convert the model JSON UUID string before strict field validation."""
        return _request_uuid(value, "world_model_id")

    @field_validator("world_snapshot_id", mode="before")
    @classmethod
    def parse_world_snapshot_id(cls, value: object) -> UUID:
        """Convert the snapshot JSON UUID string before strict field validation."""
        return _request_uuid(value, "world_snapshot_id")

    @field_validator("alternatives", mode="before")
    @classmethod
    def parse_alternatives(cls, value: object) -> tuple[object, ...]:
        """Convert the alternatives JSON array before strict item validation."""
        return _request_tuple(value, "alternatives")


class ScenarioSnapshotRef(ContractModel):
    """Frozen identity and integrity metadata for the selected world snapshot."""

    world_model_id: UUID
    world_snapshot_id: UUID
    version: Annotated[int, Field(ge=1)]
    snapshot_sha256: Sha256Digest
    evidence_count: Annotated[int, Field(ge=1, le=50)]


class Intervention(ContractModel):
    """One generated immutable intervention record."""

    id: UUID
    position: InterventionPosition
    kind: InterventionKind
    actor: InterventionActor
    channel: InterventionChannel
    content: InterventionContent
    offset_minutes: OffsetMinutes


class ScenarioVariant(ContractModel):
    """One generated baseline or alternative path."""

    id: UUID
    position: VariantPosition
    name: VariantName
    hypothesis: VariantHypothesis
    interventions: tuple[Intervention, ...]

    @model_validator(mode="after")
    def validate_intervention_positions(self) -> Self:
        """Require stable contiguous intervention ordering within one variant."""
        positions = tuple(item.position for item in self.interventions)
        if positions != tuple(range(len(self.interventions))):
            raise ValueError("intervention positions must be contiguous and start at zero")
        if len({item.id for item in self.interventions}) != len(self.interventions):
            raise ValueError("intervention IDs must be unique within a variant")
        return self


class ScenarioSummary(ContractModel):
    """Directory projection for one immutable scenario."""

    id: UUID
    title: ScenarioTitle
    decision_question: DecisionQuestion
    created_at: AwareDatetime
    scenario_sha256: Sha256Digest
    snapshot: ScenarioSnapshotRef


class ScenarioDetail(ScenarioSummary):
    """Complete immutable scenario with baseline and ordered alternatives."""

    baseline: ScenarioVariant
    alternatives: Annotated[tuple[ScenarioVariant, ...], Field(min_length=1, max_length=5)]

    @model_validator(mode="after")
    def validate_variant_composition(self) -> Self:
        """Require one no-action baseline followed by one to five alternatives."""
        if self.baseline.position != 0:
            raise ValueError("baseline position must be zero")
        if self.baseline.interventions:
            raise ValueError("baseline interventions must be empty")
        positions = tuple(item.position for item in self.alternatives)
        if positions != tuple(range(1, len(self.alternatives) + 1)):
            raise ValueError("alternative positions must be contiguous and start at one")
        if any(not 1 <= len(item.interventions) <= 20 for item in self.alternatives):
            raise ValueError("each alternative must contain 1..20 interventions")
        variant_ids = (self.baseline.id,) + tuple(item.id for item in self.alternatives)
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("baseline and alternatives must use unique variant IDs")
        return self


class ScenariosResponse(ContractModel):
    """Complete immutable scenario directory."""

    items: tuple[ScenarioSummary, ...]
    total: Annotated[int, Field(ge=0)]


# Retain the engine-neutral name consumed by the simulation boundary.
ScenarioSpec = ScenarioDetail

__all__ = [
    "Intervention",
    "ScenarioAlternativeCreate",
    "ScenarioBaselineCreate",
    "ScenarioCreateRequest",
    "ScenarioDetail",
    "ScenarioInterventionCreate",
    "ScenarioSnapshotRef",
    "ScenarioSpec",
    "ScenarioSummary",
    "ScenarioVariant",
    "ScenariosResponse",
]
