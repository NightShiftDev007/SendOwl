"""Native Agent Interaction contracts, hashes, and API availability."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.agent_interactions.contracts import AgentInteraction
from app.agent_interactions.hashing import calculate_interaction_sha256
from app.config import load_runtime_settings
from app.main import create_app


def test_agent_interaction_hash_binds_report_and_parent_lineage() -> None:
    project_id = uuid4()
    run_id = uuid4()
    root = calculate_interaction_sha256(
        project_id, run_id, "a" * 64, "b" * 64, "c" * 64, "观察到了什么？", None, None
    )
    follow_up = calculate_interaction_sha256(
        project_id,
        run_id,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "这个结论的边界呢？",
        root,
        "d" * 64,
    )

    assert root != follow_up


def test_queued_agent_interaction_requires_native_root_lineage() -> None:
    project_id = uuid4()
    simulation_run_id = uuid4()
    digest = calculate_interaction_sha256(
        project_id,
        simulation_run_id,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "观察到了什么？",
        None,
        None,
    )
    item = AgentInteraction(
        id=uuid4(),
        research_project_id=project_id,
        research_simulation_run_id=simulation_run_id,
        report_agent_run_id=uuid4(),
        report_agent_run_sha256="a" * 64,
        report_agent_draft_id=uuid4(),
        report_agent_draft_sha256="b" * 64,
        source_sha256="c" * 64,
        question="观察到了什么？",
        interaction_sha256=digest,
        model_name="qwen",
        semantic_config_sha256="d" * 64,
        prompt_schema_version="sandowl-agent-interaction/v1",
        parent_interaction_id=None,
        parent_interaction_sha256=None,
        parent_answer_sha256=None,
        conversation_depth=0,
        status="queued",
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        answer_markdown=None,
        citations=(),
        answer_sha256=None,
        error_code=None,
        error_message=None,
    )

    assert item.report_agent_draft_sha256 == "b" * 64


def test_agent_interaction_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    draft_id = uuid4()
    interaction_id = uuid4()
    responses = (
        client.get(f"/api/v2/report-agent/drafts/{draft_id}/interactions"),
        client.post(
            f"/api/v2/report-agent/drafts/{draft_id}/interactions",
            json={"question": "这次模拟说明了什么？", "parent_interaction_id": None},
        ),
        client.get(f"/api/v2/agent-interactions/{interaction_id}"),
    )

    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)
