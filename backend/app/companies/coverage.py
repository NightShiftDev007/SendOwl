"""Pure evidence-context and revision construction for company media coverage."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.companies.contracts import CompanyAliasMatch, CompanyEvidenceContext


def combine_article_text(title: str, content: str | None) -> str:
    """Build the exact text whose offsets are exposed by the coverage contract."""
    if not isinstance(title, str):
        raise TypeError(f"title must be str, got {type(title).__name__}")
    if content is not None and not isinstance(content, str):
        raise TypeError(f"content must be str or None, got {type(content).__name__}")
    return f"{title}\n{content or ''}"


def calculate_captured_text_sha256(title: str, content: str | None) -> str:
    """Hash the exact combined text exposed by company evidence offsets."""
    return sha256(combine_article_text(title, content).encode("utf-8")).hexdigest()


def _canonical_evidence_timestamp(value: datetime, field_name: str) -> str:
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
    """Serialize every mutable field reviewed and frozen for one evidence item."""
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
        "crawled_at": _canonical_evidence_timestamp(crawled_at, "crawled_at"),
        "published_at": _canonical_evidence_timestamp(published_at, "published_at"),
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
    """Hash the complete mutable article/source revision shown and frozen."""
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


def unique_matched_aliases(matches: tuple[CompanyAliasMatch, ...]) -> tuple[str, ...]:
    """Return configured aliases once, ordered by their first exact occurrence."""
    seen: set[str] = set()
    aliases: list[str] = []
    for match in matches:
        normalized_alias = match.alias.casefold()
        if normalized_alias in seen:
            continue
        seen.add(normalized_alias)
        aliases.append(match.alias)
    return tuple(aliases)


def build_evidence_contexts(
    combined_text: str,
    matches: tuple[CompanyAliasMatch, ...],
    context_radius: int,
) -> tuple[CompanyEvidenceContext, ...]:
    """Build deterministic bounded source windows without changing global offsets."""
    if not isinstance(combined_text, str):
        raise TypeError(f"combined_text must be str, got {type(combined_text).__name__}")
    if not isinstance(matches, tuple) or any(
        not isinstance(match, CompanyAliasMatch) for match in matches
    ):
        raise TypeError("matches must be a tuple of CompanyAliasMatch values")
    if isinstance(context_radius, bool) or not isinstance(context_radius, int):
        raise TypeError("context_radius must be int")
    if context_radius < 0:
        raise ValueError(f"context_radius must be non-negative, got {context_radius}")

    contexts: list[CompanyEvidenceContext] = []
    for match in matches:
        if match.end_offset > len(combined_text):
            raise ValueError(
                "company alias match exceeds combined article text: "
                f"range=[{match.start_offset},{match.end_offset}), length={len(combined_text)}"
            )
        context_start = max(0, match.start_offset - context_radius)
        context_end = min(len(combined_text), match.end_offset + context_radius)
        contexts.append(
            CompanyEvidenceContext(
                alias=match.alias,
                start_offset=match.start_offset,
                end_offset=match.end_offset,
                context=combined_text[context_start:context_end],
            )
        )
    return tuple(contexts)
