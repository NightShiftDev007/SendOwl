"""PostgreSQL queue operations for evidence-bound report questions."""

# ruff: noqa: E501

import json
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection, Cursor
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.report_qa_contracts import (
    ClaimedReportQuestion,
    NormalizedReportAnswer,
    ReportQACandidate,
    ReportQAConversationTurn,
)
from oasis_worker.report_qa_hashing import answer_sha256, question_sha256
from oasis_worker.semantic_contracts import SemanticRuntimeConfig


def report_question_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM report_questions
            WHERE status = 'queued' AND model_name = %s AND semantic_config_sha256 = %s
              AND prompt_schema_version IN ('report-evidence-qa/v1', 'report-evidence-qa/v2')
            ORDER BY created_at, id LIMIT 1
            """,
            (runtime_config.model_name, runtime_config.config_sha256),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row["id"], row["created_at"]


def _load_candidates(
    cursor: Cursor[dict[str, object]],
    graph_id: UUID,
    question: str,
) -> tuple[ReportQACandidate, ...]:
    cursor.execute(
        """
        WITH objects AS (
            SELECT node.id AS object_id, 'node' AS object_kind,
                   left(node.name || ': ' || node.summary, 500) AS object_label,
                   similarity(node.name || ' ' || node.summary, %s) AS score
            FROM semantic_world_graph_nodes node WHERE node.graph_id = %s
            UNION ALL
            SELECT edge.id, 'edge', left(source.name || ' —' || edge.relation_type || '→ ' || target.name || ': ' || edge.fact, 500),
                   similarity(source.name || ' ' || target.name || ' ' || edge.fact, %s)
            FROM semantic_world_graph_edges edge
            JOIN semantic_world_graph_nodes source ON source.graph_id = edge.graph_id AND source.id = edge.source_node_id
            JOIN semantic_world_graph_nodes target ON target.graph_id = edge.graph_id AND target.id = edge.target_node_id
            WHERE edge.graph_id = %s
        ), ranked AS (
            SELECT evidence.article_id, evidence.quote, evidence.start_offset, evidence.end_offset,
                   objects.object_label, objects.score,
                   row_number() OVER (PARTITION BY evidence.article_id, evidence.quote ORDER BY objects.score DESC, objects.object_id) AS duplicate_rank
            FROM objects
            JOIN semantic_world_graph_evidence evidence
              ON evidence.graph_id = %s AND evidence.object_kind = objects.object_kind AND evidence.object_id = objects.object_id
        )
        SELECT article_id, quote, start_offset, end_offset, object_label
        FROM ranked WHERE duplicate_rank = 1
        ORDER BY score DESC, article_id, start_offset
        LIMIT 20
        """,
        (question, graph_id, question, graph_id, graph_id),
    )
    return tuple(
        ReportQACandidate(
            position=position,
            article_id=row["article_id"],
            object_label=row["object_label"],
            quote=row["quote"],
            start_offset=row["start_offset"],
            end_offset=row["end_offset"],
        )
        for position, row in enumerate(cursor.fetchall())
    )


def claim_report_question(
    connection: Connection[dict[str, object]],
    question_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedReportQuestion | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT question.*, report.title AS report_title, report.report_sha256 AS actual_report_sha256,
                       graph.graph_sha256 AS actual_graph_sha256
                FROM report_questions question
                JOIN decision_reports report ON report.id = question.report_id AND report.sealed_at IS NOT NULL
                JOIN semantic_world_graphs graph ON graph.id = question.graph_id AND graph.status = 'succeeded'
                WHERE question.id = %s AND question.status = 'queued' AND question.model_name = %s
                  AND question.semantic_config_sha256 = %s
                FOR UPDATE OF question SKIP LOCKED
                """,
                (question_id, runtime_config.model_name, runtime_config.config_sha256),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return None
            if (
                row["actual_report_sha256"] != row["report_sha256"]
                or row["actual_graph_sha256"] != row["graph_sha256"]
            ):
                raise RuntimeError("report question frozen input digest mismatch")
            if row["question_sha256"] != question_sha256(
                row["report_sha256"],
                row["graph_sha256"],
                row["question"],
                row["parent_question_sha256"],
                row["parent_answer_sha256"],
            ):
                raise RuntimeError("report question digest mismatch")
            cursor.execute(
                """
                WITH RECURSIVE lineage AS (
                    SELECT id, parent_question_id, question, answer_markdown,
                           question_sha256, answer_sha256, conversation_depth
                    FROM report_questions WHERE id = %s
                    UNION ALL
                    SELECT parent.id, parent.parent_question_id, parent.question,
                           parent.answer_markdown, parent.question_sha256,
                           parent.answer_sha256, parent.conversation_depth
                    FROM report_questions parent
                    JOIN lineage child ON child.parent_question_id = parent.id
                )
                SELECT question, answer_markdown, question_sha256, answer_sha256,
                       conversation_depth
                FROM lineage WHERE id <> %s ORDER BY conversation_depth
                """,
                (row["id"], row["id"]),
            )
            context_rows = tuple(cursor.fetchall())
            if len(context_rows) != row["conversation_depth"] or any(
                item["answer_markdown"] is None or item["answer_sha256"] is None
                for item in context_rows
            ):
                raise RuntimeError("report question conversation lineage mismatch")
            if context_rows and (
                context_rows[-1]["question_sha256"] != row["parent_question_sha256"]
                or context_rows[-1]["answer_sha256"] != row["parent_answer_sha256"]
            ):
                raise RuntimeError("report question parent digest mismatch")
            cursor.execute(
                "SELECT body_markdown FROM decision_report_sections WHERE report_id = %s ORDER BY position",
                (row["report_id"],),
            )
            sections = tuple(item["body_markdown"] for item in cursor.fetchall())
            candidates = _load_candidates(cursor, row["graph_id"], row["question"])
            if not candidates:
                raise RuntimeError("report question graph contains no citable evidence")
            job = ClaimedReportQuestion(
                id=row["id"],
                report_id=row["report_id"],
                report_sha256=row["report_sha256"],
                graph_id=row["graph_id"],
                graph_sha256=row["graph_sha256"],
                question=row["question"],
                question_sha256=row["question_sha256"],
                model_name=row["model_name"],
                semantic_config_sha256=row["semantic_config_sha256"],
                prompt_schema_version=row["prompt_schema_version"],
                parent_question_sha256=row["parent_question_sha256"],
                parent_answer_sha256=row["parent_answer_sha256"],
                conversation_depth=row["conversation_depth"],
                created_at=row["created_at"],
                report_title=row["report_title"],
                report_sections=sections,
                candidates=candidates,
                conversation_context=tuple(
                    ReportQAConversationTurn(
                        question=item["question"],
                        answer_markdown=item["answer_markdown"],
                    )
                    for item in context_rows
                ),
            )
            cursor.execute(
                "UPDATE report_questions SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, question_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued report question could not be claimed")
        connection.commit()
        return job
    except (ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_report_question(
            connection,
            question_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=("Report question queue integrity failed: " + " ".join(str(error).split()))[
                    :500
                ],
            ),
            True,
        )
        return None


