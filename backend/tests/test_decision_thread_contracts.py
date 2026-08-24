"""Strict contract coverage for draft and revisioned decision threads."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.decision_threads.contracts import DecisionThreadDetail, DecisionThreadRevision


def test_decision_thread_detail_accepts_a_draft_without_revisions() -> None:
    detail = DecisionThreadDetail(
        id=uuid4(),
        title="Tourism decision",
        decision_question="Which intervention should be evaluated?",
        created_at=datetime.now(UTC),
        latest_revision=None,
        revisions=(),
    )

    assert detail.latest_revision is None
    assert detail.revisions == ()


def test_decision_thread_detail_rejects_a_latest_revision_on_a_draft() -> None:
    revision = DecisionThreadRevision(
        id=uuid4(),
        version=1,
        world_model_id=uuid4(),
        world_snapshot_id=uuid4(),
        snapshot_sha256="a" * 64,
        scenario_id=None,
        scenario_sha256=None,
        cohort_id=None,
        cohort_sha256=None,
        semantic_experiment_id=None,
        experiment_sha256=None,
        created_at=datetime.now(UTC),
    )

    with pytest.raises(ValidationError, match="draft decision thread"):
        DecisionThreadDetail(
            id=uuid4(),
            title="Tourism decision",
            decision_question="Which intervention should be evaluated?",
            created_at=datetime.now(UTC),
            latest_revision=revision,
            revisions=(),
        )
