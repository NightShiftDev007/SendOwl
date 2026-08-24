"""PostgreSQL integration for separated Project context and run design."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.agent_interactions.contracts import AgentInteractionCitation
from app.agent_interactions.hashing import calculate_answer_sha256
from app.api.agent_interactions import (
    create_agent_interactions_router,
    require_agent_interaction_session,
)
from app.api.report_agents import create_report_agents_router, require_report_agent_session
from app.api.research_evaluations import create_research_evaluations_router
from app.api.research_evaluations import require_session as require_research_evaluation_session
from app.api.research_projects import (
    create_research_projects_router,
    require_research_project_session,
)
from app.database import normalize_async_database_url
from app.evidence.revisions import combine_article_text
from app.report_agents.contracts import (
    ReportAgentCitedDraft,
    ReportAgentDraftCitation,
    ReportAgentDraftSection,
)
from app.report_agents.hashing import (
    calculate_report_agent_draft_sha256,
    serialize_draft_sections,
)
from app.report_agents.repository import enqueue_report_agent_draft
from app.research_projects.hashing import calculate_research_run_report_sha256
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.world_graphs.contracts import SemanticWorldGraphNode, WorldGraphEvidenceReference
from app.world_graphs.hashing import calculate_semantic_graph_sha256
from app.world_models.contracts import WorldModelCreateRequest, WorldSnapshotEvidenceSelection
from app.world_models.repository import create_world_model
from tests.test_evidence_bundles_postgresql import _insert_media_article
from tests.test_matraix_chat_postgresql import _insert_population

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


async def _exercise_research_project_flow(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                article_id, revision_sha256, _title, _content = await _insert_media_article(
                    connection
                )
                cohort_id = await _insert_population(connection)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    world_model = await create_world_model(
                        session,
                        WorldModelCreateRequest(
                            title="Research Project integration world",
                            evidence=(
                                WorldSnapshotEvidenceSelection(
                                    article_id=article_id,
                                    evidence_revision_sha256=revision_sha256,
                                ),
                            ),
                            policy_evidence=(),
                            verification="human_confirmed",
                        ),
                    )
                now = datetime.now(UTC)
                graph_id = uuid4()
                node_id = uuid4()
                input_sha256 = "4" * 64
                quote = _content[: min(100, len(_content))]
                quote_start = combine_article_text(_title, _content).index(quote)
                node = SemanticWorldGraphNode(
                    id=node_id,
                    position=0,
                    entity_type="concept",
                    name="研究证据主题",
                    summary="冻结文章中直接支持的研究背景。",
                    evidence=(
                        WorldGraphEvidenceReference(
                            position=0,
                            article_id=article_id,
                            quote=quote,
                            start_offset=quote_start,
                            end_offset=quote_start + len(quote),
                        ),
                    ),
                )
                graph_sha256 = calculate_semantic_graph_sha256(input_sha256, (node,), ())
                await connection.execute(
                    text(
                        """
                        INSERT INTO semantic_world_graphs (
                            id,world_model_id,snapshot_id,snapshot_sha256,status,model_name,
                            semantic_config_sha256,extraction_config_sha256,
                            prompt_schema_version,input_sha256,graph_sha256,created_at,
                            claimed_by_worker_id,started_at,completed_at,node_count,edge_count,
                            error_code,error_message
                        ) VALUES (
                            :id,:world_model_id,:snapshot_id,:snapshot_sha256,'queued',
                            'integration-model',:semantic_config,:extraction_config,
                            'world-graph-extraction/v1',:input_sha,NULL,:now,NULL,NULL,NULL,
                            NULL,NULL,NULL,NULL
                        )
                        """
                    ),
                    {
                        "id": graph_id,
                        "world_model_id": world_model.id,
                        "snapshot_id": world_model.latest_snapshot.id,
                        "snapshot_sha256": world_model.latest_snapshot.snapshot_sha256,
                        "semantic_config": "6" * 64,
                        "extraction_config": "5" * 64,
                        "input_sha": input_sha256,
                        "now": now,
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE semantic_world_graphs SET status='running',
                            claimed_by_worker_id='integration-graph-worker',started_at=:now
                        WHERE id=:id
                        """
                    ),
                    {"id": graph_id, "now": now},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO semantic_world_graph_nodes (
                            graph_id,position,id,entity_type,name,summary
                        ) VALUES (:graph_id,0,:node_id,'concept',:name,:summary)
                        """
                    ),
                    {
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "name": node.name,
                        "summary": node.summary,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO semantic_world_graph_evidence (
                            graph_id,object_kind,object_id,position,article_id,quote,
                            start_offset,end_offset
                        ) VALUES (
                            :graph_id,'node',:node_id,0,:article_id,:quote,
                            :start_offset,:end_offset
                        )
                        """
                    ),
                    {
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "article_id": article_id,
                        "quote": quote,
                        "start_offset": quote_start,
                        "end_offset": quote_start + len(quote),
                    },
                )
                await connection.execute(
                    text(
                        """
                        UPDATE semantic_world_graphs SET status='succeeded',
                            completed_at=:now,graph_sha256=:graph_sha,node_count=1,edge_count=0
                        WHERE id=:id
                        """
                    ),
                    {"id": graph_id, "now": now, "graph_sha": graph_sha256},
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO simulation_worker_heartbeats (
                            worker_id,worker_domain,engine,engine_version,camel_version,mode,
                            platform_runtime_ready,semantic_runtime_ready,semantic_model_name,
                            semantic_config_sha256,semantic_prompt_schema_version,
                            started_at,last_seen_at
                        ) VALUES (
                            :worker,'semantic','camel-oasis','0.2.5','0.2.78',
                            'reddit_manual_smoke',true,true,'integration-model',:config,:prompt,
                            :now,:now
                        )
                        """
                    ),
                    {
                        "worker": f"research-project-test-{uuid4()}",
                        "config": "6" * 64,
                        "prompt": PROMPT_SCHEMA_VERSION,
                        "now": now,
                    },
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO simulation_worker_heartbeats (
                            worker_id,worker_domain,engine,engine_version,camel_version,mode,
                            platform_runtime_ready,semantic_runtime_ready,semantic_model_name,
                            semantic_config_sha256,semantic_prompt_schema_version,
                            started_at,last_seen_at
                        ) VALUES (
                            :worker,'report','camel-oasis','0.2.5','0.2.78',
                            'reddit_manual_smoke',true,true,'integration-model',:config,:prompt,
                            :now,:now
                        )
                        """
                    ),
                    {
                        "worker": f"agent-interaction-test-{uuid4()}",
                        "config": "5" * 64,
                        "prompt": PROMPT_SCHEMA_VERSION,
                        "now": now,
                    },
                )
                application = FastAPI()
                application.include_router(create_research_projects_router())
                application.include_router(create_research_evaluations_router())
                application.include_router(create_agent_interactions_router())
                application.include_router(create_report_agents_router())

                async def session_override() -> AsyncIterator[AsyncSession]:
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        yield session

                application.dependency_overrides[require_research_project_session] = (
                    session_override
                )
                application.dependency_overrides[require_research_evaluation_session] = (
                    session_override
                )
                application.dependency_overrides[require_agent_interaction_session] = (
                    session_override
                )
                application.dependency_overrides[require_report_agent_session] = session_override
                async with AsyncClient(
                    transport=ASGITransport(app=application),
                    base_url="http://research-project-test",
                ) as client:
                    project_response = await client.post(
                        "/api/v2/research-projects",
                        json={
                            "title": "Project context integration",
                            "research_question": "一次模拟会观察到什么？",
                            "world_model_id": str(world_model.id),
                            "world_snapshot_id": str(world_model.latest_snapshot.id),
                            "world_graph_id": str(graph_id),
                        },
                    )
                    assert project_response.status_code == 201
                    project = project_response.json()
                    assert project["schema_version"] == "sandowl-research-project/v3"
                    assert project["graph"]["graph_id"] == str(graph_id)
                    assert project["legacy_design"] is None

                    agenda_context_response = await client.get(
                        f"/api/v2/research-projects/{project['id']}/agenda-context"
                    )
                    assert agenda_context_response.status_code == 200
                    agenda_context = agenda_context_response.json()
                    assert agenda_context["project_id"] == project["id"]
                    assert agenda_context["payload"]["frozen_article_ids"] == [str(article_id)]
                    assert agenda_context["payload"]["topics"] == []
                    assert len(agenda_context["context_sha256"]) == 64

                    run_response = await client.post(
                        f"/api/v2/research-projects/{project['id']}/runs",
                        json={
                            "cohort_id": str(cohort_id),
                            "simulation_requirement": "观察一次有界合成人群传播。",
                            "seed": 7,
                            "rounds": 1,
                            "minutes_per_round": 60,
                            "initial_post": "虚构机构发布一条合成说明。",
                        },
                    )
                    assert run_response.status_code == 201
                    run = run_response.json()
                    assert run["schema_version"] == "sandowl-research-simulation-run/v4"
                    assert run["simulation_context"]["graph"]["graph_id"] == str(graph_id)
                    assert run["simulation_context_sha256"] is not None
                    assert run["simulation_plan"]["planning_mode"] == "manual"
                    assert run["simulation_plan"]["scheduled_posts"] == [
                        {
                            "position": 0,
                            "content": "虚构机构发布一条合成说明。",
                            "offset_minutes": 0,
                            "source": "user_synthetic",
                        }
                    ]
                    assert run["simulation_plan_sha256"] is not None
                    assert run["cohort"]["cohort_id"] == str(cohort_id)
                    assert run["simulation_requirement"] == "观察一次有界合成人群传播。"
                    assert run["status"] == "queued"

                    artifact_sha256 = "7" * 64
                    report_sha256 = calculate_research_run_report_sha256(
                        run["run_spec_sha256"], artifact_sha256
                    )
                    await connection.execute(
                        text(
                            """
                            UPDATE research_simulation_runs SET
                                status='succeeded', started_at=:now, completed_at=:now,
                                claimed_by_worker_id='integration-worker',
                                artifact_sha256=:artifact, artifact_size_bytes=128,
                                user_count=2, initial_post_count=1, generated_post_count=0,
                                comment_count=0, reaction_count=0, do_nothing_count=1,
                                observed_action_count=2, rounds_completed=1,
                                limitations=ARRAY['仅描述一次合成运行。']
                            WHERE id=:run_id
                            """
                        ),
                        {"now": now, "artifact": artifact_sha256, "run_id": run["id"]},
                    )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO research_run_events (
                                run_id,sequence,round,phase,actor_kind,persona_id,
                                agent_position,action_type,content,post_id,comment_id,
                                target_post_id,observed_at_raw,recorded_at
                            ) VALUES (
                                :run_id,1,1,'intervention','scenario',NULL,0,'create_post',
                                '虚构机构发布一条合成说明。','post-1',NULL,NULL,'0',:now
                            ), (
                                :run_id,2,1,'audience','persona',NULL,1,'do_nothing',
                                NULL,NULL,NULL,NULL,'1',:now
                            )
                            """
                        ),
                        {"run_id": run["id"], "now": now},
                    )
                    await connection.execute(
                        text(
                            """
                            INSERT INTO research_run_reports (id,run_id,report_sha256,created_at)
                            VALUES (:id,:run_id,:report_sha256,:now)
                            """
                        ),
                        {
                            "id": uuid4(),
                            "run_id": run["id"],
                            "report_sha256": report_sha256,
                            "now": now,
                        },
                    )

                    directory_response = await client.get("/api/v2/research-projects/reports")
                    assert directory_response.status_code == 200
                    directory = directory_response.json()
                    assert directory["total"] == 1
                    assert directory["items"][0]["research_project"]["id"] == project["id"]
                    assert directory["items"][0]["run"]["id"] == run["id"]
                    assert directory["items"][0]["report_sha256"] == report_sha256

                    evaluation_workspace_response = await client.get(
                        "/api/v2/research-evaluations/workspace",
                        params={"project_id": project["id"], "run_id": run["id"]},
                    )
                    assert evaluation_workspace_response.status_code == 200
                    evaluation_workspace = evaluation_workspace_response.json()
                    assert evaluation_workspace["project"]["id"] == project["id"]
                    assert evaluation_workspace["run"]["id"] == run["id"]
                    assert evaluation_workspace["cohort"]["id"] == run["cohort"]["cohort_id"]
                    integration_by_kind = {
                        item["kind"]: item for item in evaluation_workspace["capabilities"]
                    }
                    assert integration_by_kind["survey"]["can_launch_for_scope"] is True
                    assert integration_by_kind["chat"]["integration_state"] == (
                        "source_sample_only"
                    )
                    assert integration_by_kind["app"]["integration_state"] == ("not_implemented")
                    assert evaluation_workspace["task_bundles"] == []
                    assert evaluation_workspace["targets"] == []

                    chat_target_response = await client.post(
                        "/api/v2/research-evaluations/targets",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "kind": "chat",
                            "title": "研究对话被测对象",
                            "target_url": "https://chat.example.test/v1/messages",
                            "transport": "rest_chat",
                            "task_goal": "核验被测对象能否解释本次研究上下文。",
                            "success_criteria": ["回答引用冻结研究问题"],
                        },
                    )
                    assert chat_target_response.status_code == 201
                    chat_target = chat_target_response.json()
                    assert chat_target["payload"]["kind"] == "chat"
                    assert chat_target["payload"]["execution_policy"] == "definition_only"

                    web_target_response = await client.post(
                        "/api/v2/research-evaluations/targets",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "kind": "web",
                            "title": "研究网页被测对象",
                            "target_url": "https://web.example.test/research",
                            "transport": "playwright_browser",
                            "task_goal": "核验页面是否呈现本次研究需要的内容。",
                            "success_criteria": ["页面保留可引用正文"],
                        },
                    )
                    assert web_target_response.status_code == 201
                    assert web_target_response.json()["payload"]["kind"] == "web"

                    app_target_response = await client.post(
                        "/api/v2/research-evaluations/targets",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "kind": "app",
                            "title": "研究 App 被测对象",
                            "target_url": None,
                            "task_package": (
                                "application/tasks/example-computer-use-linux_note-to-csv"
                            ),
                            "transport": "harbor_task",
                            "task_goal": "核验合成 Persona 能否完成受控 App 任务。",
                            "success_criteria": ["任务产物通过 task-owned verifier"],
                        },
                    )
                    assert app_target_response.status_code == 201
                    app_target = app_target_response.json()
                    assert app_target["payload"]["kind"] == "app"

                    job_response = await client.post(
                        "/api/v2/research-evaluations/jobs",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "target_id": app_target["id"],
                        },
                    )
                    assert job_response.status_code == 202
                    job = job_response.json()
                    assert job["kind"] == "app"
                    assert job["status"] == "queued"

                    bundle_response = await client.post(
                        "/api/v2/research-evaluations/task-bundles",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "kind": "survey",
                        },
                    )
                    assert bundle_response.status_code == 201
                    bundle = bundle_response.json()
                    assert bundle["research_project_id"] == project["id"]
                    assert bundle["research_simulation_run_id"] == run["id"]
                    assert bundle["cohort_id"] == run["cohort"]["cohort_id"]
                    assert bundle["payload"]["kind"] == "survey"
                    assert (
                        len(bundle["payload"]["persona_profile_sha256s"])
                        == (run["cohort"]["persona_count"])
                    )
                    assert bundle["payload"]["reward_policy"] == "not_applicable"
                    assert bundle["execution"] is None

                    repeated_bundle_response = await client.post(
                        "/api/v2/research-evaluations/task-bundles",
                        json={
                            "research_project_id": project["id"],
                            "research_simulation_run_id": run["id"],
                            "kind": "survey",
                        },
                    )
                    assert repeated_bundle_response.status_code == 201
                    assert repeated_bundle_response.json()["id"] == bundle["id"]

                    bundled_workspace_response = await client.get(
                        "/api/v2/research-evaluations/workspace",
                        params={"project_id": project["id"], "run_id": run["id"]},
                    )
                    assert bundled_workspace_response.status_code == 200
                    bundled_workspace = bundled_workspace_response.json()
                    assert bundled_workspace["task_bundles"][0]["id"] == bundle["id"]
                    assert {item["payload"]["kind"] for item in bundled_workspace["targets"]} == {
                        "app",
                        "chat",
                        "web",
                    }
                    assert bundled_workspace["jobs"][0]["id"] == job["id"]
                    bundled_capabilities = {
                        item["kind"]: item for item in bundled_workspace["capabilities"]
                    }
                    assert bundled_capabilities["chat"]["integration_state"] == ("target_defined")
                    assert bundled_capabilities["chat"]["can_launch_for_scope"] is True
                    assert bundled_capabilities["web"]["integration_state"] == ("target_defined")
                    assert bundled_capabilities["app"]["integration_state"] == ("target_defined")
                    assert bundled_capabilities["web"]["can_launch_for_scope"] is True
                    assert bundled_capabilities["app"]["can_launch_for_scope"] is True
                    boundaries_by_name = {
                        item["name"]: item for item in bundled_workspace["runtime_boundaries"]
                    }
                    assert boundaries_by_name["task_bundle"]["state"] == "available"
                    assert boundaries_by_name["verifier"]["state"] == "available"
                    assert boundaries_by_name["reward"]["state"] == "available"

                    empty_agent_response = await client.get(
                        f"/api/v2/research-projects/{project['id']}/runs/{run['id']}/report-agent"
                    )
                    assert empty_agent_response.status_code == 200
                    assert empty_agent_response.json() is None

                    agent_response = await client.post(
                        f"/api/v2/research-projects/{project['id']}/runs/{run['id']}/report-agent"
                    )
                    assert agent_response.status_code == 201
                    agent_run = agent_response.json()
                    assert agent_run["schema_version"] == ("sandowl-research-run-report-agent/v2")
                    assert agent_run["research_simulation_run_id"] == run["id"]
                    assert agent_run["research_run_report_sha256"] == report_sha256
                    assert agent_run["remaining_tool_calls"] == 0
                    assert [call["tool_name"] for call in agent_run["tool_calls"]] == [
                        "read_world_snapshot",
                        "read_world_graph",
                        "read_simulation_run",
                    ]

                    repeated_response = await client.post(
                        f"/api/v2/research-projects/{project['id']}/runs/{run['id']}/report-agent"
                    )
                    assert repeated_response.status_code == 201
                    assert repeated_response.json()["id"] == agent_run["id"]

                    existing_agent_response = await client.get(
                        f"/api/v2/research-projects/{project['id']}/runs/{run['id']}/report-agent"
                    )
                    assert existing_agent_response.status_code == 200
                    assert existing_agent_response.json()["id"] == agent_run["id"]

                    source_row = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT result_text,result_sha256 "
                                    "FROM report_agent_evidence_tool_calls "
                                    "WHERE run_id=:run_id AND tool_name='read_simulation_run'"
                                ),
                                {"run_id": agent_run["id"]},
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert project["research_question"] in source_row["result_text"]
                    assert (
                        sha256(source_row["result_text"].encode("utf-8")).hexdigest()
                        == (source_row["result_sha256"])
                    )

                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        root_draft = await enqueue_report_agent_draft(
                            session, UUID(agent_run["id"])
                        )
                    await connection.execute(
                        text(
                            "UPDATE report_agent_cited_drafts SET status='running', "
                            "started_at=:now, claimed_by_worker_id='integration-report-worker' "
                            "WHERE id=:id"
                        ),
                        {"now": now, "id": root_draft.id},
                    )
                    await connection.execute(
                        text(
                            "UPDATE report_agent_cited_drafts SET status='failed', "
                            "completed_at=:now,error_code='strict_validation',"
                            "error_message='Synthetic integration failure.' WHERE id=:id"
                        ),
                        {"now": now, "id": root_draft.id},
                    )
                    retry_response = await client.post(
                        f"/api/v2/report-agent/drafts/{root_draft.id}/retry"
                    )
                    assert retry_response.status_code == 202
                    draft = ReportAgentCitedDraft.model_validate_json(retry_response.content)
                    assert draft.attempt_number == 2
                    assert draft.semantic_config_sha256 == "5" * 64
                    assert draft.retry_of_draft_id == root_draft.id
                    assert draft.retry_of_input_sha256 == root_draft.input_sha256
                    repeated_retry_response = await client.post(
                        f"/api/v2/report-agent/drafts/{root_draft.id}/retry"
                    )
                    assert repeated_retry_response.status_code == 202
                    assert repeated_retry_response.json()["id"] == str(draft.id)
                    preserved_failure_response = await client.get(
                        f"/api/v2/report-agent/drafts/{root_draft.id}"
                    )
                    assert preserved_failure_response.status_code == 200
                    assert preserved_failure_response.json()["status"] == "failed"
                    assert preserved_failure_response.json()["attempt_number"] == 1
                    quote = "这是合成模拟记录，不是现实用户行为、现实预测、商业建议或方案比较。"
                    start_offset = source_row["result_text"].index(quote)
                    sections = tuple(
                        ReportAgentDraftSection(
                            position=section["position"],
                            title=section["title"],
                            body_markdown="本节只解释这一次冻结的合成运行。",
                            citations=(
                                ReportAgentDraftCitation(
                                    position=0,
                                    evidence_kind="simulation_run",
                                    target_id=UUID(run["id"]),
                                    tool_call_position=2,
                                    source_label="SandOwl：冻结的单次合成模拟记录",
                                    quote=quote,
                                    start_offset=start_offset,
                                    end_offset=start_offset + len(quote),
                                ),
                            ),
                        )
                        for section in agent_run["outline"]
                    )
                    title = "单次合成运行报告"
                    draft_sha256 = calculate_report_agent_draft_sha256(
                        draft.input_sha256, title, sections
                    )
                    await connection.execute(
                        text(
                            "UPDATE report_agent_cited_drafts SET status='running', "
                            "started_at=:now, claimed_by_worker_id='integration-report-worker' "
                            "WHERE id=:id"
                        ),
                        {"now": now, "id": draft.id},
                    )
                    await connection.execute(
                        text(
                            "UPDATE report_agent_cited_drafts SET status='succeeded', "
                            "completed_at=:now,title=:title,sections_json=:sections,"
                            "draft_sha256=:digest WHERE id=:id"
                        ),
                        {
                            "now": now,
                            "title": title,
                            "sections": serialize_draft_sections(sections),
                            "digest": draft_sha256,
                            "id": draft.id,
                        },
                    )
                    interaction_response = await client.post(
                        f"/api/v2/report-agent/drafts/{draft.id}/interactions",
                        json={
                            "question": "这次合成模拟记录了多少动作？",
                            "parent_interaction_id": None,
                        },
                    )
                    assert interaction_response.status_code == 202
                    interaction = interaction_response.json()
                    assert interaction["research_simulation_run_id"] == run["id"]
                    assert interaction["report_agent_draft_id"] == str(draft.id)
                    assert interaction["status"] == "queued"

                    answer_citations = (
                        AgentInteractionCitation(
                            position=0,
                            source_kind="simulation_run",
                            target_id=UUID(run["id"]),
                            source_label="SandOwl：冻结的单次合成模拟记录",
                            quote=quote,
                            start_offset=start_offset,
                            end_offset=start_offset + len(quote),
                        ),
                    )
                    answer = "本次冻结记录包含 2 个类型化动作，仅描述这次合成运行。"
                    answer_digest = calculate_answer_sha256(
                        interaction["interaction_sha256"], answer, answer_citations
                    )
                    citations_json = json.dumps(
                        [item.model_dump(mode="json") for item in answer_citations],
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    await connection.execute(
                        text(
                            "UPDATE agent_interactions SET status='running',started_at=:now,"
                            "claimed_by_worker_id='integration-report-worker' WHERE id=:id"
                        ),
                        {"now": now, "id": interaction["id"]},
                    )
                    await connection.execute(
                        text(
                            "UPDATE agent_interactions SET status='succeeded',completed_at=:now,"
                            "answer_markdown=:answer,citations_json=:citations,"
                            "answer_sha256=:digest "
                            "WHERE id=:id"
                        ),
                        {
                            "now": now,
                            "answer": answer,
                            "citations": citations_json,
                            "digest": answer_digest,
                            "id": interaction["id"],
                        },
                    )
                    projected_response = await client.get(
                        f"/api/v2/agent-interactions/{interaction['id']}"
                    )
                    assert projected_response.status_code == 200
                    assert projected_response.json()["citations"][0]["quote"] == quote

                project_row = (
                    (
                        await connection.execute(
                            text(
                                "SELECT cohort_id,simulation_requirement FROM research_projects "
                                "WHERE id=:id"
                            ),
                            {"id": project["id"]},
                        )
                    )
                    .mappings()
                    .one()
                )
                assert project_row["cohort_id"] is None
                assert project_row["simulation_requirement"] is None
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for research project integration",
)
def test_research_project_flow_separates_context_from_run_design() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_research_project_flow(TEST_POSTGRES_DATABASE_URL))
