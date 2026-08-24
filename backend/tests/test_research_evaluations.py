"""Project-bound evaluation bundle contracts and content addresses."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.research_evaluations.contracts import (
    ResearchEvaluationJob,
    ResearchEvaluationTargetCreateRequest,
    ResearchEvaluationTargetPayload,
    ResearchEvaluationTaskBundleCreateRequest,
    ResearchEvaluationTaskBundlePayload,
)
from app.research_evaluations.harbor import _runner_path
from app.research_evaluations.hashing import (
    calculate_evaluation_job_sha256,
    calculate_evaluation_target_sha256,
    calculate_survey_artifact_sha256,
    calculate_task_bundle_sha256,
)
from app.research_evaluations.jobs import fail_active_research_evaluation_jobs


class _ActiveJobRows:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows

    def scalars(self) -> "_ActiveJobRows":
        return self

    def all(self) -> tuple[object, ...]:
        return self._rows


class _ActiveJobSession:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self._rows = rows
        self.commit_count = 0

    async def execute(self, _statement: object) -> _ActiveJobRows:
        return _ActiveJobRows(self._rows)

    async def commit(self) -> None:
        self.commit_count += 1


def _payload() -> ResearchEvaluationTaskBundlePayload:
    return ResearchEvaluationTaskBundlePayload(
        schema_version="sandowl-research-evaluation-task-bundle/v1",
        kind="survey",
        project_sha256="a" * 64,
        run_spec_sha256="b" * 64,
        cohort_sha256="c" * 64,
        dataset_sha256="d" * 64,
        instrument_schema_version="single-context-observation/v1",
        instrument_sha256="e" * 64,
        persona_profile_sha256s=("f" * 64, "1" * 64),
        verifier_schema_version="research-survey-structural-verifier/v1",
        trajectory_schema_version="ordered-persona-observations/v1",
        artifact_schema_version="sandowl-research-survey-artifact/v1",
        reward_policy="not_applicable",
        limitations=("合成评测不验证现实效果。",),
    )


def test_task_bundle_hash_binds_ordered_persona_profiles() -> None:
    payload = _payload()
    reversed_payload = payload.model_copy(
        update={"persona_profile_sha256s": tuple(reversed(payload.persona_profile_sha256s))}
    )

    assert calculate_task_bundle_sha256(payload) != calculate_task_bundle_sha256(reversed_payload)
    assert calculate_survey_artifact_sha256(
        calculate_task_bundle_sha256(payload),
        ((0, "2" * 64), (1, "3" * 64)),
    ) != calculate_survey_artifact_sha256(
        calculate_task_bundle_sha256(payload),
        ((1, "3" * 64), (0, "2" * 64)),
    )


def test_task_bundle_request_rejects_unimplemented_kinds_and_extra_fields() -> None:
    request = {
        "research_project_id": str(uuid4()),
        "research_simulation_run_id": str(uuid4()),
        "kind": "survey",
    }
    assert ResearchEvaluationTaskBundleCreateRequest.model_validate(request).kind == "survey"

    with pytest.raises(ValidationError):
        ResearchEvaluationTaskBundleCreateRequest.model_validate({**request, "kind": "chat"})
    with pytest.raises(ValidationError):
        ResearchEvaluationTaskBundleCreateRequest.model_validate({**request, "reward": 1.0})


def test_chat_and_web_targets_require_matching_transports_and_safe_urls() -> None:
    common = {
        "research_project_id": str(uuid4()),
        "research_simulation_run_id": str(uuid4()),
        "title": "研究被测对象",
        "task_goal": "核验被测对象能否完成研究任务。",
        "success_criteria": ["回答必须覆盖冻结研究问题"],
    }
    chat = ResearchEvaluationTargetCreateRequest.model_validate(
        {
            **common,
            "kind": "chat",
            "target_url": "https://example.test/chat",
            "transport": "rest_chat",
        }
    )
    assert chat.success_criteria == ("回答必须覆盖冻结研究问题",)

    with pytest.raises(ValidationError):
        ResearchEvaluationTargetCreateRequest.model_validate(
            {
                **common,
                "kind": "web",
                "target_url": "https://example.test/page",
                "transport": "rest_chat",
            }
        )
    with pytest.raises(ValidationError):
        ResearchEvaluationTargetCreateRequest.model_validate(
            {
                **common,
                "kind": "chat",
                "target_url": "https://user:secret@example.test/chat",
                "transport": "rest_chat",
            }
        )


def test_evaluation_target_hash_binds_sut_and_success_criteria() -> None:
    payload = ResearchEvaluationTargetPayload(
        schema_version="sandowl-research-evaluation-target/v1",
        kind="web",
        project_sha256="a" * 64,
        run_spec_sha256="b" * 64,
        cohort_sha256="c" * 64,
        dataset_sha256="d" * 64,
        title="研究网页",
        target_url="https://example.test/page",
        task_package=None,
        transport="playwright_browser",
        task_goal="检查页面是否呈现指定研究内容。",
        success_criteria=("页面提供可直接引用的研究内容",),
        verifier_schema_version="research-web-evidence-verifier/v1",
        execution_policy="definition_only",
        limitations=("只封存定义。",),
    )
    changed = payload.model_copy(update={"target_url": "https://example.test/other"})

    assert calculate_evaluation_target_sha256(payload) != calculate_evaluation_target_sha256(
        changed
    )


def test_harbor_retry_hash_binds_parent_and_attempt() -> None:
    root = calculate_evaluation_job_sha256(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        None,
        1,
    )
    retry = calculate_evaluation_job_sha256(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        root,
        2,
    )

    assert root != retry
    with pytest.raises(ValueError, match="retry lineage"):
        calculate_evaluation_job_sha256(
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            None,
            2,
        )


def test_harbor_job_contract_rejects_partial_retry_lineage() -> None:
    job = {
        "id": uuid4(),
        "research_project_id": uuid4(),
        "research_simulation_run_id": uuid4(),
        "cohort_id": uuid4(),
        "target_id": uuid4(),
        "kind": "app",
        "status": "failed",
        "job_sha256": "a" * 64,
        "retry_of_job_id": None,
        "retry_of_job_sha256": None,
        "attempt_number": 1,
        "remote_run_id": None,
        "trajectory_sha256": None,
        "artifact_sha256": None,
        "verifier_sha256": None,
        "reward_sha256": None,
        "reward_value": None,
        "created_at": datetime(2026, 8, 20, 0, 0, 0, tzinfo=UTC),
        "started_at": datetime(2026, 8, 20, 0, 0, 1, tzinfo=UTC),
        "completed_at": datetime(2026, 8, 20, 0, 0, 2, tzinfo=UTC),
        "error_code": "runtimeerror",
        "error_message": "runner failed",
    }

    assert ResearchEvaluationJob.model_validate(job).attempt_number == 1
    with pytest.raises(ValidationError, match="retry lineage"):
        ResearchEvaluationJob.model_validate({**job, "attempt_number": 2})


def test_active_harbor_jobs_fail_explicitly_after_worker_restart() -> None:
    records = (
        SimpleNamespace(status="dispatching"),
        SimpleNamespace(status="running"),
    )
    session = _ActiveJobSession(records)

    asyncio.run(
        fail_active_research_evaluation_jobs(
            cast(AsyncSession, session),
            RuntimeError("worker restarted"),
        )
    )

    assert session.commit_count == 1
    assert {record.status for record in records} == {"failed"}
    assert {record.error_code for record in records} == {"runtimeerror"}
    assert {record.error_message for record in records} == {"worker restarted"}
    assert all(record.completed_at is not None for record in records)


def test_harbor_paths_are_translated_to_the_runner_workspace(monkeypatch) -> None:
    monkeypatch.setenv("HARBOR_RUNNER_WORKSPACE_PATH", "/workspace")

    assert (
        str(
            _runner_path(
                Path("/harbor-workspace"),
                Path("/harbor-workspace/sandowl_tasks/job/task.toml"),
            )
        )
        == "/workspace/sandowl_tasks/job/task.toml"
    )
