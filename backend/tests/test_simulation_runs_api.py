"""Strict OASIS platform-smoke HTTP contracts without external services."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.legacy_adc import LEGACY_ADC_WRITE_RETIRED_DETAIL
from app.main import create_app


def test_platform_smoke_endpoints_return_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    run_id = uuid4()
    responses = (
        client.post(
            "/api/v2/simulation-runs/platform-smoke",
            json={"scenario_id": str(uuid4()), "variant_id": str(uuid4()), "seed": 1},
        ),
        client.get("/api/v2/simulation-runs/platform-smoke"),
        client.get(f"/api/v2/simulation-runs/platform-smoke/{run_id}"),
        client.get("/api/v2/simulations/oasis/readiness"),
    )
    assert responses[0].status_code == 410
    assert responses[0].json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL}
    assert {response.status_code for response in responses[1:]} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses[1:])


def test_platform_smoke_post_is_retired_before_payload_or_database_validation() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    responses = (
        client.post("/api/v2/simulation-runs/platform-smoke", json={}),
        client.post(
            "/api/v2/simulation-runs/platform-smoke",
            json={"scenario_id": "not-a-uuid", "unexpected": True},
        ),
    )
    assert {response.status_code for response in responses} == {410}
    assert all(
        response.json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL} for response in responses
    )
