"""HTTP boundary for the Project-bound evaluation workspace."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.research_evaluations.bundles import ensure_research_evaluation_task_bundle
from app.research_evaluations.contracts import (
    ResearchEvaluationJob,
    ResearchEvaluationJobCreateRequest,
    ResearchEvaluationTarget,
    ResearchEvaluationTargetCreateRequest,
    ResearchEvaluationTaskBundle,
    ResearchEvaluationTaskBundleCreateRequest,
    ResearchEvaluationWorkspace,
)
from app.research_evaluations.errors import (
    ResearchEvaluationRetryError,
    ResearchEvaluationScopeError,
)
from app.research_evaluations.jobs import (
    create_research_evaluation_job,
    get_research_evaluation_job,
    retry_research_evaluation_job,
)
from app.research_evaluations.repository import get_research_evaluation_workspace
from app.research_evaluations.targets import ensure_research_evaluation_target


async def require_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research Evaluation data is unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


ResearchEvaluationSession = Annotated[AsyncSession, Depends(require_session)]


def create_research_evaluations_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/research-evaluations", tags=["research-evaluations"])

    @router.post(
        "/task-bundles",
        response_model=ResearchEvaluationTaskBundle,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_task_bundle(
        request: ResearchEvaluationTaskBundleCreateRequest,
        session: ResearchEvaluationSession,
    ) -> ResearchEvaluationTaskBundle:
        try:
            return await ensure_research_evaluation_task_bundle(session, request, commit=True)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    @router.post(
        "/targets",
        response_model=ResearchEvaluationTarget,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_target(
        request: ResearchEvaluationTargetCreateRequest,
        session: ResearchEvaluationSession,
    ) -> ResearchEvaluationTarget:
        try:
            return await ensure_research_evaluation_target(session, request, commit=True)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    @router.post(
        "/jobs",
        response_model=ResearchEvaluationJob,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_job(
        request: ResearchEvaluationJobCreateRequest,
        session: ResearchEvaluationSession,
    ) -> ResearchEvaluationJob:
        try:
            return await create_research_evaluation_job(session, request)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

    @router.get("/jobs/{job_id}", response_model=ResearchEvaluationJob)
    async def job(job_id: UUID, session: ResearchEvaluationSession) -> ResearchEvaluationJob:
        try:
            return await get_research_evaluation_job(session, job_id)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/jobs/{job_id}/retry",
        response_model=ResearchEvaluationJob,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_job(
        job_id: UUID,
        session: ResearchEvaluationSession,
    ) -> ResearchEvaluationJob:
        try:
            return await retry_research_evaluation_job(session, job_id)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ResearchEvaluationRetryError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/workspace", response_model=ResearchEvaluationWorkspace)
    async def workspace(
        project_id: UUID,
        run_id: UUID,
        session: ResearchEvaluationSession,
    ) -> ResearchEvaluationWorkspace:
        try:
            return await get_research_evaluation_workspace(session, project_id, run_id)
        except ResearchEvaluationScopeError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router
