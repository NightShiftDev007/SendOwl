"""Evidence Bundle HTTP availability and route shape."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.evidence_bundles import create_evidence_bundles_router


def _application() -> FastAPI:
    application = FastAPI()
    application.state.database = None
    application.include_router(create_evidence_bundles_router())
    return application


def test_evidence_bundle_endpoints_fail_explicitly_without_database() -> None:
    bundle_id = uuid4()
    article_id = uuid4()
    client = TestClient(_application())

    responses = (
        client.get("/api/v2/evidence-bundles"),
        client.get(f"/api/v2/evidence-bundles/{bundle_id}"),
        client.get(f"/api/v2/evidence-bundles/{bundle_id}/items/{article_id}/content"),
    )

    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)
