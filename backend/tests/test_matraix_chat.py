"""MatrAIx Chat public contracts, routes, and cross-package content addresses."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.matraix_chat.contracts import (
    ChatCohortRef,
    ChatPersonaRef,
    ChatTranscriptMessage,
    ChatTrialFeedback,
    MatraixChatEvaluationCreateRequest,
    MatraixChatTrial,
)
from app.matraix_chat.hashing import (
    calculate_evaluation_sha256,
    calculate_feedback_sha256,
    calculate_result_sha256,
    calculate_transcript_sha256,
    calculate_trial_sha256,
)
from app.matraix_chat.tasks import REST_TASK_ID, SUT_SPEC_SHA256, build_chat_task
from app.matraix_chat.trajectory import (
    MatraixChatTrajectoryUnavailableError,
    project_chat_trial_atif,
)

WORKER_SOURCE = Path(__file__).resolve().parents[1] / "oasis_worker" / "src"
sys.path.insert(0, str(WORKER_SOURCE))
from oasis_worker.chat_contracts import (  # noqa: E402
    ChatEvaluation as WorkerChatEvaluation,
)
from oasis_worker.chat_contracts import ChatFeedback as WorkerChatFeedback  # noqa: E402
from oasis_worker.chat_contracts import ChatMessage as WorkerChatMessage  # noqa: E402
from oasis_worker.chat_contracts import ChatResult as WorkerChatResult  # noqa: E402
from oasis_worker.chat_hashing import evaluation_sha256 as worker_evaluation_sha256  # noqa: E402
from oasis_worker.chat_hashing import feedback_sha256 as worker_feedback_sha256  # noqa: E402
from oasis_worker.chat_hashing import result_sha256 as worker_result_sha256  # noqa: E402
from oasis_worker.chat_hashing import transcript_sha256 as worker_transcript_sha256  # noqa: E402
from oasis_worker.chat_hashing import trial_sha256 as worker_trial_sha256  # noqa: E402


def _frozen_inputs() -> tuple[ChatCohortRef, ChatPersonaRef]:
    cohort = ChatCohortRef(
        id=UUID("11000000-0000-4000-8000-000000000001"),
        title="Golden cohort",
        cohort_sha256="a" * 64,
        dataset_sha256="b" * 64,
        persona_count=1,
    )
    persona = ChatPersonaRef(
        id=UUID("12000000-0000-4000-8000-000000000001"),
        position=0,
        persona_id="golden-persona",
        display_name="Golden Persona",
        profile_sha256="c" * 64,
    )
    return cohort, persona


def test_chat_hashes_match_worker_byte_for_byte() -> None:
    task = build_chat_task(REST_TASK_ID)
    cohort, persona = _frozen_inputs()
    model_name = "qwen-plus"
    config_sha256 = "d" * 64
    evaluation_digest = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.sut_spec_sha256,
        cohort,
        model_name,
        config_sha256,
        None,
        1,
    )
    trial_digest = calculate_trial_sha256(evaluation_digest, persona)
    recorded_at = datetime(2026, 8, 13, tzinfo=UTC)
    messages = (
        ChatTranscriptMessage(
            position=0,
            role="customer",
            content="My order #4521 is late.",
            recorded_at=recorded_at,
        ),
        ChatTranscriptMessage(
            position=1,
            role="support",
            content="Is the address correct?",
            recorded_at=recorded_at,
        ),
        ChatTranscriptMessage(
            position=2,
            role="customer",
            content="Yes. What does tracking show?",
            recorded_at=recorded_at,
        ),
        ChatTranscriptMessage(
            position=3,
            role="support",
            content="It left the regional hub.",
            recorded_at=recorded_at,
        ),
    )
    feedback = ChatTrialFeedback(
        schema_version="matraix-chat-feedback/acme-support-v1",
        need_constraint_satisfaction="partially",
        personal_preference_satisfaction="yes",
        overall_experience_rating=7,
        reason="The path is concrete, but delivery is pending.",
        asked_useful_clarification_questions=True,
        clarifying_notes="The address question confirmed the order details.",
    )
    transcript_digest = calculate_transcript_sha256(trial_digest, messages)
    feedback_digest = calculate_feedback_sha256(trial_digest, feedback)
    result_digest = calculate_result_sha256(
        trial_digest,
        transcript_digest,
        feedback_digest,
        "partially_resolved",
        "user",
        "clarify_then_partial",
        "advanced",
        4,
        2,
        2,
        1,
    )
    worker_evaluation = WorkerChatEvaluation(
        id=UUID("13000000-0000-4000-8000-000000000001"),
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        cohort_title=cohort.title,
        dataset_sha256=cohort.dataset_sha256,
        persona_count=cohort.persona_count,
        task_id=task.task_id,
        task_version=task.version,
        task_schema_version=task.schema_version,
        task_spec_sha256=task.task_spec_sha256,
        sut_spec_sha256=task.sut_spec_sha256,
        model_name=model_name,
        chat_config_sha256=config_sha256,
        prompt_schema_version="matraix-chat-acme-support/v1",
        evaluation_sha256=evaluation_digest,
        retry_of_evaluation_id=None,
        retry_of_evaluation_sha256=None,
        attempt_number=1,
        created_at=recorded_at,
    )
    worker_messages = tuple(
        WorkerChatMessage(position=item.position, role=item.role, content=item.content)
        for item in messages
    )
    worker_feedback = WorkerChatFeedback.model_validate(feedback.model_dump(mode="python"))
    worker_result = WorkerChatResult(
        outcome_status="partially_resolved",
        next_step_owner="user",
        conversation_path="clarify_then_partial",
        resolution_progression="advanced",
        message_count=4,
        customer_turn_count=2,
        support_turn_count=2,
        clarification_question_count=1,
    )

    assert task.task_spec_sha256 == (
        "4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1"
    )
    assert task.sut_spec_sha256 == SUT_SPEC_SHA256
    assert worker_evaluation_sha256(worker_evaluation) == evaluation_digest
    assert (
        worker_trial_sha256(
            evaluation_digest,
            persona.position,
            persona.id,
            persona.persona_id,
            persona.display_name,
            persona.profile_sha256,
        )
        == trial_digest
    )
    assert worker_transcript_sha256(trial_digest, worker_messages) == transcript_digest
    assert worker_feedback_sha256(trial_digest, worker_feedback) == feedback_digest
    assert (
        worker_result_sha256(
            trial_digest,
            transcript_digest,
            feedback_digest,
            worker_result,
        )
        == result_digest
    )

    retry_digest = calculate_evaluation_sha256(
        task.task_spec_sha256,
        task.sut_spec_sha256,
        cohort,
        model_name,
        config_sha256,
        evaluation_digest,
        2,
    )
    worker_retry = worker_evaluation.model_copy(
        update={
            "id": UUID("13000000-0000-4000-8000-000000000002"),
            "evaluation_sha256": retry_digest,
            "retry_of_evaluation_id": UUID("13000000-0000-4000-8000-000000000001"),
            "retry_of_evaluation_sha256": evaluation_digest,
            "attempt_number": 2,
        }
    )
    assert worker_evaluation_sha256(worker_retry) == retry_digest


def test_chat_contracts_normalize_text_and_reject_invalid_terminal_shapes() -> None:
    message = ChatTranscriptMessage(
        position=0,
        role="customer",
        content="  multiline\nrequest  ",
        recorded_at=datetime.now(UTC),
    )
    assert message.content == "multiline\nrequest"
    with pytest.raises(ValueError, match="at least 1 character"):
        ChatTranscriptMessage(
            position=0,
            role="customer",
            content="   ",
            recorded_at=datetime.now(UTC),
        )
    _, persona = _frozen_inputs()
    with pytest.raises(ValueError, match="fields do not match status succeeded"):
        MatraixChatTrial(
            id=uuid4(),
            status="succeeded",
            persona=persona,
            trial_sha256="e" * 64,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            transcript=(),
            feedback=None,
            result=None,
            error=None,
        )


def test_chat_transcript_projects_to_content_addressed_atif_without_inferred_telemetry() -> None:
    _, persona = _frozen_inputs()
    recorded_at = datetime(2026, 8, 13, tzinfo=UTC)
    trial = MatraixChatTrial(
        id=UUID("14000000-0000-4000-8000-000000000001"),
        status="running",
        persona=persona,
        trial_sha256="e" * 64,
        created_at=recorded_at,
        started_at=recorded_at,
        completed_at=None,
        transcript=(
            ChatTranscriptMessage(
                position=0,
                role="customer",
                content="My order is late.",
                recorded_at=recorded_at,
            ),
            ChatTranscriptMessage(
                position=1,
                role="support",
                content="Can you confirm the address?",
                recorded_at=recorded_at,
            ),
        ),
        feedback=None,
        result=None,
        error=None,
    )

    projection = project_chat_trial_atif(trial)

    assert projection.completeness == "partial"
    assert projection.trajectory.schema_version == "ATIF-v1.7"
    assert projection.trajectory.session_id == str(trial.id)
    assert projection.trajectory.trajectory_id == f"urn:sha256:{projection.projection_sha256}"
    assert tuple(step.source for step in projection.trajectory.steps) == ("user", "agent")
    assert projection.trajectory.steps[1].llm_call_count == 0
    payload = projection.model_dump(mode="json")
    assert "reasoning_content" not in str(payload)
    assert "tool_calls" not in str(payload)
    assert payload["trajectory"]["final_metrics"] == {"total_steps": 2}
    assert project_chat_trial_atif(trial) == projection


def test_chat_atif_projection_requires_a_recorded_transcript() -> None:
    _, persona = _frozen_inputs()
    trial = MatraixChatTrial(
        id=UUID("14000000-0000-4000-8000-000000000002"),
        status="queued",
        persona=persona,
        trial_sha256="f" * 64,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        started_at=None,
        completed_at=None,
        transcript=(),
        feedback=None,
        result=None,
        error=None,
    )

    with pytest.raises(MatraixChatTrajectoryUnavailableError, match="has not recorded"):
        project_chat_trial_atif(trial)


def test_chat_task_is_public_without_database_and_runtime_routes_are_explicit() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    task_response = client.get("/api/v2/matraix/chat-tasks")
    assert task_response.status_code == 200
    payload = task_response.json()
    assert payload["total"] == 2
    assert [item["transport"] for item in payload["items"]] == [
        "sidecar_http",
        "mcp_streamable_http",
    ]
    task = payload["items"][0]
    assert task["source"] == {
        "kind": "source_sample",
        "project": "MatrAIx",
        "canonical_path": "application/tasks/example-chat-api_support_chatbot",
        "production_sut": False,
    }
    assert task["sut_spec_sha256"] == SUT_SPEC_SHA256

    responses = (
        client.get("/api/v2/matraix/chat-evaluations"),
        client.get(f"/api/v2/matraix/chat-evaluations/{uuid4()}"),
        client.get(f"/api/v2/matraix/chat-evaluations/{uuid4()}/progress"),
        client.get(f"/api/v2/matraix/chat-trials/{uuid4()}"),
        client.get(f"/api/v2/matraix/chat-trials/{uuid4()}/trajectory"),
        client.get("/api/v2/matraix/chat-readiness"),
        client.post(
            "/api/v2/matraix/chat-evaluations",
            json={
                "cohort_id": str(uuid4()),
                "task_id": "matraix/acme-support-order-4521",
                "task_version": "1.0.0",
            },
        ),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "MatrAIx Chat data is unavailable because DATABASE_URL is not configured"
        }


def test_chat_create_request_rejects_unversioned_or_extra_task_input() -> None:
    with pytest.raises(ValueError):
        MatraixChatEvaluationCreateRequest.model_validate(
            {
                "cohort_id": str(uuid4()),
                "task_id": "example-chat-api_support_chatbot",
                "task_version": "1.0",
                "title": "caller-controlled",
            }
        )
