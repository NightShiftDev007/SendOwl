"""Canonical media-evidence revision and captured-content addressing."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID


def combine_article_text(title: str, content: str | None) -> str:
    """Build the exact article text frozen by a world snapshot."""
    if not isinstance(title, str):
        raise TypeError(f"title must be str, got {type(title).__name__}")
    if content is not None and not isinstance(content, str):
        raise TypeError(f"content must be str or None, got {type(content).__name__}")
    return f"{title}\n{content or ''}"


def calculate_captured_text_sha256(title: str, content: str | None) -> str:
    """Hash the exact title/newline/content text frozen by a world snapshot."""
    return sha256(combine_article_text(title, content).encode("utf-8")).hexdigest()


def _canonical_timestamp(value: datetime, field_name: str) -> str:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_evidence_revision_json(
    title: str,
    content: str | None,
    summary: str | None,
    url: str,
    published_at: datetime,
    crawled_at: datetime,
    country_code: str | None,
    source_id: UUID,
    source_name: str,
) -> str:
    """Serialize every mutable article/source field reviewed before snapshot capture."""
    if not isinstance(title, str):
        raise TypeError(f"title must be str, got {type(title).__name__}")
    if content is not None and not isinstance(content, str):
        raise TypeError(f"content must be str or None, got {type(content).__name__}")
    if summary is not None and not isinstance(summary, str):
        raise TypeError(f"summary must be str or None, got {type(summary).__name__}")
    if not isinstance(url, str):
        raise TypeError(f"url must be str, got {type(url).__name__}")
    if country_code is not None and not isinstance(country_code, str):
        raise TypeError(f"country_code must be str or None, got {type(country_code).__name__}")
    if not isinstance(source_id, UUID):
        raise TypeError(f"source_id must be UUID, got {type(source_id).__name__}")
    if not isinstance(source_name, str):
        raise TypeError(f"source_name must be str, got {type(source_name).__name__}")
    payload = {
        "content": content,
        "country_code": country_code,
        "crawled_at": _canonical_timestamp(crawled_at, "crawled_at"),
        "published_at": _canonical_timestamp(published_at, "published_at"),
        "source_id": str(source_id),
        "source_name": source_name,
        "summary": summary,
        "title": title,
        "url": url,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_evidence_revision_sha256(
    title: str,
    content: str | None,
    summary: str | None,
    url: str,
    published_at: datetime,
    crawled_at: datetime,
    country_code: str | None,
    source_id: UUID,
    source_name: str,
) -> str:
    """Hash the complete mutable media revision exposed for human confirmation."""
    canonical_json = canonical_evidence_revision_json(
        title,
        content,
        summary,
        url,
        published_at,
        crawled_at,
        country_code,
        source_id,
        source_name,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
