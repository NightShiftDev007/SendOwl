"""Strict public contracts for immutable MatrAIx population resources."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, Sha256Digest

type DatasetSlug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        strip_whitespace=True,
    ),
]
type DatasetDisplayName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type SchemaVersion = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        strip_whitespace=True,
    ),
]
type DatasetProvenance = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=500,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type PersonaDisplayName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type PersonaAttributeValue = Annotated[
    str,
    StringConstraints(min_length=1, max_length=500, strip_whitespace=True),
]
type CohortTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]


def _request_uuid(value: object, field_name: str) -> UUID:
    """Parse one JSON UUID without weakening strict response validation."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class PopulationRequestModel(ContractModel):
    """Request boundary rejecting every unspecified field."""

    model_config = ConfigDict(extra="forbid")


class DatasetSummary(ContractModel):
    """Frozen identity, provenance, and integrity data for one persona dataset."""

    id: UUID
    slug: DatasetSlug
    display_name: DatasetDisplayName
    schema_version: SchemaVersion
    parent_pool: DatasetProvenance | None
    source_repository: DatasetProvenance | None
    persona_count: Annotated[int, Field(ge=1, le=1_000_000)]
    manifest_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    created_at: AwareDatetime


class DatasetsResponse(ContractModel):
    """Complete frozen dataset directory."""

    items: tuple[DatasetSummary, ...]
    total: Annotated[int, Field(ge=0)]


class PersonaAttribute(ContractModel):
    """One typed, public persona dimension."""

    name: Identifier
    value: PersonaAttributeValue


class PersonaSummary(ContractModel):
    """Frozen public projection of one imported MatrAIx persona."""

    id: UUID
    dataset_id: UUID
    persona_id: Identifier
    display_name: PersonaDisplayName
    source: Identifier
    profile_sha256: Sha256Digest
    attributes: tuple[PersonaAttribute, ...]

    @model_validator(mode="after")
    def validate_attribute_order(self) -> Self:
        """Require deterministic unique attribute ordering in every response."""
        names = tuple(attribute.name for attribute in self.attributes)
        if names != tuple(sorted(names)):
            raise ValueError("persona attributes must be sorted by name")
        if len(set(names)) != len(names):
            raise ValueError("persona attribute names must be unique")
        return self


class PersonasResponse(ContractModel):
    """One stable page of personas from a frozen dataset."""

    items: tuple[PersonaSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: Annotated[int, Field(ge=0)]


class CohortCreateRequest(PopulationRequestModel):
    """Ordered persona selection used to create one immutable cohort."""

    title: CohortTitle
    dataset_id: UUID
    persona_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=100)]

    @field_validator("dataset_id", mode="before")
    @classmethod
    def parse_dataset_id(cls, value: object) -> UUID:
        """Convert the request transport string before strict UUID validation."""
        return _request_uuid(value, "dataset_id")

    @field_validator("persona_ids", mode="before")
    @classmethod
    def parse_persona_ids(cls, value: object) -> tuple[UUID, ...]:
        """Convert one JSON array while retaining the caller's member order."""
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"persona_ids must be an array; received {type(value).__name__}")
        return tuple(_request_uuid(item, "persona_ids item") for item in value)

    @model_validator(mode="after")
    def reject_duplicate_personas(self) -> Self:
        """Reject ambiguous repeated cohort membership."""
        if len(set(self.persona_ids)) != len(self.persona_ids):
            raise ValueError("persona_ids must not contain duplicates")
        return self


class CohortDatasetRef(ContractModel):
    """Frozen dataset identity copied into a cohort response."""

    id: UUID
    slug: DatasetSlug
    dataset_sha256: Sha256Digest


class CohortSummary(ContractModel):
    """Directory projection for one immutable cohort."""

    id: UUID
    title: CohortTitle
    dataset: CohortDatasetRef
    persona_count: Annotated[int, Field(ge=1, le=100)]
    cohort_sha256: Sha256Digest
    created_at: AwareDatetime


class CohortMember(ContractModel):
    """One ordered persona member of an immutable cohort."""

    position: Annotated[int, Field(ge=0, le=99)]
    persona: PersonaSummary


class CohortDetail(CohortSummary):
    """Complete immutable cohort and its ordered persona profiles."""

    members: Annotated[tuple[CohortMember, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        """Require contiguous positions, unique personas, and the declared count."""
        positions = tuple(member.position for member in self.members)
        if positions != tuple(range(len(self.members))):
            raise ValueError("cohort member positions must be contiguous and start at zero")
        persona_ids = tuple(member.persona.id for member in self.members)
        if len(set(persona_ids)) != len(persona_ids):
            raise ValueError("cohort members must contain unique personas")
        if len(self.members) != self.persona_count:
            raise ValueError("cohort persona_count must equal the number of members")
        if any(member.persona.dataset_id != self.dataset.id for member in self.members):
            raise ValueError("every cohort member must belong to the cohort dataset")
        return self


class CohortsResponse(ContractModel):
    """Complete immutable cohort directory."""

    items: tuple[CohortSummary, ...]
    total: Annotated[int, Field(ge=0)]


class StoredPersonaProvenance(ContractModel):
    """Fixed nullable provenance fields included in the profile content address."""

    model_config = ConfigDict(extra="forbid")

    hf_repo: str | None
    origin_persona_id: str | None
    origin_source_row_index: Annotated[int, Field(ge=0)] | None
    parent_pool: str | None


class StoredPersonaProfile(ContractModel):
    """Validated canonical JSON shape persisted by the MatrAIx importer."""

    model_config = ConfigDict(extra="forbid")

    display_name: PersonaDisplayName
    dimensions: dict[Identifier, PersonaAttributeValue]
    persona_id: Identifier
    provenance: StoredPersonaProvenance
    source: Identifier
    version: SchemaVersion


__all__ = [
    "CohortCreateRequest",
    "CohortDatasetRef",
    "CohortDetail",
    "CohortMember",
    "CohortSummary",
    "CohortsResponse",
    "DatasetSummary",
    "DatasetsResponse",
    "PersonaAttribute",
    "PersonasResponse",
    "PersonaSummary",
    "StoredPersonaProfile",
]
