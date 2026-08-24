"""PostgreSQL queue operations for evidence-cited ReportAgent drafts."""

# ruff: noqa: E501

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from psycopg import Connection, Cursor
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.report_agent_draft_contracts import (
    DRAFT_PROMPT_SCHEMA_VERSION,
    ClaimedReportAgentDraft,
    NormalizedReportAgentDraft,
    ReportAgentDraftEvidence,
    ReportAgentDraftPlanSection,
)
from oasis_worker.report_agent_draft_hashing import (
    draft_input_sha256,
    draft_sha256,
    evidence_calls_sha256,
    research_run_sha256,
    research_run_v2_sha256,
    run_sha256,
    serialize_sections,
    tool_call_sha256,
    tool_input_sha256,
)
from oasis_worker.semantic_contracts import SemanticRuntimeConfig

MAX_EVIDENCE_INPUT_CHARACTERS = 80_000


def report_agent_draft_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at FROM report_agent_cited_drafts
            WHERE status='queued' AND model_name=%s AND semantic_config_sha256=%s
              AND prompt_schema_version=%s
            ORDER BY created_at, id LIMIT 1
            """,
            (
                runtime_config.model_name,
                runtime_config.config_sha256,
                DRAFT_PROMPT_SCHEMA_VERSION,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return row["id"], row["created_at"]


def _load_evidence(
    cursor: Cursor[dict[str, object]],
    run_id: UUID,
    snapshot_id: UUID,
    run_digest: str,
    expected_count: int,
) -> tuple[ReportAgentDraftEvidence, ...]:
    cursor.execute(
        """
        SELECT position, tool_name, target_id, input_sha256, result_sha256, call_sha256,
               result_text
        FROM report_agent_evidence_tool_calls
        WHERE run_id=%s AND tool_name IN (
          'read_media','read_policy','read_world_snapshot','read_world_graph',
          'read_simulation_run','read_persona_interviews'
        )
        ORDER BY position LIMIT %s
        """,
        (run_id, expected_count),
    )
    calls = tuple(cursor.fetchall())
    if len(calls) != expected_count:
        raise RuntimeError("ReportAgent draft frozen evidence prefix is incomplete")
    maximum = max(1, MAX_EVIDENCE_INPUT_CHARACTERS // expected_count)
    evidence: list[ReportAgentDraftEvidence] = []
    for evidence_position, call in enumerate(calls):
        expected_input = tool_input_sha256(
            run_digest, call["position"], call["tool_name"], call["target_id"]
        )
        if call["input_sha256"] != expected_input or call["call_sha256"] != tool_call_sha256(
            expected_input, call["result_sha256"]
        ):
            raise RuntimeError("ReportAgent draft evidence call digest mismatch")
        if call["tool_name"] == "read_media":
            cursor.execute(
                """
                SELECT captured_text, captured_text_sha256 AS content_sha256,
                       left(source_name || ': ' || title, 500) AS source_label
                FROM world_snapshot_evidence
                WHERE snapshot_id=%s AND article_id=%s
                """,
                (snapshot_id, call["target_id"]),
            )
            evidence_kind = "media_article"
            source = cursor.fetchone()
        elif call["tool_name"] == "read_policy":
            cursor.execute(
                """
                SELECT captured_text, content_sha256,
                       left(authority_name || ': ' || title, 500) AS source_label
                FROM world_snapshot_policy_evidence
                WHERE snapshot_id=%s AND policy_version_id=%s
                """,
                (snapshot_id, call["target_id"]),
            )
            evidence_kind = "policy_document"
            source = cursor.fetchone()
        else:
            result_text = call["result_text"]
            if not isinstance(result_text, str):
                raise RuntimeError("ReportAgent frozen research source text is unavailable")
            source_identity = {
                "read_world_snapshot": (
                    "world_snapshot",
                    "SandOwl：冻结的现实背景证据",
                ),
                "read_world_graph": (
                    "world_graph",
                    "SandOwl：冻结证据语义图",
                ),
                "read_simulation_run": (
                    "simulation_run",
                    "SandOwl：冻结的单次合成模拟记录",
                ),
                "read_persona_interviews": (
                    "persona_interviews",
                    "SandOwl：经用户明确发起的运行后 Persona 追问",
                ),
            }.get(call["tool_name"])
            if source_identity is None:
                raise RuntimeError("ReportAgent frozen research source kind is unsupported")
            source = {
                "captured_text": result_text,
                "content_sha256": sha256(result_text.encode("utf-8")).hexdigest(),
                "source_label": source_identity[1],
            }
            evidence_kind = source_identity[0]
        if source is None or source["content_sha256"] != call["result_sha256"]:
            raise RuntimeError("ReportAgent draft evidence content digest mismatch")
        evidence.append(
            ReportAgentDraftEvidence(
                evidence_position=evidence_position,
                tool_call_position=call["position"],
                evidence_kind=evidence_kind,
                target_id=call["target_id"],
                source_label=source["source_label"],
                captured_text=source["captured_text"][:maximum],
                content_sha256=source["content_sha256"],
            )
        )
    return tuple(evidence)


def claim_report_agent_draft(
    connection: Connection[dict[str, object]],
    draft_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedReportAgentDraft | None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT draft.*, run.world_model_id, run.world_snapshot_id, run.snapshot_sha256,
                       run.objective, run.outline_json, run.max_tool_calls, run.schema_version,
                       run.research_simulation_run_id, run.research_run_report_sha256,
                       run.run_sha256 AS actual_run_sha256
                FROM report_agent_cited_drafts draft
                JOIN report_agent_evidence_runs run ON run.id=draft.run_id
                WHERE draft.id=%s AND draft.status='queued' AND draft.model_name=%s
                  AND draft.semantic_config_sha256=%s AND draft.prompt_schema_version=%s
                FOR UPDATE OF draft SKIP LOCKED
                """,
                (
                    draft_id,
                    runtime_config.model_name,
                    runtime_config.config_sha256,
                    DRAFT_PROMPT_SCHEMA_VERSION,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return None
            outline_data = json.loads(row["outline_json"])
            if not isinstance(outline_data, list):
                raise RuntimeError("ReportAgent draft outline JSON must be an array")
            outline = tuple(
                ReportAgentDraftPlanSection.model_validate(item) for item in outline_data
            )
            if row["schema_version"] == "bounded-report-agent-evidence/v1":
                actual_run_sha256 = run_sha256(
                    row["world_model_id"],
                    row["world_snapshot_id"],
                    row["snapshot_sha256"],
                    row["objective"],
                    outline,
                    row["max_tool_calls"],
                )
            elif (
                row["schema_version"]
                in (
                    "sandowl-research-run-report-agent/v1",
                    "sandowl-research-run-report-agent/v2",
                )
                and row["research_simulation_run_id"] is not None
                and row["research_run_report_sha256"] is not None
            ):
                calculate_research_digest = (
                    research_run_v2_sha256
                    if row["schema_version"] == "sandowl-research-run-report-agent/v2"
                    else research_run_sha256
                )
                actual_run_sha256 = calculate_research_digest(
                    row["world_model_id"],
                    row["world_snapshot_id"],
                    row["snapshot_sha256"],
                    row["research_simulation_run_id"],
                    row["research_run_report_sha256"],
                    row["objective"],
                    outline,
                    row["max_tool_calls"],
                )
            else:
                raise RuntimeError("ReportAgent draft run schema is unsupported")
            if (
                row["run_sha256"] != row["actual_run_sha256"]
                or row["run_sha256"] != actual_run_sha256
            ):
                raise RuntimeError("ReportAgent draft run digest mismatch")
            evidence = _load_evidence(
                cursor,
                row["run_id"],
                row["world_snapshot_id"],
                row["run_sha256"],
                row["evidence_call_count"],
            )
            calls_digest = evidence_calls_sha256(
                tuple(
                    tool_call_sha256(
                        tool_input_sha256(
                            row["run_sha256"],
                            item.tool_call_position,
                            {
                                "media_article": "read_media",
                                "policy_document": "read_policy",
                                "world_snapshot": "read_world_snapshot",
                                "world_graph": "read_world_graph",
                                "simulation_run": "read_simulation_run",
                                "persona_interviews": "read_persona_interviews",
                            }[item.evidence_kind],
                            item.target_id,
                        ),
                        item.content_sha256,
                    )
                    for item in evidence
                )
            )
            expected_input = draft_input_sha256(
                row["run_sha256"],
                calls_digest,
                row["model_name"],
                row["semantic_config_sha256"],
            )
            if (
                row["evidence_calls_sha256"] != calls_digest
                or row["input_sha256"] != expected_input
            ):
                raise RuntimeError("ReportAgent draft input digest mismatch")
            job = ClaimedReportAgentDraft(
                id=row["id"],
                run_id=row["run_id"],
                run_sha256=row["run_sha256"],
                evidence_call_count=row["evidence_call_count"],
                evidence_calls_sha256=row["evidence_calls_sha256"],
                input_sha256=row["input_sha256"],
                model_name=row["model_name"],
                semantic_config_sha256=row["semantic_config_sha256"],
                prompt_schema_version=row["prompt_schema_version"],
                created_at=row["created_at"],
                objective=row["objective"],
                outline=outline,
                evidence=evidence,
            )
            cursor.execute(
                "UPDATE report_agent_cited_drafts SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, draft_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("queued ReportAgent draft could not be claimed")
        connection.commit()
        return job
    except (json.JSONDecodeError, ValidationError, RuntimeError, KeyError, TypeError) as error:
        connection.rollback()
        fail_report_agent_draft(
            connection,
            draft_id,
            worker_id,
            NormalizedFailure(
                code="queue_integrity",
                message=(
                    "ReportAgent draft queue integrity failed: " + " ".join(str(error).split())
                )[:500],
            ),
            True,
        )
        return None


def complete_report_agent_draft(
    connection: Connection[dict[str, object]],
    draft_id: UUID,
    worker_id: str,
    result: NormalizedReportAgentDraft,
) -> None:
    sections_json = serialize_sections(result.sections)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT input_sha256 FROM report_agent_cited_drafts WHERE id=%s AND status='running' AND claimed_by_worker_id=%s FOR UPDATE",
            (draft_id, worker_id),
        )
        row = cursor.fetchone()
        if row is None or result.draft_sha256 != draft_sha256(
            row["input_sha256"], result.title, result.sections
        ):
            raise RuntimeError("ReportAgent draft result digest mismatch")
        cursor.execute(
            "UPDATE report_agent_cited_drafts SET status='succeeded', completed_at=now(), title=%s, sections_json=%s, draft_sha256=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (result.title, sections_json, result.draft_sha256, draft_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("running ReportAgent draft could not be completed")
    connection.commit()


def fail_report_agent_draft(
    connection: Connection[dict[str, object]],
    draft_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
    claim_first: bool,
) -> None:
    with connection.cursor() as cursor:
        if claim_first:
            cursor.execute(
                "UPDATE report_agent_cited_drafts SET status='running', started_at=now(), claimed_by_worker_id=%s WHERE id=%s AND status='queued'",
                (worker_id, draft_id),
            )
        cursor.execute(
            "UPDATE report_agent_cited_drafts SET status='failed', completed_at=now(), error_code=%s, error_message=%s WHERE id=%s AND status='running' AND claimed_by_worker_id=%s",
            (failure.code, failure.message, draft_id, worker_id),
        )
    connection.commit()


def fail_report_agent_drafts_owned_by_worker(
    connection: Connection[dict[str, object]], worker_id: str
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE report_agent_cited_drafts SET status='failed', completed_at=now(), error_code='worker_process_restarted', error_message='The model worker restarted before completing this ReportAgent draft.' WHERE status='running' AND claimed_by_worker_id=%s",
            (worker_id,),
        )
        count = cursor.rowcount
    connection.commit()
    return count


def fail_orphaned_report_agent_drafts(
    connection: Connection[dict[str, object]], cutoff: datetime
) -> int:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("ReportAgent draft orphan cutoff must be timezone-aware")
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE report_agent_cited_drafts AS draft
            SET status='failed', completed_at=now(), error_code='worker_heartbeat_expired',
                error_message='The model worker heartbeat expired before completing this ReportAgent draft.'
            WHERE draft.status='running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats heartbeat
                WHERE heartbeat.worker_id=draft.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff.astimezone(UTC),),
        )
        count = cursor.rowcount
    connection.commit()
    return count
