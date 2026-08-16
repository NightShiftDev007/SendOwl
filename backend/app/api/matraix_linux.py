"""HTTP boundary for the fixed MatrAIx Linux artifact task."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_linux.contracts import (
    MatraixLinuxEvaluation,
    MatraixLinuxReadiness,
    MatraixLinuxTasksResponse,
    MatraixLinuxTrial,
    MatraixLinuxTrialCreateRequest,
    MatraixLinuxTrialsResponse,
)
from app.matraix_linux.errors import (
    MatraixLinuxEvaluationNotFoundError,
    MatraixLinuxSelectionError,
    MatraixLinuxTrialNotFoundError,
    MatraixLinuxUnavailableError,
)
from app.matraix_linux.repository import (
    create_linux_evaluation,
    create_linux_trial,
    get_linux_artifact,
    get_linux_evaluation,
    get_linux_evaluation_progress,
    get_linux_readiness,
    get_linux_trial,
    list_linux_tasks,
    list_linux_trials,
    retry_linux_evaluation,
)
from app.populations.errors import PopulationCohortNotFoundError
from app.shared.pagination import parse_page_request
from app.shared.progress import ParentProgress

LINUX_UNAVAILABLE_DETAIL = (
    "MatrAIx Linux data is unavailable because DATABASE_URL is not configured"
)
LINUX_ARTIFACT_ROOT = Path("/linux-artifacts")


async def require_linux_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=LINUX_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


LinuxSession = Annotated[AsyncSession, Depends(require_linux_session)]


def create_matraix_linux_router() -> APIRouter:
    router = APIRouter(tags=["matraix-linux"])

    @router.get("/api/v2/matraix/linux-tasks", response_model=MatraixLinuxTasksResponse)
    async def linux_tasks() -> MatraixLinuxTasksResponse:
        return list_linux_tasks()

    @router.post(
        "/api/v2/matraix/linux-trials",
        response_model=MatraixLinuxTrial,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_linux_trial(
        body: MatraixLinuxTrialCreateRequest,
        session: LinuxSession,
    ) -> MatraixLinuxTrial:
        try:
            return await create_linux_trial(session, body)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except MatraixLinuxSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except MatraixLinuxUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @router.post(
        "/api/v2/matraix/linux-evaluations",
        response_model=MatraixLinuxEvaluation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_linux_evaluation(
        body: MatraixLinuxTrialCreateRequest,
        session: LinuxSession,
    ) -> MatraixLinuxEvaluation:
        try:
            return await create_linux_evaluation(session, body)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except MatraixLinuxSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except MatraixLinuxUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/linux-evaluations/{evaluation_id}/progress",
        response_model=ParentProgress,
    )
    async def linux_evaluation_progress(
        evaluation_id: UUID,
        session: LinuxSession,
    ) -> ParentProgress:
        try:
            return await get_linux_evaluation_progress(session, evaluation_id)
        except MatraixLinuxEvaluationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/linux-evaluations/{evaluation_id}",
        response_model=MatraixLinuxEvaluation,
    )
    async def linux_evaluation(
        evaluation_id: UUID,
        session: LinuxSession,
    ) -> MatraixLinuxEvaluation:
        try:
            return await get_linux_evaluation(session, evaluation_id)
        except MatraixLinuxEvaluationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post(
        "/api/v2/matraix/linux-evaluations/{evaluation_id}/retry",
        response_model=MatraixLinuxEvaluation,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_evaluation(
        evaluation_id: UUID,
        session: LinuxSession,
    ) -> MatraixLinuxEvaluation:
        try:
            return await retry_linux_evaluation(session, evaluation_id)
        except MatraixLinuxEvaluationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except MatraixLinuxSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except MatraixLinuxUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @router.get("/api/v2/matraix/linux-trials", response_model=MatraixLinuxTrialsResponse)
    async def linux_trials(request: Request, session: LinuxSession) -> MatraixLinuxTrialsResponse:
        pagination = parse_page_request(request, 20, 50)
        try:
            return await list_linux_trials(session, pagination.page, pagination.page_size)
        except MatraixLinuxSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/api/v2/matraix/linux-trials/{trial_id}", response_model=MatraixLinuxTrial)
    async def linux_trial(trial_id: UUID, session: LinuxSession) -> MatraixLinuxTrial:
        try:
            return await get_linux_trial(session, trial_id)
        except MatraixLinuxTrialNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.get("/api/v2/matraix/linux-trials/{trial_id}/artifacts/{artifact_name}")
    async def linux_artifact(
        trial_id: UUID,
        artifact_name: str,
        session: LinuxSession,
    ) -> FileResponse:
        try:
            path, digest = await get_linux_artifact(
                session,
                LINUX_ARTIFACT_ROOT,
                trial_id,
                artifact_name,
            )
        except MatraixLinuxTrialNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except MatraixLinuxSelectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except MatraixLinuxUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return FileResponse(path, filename=artifact_name, headers={"ETag": f'"{digest}"'})

    @router.get("/api/v2/matraix/linux-readiness", response_model=MatraixLinuxReadiness)
    async def linux_readiness(session: LinuxSession) -> MatraixLinuxReadiness:
        return await get_linux_readiness(session)

    return router
