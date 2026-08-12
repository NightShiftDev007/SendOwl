"""Strict OASIS platform-smoke HTTP contracts without external services."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api import simulation_runs as simulation_runs_api
from app.api.simulation_runs import require_simulation_run_session
from app.config import load_runtime_settings
from app.main import create_app
from app.simulations.contracts import (
    PlatformSmokeCreateRequest,
    PlatformSmokePost,
    PlatformSmokeRunDetail,
    PlatformSmokeScenarioRef,
)
from app.simulations.errors import PlatformSmokeUnavailableError


def _detail(request: PlatformSmokeCreateRequest) -> PlatformSmokeRunDetail:
    return PlatformSmokeRunDetail(
        id=uuid4(),
        mode="reddit_manual_smoke",
        status="queued",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        started_at=None,
        completed_at=None,
        scenario=PlatformSmokeScenarioRef(
            id=request.scenario_id,
            scenario_sha256="a" * 64,
            variant_id=request.variant_id,
            variant_name="Clarify",
            world_snapshot_id=uuid4(),
            snapshot_sha256="b" * 64,
            company_name="Acme",
        ),
        seed=request.seed,
        input_sha256="c" * 64,
        posts=(PlatformSmokePost(position=0, content="Verified post.", offset_minutes=0),),
        result=None,
        error=None,
    )


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
    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)


def test_platform_smoke_post_strictly_converts_uuid_strings(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    captured: list[PlatformSmokeCreateRequest] = []

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def create_response(
        session: object,
        scenario_id: UUID,
        variant_id: UUID,
        seed: int,
    ) -> PlatformSmokeRunDetail:
        assert session is not None
        request = PlatformSmokeCreateRequest(
            scenario_id=scenario_id,
            variant_id=variant_id,
            seed=seed,
        )
        captured.append(request)
        return _detail(request)

    application.dependency_overrides[require_simulation_run_session] = session_override
    monkeypatch.setattr(simulation_runs_api, "create_platform_smoke_run", create_response)
    scenario_id = uuid4()
    variant_id = uuid4()
    response = TestClient(application).post(
        "/api/v2/simulation-runs/platform-smoke",
        json={"scenario_id": str(scenario_id), "variant_id": str(variant_id), "seed": 42},
    )

    assert response.status_code == 202
    assert captured[0].scenario_id == scenario_id
    assert captured[0].variant_id == variant_id
    assert response.json()["status"] == "queued"


def test_platform_smoke_post_maps_offline_worker_gate_to_503(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def reject_offline_worker(
        session: object,
        scenario_id: UUID,
        variant_id: UUID,
        seed: int,
    ) -> PlatformSmokeRunDetail:
        assert session is not None
        assert scenario_id and variant_id and seed == 7
        raise PlatformSmokeUnavailableError("no recent correctly pinned worker")

    application.dependency_overrides[require_simulation_run_session] = session_override
    monkeypatch.setattr(
        simulation_runs_api,
        "create_platform_smoke_run",
        reject_offline_worker,
    )
    response = TestClient(application).post(
        "/api/v2/simulation-runs/platform-smoke",
        json={"scenario_id": str(uuid4()), "variant_id": str(uuid4()), "seed": 7},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "no recent correctly pinned worker"}


def test_platform_smoke_post_rejects_extra_fields_and_coercion() -> None:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_simulation_run_session] = session_override
    client = TestClient(application)
    base = {"scenario_id": str(uuid4()), "variant_id": str(uuid4()), "seed": 1}

    extra = client.post(
        "/api/v2/simulation-runs/platform-smoke",
        json={**base, "unexpected": True},
    )
    coerced = client.post(
        "/api/v2/simulation-runs/platform-smoke",
        json={**base, "seed": "1"},
    )

    assert extra.status_code == 422
    assert coerced.status_code == 422
