"""Contract behavior for lightweight immutable-attempt progress."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_runtime_settings
from app.main import create_app
from app.shared.progress import ParentProgress, build_parent_progress


def test_parent_progress_derives_status_counts_and_stable_revision() -> None:
    resource_id = uuid4()
    first = build_parent_progress(
        resource_id,
        2,
        ("succeeded", "running"),
        7,
        datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )
    observed_later = build_parent_progress(
        resource_id,
        2,
        ("succeeded", "running"),
        7,
        datetime(2026, 8, 16, 12, 1, tzinfo=UTC),
    )
    changed = build_parent_progress(
        resource_id,
        2,
        ("succeeded", "running"),
        8,
        datetime(2026, 8, 16, 12, 1, tzinfo=UTC),
    )

    assert first.status == "running"
    assert first.running_trial_count == 1
    assert first.succeeded_trial_count == 1
    assert first.progress_sha256 == observed_later.progress_sha256
    assert first.progress_sha256 != changed.progress_sha256


def test_parent_progress_rejects_tampered_revision() -> None:
    progress = build_parent_progress(
        uuid4(),
        1,
        ("failed",),
        0,
        datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )
    payload = progress.model_dump(mode="python")
    payload["progress_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="does not match"):
        ParentProgress.model_validate(payload)


def test_survey_progress_requires_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    response = client.get(f"/api/v2/matraix/survey-experiments/{uuid4()}/progress")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "MatrAIx Survey data is unavailable because DATABASE_URL is not configured"
    }
