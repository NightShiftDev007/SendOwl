"""Queue and verify report-grounded synthetic Persona interviews."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision_reports.contracts import DecisionReport
from app.decision_reports.errors import DecisionReportNotFoundError
from app.decision_reports.repository import get_decision_report
from app.persona_interviews.contracts import (
    PersonaInterview,
    PersonaInterviewPersona,
    PersonaInterviewRequest,
    PersonaInterviewSession,
    PersonaInterviewSessionRequest,
    PersonaInterviewSessionsResponse,
    PersonaInterviewsResponse,
)
from app.persona_interviews.errors import (
    PersonaInterviewNotFoundError,
    PersonaInterviewUnavailableError,
)
from app.persona_interviews.hashing import (
    answer_sha256,
    interview_session_sha256,
    interview_sha256,
)
from app.persona_interviews.models import (
    PersonaInterviewRecord,
    PersonaInterviewSessionMemberRecord,
    PersonaInterviewSessionRecord,
)
from app.populations.contracts import CohortDetail, CohortMember
from app.populations.errors import PopulationCohortNotFoundError
from app.populations.repository import get_cohort
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.semantic_experiments.models import SemanticExperimentRecord
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord

POSITIONS_ADAPTER = TypeAdapter(tuple[int, ...])
INTERVIEW_PROMPT_SCHEMA_VERSION = "persona-report-interview/v1"
INTERVIEW_SESSION_SCHEMA_VERSION = "persona-report-interview-session/v1"


def _project(record: PersonaInterviewRecord) -> PersonaInterview:
    positions = (
        ()
        if record.cited_section_positions_json is None
        else POSITIONS_ADAPTER.validate_json(record.cited_section_positions_json, strict=True)
    )
    result = PersonaInterview(
        id=record.id,
        report_id=record.report_id,
        report_sha256=record.report_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        persona=PersonaInterviewPersona(
            id=record.persona_id,
            position=record.persona_position,
            persona_id=record.persona_external_id,
            display_name=record.persona_display_name,
            profile_sha256=record.persona_profile_sha256,
        ),
        question=record.question,
        interview_sha256=record.interview_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_PROMPT_SCHEMA_VERSION,
        status=record.status,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        answer_markdown=record.answer_markdown,
        cited_section_positions=positions,
        answer_sha256=record.answer_sha256,
        error_code=record.error_code,
        error_message=record.error_message,
    )
    if result.status == "succeeded":
        expected = answer_sha256(
            result.interview_sha256,
            result.answer_markdown or "",
            result.cited_section_positions,
        )
        if expected != result.answer_sha256:
            raise RuntimeError(f"Persona interview {result.id} answer integrity mismatch")
    return result


async def enqueue_persona_interview(
    session: AsyncSession,
    report_id: UUID,
    request: PersonaInterviewRequest,
) -> PersonaInterview:
    report, cohort, heartbeat = await _load_interview_context(session, report_id)
    member = _require_member(cohort, request.persona_id)
    record = await _get_or_create_interview_record(
        session,
        report,
        cohort,
        heartbeat,
        member,
        request.question,
        datetime.now(UTC),
    )
    await session.commit()
    return _project(record)


async def _load_interview_context(
    session: AsyncSession,
    report_id: UUID,
) -> tuple[DecisionReport, CohortDetail, SimulationWorkerHeartbeatRecord]:
    try:
        report = await get_decision_report(session, report_id)
    except DecisionReportNotFoundError:
        raise
    try:
        cohort = await get_cohort(session, report.cohort_id)
    except PopulationCohortNotFoundError as error:
        raise RuntimeError(f"report {report_id} references a missing sealed cohort") from error
    if cohort.cohort_sha256 != report.cohort_sha256:
        raise RuntimeError(f"report {report_id} cohort integrity mismatch")
    experiment = await session.get(SemanticExperimentRecord, report.experiment_id)
    if experiment is None or experiment.input_sealed_at is None:
        raise RuntimeError(f"report {report_id} references a missing sealed experiment")
    cutoff = datetime.now(UTC) - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    heartbeat = await session.scalar(
        select(SimulationWorkerHeartbeatRecord)
        .where(
            SimulationWorkerHeartbeatRecord.last_seen_at >= cutoff,
            SimulationWorkerHeartbeatRecord.engine == "camel-oasis",
            SimulationWorkerHeartbeatRecord.engine_version == OASIS_ENGINE_VERSION,
            SimulationWorkerHeartbeatRecord.camel_version == CAMEL_ENGINE_VERSION,
            SimulationWorkerHeartbeatRecord.semantic_runtime_ready.is_(True),
            SimulationWorkerHeartbeatRecord.semantic_prompt_schema_version == PROMPT_SCHEMA_VERSION,
            SimulationWorkerHeartbeatRecord.semantic_model_name == experiment.model_name,
            SimulationWorkerHeartbeatRecord.semantic_config_sha256
            == experiment.semantic_config_sha256,
        )
        .limit(1)
    )
    if (
        heartbeat is None
        or heartbeat.semantic_model_name is None
        or heartbeat.semantic_config_sha256 is None
    ):
        raise PersonaInterviewUnavailableError(
            "Persona interviews require a live model worker matching the report experiment"
        )
    return report, cohort, heartbeat


def _require_member(cohort: CohortDetail, persona_id: UUID) -> CohortMember:
    member = next((item for item in cohort.members if item.persona.id == persona_id), None)
    if member is None:
        raise PersonaInterviewNotFoundError(
            f"persona {persona_id} is not a member of report cohort {cohort.id}"
        )
    return member


async def _get_or_create_interview_record(
    session: AsyncSession,
    report: DecisionReport,
    cohort: CohortDetail,
    heartbeat: SimulationWorkerHeartbeatRecord,
    member: CohortMember,
    question: str,
    created_at: datetime,
) -> PersonaInterviewRecord:
    if heartbeat.semantic_config_sha256 is None or heartbeat.semantic_model_name is None:
        raise PersonaInterviewUnavailableError(
            "Persona interview worker configuration is incomplete"
        )
    digest = interview_sha256(
        report.report_sha256,
        cohort.cohort_sha256,
        str(member.persona.id),
        member.persona.profile_sha256,
        question,
        heartbeat.semantic_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(PersonaInterviewRecord).where(PersonaInterviewRecord.interview_sha256 == digest)
    )
    if existing is not None:
        return existing
    record = PersonaInterviewRecord(
        id=uuid4(),
        report_id=report.id,
        report_sha256=report.report_sha256,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        persona_id=member.persona.id,
        persona_position=member.position,
        persona_external_id=member.persona.persona_id,
        persona_display_name=member.persona.display_name,
        persona_profile_sha256=member.persona.profile_sha256,
        question=question,
        interview_sha256=digest,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_PROMPT_SCHEMA_VERSION,
        status="queued",
        created_at=created_at,
        started_at=None,
        completed_at=None,
        claimed_by_worker_id=None,
        answer_markdown=None,
        cited_section_positions_json=None,
        answer_sha256=None,
        error_code=None,
        error_message=None,
    )
    session.add(record)
    await session.flush()
    return record


def _session_status(interviews: tuple[PersonaInterview, ...]) -> str:
    statuses = tuple(item.status for item in interviews)
    if all(status == "queued" for status in statuses):
        return "queued"
    if any(status in ("queued", "running") for status in statuses):
        return "running"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "failed"


async def _project_session(
    session: AsyncSession,
    record: PersonaInterviewSessionRecord,
) -> PersonaInterviewSession:
    if record.sealed_at is None:
        raise RuntimeError(f"Persona interview session {record.id} is not sealed")
    rows = tuple(
        (
            await session.execute(
                select(PersonaInterviewSessionMemberRecord, PersonaInterviewRecord)
                .join(
                    PersonaInterviewRecord,
                    PersonaInterviewRecord.id == PersonaInterviewSessionMemberRecord.interview_id,
                )
                .where(PersonaInterviewSessionMemberRecord.session_id == record.id)
                .order_by(PersonaInterviewSessionMemberRecord.position)
            )
        ).all()
    )
    if tuple(member.position for member, _ in rows) != tuple(range(record.persona_count)):
        raise RuntimeError(f"Persona interview session {record.id} members are incomplete")
    interviews = tuple(_project(interview) for _, interview in rows)
    expected_digest = interview_session_sha256(
        record.report_sha256,
        record.cohort_sha256,
        tuple((str(item.persona.id), item.persona.profile_sha256) for item in interviews),
        record.question,
        record.semantic_config_sha256,
    )
    if expected_digest != record.session_sha256:
        raise RuntimeError(f"Persona interview session {record.id} integrity mismatch")
    return PersonaInterviewSession(
        id=record.id,
        report_id=record.report_id,
        report_sha256=record.report_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        question=record.question,
        persona_count=record.persona_count,
        session_sha256=record.session_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_SESSION_SCHEMA_VERSION,
        status=_session_status(interviews),
        created_at=record.created_at,
        interviews=interviews,
    )


async def enqueue_persona_interview_session(
    session: AsyncSession,
    report_id: UUID,
    request: PersonaInterviewSessionRequest,
) -> PersonaInterviewSession:
    report, cohort, heartbeat = await _load_interview_context(session, report_id)
    members = tuple(_require_member(cohort, persona_id) for persona_id in request.persona_ids)
    if heartbeat.semantic_config_sha256 is None or heartbeat.semantic_model_name is None:
        raise PersonaInterviewUnavailableError(
            "Persona interview worker configuration is incomplete"
        )
    digest = interview_session_sha256(
        report.report_sha256,
        cohort.cohort_sha256,
        tuple((str(member.persona.id), member.persona.profile_sha256) for member in members),
        request.question,
        heartbeat.semantic_config_sha256,
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"),
        {"digest": digest},
    )
    existing = await session.scalar(
        select(PersonaInterviewSessionRecord).where(
            PersonaInterviewSessionRecord.session_sha256 == digest
        )
    )
    if existing is not None:
        return await _project_session(session, existing)
    created_at = datetime.now(UTC)
    interview_records = tuple(
        [
            await _get_or_create_interview_record(
                session,
                report,
                cohort,
                heartbeat,
                member,
                request.question,
                created_at,
            )
            for member in members
        ]
    )
    session_record = PersonaInterviewSessionRecord(
        id=uuid4(),
        report_id=report.id,
        report_sha256=report.report_sha256,
        cohort_id=cohort.id,
        cohort_sha256=cohort.cohort_sha256,
        question=request.question,
        persona_count=len(members),
        session_sha256=digest,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=INTERVIEW_SESSION_SCHEMA_VERSION,
        created_at=created_at,
        sealed_at=None,
    )
    session.add(session_record)
    await session.flush()
    session.add_all(
        tuple(
            PersonaInterviewSessionMemberRecord(
                session_id=session_record.id,
                position=position,
                persona_id=member.persona.id,
                interview_id=interview.id,
            )
            for position, (member, interview) in enumerate(
                zip(members, interview_records, strict=True)
            )
        )
    )
    await session.flush()
    session_record.sealed_at = created_at
    await session.commit()
    return await _project_session(session, session_record)


async def get_persona_interview_session(
    session: AsyncSession,
    session_id: UUID,
) -> PersonaInterviewSession:
    record = await session.get(PersonaInterviewSessionRecord, session_id)
    if record is None:
        raise PersonaInterviewNotFoundError(f"Persona interview session {session_id} was not found")
    return await _project_session(session, record)


async def list_persona_interview_sessions(
    session: AsyncSession,
    report_id: UUID,
) -> PersonaInterviewSessionsResponse:
    await get_decision_report(session, report_id)
    records = tuple(
        (
            await session.scalars(
                select(PersonaInterviewSessionRecord)
                .where(
                    PersonaInterviewSessionRecord.report_id == report_id,
                    PersonaInterviewSessionRecord.sealed_at.is_not(None),
                )
                .order_by(
                    PersonaInterviewSessionRecord.created_at,
                    PersonaInterviewSessionRecord.id,
                )
            )
        ).all()
    )
    items = tuple([await _project_session(session, record) for record in records])
    return PersonaInterviewSessionsResponse(items=items, total=len(items))


async def get_persona_interview(session: AsyncSession, interview_id: UUID) -> PersonaInterview:
    record = await session.get(PersonaInterviewRecord, interview_id)
    if record is None:
        raise PersonaInterviewNotFoundError(f"Persona interview {interview_id} was not found")
    return _project(record)


async def list_persona_interviews(
    session: AsyncSession,
    report_id: UUID,
) -> PersonaInterviewsResponse:
    await get_decision_report(session, report_id)
    records = tuple(
        (
            await session.scalars(
                select(PersonaInterviewRecord)
                .where(PersonaInterviewRecord.report_id == report_id)
                .order_by(PersonaInterviewRecord.created_at, PersonaInterviewRecord.id)
            )
        ).all()
    )
    return PersonaInterviewsResponse(
        items=tuple(_project(record) for record in records),
        total=len(records),
    )
