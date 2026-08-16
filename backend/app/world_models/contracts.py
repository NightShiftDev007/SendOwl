"""Strict contracts for persistent world models and immutable evidence snapshots."""

from datetime import date
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

from app.media.contracts import ArticleExcerpt, CountryCode
from app.policy_evidence.hashing import (
    calculate_policy_document_sha256,
    calculate_policy_source_sha256,
    calculate_policy_version_sha256,
)
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
type PolicyEvidenceCount = Annotated[int, Field(ge=0, le=50)]
type Verification = Literal["human_confirmed"]
type CapturedText = Annotated[str, StringConstraints(min_length=1, strip_whitespace=False)]


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
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            "evidence must be an array of article revision selections; "
            f"received {type(value).__name__}"
        )
    return tuple(value)


def _request_policy_evidence_tuple(value: object) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            "policy_evidence must be an array of Policy version selections; "
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
        return _request_uuid(value, "article_id")


class WorldSnapshotPolicyEvidenceSelection(ContractModel):
    """One exact immutable Policy version selected for snapshot capture."""

    policy_version_id: UUID
    version_sha256: Sha256Digest

    @field_validator("policy_version_id", mode="before")
    @classmethod
    def parse_policy_version_id(cls, value: object) -> UUID:
        return _request_uuid(value, "policy_version_id")


type SnapshotEvidenceSelections = Annotated[
    tuple[WorldSnapshotEvidenceSelection, ...],
    Field(min_length=1, max_length=50),
]
type SnapshotPolicyEvidenceSelections = Annotated[
    tuple[WorldSnapshotPolicyEvidenceSelection, ...],
    Field(max_length=50),
]


def _reject_duplicate_article_ids(
    selections: tuple[WorldSnapshotEvidenceSelection, ...],
) -> tuple[WorldSnapshotEvidenceSelection, ...]:
    seen: set[UUID] = set()
    duplicates: list[UUID] = []
    for selection in selections:
        if selection.article_id in seen and selection.article_id not in duplicates:
            duplicates.append(selection.article_id)
        seen.add(selection.article_id)
    if duplicates:
        values = ", ".join(str(article_id) for article_id in duplicates)
        raise ValueError(
            "evidence must contain unique article_id values; duplicate article IDs: " + values
        )
    return selections


def _reject_duplicate_policy_version_ids(
    selections: tuple[WorldSnapshotPolicyEvidenceSelection, ...],
) -> tuple[WorldSnapshotPolicyEvidenceSelection, ...]:
    seen: set[UUID] = set()
    duplicates: list[UUID] = []
    for selection in selections:
        if selection.policy_version_id in seen and selection.policy_version_id not in duplicates:
            duplicates.append(selection.policy_version_id)
        seen.add(selection.policy_version_id)
    if duplicates:
        values = ", ".join(str(version_id) for version_id in duplicates)
        raise ValueError(
            "policy_evidence must contain unique policy_version_id values; "
            "duplicate Policy version IDs: " + values
        )
    return selections


def _validate_total_evidence_count(article_count: int, policy_count: int) -> None:
    total = article_count + policy_count
    if total > 50:
        raise ValueError(f"snapshot evidence must contain at most 50 total items; received {total}")


