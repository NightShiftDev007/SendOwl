"""Single-run research-project contracts and API availability."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_runtime_settings
from app.main import create_app
from app.research_projects.contracts import (
    ResearchProjectCohortRef,
    ResearchProjectCreateRequest,
    ResearchProjectSnapshotRef,
    ResearchSimulationRunCreateRequest,
)
from app.research_projects.hashing import (
    calculate_research_project_sha256,
    calculate_research_simulation_run_sha256,
)
from app.research_projects.planning import compile_simulation_plan

DIGEST = "a" * 64


def test_project_request_rejects_multi_option_product_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResearchProjectCreateRequest.model_validate(
            {
                "title": "单次模拟研究",
                "research_question": "合成人群会产生哪些动作？",
                "world_model_id": str(uuid4()),
                "world_snapshot_id": str(uuid4()),
                "comparison_matrix": [],
            }
        )


def test_project_and_run_hashes_are_deterministic_and_separate() -> None:
    snapshot = ResearchProjectSnapshotRef(
        world_model_id=uuid4(),
        world_snapshot_id=uuid4(),
        snapshot_sha256=DIGEST,
    )
    cohort = ResearchProjectCohortRef(
        cohort_id=uuid4(),
        cohort_sha256="b" * 64,
        persona_count=5,
    )
    project_sha256 = calculate_research_project_sha256(
        "中文研究",
        "一次模拟发生了什么？",
        snapshot,
    )

    assert project_sha256 == calculate_research_project_sha256(
        "中文研究",
        "一次模拟发生了什么？",
        snapshot,
    )
    assert calculate_research_simulation_run_sha256(
        project_sha256,
        cohort,
        "使用一个模拟要求运行。",
        7,
        1,
        60,
        "起始内容",
        "model",
        "c" * 64,
    ) != (
        calculate_research_simulation_run_sha256(
            project_sha256,
            cohort,
            "使用一个模拟要求运行。",
            8,
            1,
            60,
            "起始内容",
            "model",
            "c" * 64,
        )
    )


def test_research_run_requires_one_explicit_initial_context() -> None:
    request = ResearchSimulationRunCreateRequest.model_validate(
        {
            "cohort_id": str(uuid4()),
            "simulation_requirement": "运行一次有界群体模拟。",
            "seed": 7,
            "rounds": 1,
            "minutes_per_round": 60,
            "initial_post": "虚构机构发布一条合成说明。",
        }
    )

    assert request.initial_post == "虚构机构发布一条合成说明。"


def test_automatic_plan_is_auditable_and_keeps_scheduled_content_synthetic() -> None:
    request = ResearchSimulationRunCreateRequest.model_validate(
        {
            "cohort_id": str(uuid4()),
            "simulation_requirement": "观察两天内的合成传播。",
            "seed": 7,
            "planning_mode": "automatic",
            "time_horizon_minutes": 2880,
            "activity_intensity": "standard",
            "initial_post": "虚构机构发布初始说明。",
            "scheduled_posts": [{"content": "虚构机构补充进展。", "offset_minutes": 1440}],
        }
    )

    plan = compile_simulation_plan(request, 20, 5)

    assert plan.planner_version == "deterministic-context-planner/v1"
    assert plan.rounds == 6
    assert plan.minutes_per_round == 480
    assert plan.horizon_minutes == 2880
    assert tuple(item.offset_minutes for item in plan.scheduled_posts) == (0, 1440)
    assert {item.source for item in plan.scheduled_posts} == {"user_synthetic"}


def test_plan_rejects_a_scheduled_post_outside_manual_horizon() -> None:
    request = ResearchSimulationRunCreateRequest.model_validate(
        {
            "cohort_id": str(uuid4()),
            "simulation_requirement": "观察一次有界群体模拟。",
            "seed": 7,
            "rounds": 1,
            "minutes_per_round": 60,
            "initial_post": "虚构机构发布初始说明。",
            "scheduled_posts": [{"content": "虚构机构补充进展。", "offset_minutes": 120}],
        }
    )

    with pytest.raises(ValueError, match="exceeds the compiled simulation horizon"):
        compile_simulation_plan(request, 10, 5)


def test_research_project_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    project_id = uuid4()
    run_id = uuid4()
    project = {
        "title": "单次模拟研究",
        "research_question": "合成人群会产生哪些动作？",
        "world_model_id": str(uuid4()),
        "world_snapshot_id": str(uuid4()),
    }

    responses = (
        client.get("/api/v2/research-projects"),
        client.get("/api/v2/research-projects/reports"),
        client.post("/api/v2/research-projects", json=project),
        client.get(f"/api/v2/research-projects/{project_id}"),
        client.post(
            f"/api/v2/research-projects/{project_id}/runs",
            json={
                "cohort_id": str(uuid4()),
                "simulation_requirement": "运行一次有界群体模拟。",
                "seed": 7,
                "rounds": 1,
                "minutes_per_round": 60,
                "initial_post": "虚构机构发布一条合成说明。",
            },
        ),
        client.post(
            f"/api/v2/research-projects/{project_id}/runs/plan-preview",
            json={
                "cohort_id": str(uuid4()),
                "simulation_requirement": "运行一次有界群体模拟。",
                "seed": 7,
                "rounds": 1,
                "minutes_per_round": 60,
                "initial_post": "虚构机构发布一条合成说明。",
            },
        ),
        client.get(f"/api/v2/research-projects/{project_id}/runs"),
        client.get(f"/api/v2/research-projects/{project_id}/runs/{run_id}"),
        client.get(f"/api/v2/research-projects/{project_id}/runs/{run_id}/events"),
        client.get(f"/api/v2/research-projects/{project_id}/runs/{run_id}/report"),
        client.get(f"/api/v2/research-projects/{project_id}/runs/{run_id}/report-agent"),
    )

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Research projects are unavailable because DATABASE_URL is not configured"
        }
