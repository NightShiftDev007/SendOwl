"""HTTP boundary for report-grounded synthetic Persona interviews."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.decision_reports.errors import DecisionReportNotFoundError
from app.legacy_adc import reject_legacy_adc_write
from app.persona_interviews.contracts import (
    PersonaInterview,
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
from app.persona_interviews.repository import (
    enqueue_persona_interview,
    enqueue_persona_interview_session,
    get_persona_interview,
    get_persona_interview_session,
    list_persona_interview_sessions,
    list_persona_interviews,
)


async def require_persona_interview_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Persona interviews are unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


PersonaInterviewDatabaseSession = Annotated[
    AsyncSession, Depends(require_persona_interview_session)
]


def create_persona_interviews_router() -> APIRouter:
    router = APIRouter(tags=["persona-interviews"])

    @router.post(
        "/api/v2/decision-reports/{report_id}/persona-interviews",
        response_model=PersonaInterview,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def enqueue(
        report_id: UUID,
        request: PersonaInterviewRequest,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterview:
        try:
            return await enqueue_persona_interview(session, report_id, request)
        except (DecisionReportNotFoundError, PersonaInterviewNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PersonaInterviewUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/decision-reports/{report_id}/persona-interviews",
        response_model=PersonaInterviewsResponse,
    )
    async def index(
        report_id: UUID,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterviewsResponse:
        try:
            return await list_persona_interviews(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/persona-interviews/{interview_id}",
        response_model=PersonaInterview,
    )
    async def detail(
        interview_id: UUID,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterview:
        try:
            return await get_persona_interview(session, interview_id)
        except PersonaInterviewNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/api/v2/decision-reports/{report_id}/persona-interview-sessions",
        response_model=PersonaInterviewSession,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def enqueue_session(
        report_id: UUID,
        request: PersonaInterviewSessionRequest,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterviewSession:
        try:
            return await enqueue_persona_interview_session(session, report_id, request)
        except (DecisionReportNotFoundError, PersonaInterviewNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PersonaInterviewUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/decision-reports/{report_id}/persona-interview-sessions",
        response_model=PersonaInterviewSessionsResponse,
    )
    async def index_sessions(
        report_id: UUID,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterviewSessionsResponse:
        try:
            return await list_persona_interview_sessions(session, report_id)
        except DecisionReportNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/persona-interview-sessions/{session_id}",
        response_model=PersonaInterviewSession,
    )
    async def detail_session(
        session_id: UUID,
        session: PersonaInterviewDatabaseSession,
    ) -> PersonaInterviewSession:
        try:
            return await get_persona_interview_session(session, session_id)
        except PersonaInterviewNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router
