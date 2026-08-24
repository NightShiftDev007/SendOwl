"""Canonical ReportAgent draft hashes shared with the API persistence boundary."""

import hashlib
import json
from uuid import UUID

from oasis_worker.report_agent_draft_contracts import (
    NormalizedReportAgentDraftSection,
    ReportAgentDraftPlanSection,
)


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def serialize_outline(outline: tuple[ReportAgentDraftPlanSection, ...]) -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in outline],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def run_sha256(
    world_model_id: UUID,
    snapshot_id: UUID,
    snapshot_sha256: str,
    objective: str,
    outline: tuple[ReportAgentDraftPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            "bounded-report-agent-evidence/v1",
            str(world_model_id),
            str(snapshot_id),
            snapshot_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def research_run_sha256(
    world_model_id: UUID,
    snapshot_id: UUID,
    snapshot_sha256: str,
    research_simulation_run_id: UUID,
    research_run_report_sha256: str,
    objective: str,
    outline: tuple[ReportAgentDraftPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            "sandowl-research-run-report-agent/v1",
            str(world_model_id),
            str(snapshot_id),
            snapshot_sha256,
            str(research_simulation_run_id),
            research_run_report_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def research_run_v2_sha256(
    world_model_id: UUID,
    snapshot_id: UUID,
    snapshot_sha256: str,
    research_simulation_run_id: UUID,
    research_run_report_sha256: str,
    objective: str,
    outline: tuple[ReportAgentDraftPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            "sandowl-research-run-report-agent/v2",
            str(world_model_id),
            str(snapshot_id),
            snapshot_sha256,
            str(research_simulation_run_id),
            research_run_report_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def tool_input_sha256(
    run_digest: str, position: int, tool_name: str, target_id: UUID | None
) -> str:
    return _digest(
        (
            "bounded-report-agent-tool-input/v1",
            run_digest,
            str(position),
            tool_name,
            "" if target_id is None else str(target_id),
        )
    )


def tool_call_sha256(input_digest: str, result_sha256: str) -> str:
    return _digest(("bounded-report-agent-tool-call/v1", input_digest, result_sha256))


def evidence_calls_sha256(call_hashes: tuple[str, ...]) -> str:
    if not call_hashes:
        raise ValueError("ReportAgent draft requires at least one evidence call")
    return _digest(("bounded-report-agent-evidence-calls/v1", *call_hashes))


def draft_input_sha256(
    run_digest: str,
    evidence_digest: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    return _digest(
        (
            "bounded-report-agent-cited-draft-input/v1",
            run_digest,
            evidence_digest,
            model_name,
            semantic_config_sha256,
            "bounded-report-agent-cited-draft/v1",
        )
    )


def serialize_sections(sections: tuple[NormalizedReportAgentDraftSection, ...]) -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in sections],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def draft_sha256(
    input_sha256: str,
    title: str,
    sections: tuple[NormalizedReportAgentDraftSection, ...],
) -> str:
    return _digest(
        (
            "bounded-report-agent-cited-draft/v1",
            input_sha256,
            title,
            serialize_sections(sections),
        )
    )
