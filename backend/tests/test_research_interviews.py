"""Run-grounded Persona interview contracts, hashes, and routes."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.main import create_app
from app.research_interviews.contracts import ResearchInterviewCitation, ResearchPersonaInterview
from app.research_interviews.hashing import calculate_interview_sha256


def test_research_interview_hash_binds_graph_memory_and_persona() -> None:
    first = calculate_interview_sha256(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        str(uuid4()),
        "d" * 64,
        "你看到了什么？",
        "e" * 64,
        "f" * 64,
    )
    second = calculate_interview_sha256(
        "a" * 64,
        "9" * 64,
        "c" * 64,
        str(uuid4()),
        "d" * 64,
        "你看到了什么？",
        "e" * 64,
        "f" * 64,
    )

    assert first != second


def test_queued_research_interview_has_no_generated_output() -> None:
    interview = ResearchPersonaInterview(
        id=uuid4(),
        research_project_id=uuid4(),
        research_simulation_run_id=uuid4(),
        run_spec_sha256="a" * 64,
        graph_memory_sha256="b" * 64,
        cohort_id=uuid4(),
        cohort_sha256="c" * 64,
        persona={
            "id": uuid4(),
            "position": 0,
            "persona_id": "persona-1",
            "display_name": "合成人物一",
            "profile_sha256": "d" * 64,
        },
        question="你为什么采取这个动作？",
        source_sha256="e" * 64,
        interview_sha256="f" * 64,
        model_name="qwen",
        semantic_config_sha256="0" * 64,
        prompt_schema_version="sandowl-run-persona-interview/v1",
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

    assert interview.status == "queued"


def test_research_interview_citation_preserves_exact_whitespace_span() -> None:
    quote = "\n冻结记录中的引用\n"

    citation = ResearchInterviewCitation(
        position=0,
        source_kind="research_run",
        target_id=uuid4(),
        source_label="SandOwl 冻结记录",
        quote=quote,
        start_offset=10,
        end_offset=10 + len(quote),
    )

    assert citation.quote == quote


def test_research_interview_routes_return_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    project_id = uuid4()
    run_id = uuid4()
    persona_id = uuid4()
    responses = (
        client.get(f"/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interviews"),
        client.post(
            f"/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interviews",
            json={"persona_id": str(persona_id), "question": "你为什么采取这个动作？"},
        ),
        client.post(
            f"/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interview-sessions",
            json={
                "persona_ids": [str(persona_id), str(uuid4())],
                "question": "你们分别还缺少哪些信息？",
            },
        ),
    )

    assert {response.status_code for response in responses} == {503}
    assert all("DATABASE_URL" in response.json()["detail"] for response in responses)
