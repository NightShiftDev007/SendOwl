"""Immutable evidence packages that make decision runs reproducible."""

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from app.evidence.hashing import calculate_evidence_bundle_sha256
from app.media.contracts import ArticleExcerpt, CountryCode, MediaArticle
from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest
from app.world_models.contracts import (
    CapturedText,
    SnapshotEvidence,
    SnapshotPolicyEvidence,
    Verification,
    WorldModelTitle,
)
from app.world_models.hashing import calculate_snapshot_sha256


def calculate_content_sha256(content: str) -> str:
    """Calculate the canonical lowercase digest for captured UTF-8 content."""
    return sha256(content.encode("utf-8")).hexdigest()


class EvidenceKind(StrEnum):
    """Kinds of source material currently admitted by the V2 boundary."""

    MEDIA_ARTICLE = "media_article"


class EvidenceItem(ContractModel):
    """One content-addressed source item captured for later verification."""

    evidence_id: Identifier
    kind: EvidenceKind
    article: MediaArticle
    content_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_content_digest(self) -> Self:
        """Reject a snapshot whose digest does not match its captured content."""
        actual_digest = calculate_content_sha256(self.article.content)
        if self.content_sha256 != actual_digest:
            raise ValueError("content_sha256 must match the captured article content")
        return self


EvidenceItems = Annotated[tuple[EvidenceItem, ...], Field(min_length=1)]


class EvidenceBundle(ContractModel):
    """A reproducible media snapshot used to construct a decision experiment."""

    bundle_id: Identifier
    title: NonEmptyText
    created_at: AwareDatetime
    items: EvidenceItems

    @model_validator(mode="after")
    def validate_unique_evidence_ids(self) -> Self:
        """Reject duplicate evidence identities that would be counted more than once."""
        seen_evidence_ids: set[str] = set()
        duplicate_evidence_ids: set[str] = set()
        for item in self.items:
            if item.evidence_id in seen_evidence_ids:
                duplicate_evidence_ids.add(item.evidence_id)
            seen_evidence_ids.add(item.evidence_id)

        if duplicate_evidence_ids:
            duplicates = ", ".join(sorted(duplicate_evidence_ids))
            raise ValueError(f"items must use unique evidence_id values; duplicates: {duplicates}")
        return self


class EvidenceBundleItem(ContractModel):
    """One ordered media item projected from immutable snapshot storage."""

    position: Annotated[int, Field(ge=0, le=49)]
    kind: Literal["media_article"]
    article_id: UUID
    source_name: NonEmptyText
    original_url: HttpUrl
    title: NonEmptyText
    published_at: AwareDatetime
    captured_at: AwareDatetime
    country_code: CountryCode | None
    excerpt: ArticleExcerpt
    captured_text_sha256: Sha256Digest


class EvidenceBundlePolicyItem(SnapshotPolicyEvidence):
    """One ordered Policy item projected from immutable snapshot storage."""

    position: Annotated[int, Field(ge=0, le=49)]
    kind: Literal["policy_document"]

    def snapshot_policy_evidence(self) -> SnapshotPolicyEvidence:
        return SnapshotPolicyEvidence.model_validate(
            self.model_dump(exclude={"position", "kind"}, mode="python")
        )


class EvidenceBundleSummary(ContractModel):
    """Lightweight identity for one sealed WorldSnapshot exposed as a bundle."""

    id: UUID
    bundle_sha256: Sha256Digest
    title: WorldModelTitle
    world_model_id: UUID
    world_snapshot_id: UUID
    version: Annotated[int, Field(ge=1)]
    verification: Verification
    snapshot_sha256: Sha256Digest
    item_count: Annotated[int, Field(ge=1, le=50)]
    policy_item_count: Annotated[int, Field(ge=0, le=50)]
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_derived_identity(self) -> Self:
        if self.id != self.world_snapshot_id:
            raise ValueError("bundle id must equal world_snapshot_id")
        expected = calculate_evidence_bundle_sha256(self.id, self.snapshot_sha256)
        if self.bundle_sha256 != expected:
            raise ValueError("bundle_sha256 must bind bundle id to snapshot_sha256")
        return self


