"""Semantic HTTP availability, validation, and error mapping."""

from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.semantic_experiments import require_semantic_experiment_session
from app.config import load_runtime_settings
from app.main import create_app


def _payload() -> dict[str, object]:
    return {
        "scenario_id": str(uuid4()),
        "cohort_id": str(uuid4()),
        "alternative_ids": [str(uuid4())],
        "seeds": [7],
        "rounds": 1,
        "minutes_per_round": 30,
    }


def test_semantic_reads_require_database_and_legacy_write_is_retired() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    experiment_id = uuid4()
    trial_id = uuid4()
    responses = (
        client.get("/api/v2/semantic-experiments"),
        client.get(f"/api/v2/semantic-experiments/{experiment_id}"),
        client.get(f"/api/v2/semantic-experiments/{experiment_id}/comparison"),
        client.get(f"/api/v2/semantic-trials/{trial_id}/events"),
        client.get("/api/v2/simulations/oasis/semantic-readiness"),
    )

    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)
    retired = client.post("/api/v2/semantic-experiments", json=_payload())
    assert retired.status_code == 410
    assert "legacy ADC write surface is retired" in retired.json()["detail"]


def test_semantic_post_is_retired_before_request_contract_validation() -> None:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_semantic_experiment_session] = session_override
    client = TestClient(application)
    payload = _payload()

    extra = client.post(
        "/api/v2/semantic-experiments",
        json={**payload, "model_name": "client-must-not-choose"},
    )
    coerced = client.post(
        "/api/v2/semantic-experiments",
        json={**payload, "seeds": ["7"]},
    )

    assert extra.status_code == 410
    assert coerced.status_code == 410


def test_semantic_event_cursor_has_strict_bounds() -> None:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_semantic_experiment_session] = session_override
    trial_id = uuid4()
    client = TestClient(application)

    assert (
        client.get(f"/api/v2/semantic-trials/{trial_id}/events?after_sequence=-1").status_code
        == 422
    )
    assert client.get(f"/api/v2/semantic-trials/{trial_id}/events?limit=201").status_code == 422
