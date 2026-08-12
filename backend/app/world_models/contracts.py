"""Strict contracts for persistent world models and immutable evidence snapshots."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.companies.contracts import CompanyEvidenceContext, CompanyName
from app.media.contracts import ArticleExcerpt, CountryCode
from app.shared.contracts import ContractModel, NonEmptyText, Sha256Digest

type WorldModelTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type SnapshotVersion = Annotated[int, Field(ge=1)]
type EvidenceCount = Annotated[int, Field(ge=1, le=50)]
type Verification = Literal["human_confirmed"]
type CapturedText = Annotated[
    str,
    StringConstraints(min_length=1, strip_whitespace=False),
]


def _request_uuid(value: object, field_name: str) -> UUID:
    """Parse one UUID transport string without weakening strict response contracts."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


def _request_evidence_tuple(value: object) -> tuple[object, ...]:
    """Convert an evidence JSON array before strict immutable validation."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            "evidence must be an array of article revision selections; "
            f"received {type(value).__name__}"
        )
    return tuple(value)


class WorldSnapshotEvidenceSelection(ContractModel):
    """One exact media revision selected for immutable snapshot capture."""

    article_id: UUID
    evidence_revision_sha256: Sha256Digest

    @field_validator("article_id", mode="before")
    @classmethod
    def parse_article_id(cls, value: object) -> UUID:
        """Convert the JSON UUID string before strict field validation."""
        return _request_uuid(value, "article_id")


type SnapshotEvidenceSelections = Annotated[
    tuple[WorldSnapshotEvidenceSelection, ...],
    Field(min_length=1, max_length=50),
]


def _reject_duplicate_article_ids(
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
) -> tuple[WorldSnapshotEvidenceSelection, ...]:
    """Reject repeated selected articles while preserving request order."""
    seen: set[UUID] = set()
    duplicates: list[UUID] = []
    for selection in selections:
        article_id = selection.article_id
        if article_id in seen and article_id not in duplicates:
            duplicates.append(article_id)
        seen.add(article_id)
    if duplicates:
        duplicate_values = ", ".join(str(article_id) for article_id in duplicates)
        raise ValueError(
            "evidence must contain unique article_id values; "
            f"duplicate article IDs: {duplicate_values}"
        )
    return selections


class WorldModelCreateRequest(ContractModel):
    """Create one persistent model and its initial immutable snapshot."""

    title: WorldModelTitle
    company_id: UUID
    evidence: SnapshotEvidenceSelections
    verification: Verification

    @field_validator("company_id", mode="before")
    @classmethod
    def parse_company_id(cls, value: object) -> UUID:
        """Convert the JSON UUID string before strict field validation."""
        return _request_uuid(value, "company_id")

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> tuple[object, ...]:
        """Convert the JSON array before strict tuple and item validation."""
        return _request_evidence_tuple(value)

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence_article_ids(
        cls,
        selections: tuple[WorldSnapshotEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotEvidenceSelection, ...]:
        """Ensure one article cannot be counted twice in a snapshot."""
        return _reject_duplicate_article_ids(selections)


class WorldSnapshotCreateRequest(ContractModel):
    """Append one immutable evidence snapshot to an existing model."""

    evidence: SnapshotEvidenceSelections
    verification: Verification

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> tuple[object, ...]:
        """Convert the JSON array before strict tuple and item validation."""
        return _request_evidence_tuple(value)

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence_article_ids(
        cls,
        selections: tuple[WorldSnapshotEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotEvidenceSelection, ...]:
        """Ensure one article cannot be counted twice in a snapshot."""
        return _reject_duplicate_article_ids(selections)


class SnapshotSummary(ContractModel):
    """Stable identity and content address for one model version."""

    id: UUID
    version: SnapshotVersion
    company_name: CompanyName
    evidence_count: EvidenceCount
    snapshot_sha256: Sha256Digest
    created_at: AwareDatetime


class ModelSummary(ContractModel):
    """Directory projection for one persistent world model."""

    id: UUID
    title: WorldModelTitle
    company_id: UUID
    company_name: NonEmptyText
    created_at: AwareDatetime
    latest_snapshot: SnapshotSummary


class WorldModelsResponse(ContractModel):
    """Complete persistent world-model directory."""

    items: tuple[ModelSummary, ...]
    total: Annotated[int, Field(ge=0)]


class SnapshotCompany(ContractModel):
    """Company identity copied into a snapshot independently of mutable records."""

    id: UUID
    canonical_name: NonEmptyText
    aliases: tuple[NonEmptyText, ...]


class SnapshotEvidence(ContractModel):
    """Article provenance and exact company evidence copied into a snapshot."""

    article_id: UUID
    source_name: NonEmptyText
    original_url: HttpUrl
    title: NonEmptyText
    published_at: AwareDatetime
    captured_at: AwareDatetime
    country_code: CountryCode | None
    excerpt: ArticleExcerpt
    captured_text_sha256: Sha256Digest
    matched_aliases: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
    evidence_contexts: Annotated[tuple[CompanyEvidenceContext, ...], Field(min_length=1)]


class SnapshotEvidenceContent(ContractModel):
    """Exact frozen article text fetched separately from snapshot metadata."""

    article_id: UUID
    captured_text: CapturedText
    captured_text_sha256: Sha256Digest


class SnapshotDetail(ContractModel):
    """One immutable, content-addressed version of a persistent world model."""

    id: UUID
    world_model_id: UUID
    version: SnapshotVersion
    verification: Verification
    snapshot_sha256: Sha256Digest
    created_at: AwareDatetime
    company: SnapshotCompany
    evidence: Annotated[tuple[SnapshotEvidence, ...], Field(min_length=1, max_length=50)]


class ModelDetail(ContractModel):
    """Persistent model identity, version history, and latest immutable snapshot."""

    id: UUID
    title: WorldModelTitle
    company_id: UUID
    created_at: AwareDatetime
    snapshots: Annotated[tuple[SnapshotSummary, ...], Field(min_length=1)]
    latest_snapshot: SnapshotDetail

    @model_validator(mode="after")
    def validate_latest_snapshot(self) -> Self:
        """Reject repository projections whose latest detail disagrees with history."""
        if self.latest_snapshot.world_model_id != self.id:
            raise ValueError("latest_snapshot must belong to the enclosing world model")
        if self.latest_snapshot.company.id != self.company_id:
            raise ValueError("latest snapshot company must match the world model company_id")
        matching_summaries = tuple(
            snapshot for snapshot in self.snapshots if snapshot.id == self.latest_snapshot.id
        )
        if len(matching_summaries) != 1:
            raise ValueError("latest_snapshot must have exactly one matching snapshot summary")
        summary = matching_summaries[0]
        if (
            summary.version != self.latest_snapshot.version
            or summary.company_name != self.latest_snapshot.company.canonical_name
            or summary.snapshot_sha256 != self.latest_snapshot.snapshot_sha256
            or summary.evidence_count != len(self.latest_snapshot.evidence)
        ):
            raise ValueError("latest_snapshot must match its snapshot summary")
        if summary.version != max(snapshot.version for snapshot in self.snapshots):
            raise ValueError("latest_snapshot must be the highest snapshot version")
        return self


SnapshotCreateRequest = WorldSnapshotCreateRequest
WorldModelSummary = ModelSummary
WorldModelDetail = ModelDetail

__all__ = [
    "ModelDetail",
    "ModelSummary",
    "SnapshotCompany",
    "SnapshotCreateRequest",
    "SnapshotDetail",
    "SnapshotEvidence",
    "SnapshotEvidenceContent",
    "SnapshotSummary",
    "WorldModelCreateRequest",
    "WorldModelDetail",
    "WorldModelSummary",
    "WorldModelsResponse",
    "WorldSnapshotCreateRequest",
    "WorldSnapshotEvidenceSelection",
]