class EvidenceBundleDetail(EvidenceBundleSummary):
    """Complete frozen bundle metadata without duplicating captured article text."""

    items: Annotated[tuple[EvidenceBundleItem, ...], Field(min_length=1, max_length=50)]
    policy_items: Annotated[tuple[EvidenceBundlePolicyItem, ...], Field(max_length=50)]

    @model_validator(mode="after")
    def validate_snapshot_projection(self) -> Self:
        positions = tuple(item.position for item in self.items)
        if positions != tuple(range(len(self.items))):
            raise ValueError("bundle item positions must be contiguous from zero")
        article_ids = tuple(item.article_id for item in self.items)
        if len(set(article_ids)) != len(article_ids):
            raise ValueError("bundle items must use unique article_id values")
        if self.item_count != len(self.items) or self.policy_item_count != len(self.policy_items):
            raise ValueError("bundle item counts must equal their item arrays")
        if self.item_count + self.policy_item_count > 50:
            raise ValueError("bundle cannot contain more than 50 total evidence items")
        policy_positions = tuple(item.position for item in self.policy_items)
        if policy_positions != tuple(range(len(self.policy_items))):
            raise ValueError("bundle Policy item positions must be contiguous from zero")
        policy_version_ids = tuple(item.policy_version_id for item in self.policy_items)
        if len(set(policy_version_ids)) != len(policy_version_ids):
            raise ValueError("bundle Policy items must use unique policy_version_id values")
        snapshot_evidence = tuple(
            SnapshotEvidence(
                article_id=item.article_id,
                source_name=item.source_name,
                original_url=item.original_url,
                title=item.title,
                published_at=item.published_at,
                captured_at=item.captured_at,
                country_code=item.country_code,
                excerpt=item.excerpt,
                captured_text_sha256=item.captured_text_sha256,
            )
            for item in self.items
        )
        expected_snapshot_sha256 = calculate_snapshot_sha256(
            self.world_model_id,
            self.version,
            self.verification,
            snapshot_evidence,
            tuple(item.snapshot_policy_evidence() for item in self.policy_items),
        )
        if self.snapshot_sha256 != expected_snapshot_sha256:
            raise ValueError("bundle items do not match snapshot_sha256")
        return self


class EvidenceBundleContent(ContractModel):
    """Exact frozen article text retrieved separately from bundle metadata."""

    bundle_id: UUID
    bundle_sha256: Sha256Digest
    article_id: UUID
    captured_text: CapturedText
    captured_text_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_captured_text(self) -> Self:
        actual = calculate_content_sha256(self.captured_text)
        if self.captured_text_sha256 != actual:
            raise ValueError("captured_text_sha256 must match captured_text")
        return self


class EvidenceBundlePolicyContent(ContractModel):
    """Exact frozen Policy text retrieved separately from bundle metadata."""

    bundle_id: UUID
    bundle_sha256: Sha256Digest
    policy_version_id: UUID
    captured_text: CapturedText
    content_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_captured_text(self) -> Self:
        actual = calculate_content_sha256(self.captured_text)
        if self.content_sha256 != actual:
            raise ValueError("content_sha256 must match captured Policy text")
        return self


class EvidenceBundlesResponse(ContractModel):
    """Complete sealed bundle directory ordered newest first."""

    items: tuple[EvidenceBundleSummary, ...]
    total: Annotated[int, Field(ge=0)]


__all__ = [
    "EvidenceBundle",
    "EvidenceBundleContent",
    "EvidenceBundleDetail",
    "EvidenceBundleItem",
    "EvidenceBundlePolicyContent",
    "EvidenceBundlePolicyItem",
    "EvidenceBundleSummary",
    "EvidenceBundlesResponse",
    "EvidenceItem",
    "EvidenceItems",
    "EvidenceKind",
    "calculate_content_sha256",
]
