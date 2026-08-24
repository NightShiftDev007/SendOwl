"""HTTP boundary for native single-context MatrAIx surveys."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.research_surveys.contracts import (
    ResearchSurveyCreateRequest,
    ResearchSurveyDetail,
    ResearchSurveyReadiness,
    ResearchSurveysResponse,
)
from app.research_surveys.errors import (
    ResearchSurveyNotFoundError,
    ResearchSurveySelectionError,
    ResearchSurveyUnavailableError,
)
from app.research_surveys.repository import (
    create_research_survey,
    get_research_survey,
    get_research_survey_progress,
    get_research_survey_readiness,
    list_research_surveys,
)
from app.shared.progress import ParentProgress


async def require_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research Survey data is unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


ResearchSurveySession = Annotated[AsyncSession, Depends(require_session)]


def create_research_surveys_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/research-surveys", tags=["research-surveys"])

    @router.post("", response_model=ResearchSurveyDetail, status_code=status.HTTP_202_ACCEPTED)
    async def create(
        request: ResearchSurveyCreateRequest, session: ResearchSurveySession
    ) -> ResearchSurveyDetail:
        try:
            return await create_research_survey(session, request)
        except ResearchSurveySelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        except ResearchSurveyUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
            ) from error

    @router.get("", response_model=ResearchSurveysResponse)
    async def index(session: ResearchSurveySession) -> ResearchSurveysResponse:
        return await list_research_surveys(session)

    @router.get("/readiness", response_model=ResearchSurveyReadiness)
    async def readiness(session: ResearchSurveySession) -> ResearchSurveyReadiness:
        return await get_research_survey_readiness(session)

    @router.get("/{survey_id}", response_model=ResearchSurveyDetail)
    async def detail(survey_id: UUID, session: ResearchSurveySession) -> ResearchSurveyDetail:
        try:
            return await get_research_survey(session, survey_id)
        except ResearchSurveyNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/{survey_id}/progress", response_model=ParentProgress)
    async def progress(survey_id: UUID, session: ResearchSurveySession) -> ParentProgress:
        try:
            return await get_research_survey_progress(session, survey_id)
        except ResearchSurveyNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router
