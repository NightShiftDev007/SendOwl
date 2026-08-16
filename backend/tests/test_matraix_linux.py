"""Fixed MatrAIx Linux public contracts, hashes, and no-database API boundary."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.matraix_linux.contracts import (
    LinuxArtifactHashes,
    LinuxCohortRef,
    LinuxPersonaRef,
    LinuxTrialResult,
    MatraixLinuxEvaluation,
    MatraixLinuxTrial,
    MatraixLinuxTrialCreateRequest,
)
from app.matraix_linux.hashing import (
    calculate_evaluation_sha256,
    calculate_result_sha256,
    calculate_trial_sha256,
)
from app.matraix_linux.tasks import TASK_SPEC_SHA256, build_linux_task


def test_linux_task_and_result_are_content_addressed() -> None:
    task = build_linux_task()
    cohort = LinuxCohortRef(
        id=UUID("31000000-0000-4000-8000-000000000001"),
        title="Linux cohort",
        cohort_sha256="a" * 64,
        dataset_sha256="b" * 64,
    )
    persona = LinuxPersonaRef(
        id=UUID("32000000-0000-4000-8000-000000000001"),
        position=0,
        persona_id="linux-persona",
        display_name="Linux Persona",
        profile_sha256="c" * 64,
    )
    trial_sha = calculate_trial_sha256(
        task.task_spec_sha256,
        task.runner_spec_sha256,
        cohort,
        persona,
        "qwen-plus",
        "d" * 64,
        "matraix-linux-note-to-csv/v1",
        None,
        1,
    )
    files = LinuxArtifactHashes(
        cleaned_list_csv="e" * 64,
        submission_json="f" * 64,
        user_feedback_json="1" * 64,
        verifier_json="2" * 64,
    )
    result_sha = calculate_result_sha256(
        trial_sha,
        "3" * 64,
        files,
        "The fixed rows are normalized into the requested three-column CSV.",
        "yes",
        "yes",
        8,
        "The output is clear and directly usable.",
    )
    now = datetime(2026, 8, 15, tzinfo=UTC)
    result = LinuxTrialResult(
        runner_version="1.0.0",
        model_name="qwen-plus",
        linux_config_sha256="d" * 64,
        prompt_schema_version="matraix-linux-note-to-csv/v1",
        runner_schema_version="matraix-linux-artifact-runner/v1",
        runner_spec_sha256=task.runner_spec_sha256,
        verifier_passed=True,
        rows_written=3,
        artifact_sha256="3" * 64,
        file_sha256=files,
        result_sha256=result_sha,
        reason="The fixed rows are normalized into the requested three-column CSV.",
        need_constraint_satisfaction="yes",
        personal_preference_satisfaction="yes",
        overall_experience_rating=8,
        feedback_reason="The output is clear and directly usable.",
    )
    trial = MatraixLinuxTrial(
        id=uuid4(),
        status="succeeded",
        created_at=now,
        started_at=now,
        completed_at=now,
        task=task,
        cohort=cohort,
        persona=persona,
        trial_sha256=trial_sha,
        retry_of_trial_id=None,
        retry_of_trial_sha256=None,
        attempt_number=1,
        result=result,
        error=None,
    )
    evaluation_id = uuid4()
    evaluation = MatraixLinuxEvaluation(
        id=evaluation_id,
        status="succeeded",
        execution_kind="linux_artifact_runner",
        registry_eligibility="sealed_parent",
        created_at=now,
        sealed_at=now,
        evaluation_sha256=calculate_evaluation_sha256(trial.id, trial.trial_sha256),
        trial=trial,
    )

    assert TASK_SPEC_SHA256 == ("0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9")
    assert trial.result is not None
    assert trial.result.result_sha256 == result_sha
    assert evaluation.trial.id == trial.id


def test_linux_task_is_public_and_runtime_routes_require_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    task_response = client.get("/api/v2/matraix/linux-tasks")
    assert task_response.status_code == 200
    assert task_response.json()["items"][0]["computer_use"] is False

    trial_id = uuid4()
    responses = (
        client.get("/api/v2/matraix/linux-trials"),
        client.get(f"/api/v2/matraix/linux-trials/{trial_id}"),
        client.get(f"/api/v2/matraix/linux-evaluations/{trial_id}"),
        client.get(f"/api/v2/matraix/linux-evaluations/{trial_id}/progress"),
        client.post(f"/api/v2/matraix/linux-evaluations/{trial_id}/retry", json={}),
        client.get(f"/api/v2/matraix/linux-trials/{trial_id}/artifacts/cleaned_list.csv"),
        client.get("/api/v2/matraix/linux-readiness"),
        client.post(
            "/api/v2/matraix/linux-trials",
            json={
                "cohort_id": str(uuid4()),
                "persona_id": str(uuid4()),
                "task_id": "matraix/linux-note-to-csv",
                "task_version": "1.0.0",
            },
        ),
        client.post(
            "/api/v2/matraix/linux-evaluations",
            json={
                "cohort_id": str(uuid4()),
                "persona_id": str(uuid4()),
                "task_id": "matraix/linux-note-to-csv",
                "task_version": "1.0.0",
            },
        ),
    )
    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "MatrAIx Linux data is unavailable because DATABASE_URL is not configured"
        }


def test_linux_create_request_rejects_extra_or_arbitrary_execution_input() -> None:
    with pytest.raises(ValueError):
        MatraixLinuxTrialCreateRequest.model_validate(
            {
                "cohort_id": str(uuid4()),
                "persona_id": str(uuid4()),
                "task_id": "matraix/linux-note-to-csv",
                "task_version": "1.0.0",
                "command": "sh -c anything",
            }
        )
