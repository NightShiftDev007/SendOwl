"""Content addressing shared by the Agent Interaction queue."""

import hashlib
import json
from uuid import UUID

from oasis_worker.agent_interaction_contracts import AgentInteractionCitation


def _digest(parts: tuple[str, ...]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def interaction_sha256(
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
        "sandowl-agent-interaction/v1"
        if parent_interaction_sha256 is None
        else "sandowl-agent-interaction/v2"
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


def answer_sha256(
    interaction_digest: str,
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
            interaction_digest,
            answer_markdown,
            serialized,
        )
    )
