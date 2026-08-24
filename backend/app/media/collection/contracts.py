"""Strict contracts for SandOwl-owned media collection."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
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

type CollectionMode = Literal["rss", "web"]
type CollectionStatus = Literal["running", "succeeded", "failed", "skipped"]
type CollectionText = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


def _public_http_url_shape(value: str, field_name: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{field_name} must be an HTTP(S) URL without credentials, query, or fragment"
        )
    return value


class NativeMediaSourceCreateRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: Annotated[
        str,
        StringConstraints(
            min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True
        ),
    ]
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    homepage_url: Annotated[str, StringConstraints(min_length=8, max_length=500)]
    media_type: Literal["newspaper", "agency", "broadcast", "online"]
    language: Annotated[str, StringConstraints(min_length=2, max_length=10)]
    collection_mode: CollectionMode
    feed_url: Annotated[str, StringConstraints(min_length=8, max_length=500)] | None
    poll_interval_seconds: Annotated[int, Field(ge=300, le=86400)]

    @field_validator("homepage_url", "feed_url")
    @classmethod
    def validate_url(cls, value: str | None, info) -> str | None:
        return None if value is None else _public_http_url_shape(value, info.field_name)

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.collection_mode == "rss" and self.feed_url is None:
            raise ValueError("RSS collection requires feed_url")
        return self


class NativeMediaCollectionConfigRequest(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool
    collection_mode: CollectionMode
    feed_url: Annotated[str, StringConstraints(min_length=8, max_length=500)] | None
    poll_interval_seconds: Annotated[int, Field(ge=300, le=86400)]

    @field_validator("feed_url")
    @classmethod
    def validate_feed_url(cls, value: str | None) -> str | None:
        return None if value is None else _public_http_url_shape(value, "feed_url")

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.collection_mode == "rss" and self.feed_url is None:
            raise ValueError("RSS collection requires feed_url")
        return self


class NativeMediaCollectionConfig(ContractModel):
    source_id: UUID
    enabled: bool
    collection_mode: CollectionMode
    feed_url: str | None
    poll_interval_seconds: Annotated[int, Field(ge=300, le=86400)]
    config_sha256: Sha256Digest
    last_attempt_at: AwareDatetime | None
    last_success_at: AwareDatetime | None
    consecutive_failures: Annotated[int, Field(ge=0)]


class NativeMediaCollectionRun(ContractModel):
    id: UUID
    source_id: UUID
    status: CollectionStatus
    worker_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    config_sha256: Sha256Digest
    scheduled_at: AwareDatetime
    started_at: AwareDatetime
    completed_at: AwareDatetime | None
    articles_discovered: Annotated[int, Field(ge=0)]
    articles_inserted: Annotated[int, Field(ge=0)]
    articles_existing: Annotated[int, Field(ge=0)]
    error_code: str | None
    error_message: str | None


class NativeMediaCollectionAlert(ContractModel):
    id: UUID
    source_id: UUID
    kind: Literal["consecutive_failures", "no_content"]
    severity: Literal["warning", "critical"]
    message: CollectionText
    observed_at: AwareDatetime


class NativeMediaCollectionStatus(ContractModel):
    generated_at: AwareDatetime
    worker_online: bool
    enabled_source_count: Annotated[int, Field(ge=0)]
    due_source_count: Annotated[int, Field(ge=0)]
    latest_runs: Annotated[tuple[NativeMediaCollectionRun, ...], Field(max_length=20)]
    active_alerts: Annotated[tuple[NativeMediaCollectionAlert, ...], Field(max_length=50)]
    limitations: Annotated[tuple[CollectionText, ...], Field(min_length=1)]
