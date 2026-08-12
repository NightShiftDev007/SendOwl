"""Application metadata checks for append-only world-model persistence."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import ApplicationBase
from app.world_models import models as world_model_models
from app.world_models.models import WorldSnapshotRecord
from app.world_models.repository import _require_sealed_snapshot

del world_model_models


def test_world_model_schema_uses_frozen_snapshot_tables_and_ordered_keys() -> None:
    assert {
        "world_models",
        "world_snapshots",
        "world_snapshot_evidence",
        "world_snapshot_mentions",
    }.issubset(ApplicationBase.metadata.tables)

    snapshots = ApplicationBase.metadata.tables["world_snapshots"]
    evidence = ApplicationBase.metadata.tables["world_snapshot_evidence"]
    mentions = ApplicationBase.metadata.tables["world_snapshot_mentions"]

    assert {
        "company_id",
        "company_canonical_name",
        "company_aliases",
        "sealed_at",
    }.issubset(snapshots.columns.keys())
    assert "captured_text" in evidence.columns
    assert tuple(column.name for column in evidence.primary_key.columns) == (
        "snapshot_id",
        "position",
    )
    assert tuple(column.name for column in mentions.primary_key.columns) == (
        "snapshot_id",
        "evidence_position",
        "position",
    )
    assert all(
        not foreign_key.target_fullname.startswith("media_")
        for foreign_key in evidence.foreign_keys
    )


def test_unsealed_snapshot_is_rejected_by_read_projection_guard() -> None:
    snapshot = WorldSnapshotRecord(
        id=uuid4(),
        world_model_id=uuid4(),
        version=1,
        verification="human_confirmed",
        snapshot_sha256="a" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        sealed_at=None,
        company_id=uuid4(),
        company_canonical_name="Acme",
        company_aliases=[],
    )

    with pytest.raises(RuntimeError, match=f"snapshot {snapshot.id} is not sealed"):
        _require_sealed_snapshot(snapshot)
