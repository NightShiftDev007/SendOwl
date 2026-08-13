"""Deterministic, non-inferred evidence graph checks."""

from datetime import UTC, datetime
from uuid import uuid4

from app.evidence.revisions import calculate_captured_text_sha256
from app.world_models.contracts import SnapshotDetail, SnapshotEvidence
from app.world_models.graph import project_evidence_world_graph


def _snapshot() -> SnapshotDetail:
    created_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    return SnapshotDetail(
        id=uuid4(),
        world_model_id=uuid4(),
        version=2,
        verification="human_confirmed",
        snapshot_sha256="a" * 64,
        created_at=created_at,
        evidence=(
            SnapshotEvidence(
                article_id=uuid4(),
                source_name="Example News",
                original_url="https://example.com/one",
                title="Verified event one",
                published_at=created_at,
                captured_at=created_at,
                country_code="CN",
                excerpt="First directly observed report.",
                captured_text_sha256=calculate_captured_text_sha256("one", "body"),
            ),
            SnapshotEvidence(
                article_id=uuid4(),
                source_name="Example News",
                original_url="https://example.com/two",
                title="Verified event two",
                published_at=created_at,
                captured_at=created_at,
                country_code=None,
                excerpt="Second directly observed report.",
                captured_text_sha256=calculate_captured_text_sha256("two", "body"),
            ),
        ),
    )


def test_evidence_graph_is_deterministic_and_contains_only_direct_relations() -> None:
    snapshot = _snapshot()
    first = project_evidence_world_graph(snapshot.world_model_id, snapshot)
    second = project_evidence_world_graph(snapshot.world_model_id, snapshot)

    assert first == second
    assert first.provider == "postgres_projection"
    assert first.schema_version == "evidence-world-graph/v1"
    assert tuple(node.kind for node in first.nodes) == (
        "world_snapshot",
        "article",
        "article",
        "source",
        "country",
    )
    assert tuple(edge.kind for edge in first.edges) == (
        "contains_evidence",
        "published_by",
        "located_in",
        "contains_evidence",
        "published_by",
    )


def test_evidence_graph_hash_changes_when_frozen_snapshot_identity_changes() -> None:
    snapshot = _snapshot()
    original = project_evidence_world_graph(snapshot.world_model_id, snapshot)
    changed = project_evidence_world_graph(
        snapshot.world_model_id,
        snapshot.model_copy(update={"snapshot_sha256": "b" * 64}),
    )
    assert original.graph_sha256 != changed.graph_sha256
    assert original.id == changed.id
