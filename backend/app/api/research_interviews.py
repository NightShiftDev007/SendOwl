"""HTTP boundary for run-grounded Persona interviews."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.research_interviews.contracts import (
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
from app.research_interviews.repository import (
    enqueue_research_persona_interview,
    enqueue_research_persona_interview_session,
    get_research_persona_interview,
    list_research_persona_interview_sessions,
    list_research_persona_interviews,
)
from app.research_projects.errors import ResearchSimulationRunNotFoundError


async def require_research_interview_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research interviews are unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


ResearchInterviewSession = Annotated[AsyncSession, Depends(require_research_interview_session)]


def create_research_interviews_router() -> APIRouter:
    router = APIRouter(tags=["research-interviews"])

    @router.post(
        "/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interviews",
        response_model=ResearchPersonaInterview,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue(
        project_id: UUID,
        run_id: UUID,
        request: ResearchPersonaInterviewRequest,
        session: ResearchInterviewSession,
    ) -> ResearchPersonaInterview:
        try:
            return await enqueue_research_persona_interview(session, project_id, run_id, request)
        except (ResearchSimulationRunNotFoundError, ResearchInterviewNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResearchInterviewUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interviews",
        response_model=ResearchPersonaInterviewsResponse,
    )
    async def index(
        project_id: UUID,
        run_id: UUID,
        session: ResearchInterviewSession,
    ) -> ResearchPersonaInterviewsResponse:
        try:
            return await list_research_persona_interviews(session, project_id, run_id)
        except ResearchSimulationRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interview-sessions",
        response_model=ResearchPersonaInterviewSession,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_session(
        project_id: UUID,
        run_id: UUID,
        request: ResearchPersonaInterviewSessionRequest,
        session: ResearchInterviewSession,
    ) -> ResearchPersonaInterviewSession:
        try:
            return await enqueue_research_persona_interview_session(
                session, project_id, run_id, request
            )
        except (ResearchSimulationRunNotFoundError, ResearchInterviewNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResearchInterviewUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/research-projects/{project_id}/runs/{run_id}/persona-interview-sessions",
        response_model=ResearchPersonaInterviewSessionsResponse,
    )
    async def index_sessions(
        project_id: UUID,
        run_id: UUID,
        session: ResearchInterviewSession,
    ) -> ResearchPersonaInterviewSessionsResponse:
        try:
            return await list_research_persona_interview_sessions(session, project_id, run_id)
        except ResearchSimulationRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/research-persona-interviews/{interview_id}",
        response_model=ResearchPersonaInterview,
    )
    async def detail(
        interview_id: UUID,
        session: ResearchInterviewSession,
    ) -> ResearchPersonaInterview:
        try:
            return await get_research_persona_interview(session, interview_id)
        except ResearchInterviewNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router
