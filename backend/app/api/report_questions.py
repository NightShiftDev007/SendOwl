"""HTTP boundary for evidence-bound report questions."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.decision_reports.errors import DecisionReportNotFoundError
from app.legacy_adc import reject_legacy_adc_write
from app.report_questions.contracts import (
    ReportQuestion,
    ReportQuestionContext,
    ReportQuestionRequest,
    ReportQuestionsResponse,
)
from app.report_questions.errors import ReportQuestionNotFoundError, ReportQuestionUnavailableError
from app.report_questions.repository import (
    enqueue_report_question,
    get_report_question,
    get_report_question_context,
    list_report_questions,
)


async def require_report_question_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report questions are unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


ReportQuestionSession = Annotated[AsyncSession, Depends(require_report_question_session)]


def create_report_questions_router() -> APIRouter:
    router = APIRouter(tags=["report-questions"])

    @router.post(
        "/api/v2/decision-reports/{report_id}/questions",
        response_model=ReportQuestion,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def enqueue(
        report_id: UUID, request: ReportQuestionRequest, session: ReportQuestionSession
    ) -> ReportQuestion:
        try:
            return await enqueue_report_question(session, report_id, request)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportQuestionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportQuestionUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/decision-reports/{report_id}/questions",
        response_model=ReportQuestionsResponse,
    )
    async def index(report_id: UUID, session: ReportQuestionSession) -> ReportQuestionsResponse:
        try:
            return await list_report_questions(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/api/v2/report-questions/{question_id}", response_model=ReportQuestion)
    async def detail(question_id: UUID, session: ReportQuestionSession) -> ReportQuestion:
        try:
            return await get_report_question(session, question_id)
        except ReportQuestionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/report-questions/{question_id}/context",
        response_model=ReportQuestionContext,
    )
    async def context(
        question_id: UUID,
        session: ReportQuestionSession,
    ) -> ReportQuestionContext:
        try:
            return await get_report_question_context(session, question_id)
        except ReportQuestionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportQuestionUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    return router
