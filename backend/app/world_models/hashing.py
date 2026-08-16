"""Canonical content addressing for immutable world snapshots."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.world_models.contracts import SnapshotEvidence, SnapshotPolicyEvidence, Verification


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_snapshot_json(
    world_model_id: UUID,
    version: int,
    verification: Verification,
    evidence: tuple[SnapshotEvidence, ...],
    policy_evidence: tuple[SnapshotPolicyEvidence, ...],
) -> str:
    """Serialize all frozen provenance with stable keys, timestamps, and array order."""
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("version must be int")
    if version < 1:
        raise ValueError(f"version must be positive, got {version}")
    if not evidence:
        raise ValueError("evidence must contain at least one copied article")
    payload: dict[str, object] = {
        "schema_version": "world-snapshot/v3" if policy_evidence else "world-snapshot/v2",
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
    if policy_evidence:
        payload["policy_evidence"] = [
            {
                "policy_version_id": str(item.policy_version_id),
                "authority_name": item.authority_name,
                "jurisdiction_code": item.jurisdiction_code,
                "homepage_url": str(item.homepage_url),
                "canonical_identifier": item.canonical_identifier,
                "source_sha256": item.source_sha256,
                "document_sha256": item.document_sha256,
                "version": item.version,
                "title": item.title,
                "original_url": str(item.original_url),
                "language": item.language,
                "publication_date": item.publication_date.isoformat(),
                "effective_from": (
                    None if item.effective_from is None else item.effective_from.isoformat()
                ),
                "effective_until": (
                    None if item.effective_until is None else item.effective_until.isoformat()
                ),
                "captured_at": _canonical_timestamp(item.captured_at),
                "content_sha256": item.content_sha256,
                "version_sha256": item.version_sha256,
            }
            for item in policy_evidence
        ]
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
    policy_evidence: tuple[SnapshotPolicyEvidence, ...],
) -> str:
    canonical_json = canonical_snapshot_json(
        world_model_id,
        version,
        verification,
        evidence,
        policy_evidence,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
