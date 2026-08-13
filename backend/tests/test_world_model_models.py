"""Application metadata checks for generic append-only world-model persistence."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import ApplicationBase
from app.world_models import models as world_model_models
from app.world_models.models import WorldSnapshotRecord
from app.world_models.repository import _require_sealed_snapshot

del world_model_models


def test_world_model_schema_uses_generic_frozen_snapshot_tables() -> None:
    assert {"world_models", "world_snapshots", "world_snapshot_evidence"}.issubset(
        ApplicationBase.metadata.tables
    )
    assert "world_snapshot_mentions" not in ApplicationBase.metadata.tables
    models = ApplicationBase.metadata.tables["world_models"]
    snapshots = ApplicationBase.metadata.tables["world_snapshots"]
    evidence = ApplicationBase.metadata.tables["world_snapshot_evidence"]
    assert "company_id" not in models.columns
    assert {"sealed_at", "snapshot_sha256"}.issubset(snapshots.columns.keys())
    assert not {"company_id", "company_canonical_name", "company_aliases"}.intersection(
        snapshots.columns.keys()
    )
    assert "captured_text" in evidence.columns
    assert tuple(column.name for column in evidence.primary_key.columns) == (
        "snapshot_id",
        "position",
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
    )
    with pytest.raises(RuntimeError, match=f"snapshot {snapshot.id} is not sealed"):
        _require_sealed_snapshot(snapshot)
