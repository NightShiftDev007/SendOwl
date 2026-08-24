"""PostgreSQL queue operations for native Agent Interaction."""

# ruff: noqa: E501

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from psycopg import Connection
from pydantic import TypeAdapter, ValidationError

from oasis_worker.agent_interaction_contracts import (
    AgentInteractionConversationTurn,
    ClaimedAgentInteraction,
    NormalizedAgentInteractionAnswer,
)
from oasis_worker.agent_interaction_hashing import answer_sha256, interaction_sha256
from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.report_agent_draft_contracts import NormalizedReportAgentDraftSection
from oasis_worker.report_agent_draft_hashing import draft_sha256
from oasis_worker.semantic_contracts import SemanticRuntimeConfig

SECTIONS_ADAPTER = TypeAdapter(tuple[NormalizedReportAgentDraftSection, ...])


def agent_interaction_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM agent_interactions
            WHERE status='queued' AND model_name=%s AND semantic_config_sha256=%s
              AND prompt_schema_version IN ('sandowl-agent-interaction/v1','sandowl-agent-interaction/v2')
            ORDER BY created_at, id LIMIT 1
            """,
            (runtime_config.model_name, runtime_config.config_sha256),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row["id"], row["created_at"]


def claim_agent_interaction(
    connection: Connection[dict[str, object]],
    interaction_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedAgentInteraction | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT interaction.*, run.run_sha256 AS actual_run_sha256,
                       run.schema_version AS run_schema_version,
                       run.research_simulation_run_id AS actual_simulation_run_id,
                       draft.input_sha256 AS draft_input_sha256,
                       draft.title AS report_title, draft.sections_json,
                       draft.draft_sha256 AS actual_draft_sha256,
                       tool.result_text AS source_text, tool.result_sha256 AS actual_source_sha256
                FROM agent_interactions interaction
                JOIN report_agent_evidence_runs run ON run.id=interaction.report_agent_run_id
                JOIN report_agent_cited_drafts draft
                  ON draft.id=interaction.report_agent_draft_id
                 AND draft.run_id=run.id AND draft.status='succeeded'
                JOIN report_agent_evidence_tool_calls tool
                  ON tool.run_id=run.id AND tool.tool_name='read_simulation_run'
                 AND tool.target_id=interaction.research_simulation_run_id
                WHERE interaction.id=%s AND interaction.status='queued'
                  AND interaction.model_name=%s AND interaction.semantic_config_sha256=%s
                FOR UPDATE OF interaction SKIP LOCKED
                """,
                (interaction_id, runtime_config.model_name, runtime_config.config_sha256),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return None
            if (
                row["run_schema_version"]
                not in (
                    "sandowl-research-run-report-agent/v1",
                    "sandowl-research-run-report-agent/v2",
                )
                or row["actual_simulation_run_id"] != row["research_simulation_run_id"]
                or row["actual_run_sha256"] != row["report_agent_run_sha256"]
                or row["actual_draft_sha256"] != row["report_agent_draft_sha256"]
                or row["source_text"] is None
                or sha256(row["source_text"].encode("utf-8")).hexdigest()
                != row["actual_source_sha256"]
                or row["actual_source_sha256"] != row["source_sha256"]
            ):
                raise RuntimeError("Agent Interaction frozen scope digest mismatch")
            sections = SECTIONS_ADAPTER.validate_json(row["sections_json"], strict=True)
            if row["actual_draft_sha256"] != draft_sha256(
                row["draft_input_sha256"], row["report_title"], sections
            ):
                raise RuntimeError("Agent Interaction ReportAgent draft digest mismatch")
            expected_interaction = interaction_sha256(
                row["research_project_id"],
                row["research_simulation_run_id"],
                row["report_agent_run_sha256"],
                row["report_agent_draft_sha256"],
                row["source_sha256"],
                row["question"],
                row["parent_interaction_sha256"],
                row["parent_answer_sha256"],
            )
            if row["interaction_sha256"] != expected_interaction:
                raise RuntimeError("Agent Interaction input digest mismatch")
            cursor.execute(
                """
                WITH RECURSIVE lineage AS (
                    SELECT id, parent_interaction_id, question, answer_markdown,
                           interaction_sha256, answer_sha256, conversation_depth
                    FROM agent_interactions WHERE id=%s
                    UNION ALL
                    SELECT parent.id, parent.parent_interaction_id, parent.question,
                           parent.answer_markdown, parent.interaction_sha256,
                           parent.answer_sha256, parent.conversation_depth
                    FROM agent_interactions parent
                    JOIN lineage child ON child.parent_interaction_id=parent.id
                )
                SELECT question, answer_markdown, interaction_sha256, answer_sha256,
                       conversation_depth
                FROM lineage WHERE id<>%s ORDER BY conversation_depth
                """,
                (row["id"], row["id"]),
            )
            context_rows = tuple(cursor.fetchall())
            if len(context_rows) != row["conversation_depth"] or any(
                item["answer_markdown"] is None or item["answer_sha256"] is None
                for item in context_rows
            ):
                raise RuntimeError("Agent Interaction conversation lineage mismatch")
            if context_rows and (
                context_rows[-1]["interaction_sha256"] != row["parent_interaction_sha256"]
                or context_rows[-1]["answer_sha256"] != row["parent_answer_sha256"]
            ):
                raise RuntimeError("Agent Interaction parent digest mismatch")
            report_markdown = "\n\n".join(
                f"## {section.title}\n{section.body_markdown}" for section in sections
            )
            job = ClaimedAgentInteraction(
                id=row["id"],
                research_project_id=row["research_project_id"],
                research_simulation_run_id=row["research_simulation_run_id"],
                report_agent_run_id=row["report_agent_run_id"],
                report_agent_run_sha256=row["report_agent_run_sha256"],
                report_agent_draft_id=row["report_agent_draft_id"],
                report_agent_draft_sha256=row["report_agent_draft_sha256"],
                source_sha256=row["source_sha256"],
                question=row["question"],
                interaction_sha256=row["interaction_sha256"],
                model_name=row["model_name"],
                semantic_config_sha256=row["semantic_config_sha256"],
                prompt_schema_version=row["prompt_schema_version"],
                parent_interaction_sha256=row["parent_interaction_sha256"],
                parent_answer_sha256=row["parent_answer_sha256"],
                conversation_depth=row["conversation_depth"],
                created_at=row["created_at"],
                report_title=row["report_title"],
                report_markdown=report_markdown,
                source_text=row["source_text"],
                conversation_context=tuple(
                    AgentInteractionConversationTurn(
                        question=item["question"], answer_markdown=item["answer_markdown"]
                    )
                    for item in context_rows
                ),
            )
            cursor.execute(
                "UPDATE agent_interactions SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, interaction_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued Agent Interaction could not be claimed")
        connection.commit()
        return job
    except (json.JSONDecodeError, ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_agent_interaction(
            connection,
            interaction_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    "Agent Interaction queue integrity failed: " + " ".join(str(error).split())
                )[:500],
            ),
            True,
        )
        return None


