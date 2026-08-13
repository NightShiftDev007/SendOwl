"""Population API availability, request parsing, and error mappings."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api import populations as populations_api
from app.api.populations import require_population_session
from app.config import load_runtime_settings
from app.main import create_app
from app.populations.contracts import (
    CohortCreateRequest,
    CohortDatasetRef,
    CohortDetail,
    CohortMember,
    PersonaAttribute,
    PersonaSummary,
)
from app.populations.errors import PopulationPersonaSelectionError


def _cohort_detail(request: CohortCreateRequest) -> CohortDetail:
    member = PersonaSummary(
        id=request.persona_ids[0],
        dataset_id=request.dataset_id,
        persona_id="0001",
        display_name="Tomas Horvat",
        source="wiki",
        profile_sha256="b" * 64,
        attributes=(PersonaAttribute(name="region", value="Eastern Europe"),),
    )
    return CohortDetail(
        id=uuid4(),
        title=request.title,
        dataset=CohortDatasetRef(
            id=request.dataset_id,
            slug="matraix-persona-dev-sample",
            dataset_sha256="a" * 64,
        ),
        persona_count=1,
        cohort_sha256="c" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        members=(CohortMember(position=0, persona=member),),
    )


def test_population_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    dataset_id = uuid4()
    cohort_id = uuid4()
    responses = (
        client.get("/api/v2/populations/datasets"),
        client.get(f"/api/v2/populations/datasets/{dataset_id}/personas"),
        client.get("/api/v2/populations/cohorts"),
        client.post(
            "/api/v2/populations/cohorts",
            json={
                "title": "Policy readers",
                "dataset_id": str(dataset_id),
                "persona_ids": [str(uuid4())],
            },
        ),
        client.get(f"/api/v2/populations/cohorts/{cohort_id}"),
    )

    assert {response.status_code for response in responses} == {503}
    assert all(
        response.json()
        == {"detail": "Population data is unavailable because DATABASE_URL is not configured"}
        for response in responses
    )


def test_cohort_post_preserves_ordered_uuid_selection(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    captured: list[CohortCreateRequest] = []

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def create_response(session: object, request: CohortCreateRequest) -> CohortDetail:
        assert session is not None
        captured.append(request)
        return _cohort_detail(request)

    application.dependency_overrides[require_population_session] = session_override
    monkeypatch.setattr(populations_api, "create_cohort", create_response)
    dataset_id = uuid4()
    persona_ids = (uuid4(), uuid4())
    response = TestClient(application).post(
        "/api/v2/populations/cohorts",
        json={
            "title": "Policy readers",
            "dataset_id": str(dataset_id),
            "persona_ids": [str(persona_id) for persona_id in persona_ids],
        },
    )

    assert response.status_code == 201
    assert isinstance(captured[0].dataset_id, UUID)
    assert captured[0].dataset_id == dataset_id
    assert captured[0].persona_ids == persona_ids


def test_cohort_post_maps_missing_personas_to_422(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    dataset_id = uuid4()
    persona_id = uuid4()

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def reject_selection(
        session: object,
        request: CohortCreateRequest,
    ) -> CohortDetail:
        assert session is not None
        raise PopulationPersonaSelectionError(request.dataset_id, request.persona_ids)

    application.dependency_overrides[require_population_session] = session_override
    monkeypatch.setattr(populations_api, "create_cohort", reject_selection)
    response = TestClient(application).post(
        "/api/v2/populations/cohorts",
        json={
            "title": "Missing persona",
            "dataset_id": str(dataset_id),
            "persona_ids": [str(persona_id)],
        },
    )

    assert response.status_code == 422
    assert str(persona_id) in response.json()["detail"]


def test_persona_search_rejects_trimmed_single_character() -> None:
    application = create_app(load_runtime_settings({}))

    async def session_override() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[require_population_session] = session_override
    response = TestClient(application).get(
        f"/api/v2/populations/datasets/{uuid4()}/personas?q=%20a%20"
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "q must contain between 2 and 100 non-whitespace characters after trimming"
    }
