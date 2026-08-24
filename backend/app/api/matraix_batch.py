"""HTTP boundary for registry-only grouping of sealed MatrAIx parent runs."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_batch.contracts import (
    MatraixBatchKind,
    MatraixBatchRegistriesResponse,
    MatraixBatchRegistryCandidatesResponse,
    MatraixBatchRegistryCreateRequest,
    MatraixBatchRegistryDetail,
    MatraixNativeBatchLaunchRequest,
    MatraixNativeBatchLaunchResult,
)
from app.matraix_batch.errors import (
    MatraixBatchRegistryNotFoundError,
    MatraixBatchRegistryPageOutOfRangeError,
)
from app.matraix_batch.repository import (
    create_batch_registry,
    create_native_batch_launch,
    get_batch_registry,
    list_batch_registries,
    list_batch_registry_candidates,
)
from app.matraix_chat.errors import MatraixChatSelectionError, MatraixChatUnavailableError
from app.populations.errors import PopulationCohortNotFoundError
from app.research_surveys.errors import ResearchSurveySelectionError, ResearchSurveyUnavailableError

BATCH_REGISTRY_UNAVAILABLE_DETAIL = (
    "MatrAIx Batch Registry data is unavailable because DATABASE_URL is not configured"
)
LIST_QUERY_FIELDS = frozenset({"page", "page_size"})
CANDIDATE_QUERY_FIELDS = frozenset({"page", "page_size", "kind"})


async def require_batch_registry_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BATCH_REGISTRY_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        if request.method == "GET":
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


BatchRegistrySession = Annotated[AsyncSession, Depends(require_batch_registry_session)]


def _validate_query_shape(request: Request, allowed: frozenset[str]) -> None:
    unknown = sorted(set(request.query_params) - allowed)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported MatrAIx Batch Registry query fields: {', '.join(unknown)}",
        )
    repeated = tuple(
        field for field in sorted(allowed) if len(request.query_params.getlist(field)) > 1
    )
    if repeated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"MatrAIx Batch Registry query fields must not repeat: {', '.join(repeated)}",
        )


def create_matraix_batch_router() -> APIRouter:
    router = APIRouter(tags=["matraix-batch-registry"])

    @router.post(
        "/api/v2/matraix/batch-launches",
        response_model=MatraixNativeBatchLaunchResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def launch_native_batch(
        request: MatraixNativeBatchLaunchRequest,
        session: BatchRegistrySession,
    ) -> MatraixNativeBatchLaunchResult:
        try:
            return await create_native_batch_launch(session, request)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (ResearchSurveySelectionError, MatraixChatSelectionError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except (ResearchSurveyUnavailableError, MatraixChatUnavailableError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.post(
        "/api/v2/matraix/batch-registries",
        response_model=MatraixBatchRegistryDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def register_batch(
        request: MatraixBatchRegistryCreateRequest,
        session: BatchRegistrySession,
    ) -> MatraixBatchRegistryDetail:
        try:
            return await create_batch_registry(session, request)
        except MatraixBatchRegistryNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/batch-registries",
        response_model=MatraixBatchRegistriesResponse,
    )
    async def batch_registries(
        request: Request,
        session: BatchRegistrySession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MatraixBatchRegistriesResponse:
        _validate_query_shape(request, LIST_QUERY_FIELDS)
        try:
            return await list_batch_registries(session, page, page_size)
        except MatraixBatchRegistryPageOutOfRangeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error

    @router.get(
        "/api/v2/matraix/batch-registries/{registry_id}",
        response_model=MatraixBatchRegistryDetail,
    )
    async def batch_registry(
        registry_id: UUID,
        session: BatchRegistrySession,
    ) -> MatraixBatchRegistryDetail:
        try:
            return await get_batch_registry(session, registry_id)
        except MatraixBatchRegistryNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/batch-registry-candidates",
        response_model=MatraixBatchRegistryCandidatesResponse,
    )
    async def batch_registry_candidates(
        request: Request,
        session: BatchRegistrySession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        kind: Annotated[MatraixBatchKind | None, Query()] = None,
    ) -> MatraixBatchRegistryCandidatesResponse:
        _validate_query_shape(request, CANDIDATE_QUERY_FIELDS)
        try:
            return await list_batch_registry_candidates(session, page, page_size, kind)
        except MatraixBatchRegistryPageOutOfRangeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
            ) from error

    return router


__all__ = ["create_matraix_batch_router", "require_batch_registry_session"]
