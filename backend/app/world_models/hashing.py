"""Canonical content addressing for immutable world snapshots."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.world_models.contracts import SnapshotEvidence, Verification


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_snapshot_json(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    evidence: tuple[SnapshotEvidence, ...],
) -> str:
    """Serialize all frozen provenance with stable keys, timestamps, and array order."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version must be int")
    if version < 1:
        raise ValueError(f"version must be positive, got {version}")
    if not evidence:
        raise ValueError("evidence must contain at least one copied article")
    payload = {
        "schema_version": "world-snapshot/v2",
        "world_model_id": str(world_model_id),
        "version": version,
        "verification": verification,
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
    evidence: tuple[SnapshotEvidence, ...],
) -> str:
    canonical_json = canonical_snapshot_json(world_model_id, version, verification, evidence)
    return sha256(canonical_json.encode("utf-8")).hexdigest()
