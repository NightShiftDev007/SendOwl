"""HTTP boundary for durable MatrAIx Playwright quote-choice evaluations."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_web.contracts import (
    MatraixWebEvaluationCreateRequest,
    MatraixWebEvaluationDetail,
    MatraixWebEvaluationsResponse,
    MatraixWebReadiness,
    MatraixWebTasksResponse,
    MatraixWebTrial,
)
from app.matraix_web.errors import (
    MatraixWebEvaluationNotFoundError,
    MatraixWebScreenshotNotFoundError,
    MatraixWebSelectionError,
    MatraixWebTrialNotFoundError,
    MatraixWebUnavailableError,
)
from app.matraix_web.repository import (
    create_web_evaluation,
    get_web_evaluation,
    get_web_readiness,
    get_web_screenshot,
    get_web_trial,
    list_web_evaluations,
    list_web_tasks,
)
from app.populations.errors import PopulationCohortNotFoundError

WEB_UNAVAILABLE_DETAIL = "MatrAIx Web data is unavailable because DATABASE_URL is not configured"
WEB_ARTIFACT_ROOT = Path("/web-artifacts")
WEB_LIST_QUERY_FIELDS = frozenset({"page", "page_size"})


async def require_web_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=WEB_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


WebSession = Annotated[AsyncSession, Depends(require_web_session)]


def _validate_list_query(request: Request) -> None:
    unknown = sorted(set(request.query_params) - WEB_LIST_QUERY_FIELDS)
    repeated = [
        field
        for field in sorted(WEB_LIST_QUERY_FIELDS)
        if len(request.query_params.getlist(field)) > 1
    ]
    if unknown or repeated:
        fragments = []
        if unknown:
            fragments.append(f"unknown query fields: {', '.join(unknown)}")
        if repeated:
            fragments.append(f"repeated query fields: {', '.join(repeated)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(fragments),
        )


def _query_integer(request: Request, field: str, fallback: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(field)
    if raw is None:
        return fallback
    if not raw.isdecimal():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be an integer",
        )
    value = int(raw)
    if not minimum <= value <= maximum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be between {minimum} and {maximum}",
        )
    return value


def create_matraix_web_router() -> APIRouter:
    router = APIRouter(tags=["matraix-web"])

    @router.get("/api/v2/matraix/web-tasks", response_model=MatraixWebTasksResponse)
    async def web_tasks() -> MatraixWebTasksResponse:
        return list_web_tasks()

    @router.post(
        "/api/v2/matraix/web-evaluations",
        response_model=MatraixWebEvaluationDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_web_evaluation(
        body: MatraixWebEvaluationCreateRequest,
        session: WebSession,
    ) -> MatraixWebEvaluationDetail:
        try:
            return await create_web_evaluation(session, body)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixWebSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except MatraixWebUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/web-evaluations",
        response_model=MatraixWebEvaluationsResponse,
    )
    async def web_evaluations(
        request: Request,
        session: WebSession,
    ) -> MatraixWebEvaluationsResponse:
        _validate_list_query(request)
        page = _query_integer(request, "page", 1, 1, 2_147_483_647)
        page_size = _query_integer(request, "page_size", 20, 1, 50)
        try:
            return await list_web_evaluations(session, page, page_size)
        except MatraixWebSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/web-evaluations/{evaluation_id}",
        response_model=MatraixWebEvaluationDetail,
    )
    async def web_evaluation(
        evaluation_id: UUID,
        session: WebSession,
    ) -> MatraixWebEvaluationDetail:
        try:
            return await get_web_evaluation(session, evaluation_id)
        except MatraixWebEvaluationNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/web-trials/{trial_id}",
        response_model=MatraixWebTrial,
    )
    async def web_trial(trial_id: UUID, session: WebSession) -> MatraixWebTrial:
        try:
            return await get_web_trial(session, trial_id)
        except MatraixWebTrialNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/api/v2/matraix/web-trials/{trial_id}/screenshots/{page_position}")
    async def web_screenshot(
        trial_id: UUID,
        page_position: int,
        session: WebSession,
    ) -> FileResponse:
        if not 0 <= page_position <= 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="page_position must be between 0 and 2",
            )
        try:
            path, digest = await get_web_screenshot(
                session,
                WEB_ARTIFACT_ROOT,
                trial_id,
                page_position,
            )
        except MatraixWebScreenshotNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixWebUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        return FileResponse(
            path,
            media_type="image/png",
            headers={
                "Cache-Control": "private, max-age=31536000, immutable",
                "ETag": f'"sha256-{digest}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get(
        "/api/v2/matraix/web-readiness",
        response_model=MatraixWebReadiness,
    )
    async def web_readiness(session: WebSession) -> MatraixWebReadiness:
        return await get_web_readiness(session)

    return router
