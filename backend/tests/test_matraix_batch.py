"""Contracts and HTTP behavior for the registry-only MatrAIx batch slice."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import matraix_batch as batch_api
from app.api.matraix_batch import create_matraix_batch_router, require_batch_registry_session
from app.matraix_batch.contracts import (
    LinuxBatchRegistryCandidate,
    MatraixBatchRegistriesResponse,
    MatraixBatchRegistryCreateRequest,
    MatraixBatchRegistryDetail,
    MatraixNativeBatchLaunchRequest,
    MatraixNativeBatchLaunchResult,
    SurveyBatchRegistryCandidate,
    WebBatchRegistryCandidate,
)
from app.matraix_batch.hashing import calculate_batch_registry_sha256

PARENT_ID = UUID("21000000-0000-4000-8000-000000000001")
WEB_PARENT_ID = UUID("21000000-0000-4000-8000-000000000002")
LINUX_PARENT_ID = UUID("21000000-0000-4000-8000-000000000003")
REGISTRY_ID = UUID("22000000-0000-4000-8000-000000000001")
OBSERVED_AT = datetime(2026, 8, 13, 12, 30, tzinfo=UTC)


def _request() -> MatraixBatchRegistryCreateRequest:
    return MatraixBatchRegistryCreateRequest.model_validate(
        {
            "title": "  Release evidence  ",
            "items": [{"kind": "survey", "parent_id": str(PARENT_ID)}],
        }
    )


def _detail() -> MatraixBatchRegistryDetail:
    return MatraixBatchRegistryDetail(
        id=REGISTRY_ID,
        title="Release evidence",
        registry_state="sealed",
        execution_kind="registry_only",
        observed_trial_status="queued",
        observed_at=OBSERVED_AT,
        created_at=OBSERVED_AT,
        sealed_at=OBSERVED_AT,
        registry_sha256="a" * 64,
        item_count=1,
        trial_count=1,
        succeeded_trial_count=0,
        failed_trial_count=0,
        items=(
            {
                "position": 0,
                "kind": "survey",
                "parent_id": PARENT_ID,
                "parent_sha256": "b" * 64,
                "title": "Scenario",
                "version": "scenario-preference/v1",
                "observed_status": "queued",
                "created_at": OBSERVED_AT,
                "trial_count": 1,
                "succeeded_trial_count": 0,
                "failed_trial_count": 0,
                "model_name": "qwen-plus",
                "parent_config_sha256": "c" * 64,
                "prompt_schema_version": "matraix-survey-scenario-preference/v1",
                "source_detail_path": f"/api/v2/matraix/survey-experiments/{PARENT_ID}",
            },
        ),
    )


def _application() -> FastAPI:
    application = FastAPI()
    application.include_router(create_matraix_batch_router())

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_batch_registry_session] = session_override
    return application


def test_create_request_is_strict_ordered_unique_and_trimmed() -> None:
    request = _request()
    assert request.title == "Release evidence"
    assert request.items[0].parent_id == PARENT_ID
    web_request = MatraixBatchRegistryCreateRequest.model_validate(
        {
            "title": "Web evidence",
            "items": [{"kind": "web", "parent_id": str(WEB_PARENT_ID)}],
        }
    )
    assert web_request.items[0].kind == "web"
    linux_request = MatraixBatchRegistryCreateRequest.model_validate(
        {
            "title": "Linux evidence",
            "items": [{"kind": "linux", "parent_id": str(LINUX_PARENT_ID)}],
        }
    )
    assert linux_request.items[0].kind == "linux"

    with pytest.raises(ValidationError, match="unique source references"):
        MatraixBatchRegistryCreateRequest.model_validate(
            {
                "title": "Duplicate",
                "items": [
                    {"kind": "survey", "parent_id": str(PARENT_ID)},
                    {"kind": "survey", "parent_id": str(PARENT_ID)},
                ],
            }
        )


def test_native_launch_request_is_strict_ordered_and_unique() -> None:
    request = MatraixNativeBatchLaunchRequest.model_validate(
        {
            "title": " Native release ",
            "items": [
                {
                    "kind": "survey",
                    "scenario_id": "23000000-0000-4000-8000-000000000001",
                    "cohort_id": "24000000-0000-4000-8000-000000000001",
                    "alternative_id": "25000000-0000-4000-8000-000000000001",
                },
                {
                    "kind": "chat",
                    "cohort_id": "24000000-0000-4000-8000-000000000001",
                    "task_id": "matraix/acme-support-order-4521",
                    "task_version": "1.0.0",
                },
            ],
        }
    )
    assert request.title == "Native release"
    assert tuple(item.kind for item in request.items) == ("survey", "chat")
    duplicate = request.model_dump(mode="json")
    duplicate["items"] = [duplicate["items"][0], duplicate["items"][0]]
    with pytest.raises(ValidationError, match="unique execution specs"):
        MatraixNativeBatchLaunchRequest.model_validate(duplicate)
    with pytest.raises(ValidationError, match="Input tag 'web'"):
        MatraixNativeBatchLaunchRequest.model_validate(
            {
                "title": "Web is registry-only",
                "items": [
                    {
                        "kind": "web",
                        "cohort_id": "24000000-0000-4000-8000-000000000001",
                        "task_id": "matraix/quotes-playwright-choice",
                        "task_version": "1.0.0",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="Input tag 'linux'"):
        MatraixNativeBatchLaunchRequest.model_validate(
            {
                "title": "Linux is registry-only",
                "items": [
                    {
                        "kind": "linux",
                        "cohort_id": "24000000-0000-4000-8000-000000000001",
                        "persona_id": "24000000-0000-4000-8000-000000000002",
                        "task_id": "matraix/linux-note-to-csv",
                        "task_version": "1.0.0",
                    }
                ],
            }
        )

    result = MatraixNativeBatchLaunchResult(
        launch_mode="native_parent_enqueue",
        registry=_detail(),
    )
    assert result.registry.execution_kind == "registry_only"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MatraixBatchRegistryCreateRequest.model_validate(
            {
                "title": "Unexpected",
                "items": [{"kind": "survey", "parent_id": str(PARENT_ID)}],
                "launch": True,
            }
        )


def test_registry_hash_matches_exact_canonical_utf8_json() -> None:
    items = ((0, "survey", PARENT_ID, "b" * 64),)
    payload = {
        "schema_version": "matraix-batch-registry/v1",
        "title": "区域发布证据",
        "items": [
            {
                "position": 0,
                "kind": "survey",
                "parent_id": str(PARENT_ID),
                "parent_sha256": "b" * 64,
            }
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    assert (
        calculate_batch_registry_sha256("区域发布证据", items)
        == sha256(canonical.encode("utf-8")).hexdigest()
    )


def test_observed_status_counts_and_shared_observation_time_are_enforced() -> None:
    candidate = SurveyBatchRegistryCandidate(
        kind="survey",
        parent_id=PARENT_ID,
        parent_sha256="b" * 64,
        title="Scenario",
        version="scenario-preference/v1",
        observed_status="succeeded",
        created_at=OBSERVED_AT,
        trial_count=2,
        succeeded_trial_count=2,
        failed_trial_count=0,
        model_name="qwen-plus",
        parent_config_sha256="c" * 64,
        prompt_schema_version="matraix-survey-scenario-preference/v1",
        source_detail_path=f"/api/v2/matraix/survey-experiments/{PARENT_ID}",
    )
    assert candidate.observed_status == "succeeded"
    invalid = candidate.model_dump(mode="python")
    invalid["succeeded_trial_count"] = 1
    with pytest.raises(ValidationError, match="every trial to succeed"):
        SurveyBatchRegistryCandidate.model_validate(invalid)

    web_candidate = WebBatchRegistryCandidate(
        kind="web",
        parent_id=WEB_PARENT_ID,
        parent_sha256="d" * 64,
        title="Quote to save",
        version="1.0.0",
        observed_status="queued",
        created_at=OBSERVED_AT,
        trial_count=1,
        succeeded_trial_count=0,
        failed_trial_count=0,
        model_name="qwen-plus",
        parent_config_sha256="e" * 64,
        prompt_schema_version="matraix-web-quotes-choice/v1",
        source_detail_path=f"/api/v2/matraix/web-evaluations/{WEB_PARENT_ID}",
    )
    assert web_candidate.kind == "web"
    linux_candidate = LinuxBatchRegistryCandidate(
        kind="linux",
        parent_id=LINUX_PARENT_ID,
        parent_sha256="f" * 64,
        title="Note to CSV cleanup",
        version="1.0.0",
        observed_status="queued",
        created_at=OBSERVED_AT,
        trial_count=1,
        succeeded_trial_count=0,
        failed_trial_count=0,
        model_name="qwen-plus",
        parent_config_sha256="1" * 64,
        prompt_schema_version="matraix-linux-note-to-csv/v1",
        source_detail_path=f"/api/v2/matraix/linux-evaluations/{LINUX_PARENT_ID}",
    )
    assert linux_candidate.kind == "linux"

    detail = _detail()
    summary = detail.model_dump(mode="python", exclude={"items"})
    summary["observed_at"] = datetime(2026, 8, 13, 12, 31, tzinfo=UTC)
    with pytest.raises(ValidationError, match="share the response observation time"):
        MatraixBatchRegistriesResponse(
            items=(summary,),
            page=1,
            page_size=20,
            total=1,
            observed_at=OBSERVED_AT,
        )


def test_registry_routes_are_registry_only_and_queries_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[int, int, str | None]] = []

    async def fake_create(session: object, request: object) -> MatraixBatchRegistryDetail:
        assert session is not None and request is not None
        return _detail()

    async def fake_launch(session: object, request: object) -> MatraixNativeBatchLaunchResult:
        assert session is not None and request is not None
        return MatraixNativeBatchLaunchResult(
            launch_mode="native_parent_enqueue",
            registry=_detail(),
        )

    async def fake_candidates(
        session: object,
        page: int,
        page_size: int,
        kind: str | None,
    ) -> object:
        assert session is not None
        captured.append((page, page_size, kind))
        return {
            "items": (),
            "page": page,
            "page_size": page_size,
            "total": 0,
            "observed_at": OBSERVED_AT,
        }

    monkeypatch.setattr(batch_api, "create_batch_registry", fake_create)
    monkeypatch.setattr(batch_api, "create_native_batch_launch", fake_launch)
    monkeypatch.setattr(batch_api, "list_batch_registry_candidates", fake_candidates)
    client = TestClient(_application())

    created = client.post(
        "/api/v2/matraix/batch-registries",
        json={
            "title": "Release evidence",
            "items": [{"kind": "survey", "parent_id": str(PARENT_ID)}],
        },
    )
    assert created.status_code == 201
    assert created.json()["execution_kind"] == "registry_only"
    assert "status" not in created.json()

    launched = client.post(
        "/api/v2/matraix/batch-launches",
        json={
            "title": "Native release",
            "items": [
                {
                    "kind": "chat",
                    "cohort_id": "24000000-0000-4000-8000-000000000001",
                    "task_id": "matraix/acme-support-order-4521",
                    "task_version": "1.0.0",
                }
            ],
        },
    )
    assert launched.status_code == 202
    assert launched.json()["launch_mode"] == "native_parent_enqueue"
    assert launched.json()["registry"]["execution_kind"] == "registry_only"

    candidates = client.get(
        "/api/v2/matraix/batch-registry-candidates?page=2&page_size=7&kind=chat"
    )
    assert candidates.status_code == 200
    web_candidates = client.get(
        "/api/v2/matraix/batch-registry-candidates?page=1&page_size=7&kind=web"
    )
    assert web_candidates.status_code == 200
    linux_candidates = client.get(
        "/api/v2/matraix/batch-registry-candidates?page=1&page_size=7&kind=linux"
    )
    assert linux_candidates.status_code == 200
    assert captured == [(2, 7, "chat"), (1, 7, "web"), (1, 7, "linux")]
    assert client.get("/api/v2/matraix/batch-registry-candidates?page=1&page=2").status_code == 422
    assert client.get("/api/v2/matraix/batch-registry-candidates?launch=true").status_code == 422


def test_registry_route_is_unavailable_without_database() -> None:
    application = FastAPI()
    application.include_router(create_matraix_batch_router())
    response = TestClient(application).get("/api/v2/matraix/batch-registries")
    assert response.status_code == 503
    assert response.json() == {"detail": batch_api.BATCH_REGISTRY_UNAVAILABLE_DETAIL}