def complete_report_question(
    connection: Connection[dict[str, object]],
    question_id: UUID,
    worker_id: str,
    result: NormalizedReportAnswer,
) -> None:
    citations_json = json.dumps(
        [
            {
                "position": item.position,
                "article_id": str(item.article_id),
                "quote": item.quote,
                "start_offset": item.start_offset,
                "end_offset": item.end_offset,
            }
            for item in result.citations
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT question_sha256 FROM report_questions WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE",
            (question_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or result.answer_sha256 != answer_sha256(
            row["question_sha256"], result.answer_markdown, result.citations
        ):
            raise RuntimeError("report answer digest mismatch")
        cursor.execute(
            "UPDATE report_questions SET status='succeeded', completed_at=now(), answer_markdown=%s, citations_json=%s, answer_sha256=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (result.answer_markdown, citations_json, result.answer_sha256, question_id, worker_id),
        )
    connection.commit()


def fail_report_question(
    connection: Connection[dict[str, object]],
    question_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_first: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_first:
            cursor.execute(
                "UPDATE report_questions SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, question_id),
            )
        cursor.execute(
            "UPDATE report_questions SET status='failed', completed_at=now(), error_code=%s, error_message=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (failure.code, failure.message, question_id, worker_id),
        )
    connection.commit()


def fail_report_questions_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE report_questions SET status='failed', completed_at=now(), error_code='worker_process_restarted', error_message='The model worker restarted before completing this answer.' WHERE status='running' AND claimed_by_worker_id=%s",
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_report_questions(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("report question orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE report_questions AS question
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The model worker heartbeat expired before completing this answer.'
            WHERE question.status='running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats heartbeat
                WHERE heartbeat.worker_id=question.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff.astimezone(UTC),),
        )
        count = cursor.rowcount
    connection.commit()
    return count
