"""Media API availability and strict public contract tests."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app

MEDIA_PATHS = (
    "/api/v2/media/overview",
    "/api/v2/media/articles",
    f"/api/v2/media/articles/{uuid4()}",
    "/api/v2/media/topics",
    f"/api/v2/media/topics/{uuid4()}/timeline",
    "/api/v2/media/sources",
    f"/api/v2/media/sources/{uuid4()}/evidence",
    "/api/v2/media/sync-status",
)


def test_media_endpoints_return_explicit_503_without_database_configuration() -> None:
    client = TestClient(create_app(load_runtime_settings({})))

    for path in MEDIA_PATHS:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Media data is unavailable because DATABASE_URL is not configured"
        }


def test_health_remains_available_without_media_database_configuration() -> None:
    client = TestClient(create_app(load_runtime_settings({})))

    response = client.get("/health")

    assert response.status_code == 200
