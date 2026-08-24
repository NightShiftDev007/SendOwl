"""Queue, list, and verify interviews over one frozen research run."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.contracts import CohortDetail, CohortMember
from app.populations.errors import PopulationCohortNotFoundError
from app.populations.repository import get_cohort
from app.research_interviews.contracts import (
    ResearchInterviewCitation,
    ResearchInterviewPersona,
    ResearchPersonaInterview,
    ResearchPersonaInterviewRequest,
    ResearchPersonaInterviewSession,
    ResearchPersonaInterviewSessionRequest,
    ResearchPersonaInterviewSessionsResponse,
    ResearchPersonaInterviewsResponse,
)
from app.research_interviews.errors import (
    ResearchInterviewNotFoundError,
    ResearchInterviewUnavailableError,
)
from app.research_interviews.hashing import (
    calculate_answer_sha256,
    calculate_interview_sha256,
    calculate_session_sha256,
    calculate_source_sha256,
)
from app.research_interviews.models import (
    ResearchPersonaInterviewRecord,
    ResearchPersonaInterviewSessionMemberRecord,
    ResearchPersonaInterviewSessionRecord,
)
from app.research_projects.contracts import ResearchRunReport
from app.research_projects.errors import ResearchSimulationRunNotFoundError
from app.research_projects.repository import get_research_run_report
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

INTERVIEW_SCHEMA_VERSION = "sandowl-run-persona-interview/v1"
SESSION_SCHEMA_VERSION = "sandowl-run-persona-interview-session/v1"
CITATIONS_ADAPTER = TypeAdapter(tuple[ResearchInterviewCitation, ...])


def _render_source(report: ResearchRunReport) -> str:
    """Render a stable, readable source that contains only frozen run facts."""
    run = report.run
    lines = [
        "# SandOwl 冻结运行世界",
        f"研究项目：{report.research_project.title}",
        f"研究问题：{report.research_project.research_question}",
        f"模拟要求：{run.simulation_requirement}",
        f"随机种子：{run.seed}",
        f"运行轮次：{run.rounds}",
        "",
        "## 人工设定的合成事件",
    ]
    if run.simulation_plan is None:
        lines.append(f"第 0 分钟：{run.initial_post}")
    else:
        lines.extend(
            f"第 {item.offset_minutes} 分钟：{item.content}"
            for item in run.simulation_plan.scheduled_posts
        )
    lines.extend(("", "## 已记录事件"))
    for event in report.events:
        actor = "实验预置" if event.actor_kind == "scenario" else f"Persona {event.persona_id}"
        content = "" if event.content is None else f"；内容：{event.content}"
        target = "" if event.target_post_id is None else f"；目标帖子：{event.target_post_id}"
        lines.append(
            f"事件 #{event.sequence}；第 {event.round} 轮；{actor}；"
            f"动作：{event.action_type}{target}{content}"
        )
    lines.extend(("", "## 逐轮图记忆"))
    for memory in report.graph_memory:
        lines.append(
            f"第 {memory.round} 轮图记忆：累计 {memory.cumulative_event_count} 个事件，"
            f"{len(memory.nodes)} 个节点，{len(memory.edges)} 条关系；"
            f"哈希 {memory.memory_sha256}"
        )
    lines.extend(
        (
            "",
            "## 解释边界",
            "这是一份合成模拟记录，不是现实用户访谈、现实预测、商业建议或方案比较。",
        )
    )
    return "\n".join(lines)


def _project(record: ResearchPersonaInterviewRecord) -> ResearchPersonaInterview:
    citations = (
        ()
        if record.citations_json is None
        else CITATIONS_ADAPTER.validate_json(record.citations_json, strict=True)
    )
    if calculate_source_sha256(record.source_text) != record.source_sha256:
        raise RuntimeError(f"research interview {record.id} source integrity mismatch")
    expected = calculate_interview_sha256(
        record.run_spec_sha256,
        record.graph_memory_sha256,
        record.cohort_sha256,
        str(record.persona_id),
        record.persona_profile_sha256,
        record.question,
        record.source_sha256,
        record.semantic_config_sha256,
    )
    if expected != record.interview_sha256:
        raise RuntimeError(f"research interview {record.id} input integrity mismatch")
    result = ResearchPersonaInterview(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        run_spec_sha256=record.run_spec_sha256,
        graph_memory_sha256=record.graph_memory_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        persona=ResearchInterviewPersona(
            id=record.persona_id,
            position=record.persona_position,
            persona_id=record.persona_external_id,
            display_name=record.persona_display_name,
            profile_sha256=record.persona_profile_sha256,
        ),
        question=record.question,
        source_sha256=record.source_sha256,
        interview_sha256=record.interview_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_SCHEMA_VERSION,
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
    if result.status == "succeeded":
        expected_answer = calculate_answer_sha256(
            result.interview_sha256,
            result.answer_markdown or "",
            result.citations,
        )
        if expected_answer != result.answer_sha256:
            raise RuntimeError(f"research interview {record.id} answer integrity mismatch")
        if any(
            item.target_id != result.research_simulation_run_id
            or record.source_text[item.start_offset : item.end_offset] != item.quote
            for item in result.citations
        ):
            raise RuntimeError(f"research interview {record.id} citation integrity mismatch")
    return result


async def _load_context(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> tuple[
    ResearchRunReport,
    CohortDetail,
    SimulationWorkerHeartbeatRecord,
    str,
    str,
]:
    try:
        report = await get_research_run_report(session, project_id, run_id)
    except ResearchSimulationRunNotFoundError:
        raise
    if (
        report.run.status != "succeeded"
        or report.run.schema_version != "sandowl-research-simulation-run/v4"
    ):
        raise ResearchInterviewUnavailableError(
            "运行世界访谈只支持带自动编排与图记忆的已完成原生运行"
        )
    if not report.graph_memory:
        raise ResearchInterviewUnavailableError("运行世界访谈需要至少一轮已封存图记忆")
    try:
        cohort = await get_cohort(session, report.run.cohort.cohort_id)
    except PopulationCohortNotFoundError as error:
        raise RuntimeError(f"research run {run_id} references a missing cohort") from error
    if cohort.cohort_sha256 != report.run.cohort.cohort_sha256:
        raise RuntimeError(f"research run {run_id} cohort integrity mismatch")
    if report.run.model_name is None or report.run.semantic_config_sha256 is None:
        raise RuntimeError(f"research run {run_id} model identity is incomplete")
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
            SimulationWorkerHeartbeatRecord.semantic_model_name == report.run.model_name,
        )
        .order_by(SimulationWorkerHeartbeatRecord.last_seen_at.desc())
        .limit(1)
    )
    if heartbeat is None:
        raise ResearchInterviewUnavailableError(
            "运行世界访谈需要与该运行模型配置一致的 report worker"
        )
    source_text = _render_source(report)
    if len(source_text) > 80_000:
        raise RuntimeError(f"research run {run_id} interview source exceeds its contract")
    return (
        report,
        cohort,
        heartbeat,
        source_text,
        calculate_source_sha256(source_text),
    )


def _require_member(cohort: CohortDetail, persona_id: UUID) -> CohortMember:
    member = next((item for item in cohort.members if item.persona.id == persona_id), None)
    if member is None:
        raise ResearchInterviewNotFoundError(
            f"persona {persona_id} is not a member of cohort {cohort.id}"
        )
    if member.position > 7:
        raise ResearchInterviewUnavailableError("运行世界访谈最多支持运行中的前八名 Persona")
    return member


async def _get_or_create(
    session: AsyncSession,
    report: ResearchRunReport,
    cohort: CohortDetail,
    heartbeat: SimulationWorkerHeartbeatRecord,
    member: CohortMember,
    question: str,
    source_text: str,
    source_sha256: str,
    created_at: datetime,
) -> ResearchPersonaInterviewRecord:
    if heartbeat.semantic_model_name is None or heartbeat.semantic_config_sha256 is None:
        raise ResearchInterviewUnavailableError("report worker model identity is incomplete")
    graph_memory_sha256 = report.graph_memory[-1].memory_sha256
    digest = calculate_interview_sha256(
        report.run.run_spec_sha256,
        graph_memory_sha256,
        cohort.cohort_sha256,
        str(member.persona.id),
        member.persona.profile_sha256,
        question,
        source_sha256,
        heartbeat.semantic_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(ResearchPersonaInterviewRecord).where(
            ResearchPersonaInterviewRecord.interview_sha256 == digest
        )
    )
    if existing is not None:
        return existing
    record = ResearchPersonaInterviewRecord(
        id=uuid4(),
        research_project_id=report.research_project.id,
        research_simulation_run_id=report.run.id,
        run_spec_sha256=report.run.run_spec_sha256,
        graph_memory_sha256=graph_memory_sha256,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        persona_id=member.persona.id,
        persona_position=member.position,
        persona_external_id=member.persona.persona_id,
        persona_display_name=member.persona.display_name,
        persona_profile_sha256=member.persona.profile_sha256,
        question=question,
        source_text=source_text,
        source_sha256=source_sha256,
        interview_sha256=digest,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_SCHEMA_VERSION,
        status="queued",
        created_at=created_at,
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
    await session.flush()
    return record


async def enqueue_research_persona_interview(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    request: ResearchPersonaInterviewRequest,
) -> ResearchPersonaInterview:
    report, cohort, heartbeat, source_text, source_sha256 = await _load_context(
        session, project_id, run_id
    )
    member = _require_member(cohort, request.persona_id)
    record = await _get_or_create(
        session,
        report,
        cohort,
        heartbeat,
        member,
        request.question,
        source_text,
        source_sha256,
        datetime.now(UTC),
    )
    await session.commit()
    return _project(record)


async def list_research_persona_interviews(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchPersonaInterviewsResponse:
    await get_research_run_report(session, project_id, run_id)
    records = tuple(
        (
            await session.scalars(
                select(ResearchPersonaInterviewRecord)
                .where(
                    ResearchPersonaInterviewRecord.research_project_id == project_id,
                    ResearchPersonaInterviewRecord.research_simulation_run_id == run_id,
                )
                .order_by(
                    ResearchPersonaInterviewRecord.created_at, ResearchPersonaInterviewRecord.id
                )
            )
        ).all()
    )
    items = tuple(_project(record) for record in records)
    return ResearchPersonaInterviewsResponse(items=items, total=len(items))


def _session_status(interviews: tuple[ResearchPersonaInterview, ...]) -> str:
    statuses = tuple(item.status for item in interviews)
    if all(item == "queued" for item in statuses):
        return "queued"
    if any(item in ("queued", "running") for item in statuses):
        return "running"
    if all(item == "succeeded" for item in statuses):
        return "succeeded"
    return "failed"


async def _project_session(
    session: AsyncSession,
    record: ResearchPersonaInterviewSessionRecord,
) -> ResearchPersonaInterviewSession:
    if record.sealed_at is None:
        raise RuntimeError(f"research interview session {record.id} is not sealed")
    rows = tuple(
        (
            await session.execute(
                select(
                    ResearchPersonaInterviewSessionMemberRecord,
                    ResearchPersonaInterviewRecord,
                )
                .join(
                    ResearchPersonaInterviewRecord,
                    ResearchPersonaInterviewRecord.id
                    == ResearchPersonaInterviewSessionMemberRecord.interview_id,
                )
                .where(ResearchPersonaInterviewSessionMemberRecord.session_id == record.id)
                .order_by(ResearchPersonaInterviewSessionMemberRecord.position)
            )
        ).all()
    )
    if tuple(member.position for member, _ in rows) != tuple(range(record.persona_count)):
        raise RuntimeError(f"research interview session {record.id} members are incomplete")
    interviews = tuple(_project(interview) for _, interview in rows)
    if not interviews:
        raise RuntimeError(f"research interview session {record.id} has no interviews")
    expected = calculate_session_sha256(
        record.run_spec_sha256,
        record.graph_memory_sha256,
        record.cohort_sha256,
        tuple((str(item.persona.id), item.persona.profile_sha256) for item in interviews),
        record.question,
        interviews[0].source_sha256,
        record.semantic_config_sha256,
    )
    if expected != record.session_sha256:
        raise RuntimeError(f"research interview session {record.id} integrity mismatch")
    return ResearchPersonaInterviewSession(
        id=record.id,
        research_project_id=record.research_project_id,
        research_simulation_run_id=record.research_simulation_run_id,
        run_spec_sha256=record.run_spec_sha256,
        graph_memory_sha256=record.graph_memory_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        question=record.question,
        persona_count=record.persona_count,
        session_sha256=record.session_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=SESSION_SCHEMA_VERSION,
        status=_session_status(interviews),
        created_at=record.created_at,
        interviews=interviews,
    )


async def enqueue_research_persona_interview_session(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    request: ResearchPersonaInterviewSessionRequest,
) -> ResearchPersonaInterviewSession:
    report, cohort, heartbeat, source_text, source_sha256 = await _load_context(
        session, project_id, run_id
    )
    members = tuple(_require_member(cohort, persona_id) for persona_id in request.persona_ids)
    if heartbeat.semantic_model_name is None or heartbeat.semantic_config_sha256 is None:
        raise ResearchInterviewUnavailableError("report worker model identity is incomplete")
    graph_memory_sha256 = report.graph_memory[-1].memory_sha256
    digest = calculate_session_sha256(
        report.run.run_spec_sha256,
        graph_memory_sha256,
        cohort.cohort_sha256,
        tuple((str(item.persona.id), item.persona.profile_sha256) for item in members),
        request.question,
        source_sha256,
        heartbeat.semantic_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(ResearchPersonaInterviewSessionRecord).where(
            ResearchPersonaInterviewSessionRecord.session_sha256 == digest
        )
    )
    if existing is not None:
        return await _project_session(session, existing)
    created_at = datetime.now(UTC)
    interview_records = tuple(
        [
            await _get_or_create(
                session,
                report,
                cohort,
                heartbeat,
                member,
                request.question,
                source_text,
                source_sha256,
                created_at,
            )
            for member in members
        ]
    )
    record = ResearchPersonaInterviewSessionRecord(
        id=uuid4(),
        research_project_id=project_id,
        research_simulation_run_id=run_id,
        run_spec_sha256=report.run.run_spec_sha256,
        graph_memory_sha256=graph_memory_sha256,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        question=request.question,
        persona_count=len(members),
        session_sha256=digest,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=SESSION_SCHEMA_VERSION,
        created_at=created_at,
        sealed_at=None,
    )
    session.add(record)
    await session.flush()
    session.add_all(
        tuple(
            ResearchPersonaInterviewSessionMemberRecord(
                session_id=record.id,
                position=position,
                persona_id=member.persona.id,
                interview_id=interview.id,
            )
            for position, (member, interview) in enumerate(
                zip(members, interview_records, strict=True)
            )
        )
    )
    record.sealed_at = datetime.now(UTC)
    await session.commit()
    return await _project_session(session, record)


async def list_research_persona_interview_sessions(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
) -> ResearchPersonaInterviewSessionsResponse:
    await get_research_run_report(session, project_id, run_id)
    records = tuple(
        (
            await session.scalars(
                select(ResearchPersonaInterviewSessionRecord)
                .where(
                    ResearchPersonaInterviewSessionRecord.research_project_id == project_id,
                    ResearchPersonaInterviewSessionRecord.research_simulation_run_id == run_id,
                )
                .order_by(
                    ResearchPersonaInterviewSessionRecord.created_at,
                    ResearchPersonaInterviewSessionRecord.id,
                )
            )
        ).all()
    )
    items = tuple([await _project_session(session, record) for record in records])
    return ResearchPersonaInterviewSessionsResponse(items=items, total=len(items))


async def get_research_persona_interview(
    session: AsyncSession,
    interview_id: UUID,
) -> ResearchPersonaInterview:
    record = await session.get(ResearchPersonaInterviewRecord, interview_id)
    if record is None:
        raise ResearchInterviewNotFoundError(f"research interview {interview_id} was not found")
    return _project(record)
