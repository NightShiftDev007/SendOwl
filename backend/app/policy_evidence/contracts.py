"""Strict contracts for captured Policy evidence."""

from datetime import date, datetime
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

from app.policy_evidence.hashing import (
    calculate_policy_content_sha256,
    calculate_policy_document_sha256,
    calculate_policy_source_sha256,
    calculate_policy_version_sha256,
)
from app.shared.contracts import ContractModel, LanguageCode, Sha256Digest

PolicyTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=500, pattern=r"^[^\r\n]+$"),
]
AuthorityName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$"),
]
JurisdictionCode = Annotated[
    str,
    StringConstraints(min_length=2, max_length=16, pattern=r"^[A-Z0-9][A-Z0-9-]+$"),
]
CanonicalIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256, pattern=r"^[^\r\n]+$"),
]
CapturedPolicyText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2_000_000, strip_whitespace=False),
]


def _request_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field_name} must be an ISO date without a time component")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"{field_name} must be an ISO date string; received {type(value).__name__}"
        )
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"{field_name} must be a valid ISO date string; received {value!r}"
        ) from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use canonical YYYY-MM-DD format; received {value!r}")
    return parsed


class PolicySourceInput(ContractModel):
    authority_name: AuthorityName
    jurisdiction_code: JurisdictionCode
    homepage_url: HttpUrl


class PolicySource(PolicySourceInput):
    id: UUID
    source_sha256: Sha256Digest
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        expected = calculate_policy_source_sha256(
            self.authority_name,
            self.jurisdiction_code,
            str(self.homepage_url),
        )
        if self.source_sha256 != expected:
            raise ValueError("Policy source digest does not match its identity")
        return self


class PolicyVersionInput(ContractModel):
    title: PolicyTitle
    original_url: HttpUrl
    language: LanguageCode
    publication_date: date
    effective_from: date | None
    effective_until: date | None
    captured_text: CapturedPolicyText
    verification: Literal["human_confirmed"]

    @field_validator("publication_date", mode="before")
    @classmethod
    def parse_publication_date(cls, value: object) -> date:
        return _request_date(value, "publication_date")

    @field_validator("effective_from", mode="before")
    @classmethod
    def parse_effective_from(cls, value: object) -> date | None:
        if value is None:
            return None
        return _request_date(value, "effective_from")

    @field_validator("effective_until", mode="before")
    @classmethod
    def parse_effective_until(cls, value: object) -> date | None:
        if value is None:
            return None
        return _request_date(value, "effective_until")

    @model_validator(mode="after")
    def validate_effectivity(self) -> Self:
        if self.verification != "human_confirmed":
            raise ValueError("Policy evidence verification must be human_confirmed")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("effective_until must be later than effective_from")
        return self


class PolicyDocumentCaptureRequest(PolicyVersionInput):
    source: PolicySourceInput
    canonical_identifier: CanonicalIdentifier


class PolicyVersionCaptureRequest(PolicyVersionInput):
    pass


class PolicyVersionSummary(ContractModel):
    id: UUID
    version: Annotated[int, Field(ge=1, le=100)]
    title: PolicyTitle
    original_url: HttpUrl
    language: LanguageCode
    publication_date: date
    effective_from: date | None
    effective_until: date | None
    captured_at: AwareDatetime
    verification: Literal["human_confirmed"]
    content_sha256: Sha256Digest
    version_sha256: Sha256Digest

    def verify_digest(self, document_sha256: str) -> None:
        expected = calculate_policy_version_sha256(
            document_sha256,
            self.title,
            str(self.original_url),
            self.language,
            self.publication_date,
            self.effective_from,
            self.effective_until,
            self.content_sha256,
        )
        if self.version_sha256 != expected:
            raise ValueError("Policy version digest does not match its frozen metadata")
        if self.verification != "human_confirmed":
            raise ValueError("Policy version must be human_confirmed")


class PolicyDocumentSummary(ContractModel):
    id: UUID
    source: PolicySource
    canonical_identifier: CanonicalIdentifier
    document_sha256: Sha256Digest
    created_at: AwareDatetime
    version_count: Annotated[int, Field(ge=1, le=100)]
    latest_version: PolicyVersionSummary

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = calculate_policy_document_sha256(
            self.source.source_sha256,
            self.canonical_identifier,
        )
        if self.document_sha256 != expected:
            raise ValueError("Policy document digest does not match its stable identity")
        if self.latest_version.version != self.version_count:
            raise ValueError("latest Policy version must equal version_count")
        self.latest_version.verify_digest(self.document_sha256)
        return self


class PolicyDocumentDetail(PolicyDocumentSummary):
    versions: Annotated[tuple[PolicyVersionSummary, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def validate_versions(self) -> Self:
        if tuple(item.version for item in self.versions) != tuple(range(1, len(self.versions) + 1)):
            raise ValueError("Policy versions must be contiguous and start at one")
        if len(self.versions) != self.version_count or self.versions[-1] != self.latest_version:
            raise ValueError("Policy version history must match the latest summary")
        for version in self.versions:
            version.verify_digest(self.document_sha256)
        return self


class PolicyDocumentsResponse(ContractModel):
    items: Annotated[tuple[PolicyDocumentSummary, ...], Field(max_length=50)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]
    total: Annotated[int, Field(ge=0)]


class PolicyVersionContent(ContractModel):
    document_id: UUID
    version_id: UUID
    captured_text: CapturedPolicyText
    content_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if calculate_policy_content_sha256(self.captured_text) != self.content_sha256:
            raise ValueError("Policy content digest does not match captured_text")
        return self
