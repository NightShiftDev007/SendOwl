"""Strict contracts and HTTP boundary for the unified MatrAIx trial archive."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api import matraix_trial_archive as archive_api
from app.api.matraix_trial_archive import require_trial_archive_session
from app.config import load_runtime_settings
from app.main import create_app
from app.matraix_trial_archive.contracts import (
    ChatTrialArchiveItem,
    ChatTrialArchiveProvenance,
    MatraixTrialArchivePersona,
    MatraixTrialArchiveResponse,
    MatraixTrialArchiveStatistics,
    MatraixTrialIntegrityVerification,
)


def _persona() -> MatraixTrialArchivePersona:
    return MatraixTrialArchivePersona(
        id=UUID("12000000-0000-4000-8000-000000000001"),
        position=0,
        persona_id="archive-persona",
        display_name="Archive Persona",
        profile_sha256="a" * 64,
    )


def _queued_chat_item(created_at: datetime, trial_id: UUID) -> ChatTrialArchiveItem:
    return ChatTrialArchiveItem(
        kind="chat",
        id=trial_id,
        status="queued",
        parent_id=UUID("13000000-0000-4000-8000-000000000001"),
        parent_sha256="b" * 64,
        trial_sha256="c" * 64,
        task={"title": "Acme support: late order #4521", "version": "1.0.0"},
        persona=_persona(),
        created_at=created_at,
        started_at=None,
        completed_at=None,
        error=None,
        provenance=ChatTrialArchiveProvenance(
            runner_version=None,
            model_name="qwen-plus",
            parent_config_sha256="d" * 64,
            prompt_schema_version="matraix-chat-acme-support/v1",
            transcript_sha256=None,
            feedback_sha256=None,
            result_sha256=None,
        ),
        source_detail_path=f"/api/v2/matraix/chat-trials/{trial_id}",
    )


def _statistics(total: int) -> MatraixTrialArchiveStatistics:
    return MatraixTrialArchiveStatistics(
        total=total,
        by_kind={"survey": 0, "chat": total, "web": 0, "linux": 0},
        by_status={"queued": total, "running": 0, "succeeded": 0, "failed": 0},
    )


def test_archive_contract_enforces_state_path_and_ordering() -> None:
    created_at = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    first = _queued_chat_item(created_at, UUID("14000000-0000-4000-8000-000000000001"))
    second = _queued_chat_item(
        created_at - timedelta(seconds=1),
        UUID("14000000-0000-4000-8000-000000000002"),
    )
    response = MatraixTrialArchiveResponse(
        items=(first, second),
        page=1,
        page_size=20,
        total=2,
        statistics=_statistics(2),
    )
    assert tuple(item.id for item in response.items) == (first.id, second.id)

    invalid = first.model_dump(mode="python")
    invalid["status"] = "succeeded"
    with pytest.raises(ValueError, match="fields do not match status succeeded"):
        ChatTrialArchiveItem.model_validate(invalid)

    invalid_path = first.model_dump(mode="python")
    invalid_path["source_detail_path"] = f"/api/v2/matraix/survey-trials/{first.id}"
    with pytest.raises(ValueError, match="must address the source trial"):
        ChatTrialArchiveItem.model_validate(invalid_path)

    with pytest.raises(ValueError, match="created_at descending"):
        MatraixTrialArchiveResponse(
            items=(second, first),
            page=1,
            page_size=20,
            total=2,
            statistics=_statistics(2),
        )


def test_archive_route_is_explicitly_unavailable_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    response = client.get("/api/v2/matraix/trials")
    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "MatrAIx Trial Archive data is unavailable because DATABASE_URL is not configured"
        )
    }


def test_archive_route_forwards_strict_filters_and_rejects_ambiguous_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(load_runtime_settings({}))
    captured: list[tuple[int, int, str | None, str | None]] = []

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def archive_response(
        session: object,
        page: int,
        page_size: int,
        kind: str | None,
        trial_status: str | None,
    ) -> MatraixTrialArchiveResponse:
        assert session is not None
        captured.append((page, page_size, kind, trial_status))
        return MatraixTrialArchiveResponse(
            items=(),
            page=page,
            page_size=page_size,
            total=8,
            statistics=_statistics(8),
        )

    application.dependency_overrides[require_trial_archive_session] = session_override
    monkeypatch.setattr(archive_api, "list_matraix_trial_archive", archive_response)
    client = TestClient(application)

    response = client.get("/api/v2/matraix/trials?page=2&page_size=7&kind=survey&status=failed")
    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": 2,
        "page_size": 7,
        "total": 8,
        "statistics": {
            "total": 8,
            "by_kind": {"survey": 0, "chat": 8, "web": 0, "linux": 0},
            "by_status": {"queued": 8, "running": 0, "succeeded": 0, "failed": 0},
        },
    }
    assert captured == [(2, 7, "survey", "failed")]

    assert client.get("/api/v2/matraix/trials?kind=chat&kind=survey").status_code == 422
    assert client.get("/api/v2/matraix/trials?unknown=value").status_code == 422
    assert client.get("/api/v2/matraix/trials?page_size=101").status_code == 422
    assert client.get("/api/v2/matraix/trials?status=complete").status_code == 422


def test_trial_integrity_route_returns_kind_specific_recomputation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(load_runtime_settings({}))
    trial_id = UUID("14000000-0000-4000-8000-000000000001")

    async def session_override() -> AsyncIterator[object]:
        yield object()

    async def verification_response(
        session: object,
        kind: str,
        requested_trial_id: UUID,
    ) -> MatraixTrialIntegrityVerification:
        assert session is not None
        assert kind == "survey"
        assert requested_trial_id == trial_id
        return MatraixTrialIntegrityVerification(
            kind="survey",
            trial_id=trial_id,
            status="succeeded",
            verification="verified",
            verified_at=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
            checks=(
                {"name": "sealed_parent", "status": "passed", "content_sha256": "a" * 64},
                {"name": "trial_address", "status": "passed", "content_sha256": "b" * 64},
                {"name": "state_shape", "status": "passed", "content_sha256": None},
                {"name": "survey_answers", "status": "passed", "content_sha256": "c" * 64},
            ),
            limitations=(
                "Verification proves stored parent, Trial, state, and output "
                "content-address integrity.",
                "A verified Trial is not a benchmark reward, real-human result, "
                "forecast, or causal claim.",
            ),
        )

    application.dependency_overrides[require_trial_archive_session] = session_override
    monkeypatch.setattr(archive_api, "verify_trial_integrity", verification_response)
    response = TestClient(application).get(f"/api/v2/matraix/trials/survey/{trial_id}/verification")
    assert response.status_code == 200
    assert response.json()["checks"][3] == {
        "name": "survey_answers",
        "status": "passed",
        "content_sha256": "c" * 64,
    }
    assert (
        TestClient(application)
        .get(f"/api/v2/matraix/trials/survey/{trial_id}/verification?unknown=value")
        .status_code
        == 422
    )
