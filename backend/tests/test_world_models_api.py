"""World-model API availability checks without external services."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import world_models as world_models_api
from app.api.world_models import require_world_model_session
from app.companies.coverage import calculate_captured_text_sha256
from app.config import load_runtime_settings
from app.main import create_app
from app.world_models.contracts import (
    ModelDetail,
    SnapshotCompany,
    SnapshotDetail,
    SnapshotEvidence,
    SnapshotEvidenceContent,
    SnapshotSummary,
    WorldModelCreateRequest,
)
from app.world_models.errors import (
    SnapshotEvidenceLimitError,
    WorldSnapshotRevisionConflictError,
)
from app.world_models.hashing import calculate_snapshot_sha256


def test_world_model_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    model_id = uuid4()
    snapshot_id = uuid4()
    request = {
        "title": "Verified world",
        "company_id": str(uuid4()),
        "evidence": [
            {
                "article_id": str(uuid4()),
                "evidence_revision_sha256": "a" * 64,
            }
        ],
        "verification": "human_confirmed",
    }

    responses = (
        client.get("/api/v2/world-models"),
        client.post("/api/v2/world-models", json=request),
        client.get(f"/api/v2/world-models/{model_id}"),
        client.post(
            f"/api/v2/world-models/{model_id}/snapshots",
            json={
                "evidence": request["evidence"],
                "verification": "human_confirmed",
            },
        ),
        client.get(f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}"),
        client.get(
            f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence/{uuid4()}/content"
        ),
    )

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "World model data is unavailable because DATABASE_URL is not configured"
        }


def test_world_model_post_converts_json_uuid_strings_before_handler(
    monkeypatch,
) -> None:
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
        company = SnapshotCompany(
            id=request.company_id,
            canonical_name="Acme",
            aliases=("Acme Inc.",),
        )
        title = "Acme update"
        content = "Acme confirmed the update."
        evidence = (
            SnapshotEvidence(
                article_id=request.evidence[0].article_id,
                source_name="Example News",
                original_url="https://example.com/acme",
                title=title,
                published_at=created_at,
                captured_at=created_at,
                country_code="US",
                excerpt=content,
                captured_text_sha256=calculate_captured_text_sha256(title, content),
                matched_aliases=("Acme",),
                evidence_contexts=(
                    {
                        "alias": "Acme",
                        "start_offset": 0,
                        "end_offset": 4,
                        "context": f"{title}\n{content}",
                    },
                ),
            ),
        )
        digest = calculate_snapshot_sha256(
            model_id,
            1,
            "human_confirmed",
            company,
            evidence,
        )
        snapshot = SnapshotDetail(
            id=snapshot_id,
            world_model_id=model_id,
            version=1,
            verification="human_confirmed",
            snapshot_sha256=digest,
            created_at=created_at,
            company=company,
            evidence=evidence,
        )
        return ModelDetail(
            id=model_id,
            title=request.title,
            company_id=request.company_id,
            created_at=created_at,
            snapshots=(
                SnapshotSummary(
                    id=snapshot_id,
                    version=1,
                    company_name=company.canonical_name,
                    evidence_count=1,
                    snapshot_sha256=digest,
                    created_at=created_at,
                ),
            ),
            latest_snapshot=snapshot,
        )

    application.dependency_overrides[require_world_model_session] = override_world_model_session
    monkeypatch.setattr(world_models_api, "create_world_model", create_world_model_response)
    company_id = uuid4()
    article_id = uuid4()

    response = TestClient(application).post(
        "/api/v2/world-models",
        json={
            "title": "Verified Acme world",
            "company_id": str(company_id),
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
    assert captured_requests[0].company_id == company_id
    assert captured_requests[0].evidence[0].article_id == article_id


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    (
        (WorldSnapshotRevisionConflictError((uuid4(),)), 409),
        (
            SnapshotEvidenceLimitError(
                resource="exact alias matches per article",
                article_ids=(uuid4(),),
                actual=201,
                limit=200,
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

    response = TestClient(application).post(
        "/api/v2/world-models",
        json={
            "title": "Verified Acme world",
            "company_id": str(uuid4()),
            "evidence": [
                {
                    "article_id": str(uuid4()),
                    "evidence_revision_sha256": "a" * 64,
                }
            ],
            "verification": "human_confirmed",
        },
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(failure)}


def test_snapshot_content_endpoint_returns_only_frozen_content_contract(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    model_id = uuid4()
    snapshot_id = uuid4()
    article_id = uuid4()
    captured_text = "Acme title\nAcme body"
    digest = calculate_captured_text_sha256("Acme title", "Acme body")

    async def override_world_model_session() -> AsyncIterator[object]:
        yield object()

    async def frozen_content(
        session: object,
        requested_model_id: object,
        requested_snapshot_id: object,
        requested_article_id: object,
    ) -> SnapshotEvidenceContent:
        assert session is not None
        assert requested_model_id == model_id
        assert requested_snapshot_id == snapshot_id
        assert requested_article_id == article_id
        return SnapshotEvidenceContent(
            article_id=article_id,
            captured_text=captured_text,
            captured_text_sha256=digest,
        )

    application.dependency_overrides[require_world_model_session] = override_world_model_session
    monkeypatch.setattr(
        world_models_api,
        "get_world_snapshot_evidence_content",
        frozen_content,
    )

    response = TestClient(application).get(
        f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence/{article_id}/content"
    )

    assert response.status_code == 200
    assert response.json() == {
        "article_id": str(article_id),
        "captured_text": captured_text,
        "captured_text_sha256": digest,
    }
