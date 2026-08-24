"""Persona interview contracts, content addresses, and HTTP availability."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.legacy_adc import LEGACY_ADC_WRITE_RETIRED_DETAIL
from app.main import create_app
from app.persona_interviews.contracts import (
    PersonaInterview,
    PersonaInterviewPersona,
    PersonaInterviewSessionRequest,
)
from app.persona_interviews.hashing import (
    answer_sha256,
    interview_session_sha256,
    interview_sha256,
)


def test_persona_interview_digest_binds_report_persona_question_and_runtime() -> None:
    first = interview_sha256(
        "a" * 64,
        "b" * 64,
        str(uuid4()),
        "c" * 64,
        "What matters to you?",
        "d" * 64,
    )
    second = interview_sha256(
        "a" * 64,
        "b" * 64,
        str(uuid4()),
        "c" * 64,
        "What matters to you?",
        "d" * 64,
    )

    assert first != second
    assert answer_sha256(first, "Synthetic answer", (0, 2)) != answer_sha256(
        first,
        "Synthetic answer",
        (0, 3),
    )


def test_succeeded_persona_interview_requires_sorted_report_section_citations() -> None:
    now = datetime.now(UTC)
    digest = "a" * 64
    result = PersonaInterview(
        id=uuid4(),
        report_id=uuid4(),
        report_sha256="b" * 64,
        cohort_id=uuid4(),
        cohort_sha256="c" * 64,
        persona=PersonaInterviewPersona(
            id=uuid4(),
            position=0,
            persona_id="persona-1",
            display_name="Persona One",
            profile_sha256="d" * 64,
        ),
        question="What matters to you?",
        interview_sha256=digest,
        model_name="qwen",
        semantic_config_sha256="e" * 64,
        prompt_schema_version="persona-report-interview/v1",
        status="succeeded",
        created_at=now,
        started_at=now,
        completed_at=now,
        answer_markdown="Synthetic answer",
        cited_section_positions=(0, 2),
        answer_sha256=answer_sha256(digest, "Synthetic answer", (0, 2)),
        error_code=None,
        error_message=None,
    )

    assert result.cited_section_positions == (0, 2)


def test_persona_interview_session_digest_preserves_order_and_profile_versions() -> None:
    first_persona = str(uuid4())
    second_persona = str(uuid4())
    first = interview_session_sha256(
        "a" * 64,
        "b" * 64,
        ((first_persona, "c" * 64), (second_persona, "d" * 64)),
        "What matters to this group?",
        "e" * 64,
    )
    reordered = interview_session_sha256(
        "a" * 64,
        "b" * 64,
        ((second_persona, "d" * 64), (first_persona, "c" * 64)),
        "What matters to this group?",
        "e" * 64,
    )

    assert first != reordered


def test_persona_interview_session_request_rejects_duplicate_personas() -> None:
    persona_id = uuid4()

    with pytest.raises(ValueError, match="must not contain duplicates"):
        PersonaInterviewSessionRequest.model_validate(
            {
                "persona_ids": [str(persona_id), str(persona_id)],
                "question": "What matters to this group?",
            }
        )


def test_persona_interview_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    report_id = uuid4()
    interview_id = uuid4()

    read_responses = (
        client.get(f"/api/v2/decision-reports/{report_id}/persona-interviews"),
        client.get(f"/api/v2/persona-interviews/{interview_id}"),
        client.get(f"/api/v2/decision-reports/{report_id}/persona-interview-sessions"),
        client.get(f"/api/v2/persona-interview-sessions/{uuid4()}"),
    )

    for response in read_responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Persona interviews are unavailable because DATABASE_URL is not configured"
        }

    write_responses = (
        client.post(
            f"/api/v2/decision-reports/{report_id}/persona-interviews",
            json={"persona_id": str(uuid4()), "question": "What matters to you?"},
        ),
        client.post(
            f"/api/v2/decision-reports/{report_id}/persona-interview-sessions",
            json={
                "persona_ids": [str(uuid4()), str(uuid4())],
                "question": "What matters to this group?",
            },
        ),
    )
    for response in write_responses:
        assert response.status_code == 410
        assert response.json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL}
