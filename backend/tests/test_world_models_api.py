"""World-model API availability and generic request checks."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import world_models as world_models_api
from app.api.world_models import require_world_model_session
from app.config import load_runtime_settings
from app.evidence.revisions import calculate_captured_text_sha256
from app.main import create_app
from app.world_models.contracts import (
    ModelDetail,
    SnapshotDetail,
    SnapshotEvidence,
    SnapshotEvidenceContent,
    SnapshotSummary,
    WorldModelCreateRequest,
)
from app.world_models.errors import SnapshotEvidenceLimitError, WorldSnapshotRevisionConflictError
from app.world_models.hashing import calculate_snapshot_sha256


def _request() -> dict[str, object]:
    return {
        "title": "Verified world",
        "evidence": [
            {
                "article_id": str(uuid4()),
                "evidence_revision_sha256": "a" * 64,
            }
        ],
        "verification": "human_confirmed",
    }


def test_world_model_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    model_id = uuid4()
    snapshot_id = uuid4()
    request = _request()
    responses = (
        client.get("/api/v2/world-models"),
        client.post("/api/v2/world-models", json=request),
        client.get(f"/api/v2/world-models/{model_id}"),
        client.post(
            f"/api/v2/world-models/{model_id}/snapshots",
            json={"evidence": request["evidence"], "verification": "human_confirmed"},
        ),
        client.get(f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}"),
        client.get(f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence-graph"),
        client.get(
            f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence/{uuid4()}/content"
        ),
    )
    for response in responses:
        assert response.status_code == 503


def test_world_model_post_converts_json_uuid_strings_before_handler(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    captured_requests: list[WorldModelCreateRequest] = []

    async def override_world_model_session() -> AsyncIterator[object]:
        yield object()

    async def create_world_model_response(
        session: object,
        request: WorldModelCreateRequest,
    ) -> ModelDetail:
        assert session is not None
        captured_requests.append(request)
        created_at = datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
        model_id = uuid4()
        snapshot_id = uuid4()
        title = "Verified update"
        content = "The source confirmed the update."
        evidence = (
            SnapshotEvidence(
                article_id=request.evidence[0].article_id,
                source_name="Example News",
                original_url="https://example.com/event",
                title=title,
                published_at=created_at,
                captured_at=created_at,
                country_code="US",
                excerpt=content,
                captured_text_sha256=calculate_captured_text_sha256(title, content),
            ),
        )
        digest = calculate_snapshot_sha256(model_id, 1, "human_confirmed", evidence)
        snapshot = SnapshotDetail(
            id=snapshot_id,
            world_model_id=model_id,
            version=1,
            verification="human_confirmed",
            snapshot_sha256=digest,
            created_at=created_at,
            evidence=evidence,
        )
        return ModelDetail(
            id=model_id,
            title=request.title,
            created_at=created_at,
            snapshots=(
                SnapshotSummary(
                    id=snapshot_id,
                    version=1,
                    evidence_count=1,
                    snapshot_sha256=digest,
                    created_at=created_at,
                ),
            ),
            latest_snapshot=snapshot,
        )

    application.dependency_overrides[require_world_model_session] = override_world_model_session
    monkeypatch.setattr(world_models_api, "create_world_model", create_world_model_response)
    article_id = uuid4()
    response = TestClient(application).post(
        "/api/v2/world-models",
        json={
            "title": "Verified world",
            "evidence": [
                {
                    "article_id": str(article_id),
                    "evidence_revision_sha256": "a" * 64,
                }
            ],
            "verification": "human_confirmed",
        },
    )
    assert response.status_code == 201
    assert captured_requests[0].evidence[0].article_id == article_id
    assert "company_id" not in response.json()
    assert "company" not in response.json()["latest_snapshot"]


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    (
        (WorldSnapshotRevisionConflictError((uuid4(),)), 409),
        (
            SnapshotEvidenceLimitError(
                resource="captured_text UTF-8 bytes per article",
                article_ids=(uuid4(),),
                actual=2_097_153,
                limit=2_097_152,
            ),
            422,
        ),
    ),
)
def test_world_model_post_maps_revision_and_limit_failures(
    monkeypatch,
    failure: WorldSnapshotRevisionConflictError | SnapshotEvidenceLimitError,
    expected_status: int,
) -> None:
    application = create_app(load_runtime_settings({}))

    async def override_world_model_session() -> AsyncIterator[object]:
        yield object()

    async def raise_failure(
        session: object,
        request: WorldModelCreateRequest,
    ) -> ModelDetail:
        assert session is not None
        assert request.evidence
        raise failure

    application.dependency_overrides[require_world_model_session] = override_world_model_session
    monkeypatch.setattr(world_models_api, "create_world_model", raise_failure)
    response = TestClient(application).post("/api/v2/world-models", json=_request())
    assert response.status_code == expected_status
    assert response.json() == {"detail": str(failure)}


def test_snapshot_content_endpoint_returns_only_frozen_content_contract(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    model_id = uuid4()
    snapshot_id = uuid4()
    article_id = uuid4()
    captured_text = "Event title\nEvent body"
    digest = calculate_captured_text_sha256("Event title", "Event body")

    async def override_world_model_session() -> AsyncIterator[object]:
        yield object()

    async def frozen_content(
        session: object,
        requested_model_id: object,
        requested_snapshot_id: object,
        requested_article_id: object,
    ) -> SnapshotEvidenceContent:
        assert session is not None
        assert (requested_model_id, requested_snapshot_id, requested_article_id) == (
            model_id,
            snapshot_id,
            article_id,
        )
        return SnapshotEvidenceContent(
            article_id=article_id,
            captured_text=captured_text,
            captured_text_sha256=digest,
        )

    application.dependency_overrides[require_world_model_session] = override_world_model_session
    monkeypatch.setattr(world_models_api, "get_world_snapshot_evidence_content", frozen_content)
    response = TestClient(application).get(
        f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence/{article_id}/content"
    )
    assert response.status_code == 200
    assert response.json() == {
        "article_id": str(article_id),
        "captured_text": captured_text,
        "captured_text_sha256": digest,
    }
