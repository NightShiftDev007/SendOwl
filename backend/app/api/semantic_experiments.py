"""HTTP boundary for durable OASIS semantic experiments."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.populations.errors import PopulationCohortNotFoundError
from app.scenarios.errors import ScenarioNotFoundError
from app.semantic_experiments.contracts import (
    SemanticExperimentComparison,
    SemanticExperimentCreateRequest,
    SemanticExperimentDetail,
    SemanticExperimentsResponse,
    SemanticReadiness,
    SemanticTrialEventsResponse,
)
from app.semantic_experiments.errors import (
    SemanticExperimentNotFoundError,
    SemanticExperimentSelectionError,
    SemanticExperimentUnavailableError,
    SemanticTrialNotFoundError,
)
from app.semantic_experiments.repository import (
    compare_semantic_experiment,
    create_semantic_experiment,
    get_semantic_experiment,
    get_semantic_readiness,
    list_semantic_experiments,
    list_semantic_trial_events,
)

SEMANTIC_EXPERIMENTS_UNAVAILABLE_DETAIL = (
    "Semantic experiment data is unavailable because DATABASE_URL is not configured"
)


async def require_semantic_experiment_session(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SEMANTIC_EXPERIMENTS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


SemanticExperimentSession = Annotated[
    AsyncSession,
    Depends(require_semantic_experiment_session),
]


def create_semantic_experiments_router() -> APIRouter:
    router = APIRouter(tags=["semantic-experiments"])

    @router.post(
        "/api/v2/semantic-experiments",
        response_model=SemanticExperimentDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_semantic_experiment(
        request: SemanticExperimentCreateRequest,
        session: SemanticExperimentSession,
    ) -> SemanticExperimentDetail:
        try:
            return await create_semantic_experiment(session, request)
        except (ScenarioNotFoundError, PopulationCohortNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except SemanticExperimentSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except SemanticExperimentUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/semantic-experiments",
        response_model=SemanticExperimentsResponse,
    )
    async def semantic_experiments(
        session: SemanticExperimentSession,
    ) -> SemanticExperimentsResponse:
        return await list_semantic_experiments(session)

    @router.get(
        "/api/v2/semantic-experiments/{experiment_id}",
        response_model=SemanticExperimentDetail,
    )
    async def semantic_experiment(
        experiment_id: UUID,
        session: SemanticExperimentSession,
    ) -> SemanticExperimentDetail:
        try:
            return await get_semantic_experiment(session, experiment_id)
        except SemanticExperimentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/semantic-experiments/{experiment_id}/comparison",
        response_model=SemanticExperimentComparison,
    )
    async def semantic_experiment_comparison(
        experiment_id: UUID,
        session: SemanticExperimentSession,
    ) -> SemanticExperimentComparison:
        try:
            return await compare_semantic_experiment(session, experiment_id)
        except SemanticExperimentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/semantic-trials/{trial_id}/events",
        response_model=SemanticTrialEventsResponse,
    )
    async def semantic_trial_events(
        trial_id: UUID,
        session: SemanticExperimentSession,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> SemanticTrialEventsResponse:
        try:
            return await list_semantic_trial_events(
                session,
                trial_id,
                after_sequence,
                limit,
            )
        except SemanticTrialNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/simulations/oasis/semantic-readiness",
        response_model=SemanticReadiness,
    )
    async def semantic_readiness(
        session: SemanticExperimentSession,
    ) -> SemanticReadiness:
        return await get_semantic_readiness(session)

    return router
