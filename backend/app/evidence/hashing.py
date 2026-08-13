"""Canonical identity for the read-only Evidence Bundle projection."""

import json
from hashlib import sha256
from uuid import UUID

from app.shared.contracts import Sha256Digest

EVIDENCE_BUNDLE_SCHEMA_VERSION = "evidence-bundle/v1"


def canonical_evidence_bundle_json(
    bundle_id: UUID,
    snapshot_sha256: Sha256Digest,
) -> str:
    """Bind a bundle identity to one already verified immutable world snapshot."""
    if not isinstance(bundle_id, UUID):
        raise TypeError(f"bundle_id must be UUID, got {type(bundle_id).__name__}")
    if not isinstance(snapshot_sha256, str):
        raise TypeError(f"snapshot_sha256 must be str, got {type(snapshot_sha256).__name__}")
    if len(snapshot_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in snapshot_sha256
    ):
        raise ValueError("snapshot_sha256 must be a lowercase SHA-256 digest")
    return json.dumps(
        {
            "bundle_id": str(bundle_id),
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "snapshot_sha256": snapshot_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_evidence_bundle_sha256(
    bundle_id: UUID,
    snapshot_sha256: Sha256Digest,
) -> str:
    """Calculate the transitive content address for a sealed world snapshot bundle."""
    canonical_json = canonical_evidence_bundle_json(bundle_id, snapshot_sha256)
    return sha256(canonical_json.encode("utf-8")).hexdigest()


__all__ = [
    "EVIDENCE_BUNDLE_SCHEMA_VERSION",
    "calculate_evidence_bundle_sha256",
    "canonical_evidence_bundle_json",
]
