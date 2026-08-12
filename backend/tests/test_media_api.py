"""Media API availability and strict public contract tests."""

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app

MEDIA_PATHS = (
    "/api/v2/media/overview",
    "/api/v2/media/articles",
    "/api/v2/media/topics",
    "/api/v2/media/sources",
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