def complete_agent_interaction(
    connection: Connection[dict[str, object]],
    interaction_id: UUID,
    worker_id: str,
    result: NormalizedAgentInteractionAnswer,
) -> None:
    citations_json = json.dumps(
        [item.model_dump(mode="json") for item in result.citations],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT interaction_sha256, research_simulation_run_id, report_agent_run_id, source_sha256 FROM agent_interactions WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE",
            (interaction_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or result.answer_sha256 != answer_sha256(
            row["interaction_sha256"], result.answer_markdown, result.citations
        ):
            raise RuntimeError("Agent Interaction answer digest mismatch")
        cursor.execute(
            "SELECT result_text FROM report_agent_evidence_tool_calls WHERE run_id=%s AND tool_name='read_simulation_run' AND target_id=%s AND result_sha256=%s",
            (
                row["report_agent_run_id"],
                row["research_simulation_run_id"],
                row["source_sha256"],
            ),
        )
        source = cursor.fetchone()
        if source is None or any(
            citation.target_id != row["research_simulation_run_id"]
            or source["result_text"][citation.start_offset : citation.end_offset] != citation.quote
            for citation in result.citations
        ):
            raise RuntimeError("Agent Interaction citations failed frozen-source verification")
        cursor.execute(
            "UPDATE agent_interactions SET status='succeeded', completed_at=now(), answer_markdown=%s, citations_json=%s, answer_sha256=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (
                result.answer_markdown,
                citations_json,
                result.answer_sha256,
                interaction_id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("running Agent Interaction could not be completed")
    connection.commit()


def fail_agent_interaction(
    connection: Connection[dict[str, object]],
    interaction_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_first: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_first:
            cursor.execute(
                "UPDATE agent_interactions SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, interaction_id),
            )
        cursor.execute(
            "UPDATE agent_interactions SET status='failed', completed_at=now(), error_code=%s, error_message=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (failure.code, failure.message, interaction_id, worker_id),
        )
    connection.commit()


def fail_agent_interactions_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_interactions SET status='failed', completed_at=now(), error_code='worker_process_restarted', error_message='The report worker restarted before completing this Agent Interaction.' WHERE status='running' AND claimed_by_worker_id=%s",
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_agent_interactions(
    connection: Connection[dict[str, object]], cutoff: datetime
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Agent Interaction orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE agent_interactions AS interaction
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The report worker heartbeat expired before completing this Agent Interaction.'
            WHERE interaction.status='running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats heartbeat
                WHERE heartbeat.worker_id=interaction.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff.astimezone(UTC),),
        )
        count = cursor.rowcount
    connection.commit()
    return count
