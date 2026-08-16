"""Policy evidence contracts, hashes, and unavailable API behavior."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.policy_evidence.contracts import (
    PolicyDocumentCaptureRequest,
    PolicyDocumentDetail,
    PolicySource,
    PolicyVersionSummary,
)
from app.policy_evidence.hashing import (
    calculate_policy_content_sha256,
    calculate_policy_document_sha256,
    calculate_policy_source_sha256,
    calculate_policy_version_sha256,
)


def test_policy_contract_validates_identity_effectivity_and_content_hashes() -> None:
    created_at = datetime(2026, 8, 16, tzinfo=UTC)
    homepage = "https://policy.example.gov/"
    source_sha = calculate_policy_source_sha256("Example Authority", "EX", homepage)
    document_sha = calculate_policy_document_sha256(source_sha, "EX-2026-17")
    content = "Section 1. This captured policy text is authoritative evidence."
    content_sha = calculate_policy_content_sha256(content)
    publication_date = date(2026, 8, 1)
    effective_from = date(2026, 9, 1)
    version_sha = calculate_policy_version_sha256(
        document_sha,
        "Example Policy",
        "https://policy.example.gov/documents/17",
        "en",
        publication_date,
        effective_from,
        None,
        content_sha,
    )
    source = PolicySource(
        id=uuid4(),
        authority_name="Example Authority",
        jurisdiction_code="EX",
        homepage_url=homepage,
        source_sha256=source_sha,
        created_at=created_at,
    )
    version = PolicyVersionSummary(
        id=uuid4(),
        version=1,
        title="Example Policy",
        original_url="https://policy.example.gov/documents/17",
        language="en",
        publication_date=publication_date,
        effective_from=effective_from,
        effective_until=None,
        captured_at=created_at,
        verification="human_confirmed",
        content_sha256=content_sha,
        version_sha256=version_sha,
    )
    detail = PolicyDocumentDetail(
        id=uuid4(),
        source=source,
        canonical_identifier="EX-2026-17",
        document_sha256=document_sha,
        created_at=created_at,
        version_count=1,
        latest_version=version,
        versions=(version,),
    )

    assert detail.latest_version.effective_from == effective_from
    with pytest.raises(ValueError, match="digest"):
        PolicyDocumentDetail.model_validate(
            {**detail.model_dump(mode="python"), "document_sha256": "f" * 64}
        )


def test_policy_capture_request_parses_only_canonical_iso_dates() -> None:
    payload = {
        "source": {
            "authority_name": "Example Authority",
            "jurisdiction_code": "EX",
            "homepage_url": "https://policy.example.gov/",
        },
        "canonical_identifier": "EX-2026-17",
        "title": "Example Policy",
        "original_url": "https://policy.example.gov/documents/17",
        "language": "en",
        "publication_date": "2026-08-01",
        "effective_from": "2026-09-01",
        "effective_until": None,
        "captured_text": "Captured policy text.",
        "verification": "human_confirmed",
    }

    request = PolicyDocumentCaptureRequest.model_validate(payload)

    assert request.publication_date == date(2026, 8, 1)
    assert request.effective_from == date(2026, 9, 1)
    with pytest.raises(ValueError, match="canonical YYYY-MM-DD"):
        PolicyDocumentCaptureRequest.model_validate({**payload, "publication_date": "20260801"})


def test_policy_routes_require_dedicated_application_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    document_id = uuid4()
    version_id = uuid4()
    responses = (
        client.get("/api/v2/policy-documents"),
        client.get(f"/api/v2/policy-documents/{document_id}"),
        client.get(f"/api/v2/policy-documents/{document_id}/versions/{version_id}/content"),
        client.post(
            "/api/v2/policy-documents",
            json={
                "source": {
                    "authority_name": "Example Authority",
                    "jurisdiction_code": "EX",
                    "homepage_url": "https://policy.example.gov/",
                },
                "canonical_identifier": "EX-2026-17",
                "title": "Example Policy",
                "original_url": "https://policy.example.gov/documents/17",
                "language": "en",
                "publication_date": "2026-08-01",
                "effective_from": "2026-09-01",
                "effective_until": None,
                "captured_text": "Captured policy text.",
                "verification": "human_confirmed",
            },
        ),
    )

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Policy evidence is unavailable because DATABASE_URL is not configured"
        }
