"""Canonical content address for a registry-only MatrAIx batch."""

import json
from hashlib import sha256
from typing import TypedDict
from uuid import UUID

from app.matraix_batch.contracts import MatraixBatchKind

SCHEMA_VERSION = "matraix-batch-registry/v1"


class CanonicalBatchItem(TypedDict):
    position: int
    kind: MatraixBatchKind
    parent_id: str
    parent_sha256: str


class CanonicalBatchPayload(TypedDict):
    schema_version: str
    title: str
    items: list[CanonicalBatchItem]


def calculate_batch_registry_sha256(
    title: str,
    items: tuple[tuple[int, MatraixBatchKind, UUID, str], ...],
) -> str:
    payload: CanonicalBatchPayload = {
        "schema_version": SCHEMA_VERSION,
        "title": title,
        "items": [
            {
                "position": position,
                "kind": kind,
                "parent_id": str(parent_id),
                "parent_sha256": parent_sha256,
            }
            for position, kind, parent_id, parent_sha256 in items
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["SCHEMA_VERSION", "calculate_batch_registry_sha256"]
