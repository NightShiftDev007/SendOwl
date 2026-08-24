"""Bounded ReportAgent evidence contracts, hashes, and API availability."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import load_runtime_settings
from app.main import create_app
from app.report_agents.contracts import (
    ReportAgentPlanSection,
    ReportAgentRun,
    ReportAgentRunRequest,
    ReportAgentToolCall,
)
from app.report_agents.hashing import (
    calculate_report_agent_run_sha256,
    calculate_report_agent_tool_call_sha256,
    calculate_report_agent_tool_input_sha256,
    calculate_research_run_report_agent_sha256,
    calculate_research_run_report_agent_v2_sha256,
)


def _outline() -> tuple[ReportAgentPlanSection, ...]:
    return (
        ReportAgentPlanSection(position=0, title="证据观察", focus="列出可核验的媒体与政策证据。"),
        ReportAgentPlanSection(position=1, title="限制", focus="明确证据尚不能证明的事项。"),
    )


def test_report_agent_run_hash_binds_snapshot_plan_and_budget() -> None:
    world_model_id = uuid4()
    snapshot_id = uuid4()
    outline = _outline()
    first = calculate_report_agent_run_sha256(
        world_model_id,
        snapshot_id,
        "a" * 64,
        "整理证据边界",
        outline,
        6,
    )
    second = calculate_report_agent_run_sha256(
        world_model_id,
        snapshot_id,
        "a" * 64,
        "整理证据边界",
        outline,
        7,
    )

    assert first != second
    run = ReportAgentRun(
        id=uuid4(),
        world_model_id=world_model_id,
        world_snapshot_id=snapshot_id,
        snapshot_sha256="a" * 64,
        objective="整理证据边界",
        outline=outline,
        max_tool_calls=6,
        schema_version="bounded-report-agent-evidence/v1",
        research_simulation_run_id=None,
        research_run_report_sha256=None,
        run_sha256=first,
        created_at=datetime.now(UTC),
        tool_calls=(),
        tool_call_count=0,
        remaining_tool_calls=6,
    )
    assert run.remaining_tool_calls == 6


def test_report_agent_request_rejects_noncontiguous_outline() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        ReportAgentRunRequest(
            world_model_id=uuid4(),
            world_snapshot_id=uuid4(),
            snapshot_sha256="a" * 64,
            objective="整理证据边界",
            outline=(
                ReportAgentPlanSection(position=0, title="证据", focus="读取冻结证据。"),
                ReportAgentPlanSection(position=2, title="限制", focus="说明证据限制。"),
            ),
            max_tool_calls=4,
        )


def test_report_agent_research_run_hash_binds_one_report() -> None:
    world_model_id = uuid4()
    snapshot_id = uuid4()
    simulation_run_id = uuid4()
    report_digest = "b" * 64
    outline = _outline()
    run_digest = calculate_research_run_report_agent_sha256(
        world_model_id,
        snapshot_id,
        "a" * 64,
        simulation_run_id,
        report_digest,
        "整理单次运行",
        outline,
        1,
    )
    input_digest = calculate_report_agent_tool_input_sha256(
        run_digest, 0, "read_simulation_run", simulation_run_id
    )
    call_digest = calculate_report_agent_tool_call_sha256(input_digest, "c" * 64)
    run_id = uuid4()

    run = ReportAgentRun(
        id=run_id,
        world_model_id=world_model_id,
        world_snapshot_id=snapshot_id,
        snapshot_sha256="a" * 64,
        objective="整理单次运行",
        outline=outline,
        max_tool_calls=1,
        schema_version="sandowl-research-run-report-agent/v1",
        research_simulation_run_id=simulation_run_id,
        research_run_report_sha256=report_digest,
        run_sha256=run_digest,
        created_at=datetime.now(UTC),
        tool_calls=(
            ReportAgentToolCall(
                id=uuid4(),
                run_id=run_id,
                position=0,
                tool_name="read_simulation_run",
                target_id=simulation_run_id,
                input_sha256=input_digest,
                result_sha256="c" * 64,
                call_sha256=call_digest,
                created_at=datetime.now(UTC),
            ),
        ),
        tool_call_count=1,
        remaining_tool_calls=0,
    )

    assert run.research_simulation_run_id == simulation_run_id


def test_report_agent_v2_accepts_audited_multi_source_calls() -> None:
    world_model_id = uuid4()
    snapshot_id = uuid4()
    simulation_run_id = uuid4()
    outline = _outline()
    run_digest = calculate_research_run_report_agent_v2_sha256(
        world_model_id,
        snapshot_id,
        "a" * 64,
        simulation_run_id,
        "b" * 64,
        "整理多来源单次运行",
        outline,
        2,
    )
    run_id = uuid4()
    calls = []
    for position, (tool_name, target_id) in enumerate(
        (("read_world_snapshot", snapshot_id), ("read_simulation_run", simulation_run_id))
    ):
        input_digest = calculate_report_agent_tool_input_sha256(
            run_digest, position, tool_name, target_id
        )
        calls.append(
            ReportAgentToolCall(
                id=uuid4(),
                run_id=run_id,
                position=position,
                tool_name=tool_name,
                target_id=target_id,
                input_sha256=input_digest,
                result_sha256="c" * 64,
                call_sha256=calculate_report_agent_tool_call_sha256(input_digest, "c" * 64),
                created_at=datetime.now(UTC),
            )
        )
    run = ReportAgentRun(
        id=run_id,
        world_model_id=world_model_id,
        world_snapshot_id=snapshot_id,
        snapshot_sha256="a" * 64,
        objective="整理多来源单次运行",
        outline=outline,
        max_tool_calls=2,
        schema_version="sandowl-research-run-report-agent/v2",
        research_simulation_run_id=simulation_run_id,
        research_run_report_sha256="b" * 64,
        run_sha256=run_digest,
        created_at=datetime.now(UTC),
        tool_calls=tuple(calls),
        tool_call_count=2,
        remaining_tool_calls=0,
    )

    assert tuple(call.tool_name for call in run.tool_calls) == (
        "read_world_snapshot",
        "read_simulation_run",
    )


def test_report_agent_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    run_id = uuid4()
    request = {
        "world_model_id": str(uuid4()),
        "world_snapshot_id": str(uuid4()),
        "snapshot_sha256": "a" * 64,
        "objective": "整理证据边界",
        "outline": [
            {"position": 0, "title": "证据", "focus": "读取冻结证据。"},
            {"position": 1, "title": "限制", "focus": "说明证据限制。"},
        ],
        "max_tool_calls": 4,
    }
    responses = (
        client.post("/api/v2/report-agent/runs", json=request),
        client.get(f"/api/v2/report-agent/runs/{run_id}"),
        client.post(f"/api/v2/report-agent/runs/{run_id}/tools/list-evidence"),
        client.post(f"/api/v2/report-agent/runs/{run_id}/tools/read-media/{uuid4()}"),
        client.post(f"/api/v2/report-agent/runs/{run_id}/tools/read-policy/{uuid4()}"),
        client.post(f"/api/v2/report-agent/drafts/{uuid4()}/retry"),
    )

    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)
