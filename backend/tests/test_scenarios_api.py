"""Scenario API availability and UUID transport checks without external services."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import scenarios as scenarios_api
from app.api.scenarios import require_scenario_session
from app.config import load_runtime_settings
from app.main import create_app
from app.scenarios.contracts import (
    Intervention,
    ScenarioCreateRequest,
    ScenarioDetail,
    ScenarioSnapshotRef,
    ScenarioVariant,
)
from app.scenarios.hashing import calculate_scenario_sha256


def _request_payload() -> dict[str, object]:
    return {
        "title": "Verified response plan",
        "decision_question": "Should the scenario actor publish a clarification?",
        "world_model_id": str(uuid4()),
        "world_snapshot_id": str(uuid4()),
        "baseline": {"name": "No action", "hypothesis": "Discussion continues."},
        "alternatives": [
            {
                "name": "Clarify",
                "hypothesis": "Verified facts reduce confusion.",
                "interventions": [
                    {
                        "kind": "initial_post",
                        "actor": "scenario_actor",
                        "channel": "reddit",
                        "content": "Here are the verified facts.",
                        "offset_minutes": 0,
                    }
                ],
            }
        ],
    }


def _scenario_response(request: ScenarioCreateRequest) -> ScenarioDetail:
    snapshot = ScenarioSnapshotRef(
        world_model_id=request.world_model_id,
        world_snapshot_id=request.world_snapshot_id,
        version=3,
        snapshot_sha256="a" * 64,
        evidence_count=2,
    )
    baseline = ScenarioVariant(
        id=uuid4(),
        position=0,
        name=request.baseline.name,
        hypothesis=request.baseline.hypothesis,
        interventions=(),
    )
    alternative_request = request.alternatives[0]
    intervention_request = alternative_request.interventions[0]
    alternatives = (
        ScenarioVariant(
            id=uuid4(),
            position=1,
            name=alternative_request.name,
            hypothesis=alternative_request.hypothesis,
            interventions=(
                Intervention(
                    id=uuid4(),
                    position=0,
                    kind=intervention_request.kind,
                    actor=intervention_request.actor,
                    channel=intervention_request.channel,
                    content=intervention_request.content,
                    offset_minutes=intervention_request.offset_minutes,
                ),
            ),
        ),
    )
    return ScenarioDetail(
        id=uuid4(),
        title=request.title,
        decision_question=request.decision_question,
        created_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        scenario_sha256=calculate_scenario_sha256(
            request.title,
            request.decision_question,
            snapshot,
            baseline,
            alternatives,
        ),
        snapshot=snapshot,
        baseline=baseline,
        alternatives=alternatives,
    )


def test_scenario_reads_require_database_and_legacy_write_is_retired() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    scenario_id = uuid4()

    for response in (
        client.get("/api/v2/scenarios"),
        client.get(f"/api/v2/scenarios/{scenario_id}"),
    ):
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Scenario data is unavailable because DATABASE_URL is not configured"
        }
    retired = client.post("/api/v2/scenarios", json=_request_payload())
    assert retired.status_code == 410
    assert "legacy ADC write surface is retired" in retired.json()["detail"]


def test_scenario_post_is_rejected_before_repository(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    captured_requests: list[ScenarioCreateRequest] = []

    async def override_scenario_session() -> AsyncIterator[object]:
        yield object()

    async def create_scenario_response(
        session: object,
        request: ScenarioCreateRequest,
    ) -> ScenarioDetail:
        assert session is not None
        captured_requests.append(request)
        return _scenario_response(request)

    application.dependency_overrides[require_scenario_session] = override_scenario_session
    monkeypatch.setattr(scenarios_api, "create_scenario", create_scenario_response)
    payload = _request_payload()

    response = TestClient(application).post("/api/v2/scenarios", json=payload)

    assert response.status_code == 410
    assert captured_requests == []
