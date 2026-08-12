"""Strict contracts for company identity, monitoring, and evidence coverage."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.media.contracts import MediaArticleSummary
from app.shared.contracts import (
    ContractModel,
    Identifier,
    LanguageCode,
    NonEmptyText,
    Sha256Digest,
)

type CompanyName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]


class CompanyAlias(ContractModel):
    """One source-backed name used to resolve a company."""

    value: NonEmptyText
    language: LanguageCode
    evidence_ids: tuple[Identifier, ...]


class CompanyProfile(ContractModel):
    """Canonical identity shared by evidence and scenario domains."""

    company_id: Identifier
    canonical_name: NonEmptyText
    jurisdiction: NonEmptyText
    aliases: tuple[CompanyAlias, ...]


class MatchableCompany(ContractModel):
    """Minimal company identity accepted by the shared alias-matching kernel."""

    company_id: Identifier
    names: Annotated[tuple[CompanyName, ...], Field(min_length=1)]


class CompanyAliasMatch(ContractModel):
    """One resolved configured alias and its exact surface range in source text."""

    company_id: Identifier
    alias: CompanyName
    surface_form: NonEmptyText
    start_offset: NonNegativeInt
    end_offset: PositiveInt

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        """Reject empty or reversed source ranges."""
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class CompanyMention(ContractModel):
    """Exact character range where evidence mentions a resolved company."""

    company_id: Identifier
    evidence_id: Identifier
    surface_form: NonEmptyText
    start_offset: NonNegativeInt
    end_offset: PositiveInt

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        """Reject empty or reversed source ranges."""
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class CompanyCreateRequest(ContractModel):
    """User-supplied identity for one monitored company."""

    canonical_name: CompanyName
    aliases: tuple[CompanyName, ...]

    @field_validator("aliases", mode="before")
    @classmethod
    def accept_json_alias_array(cls, value: object) -> object:
        """Convert the JSON array transport shape to an immutable domain tuple."""
        if isinstance(value, list):
            return tuple(value)
        return value


class CompanyItem(ContractModel):
    """Persisted monitored company returned by the public API."""

    id: UUID
    canonical_name: CompanyName
    aliases: tuple[CompanyName, ...]
    created_at: AwareDatetime


class CompaniesResponse(ContractModel):
    """Complete monitored-company catalog."""

    items: tuple[CompanyItem, ...]
    total: NonNegativeInt


class CompanyEvidenceContext(ContractModel):
    """Deterministic source window around one exact company alias match.

    Offsets always refer to ``article.title + "\\n" + (article.content or "")``.
    """

    alias: CompanyName
    start_offset: NonNegativeInt
    end_offset: PositiveInt
    context: NonEmptyText

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        """Reject empty or reversed source ranges."""
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        return self


class CompanyCoverageItem(ContractModel):
    """One media article with exact deterministic company evidence."""

    article: MediaArticleSummary
    captured_text_sha256: Sha256Digest
    evidence_revision_sha256: Sha256Digest
    matched_aliases: Annotated[tuple[CompanyName, ...], Field(min_length=1)]
    evidence_contexts: Annotated[tuple[CompanyEvidenceContext, ...], Field(min_length=1)]


class CompanyCoverageResponse(ContractModel):
    """Exact media coverage for one monitored company."""

    company: CompanyItem
    total_matching_articles: NonNegativeInt
    source_count: NonNegativeInt
    country_count: NonNegativeInt
    topic_count: NonNegativeInt
    items: tuple[CompanyCoverageItem, ...]
    page: PositiveInt
    page_size: Annotated[int, Field(ge=1, le=100)]
