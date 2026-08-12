"""Canonical content addressing for immutable world snapshots."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.world_models.contracts import SnapshotCompany, SnapshotEvidence, Verification


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_snapshot_json(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    company: SnapshotCompany,
    evidence: tuple[SnapshotEvidence, ...],
) -> str:
    """Serialize all hashed fields with stable keys, timestamps, and array order."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version must be int")
    if version < 1:
        raise ValueError(f"version must be positive, got {version}")
    if not evidence:
        raise ValueError("evidence must contain at least one copied article")
    payload = {
        "world_model_id": str(world_model_id),
        "version": version,
        "verification": verification,
        "company": {
            "id": str(company.id),
            "canonical_name": company.canonical_name,
            "aliases": list(company.aliases),
        },
        "evidence": [
            {
                "article_id": str(item.article_id),
                "source_name": item.source_name,
                "original_url": str(item.original_url),
                "title": item.title,
                "published_at": _canonical_timestamp(item.published_at),
                "captured_at": _canonical_timestamp(item.captured_at),
                "country_code": item.country_code,
                "excerpt": item.excerpt,
                "captured_text_sha256": item.captured_text_sha256,
                "matched_aliases": list(item.matched_aliases),
                "mentions": [
                    {
                        "alias": context.alias,
                        "start_offset": context.start_offset,
                        "end_offset": context.end_offset,
                        "context": context.context,
                    }
                    for context in item.evidence_contexts
                ],
            }
            for item in evidence
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_snapshot_sha256(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    company: SnapshotCompany,
    evidence: tuple[SnapshotEvidence, ...],
) -> str:
    """Calculate the lowercase SHA-256 address of one canonical snapshot payload."""
    canonical_json = canonical_snapshot_json(
        world_model_id,
        version,
        verification,
        company,
        evidence,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
