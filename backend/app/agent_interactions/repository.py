"""Enqueue and fail-closed reads for native Agent Interaction."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_interactions.contracts import (
    AgentInteraction,
    AgentInteractionCitation,
    AgentInteractionContext,
    AgentInteractionRequest,
    AgentInteractionsResponse,
)
from app.agent_interactions.errors import (
    AgentInteractionNotFoundError,
    AgentInteractionUnavailableError,
)
from app.agent_interactions.hashing import (
    FOLLOW_UP_PROMPT_SCHEMA_VERSION,
    ROOT_PROMPT_SCHEMA_VERSION,
    calculate_answer_sha256,
    calculate_interaction_sha256,
)
from app.agent_interactions.models import AgentInteractionRecord
from app.report_agents.contracts import ReportAgentCitedDraft
from app.report_agents.hashing import RESEARCH_RUN_SCHEMA_VERSION, RESEARCH_RUN_V2_SCHEMA_VERSION
from app.report_agents.models import ReportAgentEvidenceToolCallRecord
from app.report_agents.repository import get_report_agent_draft, get_report_agent_run
from app.research_projects.hashing import calculate_research_run_report_source_sha256
from app.research_projects.models import ResearchSimulationRunRecord
from app.research_projects.repository import get_research_run_report
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

CITATIONS_ADAPTER = TypeAdapter(tuple[AgentInteractionCitation, ...])


async def _load_native_scope(
    session: AsyncSession,
    draft_id: UUID,
) -> tuple[ReportAgentCitedDraft, UUID, UUID, str, str]:
    draft = await get_report_agent_draft(session, draft_id)
    if draft.status != "succeeded" or draft.draft_sha256 is None:
        raise AgentInteractionUnavailableError(
            "Agent Interaction requires a succeeded ReportAgent draft"
        )
    run = await get_report_agent_run(session, draft.run_id)
    if (
        run.schema_version not in (RESEARCH_RUN_SCHEMA_VERSION, RESEARCH_RUN_V2_SCHEMA_VERSION)
        or run.research_simulation_run_id is None
    ):
        raise AgentInteractionUnavailableError(
            "Agent Interaction requires a ReportAgent report bound to one simulation run"
        )
    simulation_run = await session.get(ResearchSimulationRunRecord, run.research_simulation_run_id)
    if simulation_run is None:
        raise AgentInteractionUnavailableError("Agent Interaction simulation run is unavailable")
    report = await get_research_run_report(
        session,
        simulation_run.research_project_id,
        run.research_simulation_run_id,
    )
    tool_record = await session.scalar(
        select(ReportAgentEvidenceToolCallRecord).where(
            ReportAgentEvidenceToolCallRecord.run_id == run.id,
            ReportAgentEvidenceToolCallRecord.tool_name == "read_simulation_run",
            ReportAgentEvidenceToolCallRecord.target_id == run.research_simulation_run_id,
        )
    )
    if tool_record is None or tool_record.result_text is None:
        raise AgentInteractionUnavailableError(
            "Agent Interaction frozen simulation-run source is unavailable"
        )
    source_sha256 = calculate_research_run_report_source_sha256(tool_record.result_text)
    if source_sha256 != tool_record.result_sha256:
        raise RuntimeError("Agent Interaction simulation-run source failed integrity verification")
    return (
        draft,
        report.research_project.id,
        run.research_simulation_run_id,
        run.run_sha256,
        source_sha256,
    )


def _project(record: AgentInteractionRecord) -> AgentInteraction:
    citations = (
        ()
        if record.citations_json is None
        else CITATIONS_ADAPTER.validate_json(record.citations_json, strict=True)
    )
    expected = calculate_interaction_sha256(
        record.research_project_id,
        record.research_simulation_run_id,
        record.report_agent_run_sha256,
        record.report_agent_draft_sha256,
        record.source_sha256,
        record.question,
        record.parent_interaction_sha256,
        record.parent_answer_sha256,
    )
    expected_prompt = (
        ROOT_PROMPT_SCHEMA_VERSION
        if record.parent_interaction_id is None
        else FOLLOW_UP_PROMPT_SCHEMA_VERSION
    )
    if record.interaction_sha256 != expected or record.prompt_schema_version != expected_prompt:
        raise RuntimeError(f"Agent Interaction {record.id} failed input integrity verification")
    result = AgentInteraction(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        report_agent_run_id=record.report_agent_run_id,
        report_agent_run_sha256=record.report_agent_run_sha256,
        report_agent_draft_id=record.report_agent_draft_id,
        report_agent_draft_sha256=record.report_agent_draft_sha256,
        source_sha256=record.source_sha256,
        question=record.question,
        interaction_sha256=record.interaction_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        parent_interaction_id=record.parent_interaction_id,
        parent_interaction_sha256=record.parent_interaction_sha256,
        parent_answer_sha256=record.parent_answer_sha256,
        conversation_depth=record.conversation_depth,
        status=record.status,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        answer_markdown=record.answer_markdown,
        citations=citations,
        answer_sha256=record.answer_sha256,
        error_code=record.error_code,
        error_message=record.error_message,
    )
    if (
        result.status == "succeeded"
        and result.answer_markdown is not None
        and result.answer_sha256
        != calculate_answer_sha256(
            result.interaction_sha256, result.answer_markdown, result.citations
        )
    ):
        raise RuntimeError(f"Agent Interaction {record.id} failed answer integrity verification")
    return result


async def _verify_projected_citations(
    session: AsyncSession,
    result: AgentInteraction,
) -> None:
    if result.status != "succeeded":
        return
    tool_record = await session.scalar(
        select(ReportAgentEvidenceToolCallRecord).where(
            ReportAgentEvidenceToolCallRecord.run_id == result.report_agent_run_id,
            ReportAgentEvidenceToolCallRecord.tool_name == "read_simulation_run",
            ReportAgentEvidenceToolCallRecord.target_id == result.research_simulation_run_id,
            ReportAgentEvidenceToolCallRecord.result_sha256 == result.source_sha256,
        )
    )
    if tool_record is None or tool_record.result_text is None:
        raise RuntimeError(f"Agent Interaction {result.id} frozen citation source is unavailable")
    if calculate_research_run_report_source_sha256(tool_record.result_text) != result.source_sha256:
        raise RuntimeError(
            f"Agent Interaction {result.id} frozen citation source failed integrity verification"
        )
    if any(
        citation.target_id != result.research_simulation_run_id
        or tool_record.result_text[citation.start_offset : citation.end_offset] != citation.quote
        for citation in result.citations
    ):
        raise RuntimeError(
            f"Agent Interaction {result.id} citations failed exact offset verification"
        )


async def enqueue_agent_interaction(
    session: AsyncSession,
    draft_id: UUID,
    request: AgentInteractionRequest,
) -> AgentInteraction:
    (
        draft,
        project_id,
        simulation_run_id,
        report_agent_run_sha,
        source_sha,
    ) = await _load_native_scope(session, draft_id)
    if draft.draft_sha256 is None:
        raise RuntimeError("succeeded ReportAgent draft is missing its digest")
    parent: AgentInteractionRecord | None = None
    if request.parent_interaction_id is not None:
        parent = await session.get(AgentInteractionRecord, request.parent_interaction_id)
        if parent is None:
            raise AgentInteractionNotFoundError(
                f"succeeded parent Agent Interaction {request.parent_interaction_id} was not found"
            )
        if parent.report_agent_draft_id != draft_id or parent.status != "succeeded":
            raise AgentInteractionUnavailableError(
                "a follow-up requires a succeeded parent from the same ReportAgent report"
            )
        if parent.conversation_depth >= 4 or parent.answer_sha256 is None:
            raise AgentInteractionUnavailableError(
                "Agent Interaction conversation depth is limited to 4 follow-ups"
            )
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeat = await session.scalar(
        select(SimulationWorkerHeartbeatRecord)
        .where(
            SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
            SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
            SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
            SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
            SimulationWorkerHeartbeatRecord.worker_domain == "report",
            SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
            SimulationWorkerHeartbeatRecord.semantic_prompt_schema_version == PROMPT_SCHEMA_VERSION,
            SimulationWorkerHeartbeatRecord.semantic_model_name == draft.model_name,
            SimulationWorkerHeartbeatRecord.semantic_config_sha256 == draft.semantic_config_sha256,
        )
        .order_by(SimulationWorkerHeartbeatRecord.last_seen_at.desc())
        .limit(1)
    )
    if heartbeat is None:
        raise AgentInteractionUnavailableError(
            "Agent Interaction requires a live report worker matching the ReportAgent model"
        )
    parent_interaction_sha = None if parent is None else parent.interaction_sha256
    parent_answer_sha = None if parent is None else parent.answer_sha256
    digest = calculate_interaction_sha256(
        project_id,
        simulation_run_id,
        report_agent_run_sha,
        draft.draft_sha256,
        source_sha,
        request.question,
        parent_interaction_sha,
        parent_answer_sha,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(AgentInteractionRecord).where(AgentInteractionRecord.interaction_sha256 == digest)
    )
    if existing is not None:
        return _project(existing)
    record = AgentInteractionRecord(
        id=uuid4(),
        research_project_id=project_id,
        research_simulation_run_id=simulation_run_id,
        report_agent_run_id=draft.run_id,
        report_agent_run_sha256=report_agent_run_sha,
        report_agent_draft_id=draft.id,
        report_agent_draft_sha256=draft.draft_sha256,
        source_sha256=source_sha,
        question=request.question,
        interaction_sha256=digest,
        model_name=draft.model_name,
        semantic_config_sha256=draft.semantic_config_sha256,
        prompt_schema_version=(
            ROOT_PROMPT_SCHEMA_VERSION if parent is None else FOLLOW_UP_PROMPT_SCHEMA_VERSION
        ),
        parent_interaction_id=None if parent is None else parent.id,
        parent_interaction_sha256=parent_interaction_sha,
        parent_answer_sha256=parent_answer_sha,
        conversation_depth=0 if parent is None else parent.conversation_depth + 1,
        status="queued",
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        claimed_by_worker_id=None,
        answer_markdown=None,
        citations_json=None,
        answer_sha256=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return _project(record)


async def get_agent_interaction(session: AsyncSession, interaction_id: UUID) -> AgentInteraction:
    record = await session.get(AgentInteractionRecord, interaction_id)
    if record is None:
        raise AgentInteractionNotFoundError(f"Agent Interaction {interaction_id} was not found")
    result = _project(record)
    await _verify_projected_citations(session, result)
    return result


async def list_agent_interactions(
    session: AsyncSession, draft_id: UUID
) -> AgentInteractionsResponse:
    await _load_native_scope(session, draft_id)
    records = tuple(
        (
            await session.scalars(
                select(AgentInteractionRecord)
                .where(AgentInteractionRecord.report_agent_draft_id == draft_id)
                .order_by(AgentInteractionRecord.created_at, AgentInteractionRecord.id)
            )
        ).all()
    )
    items = tuple(_project(record) for record in records)
    for item in items:
        await _verify_projected_citations(session, item)
    return AgentInteractionsResponse(items=items, total=len(items))


async def get_agent_interaction_context(
    session: AsyncSession, interaction_id: UUID
) -> AgentInteractionContext:
    current = await session.get(AgentInteractionRecord, interaction_id)
    if current is None:
        raise AgentInteractionNotFoundError(f"Agent Interaction {interaction_id} was not found")
    if current.status != "succeeded":
        raise AgentInteractionUnavailableError(
            "Agent Interaction context requires a succeeded current interaction"
        )
    lineage = [current]
    cursor = current
    while cursor.parent_interaction_id is not None:
        parent = await session.get(AgentInteractionRecord, cursor.parent_interaction_id)
        if parent is None:
            raise RuntimeError(f"Agent Interaction {cursor.id} references a missing parent")
        lineage.append(parent)
        cursor = parent
    lineage.reverse()
    items = tuple(_project(record) for record in lineage)
    for item in items:
        await _verify_projected_citations(session, item)
    return AgentInteractionContext(
        root_interaction_id=lineage[0].id,
        items=items,
    )


__all__ = [
    "enqueue_agent_interaction",
    "get_agent_interaction",
    "get_agent_interaction_context",
    "list_agent_interactions",
]
