"""Enqueue and fail-closed reads for cited report questions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision_reports.errors import DecisionReportNotFoundError
from app.decision_reports.models import DecisionReportRecord
from app.report_questions.contracts import (
    ReportAnswerCitation,
    ReportQuestion,
    ReportQuestionRequest,
    ReportQuestionsResponse,
)
from app.report_questions.errors import ReportQuestionNotFoundError, ReportQuestionUnavailableError
from app.report_questions.hashing import answer_sha256, question_sha256
from app.report_questions.models import ReportQuestionRecord
from app.scenarios.models import ScenarioRecord
from app.semantic_experiments.hashing import PROMPT_SCHEMA_VERSION
from app.simulations.constants import (
    CAMEL_ENGINE_VERSION,
    OASIS_ENGINE_VERSION,
    WORKER_HEARTBEAT_MAX_AGE_SECONDS,
)
from app.simulations.models import SimulationWorkerHeartbeatRecord
from app.world_graphs.models import SemanticWorldGraphRecord

CITATIONS_ADAPTER = TypeAdapter(tuple[ReportAnswerCitation, ...])
QA_PROMPT_SCHEMA_VERSION = "report-evidence-qa/v1"


def _project(record: ReportQuestionRecord) -> ReportQuestion:
    citations = (
        ()
        if record.citations_json is None
        else CITATIONS_ADAPTER.validate_json(record.citations_json, strict=True)
    )
    result = ReportQuestion(
        id=record.id,
        report_id=record.report_id,
        report_sha256=record.report_sha256,
        graph_id=record.graph_id,
        graph_sha256=record.graph_sha256,
        question=record.question,
        question_sha256=record.question_sha256,
        model_name=record.model_name,
        semantic_config_sha256=record.semantic_config_sha256,
        prompt_schema_version=QA_PROMPT_SCHEMA_VERSION,
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
        expected = answer_sha256(
            result.question_sha256, result.answer_markdown or "", result.citations
        )
        if expected != result.answer_sha256:
            raise RuntimeError(f"report question {result.id} answer integrity mismatch")
    return result


async def enqueue_report_question(
    session: AsyncSession,
    report_id: UUID,
    request: ReportQuestionRequest,
) -> ReportQuestion:
    report = await session.get(DecisionReportRecord, report_id)
    if report is None or report.sealed_at is None:
        raise DecisionReportNotFoundError(f"sealed decision report {report_id} was not found")
    scenario = await session.get(ScenarioRecord, report.scenario_id)
    if scenario is None or scenario.sealed_at is None:
        raise RuntimeError(f"decision report {report_id} references a missing sealed scenario")
    graph = await session.scalar(
        select(SemanticWorldGraphRecord)
        .where(
            SemanticWorldGraphRecord.world_model_id == scenario.world_model_id,
            SemanticWorldGraphRecord.snapshot_id == scenario.world_snapshot_id,
            SemanticWorldGraphRecord.snapshot_sha256 == scenario.snapshot_sha256,
            SemanticWorldGraphRecord.status == "succeeded",
        )
        .order_by(SemanticWorldGraphRecord.completed_at.desc(), SemanticWorldGraphRecord.id)
        .limit(1)
    )
    if graph is None or graph.graph_sha256 is None:
        raise ReportQuestionUnavailableError(
            "report questions require a succeeded evidence-backed semantic graph "
            "for the same snapshot"
        )
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
            SimulationWorkerHeartbeatRecord.semantic_model_name == graph.model_name,
            SimulationWorkerHeartbeatRecord.semantic_config_sha256 == graph.semantic_config_sha256,
        )
        .limit(1)
    )
    if (
        heartbeat is None
        or heartbeat.semantic_model_name is None
        or heartbeat.semantic_config_sha256 is None
    ):
        raise ReportQuestionUnavailableError(
            "report questions require a live model worker matching the graph configuration"
        )
    digest = question_sha256(report.report_sha256, graph.graph_sha256, request.question)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:digest, 0))"), {"digest": digest}
    )
    existing = await session.scalar(
        select(ReportQuestionRecord).where(ReportQuestionRecord.question_sha256 == digest)
    )
    if existing is not None:
        return _project(existing)
    record = ReportQuestionRecord(
        id=uuid4(),
        report_id=report.id,
        report_sha256=report.report_sha256,
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        question=request.question,
        question_sha256=digest,
        model_name=heartbeat.semantic_model_name,
        semantic_config_sha256=heartbeat.semantic_config_sha256,
        prompt_schema_version=QA_PROMPT_SCHEMA_VERSION,
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


async def get_report_question(session: AsyncSession, question_id: UUID) -> ReportQuestion:
    record = await session.get(ReportQuestionRecord, question_id)
    if record is None:
        raise ReportQuestionNotFoundError(f"report question {question_id} was not found")
    return _project(record)


async def list_report_questions(session: AsyncSession, report_id: UUID) -> ReportQuestionsResponse:
    report = await session.get(DecisionReportRecord, report_id)
    if report is None or report.sealed_at is None:
        raise DecisionReportNotFoundError(f"sealed decision report {report_id} was not found")
    records = tuple(
        (
            await session.scalars(
                select(ReportQuestionRecord)
                .where(ReportQuestionRecord.report_id == report_id)
                .order_by(ReportQuestionRecord.created_at, ReportQuestionRecord.id)
            )
        ).all()
    )
    return ReportQuestionsResponse(
        items=tuple(_project(record) for record in records), total=len(records)
    )
