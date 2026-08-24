"""Content addressing for bounded ReportAgent evidence runs and tool calls."""

import hashlib
import json
from uuid import UUID

from app.report_agents.contracts import ReportAgentDraftSection, ReportAgentPlanSection

RUN_SCHEMA_VERSION = "bounded-report-agent-evidence/v1"
RESEARCH_RUN_SCHEMA_VERSION = "sandowl-research-run-report-agent/v1"
RESEARCH_RUN_V2_SCHEMA_VERSION = "sandowl-research-run-report-agent/v2"
TOOL_INPUT_SCHEMA_VERSION = "bounded-report-agent-tool-input/v1"
TOOL_CALL_SCHEMA_VERSION = "bounded-report-agent-tool-call/v1"
EVIDENCE_CALLS_SCHEMA_VERSION = "bounded-report-agent-evidence-calls/v1"
DRAFT_PROMPT_SCHEMA_VERSION = "bounded-report-agent-cited-draft/v1"
DRAFT_INPUT_SCHEMA_VERSION = "bounded-report-agent-cited-draft-input/v1"
DRAFT_SCHEMA_VERSION = "bounded-report-agent-cited-draft/v1"


def serialize_outline(outline: tuple[ReportAgentPlanSection, ...]) -> str:
    """Serialize the frozen ordered outline once for hashing and persistence."""
    return json.dumps(
        [section.model_dump(mode="json") for section in outline],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def calculate_report_agent_run_sha256(
    world_model_id: UUID,
    world_snapshot_id: UUID,
    snapshot_sha256: str,
    objective: str,
    outline: tuple[ReportAgentPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            RUN_SCHEMA_VERSION,
            str(world_model_id),
            str(world_snapshot_id),
            snapshot_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def calculate_research_run_report_agent_sha256(
    world_model_id: UUID,
    world_snapshot_id: UUID,
    snapshot_sha256: str,
    research_simulation_run_id: UUID,
    research_run_report_sha256: str,
    objective: str,
    outline: tuple[ReportAgentPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            RESEARCH_RUN_SCHEMA_VERSION,
            str(world_model_id),
            str(world_snapshot_id),
            snapshot_sha256,
            str(research_simulation_run_id),
            research_run_report_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def calculate_research_run_report_agent_v2_sha256(
    world_model_id: UUID,
    world_snapshot_id: UUID,
    snapshot_sha256: str,
    research_simulation_run_id: UUID,
    research_run_report_sha256: str,
    objective: str,
    outline: tuple[ReportAgentPlanSection, ...],
    max_tool_calls: int,
) -> str:
    return _digest(
        (
            RESEARCH_RUN_V2_SCHEMA_VERSION,
            str(world_model_id),
            str(world_snapshot_id),
            snapshot_sha256,
            str(research_simulation_run_id),
            research_run_report_sha256,
            objective,
            serialize_outline(outline),
            str(max_tool_calls),
        )
    )


def calculate_report_agent_tool_input_sha256(
    run_sha256: str,
    position: int,
    tool_name: str,
    target_id: UUID | None,
) -> str:
    return _digest(
        (
            TOOL_INPUT_SCHEMA_VERSION,
            run_sha256,
            str(position),
            tool_name,
            "" if target_id is None else str(target_id),
        )
    )


def calculate_report_agent_tool_call_sha256(
    input_sha256: str,
    result_sha256: str,
) -> str:
    return _digest((TOOL_CALL_SCHEMA_VERSION, input_sha256, result_sha256))


def calculate_report_agent_evidence_calls_sha256(call_sha256_values: tuple[str, ...]) -> str:
    if not call_sha256_values:
        raise ValueError("ReportAgent cited draft requires at least one evidence read call")
    return _digest((EVIDENCE_CALLS_SCHEMA_VERSION, *call_sha256_values))


def calculate_report_agent_draft_input_sha256(
    run_sha256: str,
    evidence_calls_sha256: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    return _digest(
        (
            DRAFT_INPUT_SCHEMA_VERSION,
            run_sha256,
            evidence_calls_sha256,
            model_name,
            semantic_config_sha256,
            DRAFT_PROMPT_SCHEMA_VERSION,
        )
    )


def serialize_draft_sections(sections: tuple[ReportAgentDraftSection, ...]) -> str:
    return json.dumps(
        [section.model_dump(mode="json") for section in sections],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_report_agent_draft_sha256(
    input_sha256: str,
    title: str,
    sections: tuple[ReportAgentDraftSection, ...],
) -> str:
    return _digest(
        (
            DRAFT_SCHEMA_VERSION,
            input_sha256,
            title,
            serialize_draft_sections(sections),
        )
    )


__all__ = [
    "RUN_SCHEMA_VERSION",
    "RESEARCH_RUN_SCHEMA_VERSION",
    "RESEARCH_RUN_V2_SCHEMA_VERSION",
    "DRAFT_PROMPT_SCHEMA_VERSION",
    "calculate_report_agent_draft_input_sha256",
    "calculate_report_agent_draft_sha256",
    "calculate_report_agent_evidence_calls_sha256",
    "calculate_report_agent_run_sha256",
    "calculate_research_run_report_agent_sha256",
    "calculate_research_run_report_agent_v2_sha256",
    "calculate_report_agent_tool_call_sha256",
    "calculate_report_agent_tool_input_sha256",
    "serialize_outline",
    "serialize_draft_sections",
]
