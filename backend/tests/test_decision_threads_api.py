"""Decision-thread API availability without an external database."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.legacy_adc import LEGACY_ADC_WRITE_RETIRED_DETAIL
from app.main import create_app


def test_decision_thread_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    thread_id = uuid4()
    context = {
        "world_model_id": str(uuid4()),
        "world_snapshot_id": str(uuid4()),
        "scenario_id": None,
        "cohort_id": None,
        "semantic_experiment_id": None,
    }

    read_responses = (
        client.get("/api/v2/decision-threads"),
        client.get(f"/api/v2/decision-threads/{thread_id}"),
    )
    write_responses = (
        client.post(
            "/api/v2/decision-threads",
            json={
                **context,
                "title": "Tourism decision",
                "decision_question": "Which intervention should be evaluated?",
            },
        ),
        client.post(
            "/api/v2/decision-threads/drafts",
            json={
                "title": "Tourism decision",
                "decision_question": "Which intervention should be evaluated?",
            },
        ),
        client.post(f"/api/v2/decision-threads/{thread_id}/revisions", json=context),
    )

    for response in read_responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Decision threads are unavailable because DATABASE_URL is not configured"
        }

    for response in write_responses:
        assert response.status_code == 410
        assert response.json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL}
