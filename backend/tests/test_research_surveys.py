"""Native research Survey boundary and content-address tests."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_runtime_settings
from app.main import create_app
from app.research_surveys.contracts import ResearchSurveyCreateRequest
from app.research_surveys.hashing import instrument_sha256, survey_sha256, trial_sha256


def test_create_request_parses_transport_uuids_and_rejects_adc_fields() -> None:
    project_id = uuid4()
    run_id = uuid4()
    request = ResearchSurveyCreateRequest.model_validate(
        {
            "research_project_id": str(project_id),
            "research_simulation_run_id": str(run_id),
        }
    )

    assert request.research_project_id == project_id
    assert request.research_simulation_run_id == run_id
    assert isinstance(request.research_project_id, UUID)
    with pytest.raises(ValidationError):
        ResearchSurveyCreateRequest.model_validate(
            {
                "research_project_id": str(project_id),
                "research_simulation_run_id": str(run_id),
                "alternative_id": str(uuid4()),
            }
        )


def test_native_survey_hashes_bind_single_run_without_variant_semantics() -> None:
    digest = survey_sha256("a" * 64, "b" * 64, "c" * 64, "model", "d" * 64)

    assert len(instrument_sha256()) == 64
    assert len(digest) == 64
    assert trial_sha256(digest, 0, uuid4(), "e" * 64) != trial_sha256(
        digest,
        1,
        uuid4(),
        "e" * 64,
    )


def test_native_routes_fail_explicitly_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    survey_id = uuid4()

    for response in (
        client.get("/api/v2/research-surveys"),
        client.get("/api/v2/research-surveys/readiness"),
        client.get(f"/api/v2/research-surveys/{survey_id}"),
        client.post(
            "/api/v2/research-surveys",
            json={
                "research_project_id": str(uuid4()),
                "research_simulation_run_id": str(uuid4()),
            },
        ),
    ):
        assert response.status_code == 503
        assert "DATABASE_URL" in response.json()["detail"]


def test_all_adc_comparison_writes_are_retired() -> None:
    client = TestClient(create_app(load_runtime_settings({})))

    responses = (
        client.post("/api/v2/scenarios", json={}),
        client.post("/api/v2/semantic-experiments", json={}),
        client.post("/api/v2/matraix/survey-experiments", json={}),
        client.post(f"/api/v2/matraix/survey-experiments/{uuid4()}/retry", json={}),
    )
    assert {response.status_code for response in responses} == {410}
    assert all(
        "legacy ADC write surface is retired" in response.json()["detail"] for response in responses
    )
