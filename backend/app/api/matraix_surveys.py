"""HTTP boundary for durable MatrAIx scenario-preference surveys."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_surveys.contracts import (
    MatraixSurveyCreateRequest,
    MatraixSurveyExperimentDetail,
    MatraixSurveyExperimentsResponse,
    MatraixSurveyReadiness,
    MatraixSurveyTrial,
)
from app.matraix_surveys.errors import (
    MatraixSurveyExperimentNotFoundError,
    MatraixSurveySelectionError,
    MatraixSurveyTrialNotFoundError,
    MatraixSurveyUnavailableError,
)
from app.matraix_surveys.repository import (
    create_matraix_survey_experiment,
    get_matraix_survey_experiment,
    get_matraix_survey_readiness,
    get_matraix_survey_trial,
    list_matraix_survey_experiments,
)
from app.populations.errors import PopulationCohortNotFoundError
from app.scenarios.errors import ScenarioNotFoundError

SURVEY_UNAVAILABLE_DETAIL = (
    "MatrAIx Survey data is unavailable because DATABASE_URL is not configured"
)


async def require_matraix_survey_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SURVEY_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


MatraixSurveySession = Annotated[AsyncSession, Depends(require_matraix_survey_session)]


def create_matraix_surveys_router() -> APIRouter:
    router = APIRouter(tags=["matraix-surveys"])

    @router.post(
        "/api/v2/matraix/survey-experiments",
        response_model=MatraixSurveyExperimentDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_survey_experiment(
        request: MatraixSurveyCreateRequest,
        session: MatraixSurveySession,
    ) -> MatraixSurveyExperimentDetail:
        try:
            return await create_matraix_survey_experiment(session, request)
        except (ScenarioNotFoundError, PopulationCohortNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixSurveySelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except MatraixSurveyUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/survey-experiments",
        response_model=MatraixSurveyExperimentsResponse,
    )
    async def survey_experiments(
        session: MatraixSurveySession,
    ) -> MatraixSurveyExperimentsResponse:
        return await list_matraix_survey_experiments(session)

    @router.get(
        "/api/v2/matraix/survey-experiments/{experiment_id}",
        response_model=MatraixSurveyExperimentDetail,
    )
    async def survey_experiment(
        experiment_id: UUID,
        session: MatraixSurveySession,
    ) -> MatraixSurveyExperimentDetail:
        try:
            return await get_matraix_survey_experiment(session, experiment_id)
        except MatraixSurveyExperimentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/survey-trials/{trial_id}",
        response_model=MatraixSurveyTrial,
    )
    async def survey_trial(
        trial_id: UUID,
        session: MatraixSurveySession,
    ) -> MatraixSurveyTrial:
        try:
            return await get_matraix_survey_trial(session, trial_id)
        except MatraixSurveyTrialNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/survey-readiness",
        response_model=MatraixSurveyReadiness,
    )
    async def survey_readiness(session: MatraixSurveySession) -> MatraixSurveyReadiness:
        return await get_matraix_survey_readiness(session)

    return router
