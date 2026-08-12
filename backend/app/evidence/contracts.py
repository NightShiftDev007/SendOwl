"""Immutable evidence packages that make decision runs reproducible."""

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Self

from pydantic import AwareDatetime, Field, model_validator

from app.media.contracts import MediaArticle
from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest


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
    company_ids: tuple[Identifier, ...]

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