class WorldModelCreateRequest(ContractModel):
    """Create one persistent model and its initial immutable snapshot."""

    title: WorldModelTitle
    evidence: SnapshotEvidenceSelections
    policy_evidence: SnapshotPolicyEvidenceSelections
    verification: Verification

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> tuple[object, ...]:
        return _request_evidence_tuple(value)

    @field_validator("policy_evidence", mode="before")
    @classmethod
    def parse_policy_evidence(cls, value: object) -> tuple[object, ...]:
        return _request_policy_evidence_tuple(value)

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence_article_ids(
        cls,
        selections: tuple[WorldSnapshotEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotEvidenceSelection, ...]:
        return _reject_duplicate_article_ids(selections)

    @field_validator("policy_evidence")
    @classmethod
    def validate_unique_policy_version_ids(
        cls,
        selections: tuple[WorldSnapshotPolicyEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotPolicyEvidenceSelection, ...]:
        return _reject_duplicate_policy_version_ids(selections)

    @model_validator(mode="after")
    def validate_total_evidence_count(self) -> Self:
        _validate_total_evidence_count(len(self.evidence), len(self.policy_evidence))
        return self


class WorldSnapshotCreateRequest(ContractModel):
    """Append one immutable evidence snapshot to an existing model."""

    evidence: SnapshotEvidenceSelections
    policy_evidence: SnapshotPolicyEvidenceSelections
    verification: Verification

    @field_validator("evidence", mode="before")
    @classmethod
    def parse_evidence(cls, value: object) -> tuple[object, ...]:
        return _request_evidence_tuple(value)

    @field_validator("policy_evidence", mode="before")
    @classmethod
    def parse_policy_evidence(cls, value: object) -> tuple[object, ...]:
        return _request_policy_evidence_tuple(value)

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence_article_ids(
        cls,
        selections: tuple[WorldSnapshotEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotEvidenceSelection, ...]:
        return _reject_duplicate_article_ids(selections)

    @field_validator("policy_evidence")
    @classmethod
    def validate_unique_policy_version_ids(
        cls,
        selections: tuple[WorldSnapshotPolicyEvidenceSelection, ...],
    ) -> tuple[WorldSnapshotPolicyEvidenceSelection, ...]:
        return _reject_duplicate_policy_version_ids(selections)

    @model_validator(mode="after")
    def validate_total_evidence_count(self) -> Self:
        _validate_total_evidence_count(len(self.evidence), len(self.policy_evidence))
        return self


class SnapshotSummary(ContractModel):
    """Stable identity and content address for one model version."""

    id: UUID
    version: SnapshotVersion
    evidence_count: EvidenceCount
    policy_evidence_count: PolicyEvidenceCount
    snapshot_sha256: Sha256Digest
    created_at: AwareDatetime


class ModelSummary(ContractModel):
    """Directory projection for one persistent world model."""

    id: UUID
    title: WorldModelTitle
    created_at: AwareDatetime
    latest_snapshot: SnapshotSummary


class WorldModelsResponse(ContractModel):
    """Complete persistent world-model directory."""

    items: tuple[ModelSummary, ...]
    total: Annotated[int, Field(ge=0)]


class SnapshotEvidence(ContractModel):
    """Complete media provenance copied into an immutable snapshot."""

    article_id: UUID
    source_name: NonEmptyText
    original_url: HttpUrl
    title: NonEmptyText
    published_at: AwareDatetime
    captured_at: AwareDatetime
    country_code: CountryCode | None
    excerpt: ArticleExcerpt
    captured_text_sha256: Sha256Digest


class SnapshotEvidenceContent(ContractModel):
    """Exact frozen article text fetched separately from snapshot metadata."""

    article_id: UUID
    captured_text: CapturedText
    captured_text_sha256: Sha256Digest


class SnapshotPolicyEvidence(ContractModel):
    """Policy version metadata copied into one immutable world snapshot."""

    policy_version_id: UUID
    authority_name: NonEmptyText
    jurisdiction_code: Annotated[
        str,
        StringConstraints(min_length=2, max_length=16, pattern=r"^[A-Z0-9][A-Z0-9-]+$"),
    ]
    homepage_url: HttpUrl
    canonical_identifier: NonEmptyText
    source_sha256: Sha256Digest
    document_sha256: Sha256Digest
    version: Annotated[int, Field(ge=1, le=100)]
    title: NonEmptyText
    original_url: HttpUrl
    language: Annotated[
        str,
        StringConstraints(
            min_length=2,
            max_length=16,
            pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
        ),
    ]
    publication_date: date
    effective_from: date | None
    effective_until: date | None
    captured_at: AwareDatetime
    content_sha256: Sha256Digest
    version_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_effectivity(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("Policy effective_until must be later than effective_from")
        expected_source_sha256 = calculate_policy_source_sha256(
            self.authority_name,
            self.jurisdiction_code,
            str(self.homepage_url),
        )
        if self.source_sha256 != expected_source_sha256:
            raise ValueError("frozen Policy source_sha256 does not match its identity")
        expected_document_sha256 = calculate_policy_document_sha256(
            self.source_sha256,
            self.canonical_identifier,
        )
        if self.document_sha256 != expected_document_sha256:
            raise ValueError("frozen Policy document_sha256 does not match its identity")
        expected_version_sha256 = calculate_policy_version_sha256(
            self.document_sha256,
            self.title,
            str(self.original_url),
            self.language,
            self.publication_date,
            self.effective_from,
            self.effective_until,
            self.content_sha256,
        )
        if self.version_sha256 != expected_version_sha256:
            raise ValueError("frozen Policy version_sha256 does not match its metadata")
        return self


class SnapshotPolicyEvidenceContent(ContractModel):
    """Exact frozen Policy text fetched separately from snapshot metadata."""

    policy_version_id: UUID
    captured_text: CapturedText
    content_sha256: Sha256Digest


class SnapshotDetail(ContractModel):
    """One immutable, content-addressed version of a persistent world model."""

    id: UUID
    world_model_id: UUID
    version: SnapshotVersion
    verification: Verification
    snapshot_sha256: Sha256Digest
    created_at: AwareDatetime
    evidence: Annotated[tuple[SnapshotEvidence, ...], Field(min_length=1, max_length=50)]
    policy_evidence: Annotated[tuple[SnapshotPolicyEvidence, ...], Field(max_length=50)]

    @model_validator(mode="after")
    def validate_total_evidence_count(self) -> Self:
        _validate_total_evidence_count(len(self.evidence), len(self.policy_evidence))
        return self


class ModelDetail(ContractModel):
    """Persistent model identity, version history, and latest immutable snapshot."""

    id: UUID
    title: WorldModelTitle
    created_at: AwareDatetime
    snapshots: Annotated[tuple[SnapshotSummary, ...], Field(min_length=1)]
    latest_snapshot: SnapshotDetail

    @model_validator(mode="after")
    def validate_latest_snapshot(self) -> Self:
        if self.latest_snapshot.world_model_id != self.id:
            raise ValueError("latest_snapshot must belong to the enclosing world model")
        matching = tuple(
            snapshot for snapshot in self.snapshots if snapshot.id == self.latest_snapshot.id
        )
        if len(matching) != 1:
            raise ValueError("latest_snapshot must have exactly one matching snapshot summary")
        summary = matching[0]
        if (
            summary.version != self.latest_snapshot.version
            or summary.snapshot_sha256 != self.latest_snapshot.snapshot_sha256
            or summary.evidence_count != len(self.latest_snapshot.evidence)
            or summary.policy_evidence_count != len(self.latest_snapshot.policy_evidence)
        ):
            raise ValueError("latest_snapshot must match its snapshot summary")
        if summary.version != max(snapshot.version for snapshot in self.snapshots):
            raise ValueError("latest_snapshot must be the highest snapshot version")
        return self


SnapshotCreateRequest = WorldSnapshotCreateRequest
WorldModelSummary = ModelSummary
WorldModelDetail = ModelDetail
