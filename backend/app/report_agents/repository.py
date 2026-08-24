"""Immutable run creation and audited read-only tools over one sealed snapshot."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.evidence.errors import EvidenceBundleItemNotFoundError, EvidenceBundleNotFoundError
from app.evidence.repository import (
    get_evidence_bundle,
    get_evidence_bundle_content,
    get_evidence_bundle_policy_content,
)
from app.report_agents.contracts import (
    ReportAgentCitedDraft,
    ReportAgentDraftSection,
    ReportAgentDraftsResponse,
    ReportAgentEvidenceDirectoryResult,
    ReportAgentMediaReadResult,
    ReportAgentPlanSection,
    ReportAgentPolicyReadResult,
    ReportAgentRun,
    ReportAgentRunRequest,
    ReportAgentToolCall,
    ReportAgentToolName,
)
from app.report_agents.errors import (
    ReportAgentDraftNotFoundError,
    ReportAgentDraftRetryError,
    ReportAgentDraftUnavailableError,
    ReportAgentRunNotFoundError,
    ReportAgentScopeError,
    ReportAgentToolBudgetExhaustedError,
)
from app.report_agents.hashing import (
    DRAFT_PROMPT_SCHEMA_VERSION,
    RESEARCH_RUN_SCHEMA_VERSION,
    RESEARCH_RUN_V2_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    calculate_report_agent_draft_input_sha256,
    calculate_report_agent_draft_sha256,
    calculate_report_agent_evidence_calls_sha256,
    calculate_report_agent_run_sha256,
    calculate_report_agent_tool_call_sha256,
    calculate_report_agent_tool_input_sha256,
    calculate_research_run_report_agent_sha256,
    calculate_research_run_report_agent_v2_sha256,
    serialize_outline,
)
from app.report_agents.models import (
    ReportAgentCitedDraftRecord,
    ReportAgentEvidenceRunRecord,
    ReportAgentEvidenceToolCallRecord,
)
from app.report_agents.research_sources import (
    ResearchReportSource,
    render_graph_source,
    render_interviews_source,
    render_run_source,
    render_snapshot_source,
)
from app.research_interviews.repository import list_research_persona_interviews
from app.research_projects.hashing import calculate_research_run_report_source_sha256
from app.research_projects.repository import get_research_run_report
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord
from app.world_graphs.repository import get_semantic_world_graph

OUTLINE_ADAPTER = TypeAdapter(tuple[ReportAgentPlanSection, ...])
DRAFT_SECTIONS_ADAPTER = TypeAdapter(tuple[ReportAgentDraftSection, ...])


def _project_tool_call(
    record: ReportAgentEvidenceToolCallRecord,
    run_sha256: str,
) -> ReportAgentToolCall:
    expected_input = calculate_report_agent_tool_input_sha256(
        run_sha256,
        record.position,
        record.tool_name,
        record.target_id,
    )
    expected_call = calculate_report_agent_tool_call_sha256(
        expected_input,
        record.result_sha256,
    )
    if record.input_sha256 != expected_input or record.call_sha256 != expected_call:
        raise RuntimeError(f"ReportAgent tool call {record.id} failed integrity verification")
    return ReportAgentToolCall(
        id=record.id,
        run_id=record.run_id,
        position=record.position,
        tool_name=record.tool_name,
        target_id=record.target_id,
        input_sha256=record.input_sha256,
        result_sha256=record.result_sha256,
        call_sha256=record.call_sha256,
        created_at=record.created_at,
    )


async def _project_run(
    session: AsyncSession,
    record: ReportAgentEvidenceRunRecord,
) -> ReportAgentRun:
    outline = OUTLINE_ADAPTER.validate_json(record.outline_json, strict=True)
    if record.schema_version == RUN_SCHEMA_VERSION:
        expected_run_sha256 = calculate_report_agent_run_sha256(
            record.world_model_id,
            record.world_snapshot_id,
            record.snapshot_sha256,
            record.objective,
            outline,
            record.max_tool_calls,
        )
        research_simulation_run_id = None
        research_run_report_sha256 = None
    elif (
        record.schema_version in (RESEARCH_RUN_SCHEMA_VERSION, RESEARCH_RUN_V2_SCHEMA_VERSION)
        and record.research_simulation_run_id is not None
        and record.research_run_report_sha256 is not None
    ):
        calculate_digest = (
            calculate_research_run_report_agent_v2_sha256
            if record.schema_version == RESEARCH_RUN_V2_SCHEMA_VERSION
            else calculate_research_run_report_agent_sha256
        )
        expected_run_sha256 = calculate_digest(
            record.world_model_id,
            record.world_snapshot_id,
            record.snapshot_sha256,
            record.research_simulation_run_id,
            record.research_run_report_sha256,
            record.objective,
            outline,
            record.max_tool_calls,
        )
        research_simulation_run_id = record.research_simulation_run_id
        research_run_report_sha256 = record.research_run_report_sha256
    else:
        raise RuntimeError(f"ReportAgent evidence run {record.id} has an invalid scope shape")
    if record.run_sha256 != expected_run_sha256:
        raise RuntimeError(f"ReportAgent evidence run {record.id} failed integrity verification")
    call_records = tuple(
        (
            await session.scalars(
                select(ReportAgentEvidenceToolCallRecord)
                .where(ReportAgentEvidenceToolCallRecord.run_id == record.id)
                .order_by(ReportAgentEvidenceToolCallRecord.position)
            )
        ).all()
    )
    calls = tuple(_project_tool_call(call, record.run_sha256) for call in call_records)
    return ReportAgentRun(
        id=record.id,
        world_model_id=record.world_model_id,
        world_snapshot_id=record.world_snapshot_id,
        snapshot_sha256=record.snapshot_sha256,
        objective=record.objective,
        outline=outline,
        max_tool_calls=record.max_tool_calls,
        schema_version=record.schema_version,
        research_simulation_run_id=research_simulation_run_id,
        research_run_report_sha256=research_run_report_sha256,
        run_sha256=record.run_sha256,
        created_at=record.created_at,
        tool_calls=calls,
        tool_call_count=len(calls),
        remaining_tool_calls=record.max_tool_calls - len(calls),
    )


async def create_report_agent_run(
    session: AsyncSession,
    request: ReportAgentRunRequest,
) -> ReportAgentRun:
    try:
        bundle = await get_evidence_bundle(session, request.world_snapshot_id)
    except EvidenceBundleNotFoundError as error:
        raise ReportAgentScopeError(str(error)) from error
    if (
        bundle.world_model_id != request.world_model_id
        or bundle.snapshot_sha256 != request.snapshot_sha256
    ):
        raise ReportAgentScopeError(
            "ReportAgent run must bind the exact world model and sealed snapshot digest"
        )
    run_sha256 = calculate_report_agent_run_sha256(
        request.world_model_id,
        request.world_snapshot_id,
        request.snapshot_sha256,
        request.objective,
        request.outline,
        request.max_tool_calls,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": run_sha256},
    )
    existing = await session.scalar(
        select(ReportAgentEvidenceRunRecord).where(
            ReportAgentEvidenceRunRecord.run_sha256 == run_sha256
        )
    )
    if existing is not None:
        return await _project_run(session, existing)
    record = ReportAgentEvidenceRunRecord(
        id=uuid4(),
        world_model_id=request.world_model_id,
        world_snapshot_id=request.world_snapshot_id,
        snapshot_sha256=request.snapshot_sha256,
        research_simulation_run_id=None,
        research_run_report_sha256=None,
        objective=request.objective,
        outline_json=serialize_outline(request.outline),
        max_tool_calls=request.max_tool_calls,
        schema_version=RUN_SCHEMA_VERSION,
        run_sha256=run_sha256,
        created_at=datetime.now(UTC),
    )
    session.add(record)
    await session.commit()
    return await _project_run(session, record)


async def create_research_run_report_agent(
    session: AsyncSession,
    project_id: UUID,
    research_simulation_run_id: UUID,
) -> ReportAgentRun:
    """Create one idempotent multi-source scope over a sealed SandOwl run."""
    report = await get_research_run_report(session, project_id, research_simulation_run_id)
    bundle = await get_evidence_bundle(session, report.research_project.snapshot.world_snapshot_id)
    if bundle.snapshot_sha256 != report.research_project.snapshot.snapshot_sha256:
        raise RuntimeError("research report snapshot digest drifted before ReportAgent creation")
    sources: list[ResearchReportSource] = [render_snapshot_source(bundle)]
    graph_ref = report.research_project.graph
    if graph_ref is not None:
        graph = await get_semantic_world_graph(session, graph_ref.graph_id)
        if graph.graph_sha256 != graph_ref.graph_sha256:
            raise RuntimeError("research report graph digest drifted before ReportAgent creation")
        sources.append(render_graph_source(graph))
    sources.append(render_run_source(report))
    interviews = await list_research_persona_interviews(
        session, project_id, research_simulation_run_id
    )
    interview_source = render_interviews_source(research_simulation_run_id, interviews.items)
    if interview_source is not None:
        sources.append(interview_source)
    outline = (
        ReportAgentPlanSection(
            position=0,
            title="先看结论",
            focus="用普通读者可理解的语言概括本次单次合成观察，不夸大其意义。",
        ),
        ReportAgentPlanSection(
            position=1,
            title="现实背景与研究边界",
            focus="区分冻结媒体或政策证据、语义图整理结果与后续合成内容。",
        ),
        ReportAgentPlanSection(
            position=2,
            title="本次模拟是怎么进行的",
            focus="准确说明合成人群、起始内容、编排、轮次与观察范围。",
        ),
        ReportAgentPlanSection(
            position=3,
            title="观察到了什么",
            focus="按事件与逐轮记忆归纳本次动作，并明确哪些内容由实验预置。",
        ),
        ReportAgentPlanSection(
            position=4,
            title="Persona 视角与未解问题",
            focus=(
                "结合用户明确发起并已成功的运行后 Persona 追问，整理分歧与未解问题。"
                if interview_source is not None
                else "说明当前没有获授权的运行后 Persona 追问，不虚构人物解释。"
            ),
        ),
        ReportAgentPlanSection(
            position=5,
            title="如何使用这份观察",
            focus="给出可继续验证的问题和明确限制，不提供现实预测、商业建议或方案排名。",
        ),
    )
    objective = "把冻结现实证据、语义图、单次模拟和获授权 Persona 追问整理为用户可读报告。"
    max_tool_calls = len(sources)
    run_sha256 = calculate_research_run_report_agent_v2_sha256(
        report.research_project.snapshot.world_model_id,
        report.research_project.snapshot.world_snapshot_id,
        report.research_project.snapshot.snapshot_sha256,
        research_simulation_run_id,
        report.report_sha256,
        objective,
        outline,
        max_tool_calls,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": run_sha256},
    )
    record = await session.scalar(
        select(ReportAgentEvidenceRunRecord).where(
            ReportAgentEvidenceRunRecord.run_sha256 == run_sha256
        )
    )
    if record is None:
        record = ReportAgentEvidenceRunRecord(
            id=uuid4(),
            world_model_id=report.research_project.snapshot.world_model_id,
            world_snapshot_id=report.research_project.snapshot.world_snapshot_id,
            snapshot_sha256=report.research_project.snapshot.snapshot_sha256,
            research_simulation_run_id=research_simulation_run_id,
            research_run_report_sha256=report.report_sha256,
            objective=objective,
            outline_json=serialize_outline(outline),
            max_tool_calls=max_tool_calls,
            schema_version=RESEARCH_RUN_V2_SCHEMA_VERSION,
            run_sha256=run_sha256,
            created_at=datetime.now(UTC),
        )
        session.add(record)
        await session.flush()
        for position, source in enumerate(sources):
            input_sha256 = calculate_report_agent_tool_input_sha256(
                run_sha256,
                position,
                source.tool_name,
                source.target_id,
            )
            session.add(
                ReportAgentEvidenceToolCallRecord(
                    id=uuid4(),
                    run_id=record.id,
                    position=position,
                    tool_name=source.tool_name,
                    target_id=source.target_id,
                    input_sha256=input_sha256,
                    result_sha256=source.sha256,
                    result_text=source.text,
                    call_sha256=calculate_report_agent_tool_call_sha256(
                        input_sha256, source.sha256
                    ),
                    created_at=datetime.now(UTC),
                )
            )
        await session.commit()
    return await _project_run(session, record)


async def get_report_agent_run(session: AsyncSession, run_id: UUID) -> ReportAgentRun:
    record = await session.get(ReportAgentEvidenceRunRecord, run_id)
    if record is None:
        raise ReportAgentRunNotFoundError(f"ReportAgent evidence run {run_id} was not found")
    return await _project_run(session, record)


async def find_research_run_report_agent(
    session: AsyncSession,
    research_simulation_run_id: UUID,
) -> ReportAgentRun | None:
    """Return the existing native ReportAgent scope without creating one."""
    record = await session.scalar(
        select(ReportAgentEvidenceRunRecord).where(
            ReportAgentEvidenceRunRecord.research_simulation_run_id == research_simulation_run_id,
            ReportAgentEvidenceRunRecord.schema_version == RESEARCH_RUN_V2_SCHEMA_VERSION,
        )
    )
    return None if record is None else await _project_run(session, record)


def _evidence_calls(run: ReportAgentRun) -> tuple[ReportAgentToolCall, ...]:
    return tuple(
        call
        for call in run.tool_calls
        if call.tool_name
        in (
            "read_media",
            "read_policy",
            "read_world_snapshot",
            "read_world_graph",
            "read_simulation_run",
            "read_persona_interviews",
        )
    )


async def _verify_draft_citations(
    session: AsyncSession,
    run: ReportAgentRun,
    evidence_calls: tuple[ReportAgentToolCall, ...],
    sections: tuple[ReportAgentDraftSection, ...],
) -> None:
    calls_by_position = {call.position: call for call in evidence_calls}
    content_by_position: dict[int, str] = {}
    for section in sections:
        for citation in section.citations:
            call = calls_by_position.get(citation.tool_call_position)
            if call is None or call.target_id != citation.target_id:
                raise RuntimeError(
                    "ReportAgent draft citation does not match frozen evidence calls"
                )
            expected_kind = {
                "read_media": "media_article",
                "read_policy": "policy_document",
                "read_world_snapshot": "world_snapshot",
                "read_world_graph": "world_graph",
                "read_simulation_run": "simulation_run",
                "read_persona_interviews": "persona_interviews",
            }.get(call.tool_name)
            if citation.evidence_kind != expected_kind:
                raise RuntimeError(
                    "ReportAgent draft citation kind does not match its evidence call"
                )
            captured_text = content_by_position.get(call.position)
            if captured_text is None:
                if call.tool_name == "read_media":
                    content = await get_evidence_bundle_content(
                        session, run.world_snapshot_id, citation.target_id
                    )
                    captured_text = content.captured_text
                elif call.tool_name == "read_policy":
                    policy_content = await get_evidence_bundle_policy_content(
                        session, run.world_snapshot_id, citation.target_id
                    )
                    captured_text = policy_content.captured_text
                else:
                    tool_record = await session.get(ReportAgentEvidenceToolCallRecord, call.id)
                    if tool_record is None or tool_record.result_text is None:
                        raise RuntimeError("ReportAgent frozen research source is unavailable")
                    captured_text = tool_record.result_text
                    if (
                        calculate_research_run_report_source_sha256(captured_text)
                        != call.result_sha256
                    ):
                        raise RuntimeError(
                            "ReportAgent frozen research source failed digest verification"
                        )
                content_by_position[call.position] = captured_text
            if captured_text[citation.start_offset : citation.end_offset] != citation.quote:
                raise RuntimeError(
                    "ReportAgent draft citation quote failed exact offset verification"
                )


async def _project_draft(
    session: AsyncSession,
    record: ReportAgentCitedDraftRecord,
) -> ReportAgentCitedDraft:
    run = await get_report_agent_run(session, record.run_id)
    evidence_calls = _evidence_calls(run)[: record.evidence_call_count]
    if len(evidence_calls) != record.evidence_call_count:
        raise RuntimeError(f"ReportAgent cited draft {record.id} evidence prefix is unavailable")
    evidence_calls_sha256 = calculate_report_agent_evidence_calls_sha256(
        tuple(call.call_sha256 for call in evidence_calls)
    )
    expected_input = calculate_report_agent_draft_input_sha256(
        run.run_sha256,
        evidence_calls_sha256,
        record.model_name,
        record.semantic_config_sha256,
    )
    if (
        record.run_sha256 != run.run_sha256
        or record.evidence_calls_sha256 != evidence_calls_sha256
        or record.input_sha256 != expected_input
        or record.prompt_schema_version != DRAFT_PROMPT_SCHEMA_VERSION
    ):
        raise RuntimeError(f"ReportAgent cited draft {record.id} failed input verification")
    sections = (
        ()
        if record.sections_json is None
        else DRAFT_SECTIONS_ADAPTER.validate_json(record.sections_json, strict=True)
    )
    if record.status == "succeeded":
        if tuple((section.position, section.title) for section in sections) != tuple(
            (section.position, section.title) for section in run.outline
        ):
            raise RuntimeError(
                f"ReportAgent cited draft {record.id} does not match its frozen outline"
            )
        await _verify_draft_citations(session, run, evidence_calls, sections)
        expected_draft = calculate_report_agent_draft_sha256(
            record.input_sha256, record.title or "", sections
        )
        if record.draft_sha256 != expected_draft:
            raise RuntimeError(f"ReportAgent cited draft {record.id} failed output verification")
    return ReportAgentCitedDraft(
        id=record.id,
        run_id=record.run_id,
        run_sha256=record.run_sha256,
        evidence_call_count=record.evidence_call_count,
        evidence_calls_sha256=record.evidence_calls_sha256,
        input_sha256=record.input_sha256,
        retry_of_draft_id=record.retry_of_draft_id,
        retry_of_input_sha256=record.retry_of_input_sha256,
        attempt_number=record.attempt_number,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=record.prompt_schema_version,
        status=record.status,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        title=record.title,
        sections=sections,
        draft_sha256=record.draft_sha256,
        error_code=record.error_code,
        error_message=record.error_message,
    )


async def enqueue_report_agent_draft(
    session: AsyncSession,
    run_id: UUID,
) -> ReportAgentCitedDraft:
    run = await get_report_agent_run(session, run_id)
    evidence_calls = _evidence_calls(run)
    if not evidence_calls:
        raise ReportAgentDraftUnavailableError(
            "ReportAgent cited drafts require at least one audited media or Policy read"
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
        )
        .order_by(SimulationWorkerHeartbeatRecord.last_seen_at.desc())
        .limit(1)
    )
    if (
        heartbeat is None
        or heartbeat.semantic_model_name is None
        or heartbeat.semantic_config_sha256 is None
    ):
        raise ReportAgentDraftUnavailableError(
            "ReportAgent cited drafts require a live report-domain model worker"
        )
    evidence_calls_sha256 = calculate_report_agent_evidence_calls_sha256(
        tuple(call.call_sha256 for call in evidence_calls)
    )
    input_sha256 = calculate_report_agent_draft_input_sha256(
        run.run_sha256,
        evidence_calls_sha256,
        heartbeat.semantic_model_name,
        heartbeat.semantic_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": input_sha256},
    )
    existing = await session.scalar(
        select(ReportAgentCitedDraftRecord).where(
            ReportAgentCitedDraftRecord.input_sha256 == input_sha256,
            ReportAgentCitedDraftRecord.attempt_number == 1,
        )
    )
    if existing is not None:
        return await _project_draft(session, existing)
    record = ReportAgentCitedDraftRecord(
        id=uuid4(),
        run_id=run.id,
        run_sha256=run.run_sha256,
        evidence_call_count=len(evidence_calls),
        evidence_calls_sha256=evidence_calls_sha256,
        input_sha256=input_sha256,
        retry_of_draft_id=None,
        retry_of_input_sha256=None,
        attempt_number=1,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=DRAFT_PROMPT_SCHEMA_VERSION,
        status="queued",
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        claimed_by_worker_id=None,
        title=None,
        sections_json=None,
        draft_sha256=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return await _project_draft(session, record)


async def retry_report_agent_draft(
    session: AsyncSession,
    draft_id: UUID,
) -> ReportAgentCitedDraft:
    """Append one immutable retry attempt after an explicitly failed draft."""
    parent = await session.scalar(
        select(ReportAgentCitedDraftRecord)
        .where(ReportAgentCitedDraftRecord.id == draft_id)
        .with_for_update()
    )
    if parent is None:
        raise ReportAgentDraftNotFoundError(f"ReportAgent cited draft {draft_id} was not found")
    existing = await session.scalar(
        select(ReportAgentCitedDraftRecord).where(
            ReportAgentCitedDraftRecord.retry_of_draft_id == parent.id
        )
    )
    if existing is not None:
        return await _project_draft(session, existing)
    if parent.status != "failed":
        raise ReportAgentDraftRetryError(
            f"ReportAgent cited draft {draft_id} must be failed before retry"
        )
    if parent.attempt_number >= 5:
        raise ReportAgentDraftRetryError(
            f"ReportAgent cited draft {draft_id} exhausted its five-attempt limit"
        )
    record = ReportAgentCitedDraftRecord(
        id=uuid4(),
        run_id=parent.run_id,
        run_sha256=parent.run_sha256,
        evidence_call_count=parent.evidence_call_count,
        evidence_calls_sha256=parent.evidence_calls_sha256,
        input_sha256=parent.input_sha256,
        retry_of_draft_id=parent.id,
        retry_of_input_sha256=parent.input_sha256,
        attempt_number=parent.attempt_number + 1,
        model_name=parent.model_name,
        semantic_config_sha256=parent.semantic_config_sha256,
        prompt_schema_version=parent.prompt_schema_version,
        status="queued",
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
        claimed_by_worker_id=None,
        title=None,
        sections_json=None,
        draft_sha256=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.commit()
    return await _project_draft(session, record)


async def get_report_agent_draft(
    session: AsyncSession,
    draft_id: UUID,
) -> ReportAgentCitedDraft:
    record = await session.get(ReportAgentCitedDraftRecord, draft_id)
    if record is None:
        raise ReportAgentDraftNotFoundError(f"ReportAgent cited draft {draft_id} was not found")
    return await _project_draft(session, record)


async def list_report_agent_drafts(
    session: AsyncSession,
    run_id: UUID,
) -> ReportAgentDraftsResponse:
    await get_report_agent_run(session, run_id)
    records = tuple(
        (
            await session.scalars(
                select(ReportAgentCitedDraftRecord)
                .where(ReportAgentCitedDraftRecord.run_id == run_id)
                .order_by(ReportAgentCitedDraftRecord.created_at, ReportAgentCitedDraftRecord.id)
            )
        ).all()
    )
    items = tuple([await _project_draft(session, record) for record in records])
    return ReportAgentDraftsResponse(items=items, total=len(items))


def _require_remaining_tool_budget(run: ReportAgentRun) -> None:
    if run.remaining_tool_calls == 0:
        raise ReportAgentToolBudgetExhaustedError(
            f"ReportAgent evidence run {run.id} exhausted its {run.max_tool_calls} tool-call budget"
        )


async def _append_tool_call(
    session: AsyncSession,
    run_id: UUID,
    tool_name: ReportAgentToolName,
    target_id: UUID | None,
    result_sha256: str,
    result_text: str | None = None,
) -> ReportAgentRun:
    record = await session.scalar(
        select(ReportAgentEvidenceRunRecord)
        .where(ReportAgentEvidenceRunRecord.id == run_id)
        .with_for_update()
    )
    if record is None:
        raise ReportAgentRunNotFoundError(f"ReportAgent evidence run {run_id} was not found")
    position = int(
        await session.scalar(
            select(func.count(ReportAgentEvidenceToolCallRecord.id)).where(
                ReportAgentEvidenceToolCallRecord.run_id == run_id
            )
        )
        or 0
    )
    if position >= record.max_tool_calls:
        raise ReportAgentToolBudgetExhaustedError(
            f"ReportAgent evidence run {run_id} exhausted its "
            f"{record.max_tool_calls} tool-call budget"
        )
    input_sha256 = calculate_report_agent_tool_input_sha256(
        record.run_sha256,
        position,
        tool_name,
        target_id,
    )
    call_sha256 = calculate_report_agent_tool_call_sha256(input_sha256, result_sha256)
    session.add(
        ReportAgentEvidenceToolCallRecord(
            id=uuid4(),
            run_id=run_id,
            position=position,
            tool_name=tool_name,
            target_id=target_id,
            input_sha256=input_sha256,
            result_sha256=result_sha256,
            result_text=result_text,
            call_sha256=call_sha256,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return await _project_run(session, record)


async def list_report_agent_evidence(
    session: AsyncSession,
    run_id: UUID,
) -> ReportAgentEvidenceDirectoryResult:
    run = await get_report_agent_run(session, run_id)
    _require_remaining_tool_budget(run)
    bundle = await get_evidence_bundle(session, run.world_snapshot_id)
    if bundle.snapshot_sha256 != run.snapshot_sha256:
        raise ReportAgentScopeError(f"ReportAgent evidence run {run_id} snapshot digest drifted")
    updated_run = await _append_tool_call(
        session,
        run_id,
        "list_evidence",
        None,
        bundle.snapshot_sha256,
    )
    return ReportAgentEvidenceDirectoryResult(run=updated_run, bundle=bundle)


async def read_report_agent_media(
    session: AsyncSession,
    run_id: UUID,
    article_id: UUID,
) -> ReportAgentMediaReadResult:
    run = await get_report_agent_run(session, run_id)
    _require_remaining_tool_budget(run)
    try:
        content = await get_evidence_bundle_content(session, run.world_snapshot_id, article_id)
    except (EvidenceBundleNotFoundError, EvidenceBundleItemNotFoundError) as error:
        raise ReportAgentScopeError(str(error)) from error
    updated_run = await _append_tool_call(
        session,
        run_id,
        "read_media",
        article_id,
        content.captured_text_sha256,
    )
    return ReportAgentMediaReadResult(run=updated_run, content=content)


async def read_report_agent_policy(
    session: AsyncSession,
    run_id: UUID,
    policy_version_id: UUID,
) -> ReportAgentPolicyReadResult:
    run = await get_report_agent_run(session, run_id)
    _require_remaining_tool_budget(run)
    try:
        content = await get_evidence_bundle_policy_content(
            session,
            run.world_snapshot_id,
            policy_version_id,
        )
    except (EvidenceBundleNotFoundError, EvidenceBundleItemNotFoundError) as error:
        raise ReportAgentScopeError(str(error)) from error
    updated_run = await _append_tool_call(
        session,
        run_id,
        "read_policy",
        policy_version_id,
        content.content_sha256,
    )
    return ReportAgentPolicyReadResult(run=updated_run, content=content)


__all__ = [
    "create_report_agent_run",
    "create_research_run_report_agent",
    "find_research_run_report_agent",
    "enqueue_report_agent_draft",
    "get_report_agent_draft",
    "get_report_agent_run",
    "list_report_agent_drafts",
    "list_report_agent_evidence",
    "read_report_agent_media",
    "read_report_agent_policy",
    "retry_report_agent_draft",
]
