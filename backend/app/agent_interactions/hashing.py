"""Content addressing for native Agent Interaction."""

import hashlib
import json
from uuid import UUID

from app.agent_interactions.contracts import AgentInteractionCitation

ROOT_PROMPT_SCHEMA_VERSION = "sandowl-agent-interaction/v1"
FOLLOW_UP_PROMPT_SCHEMA_VERSION = "sandowl-agent-interaction/v2"


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def calculate_interaction_sha256(
    research_project_id: UUID,
    research_simulation_run_id: UUID,
    report_agent_run_sha256: str,
    report_agent_draft_sha256: str,
    source_sha256: str,
    question: str,
    parent_interaction_sha256: str | None,
    parent_answer_sha256: str | None,
) -> str:
    schema = (
        ROOT_PROMPT_SCHEMA_VERSION
        if parent_interaction_sha256 is None
        else FOLLOW_UP_PROMPT_SCHEMA_VERSION
    )
    return _digest(
        (
            schema,
            str(research_project_id),
            str(research_simulation_run_id),
            report_agent_run_sha256,
            report_agent_draft_sha256,
            source_sha256,
            question,
            parent_interaction_sha256 or "",
            parent_answer_sha256 or "",
        )
    )


def calculate_answer_sha256(
    interaction_sha256: str,
    answer_markdown: str,
    citations: tuple[AgentInteractionCitation, ...],
) -> str:
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in citations],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _digest(
        (
            "sandowl-agent-interaction-answer/v1",
            interaction_sha256,
            answer_markdown,
            serialized,
        )
    )
