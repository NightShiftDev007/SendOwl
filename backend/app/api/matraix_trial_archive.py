"""Read-only HTTP boundary for the unified MatrAIx trial archive."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_chat.errors import MatraixChatTrialNotFoundError
from app.matraix_linux.errors import MatraixLinuxTrialNotFoundError
from app.matraix_surveys.errors import MatraixSurveyTrialNotFoundError
from app.matraix_trial_archive.contracts import (
    MatraixTrialArchiveResponse,
    MatraixTrialIntegrityVerification,
    MatraixTrialKind,
    MatraixTrialStatus,
)
from app.matraix_trial_archive.errors import MatraixTrialArchivePageOutOfRangeError
from app.matraix_trial_archive.repository import (
    list_matraix_trial_archive,
    verify_trial_integrity,
)
from app.matraix_web.errors import MatraixWebTrialNotFoundError

TRIAL_ARCHIVE_UNAVAILABLE_DETAIL = (
    "MatrAIx Trial Archive data is unavailable because DATABASE_URL is not configured"
)
TRIAL_ARCHIVE_QUERY_FIELDS = frozenset({"page", "page_size", "kind", "status"})


async def require_trial_archive_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=TRIAL_ARCHIVE_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


TrialArchiveSession = Annotated[AsyncSession, Depends(require_trial_archive_session)]


def _validate_query_shape(request: Request) -> None:
    unknown = sorted(set(request.query_params) - TRIAL_ARCHIVE_QUERY_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported MatrAIx Trial Archive query fields: {', '.join(unknown)}",
        )
    repeated = tuple(
        field
        for field in ("page", "page_size", "kind", "status")
        if len(request.query_params.getlist(field)) > 1
    )
    if repeated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"MatrAIx Trial Archive query fields must not repeat: {', '.join(repeated)}",
        )


def create_matraix_trial_archive_router() -> APIRouter:
    router = APIRouter(tags=["matraix-trial-archive"])

    @router.get(
        "/api/v2/matraix/trials",
        response_model=MatraixTrialArchiveResponse,
    )
    async def trial_archive(
        request: Request,
        session: TrialArchiveSession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        kind: Annotated[MatraixTrialKind | None, Query()] = None,
        trial_status: Annotated[
            MatraixTrialStatus | None,
            Query(alias="status"),
        ] = None,
    ) -> MatraixTrialArchiveResponse:
        _validate_query_shape(request)
        try:
            return await list_matraix_trial_archive(
                session,
                page,
                page_size,
                kind,
                trial_status,
            )
        except MatraixTrialArchivePageOutOfRangeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/trials/{kind}/{trial_id}/verification",
        response_model=MatraixTrialIntegrityVerification,
    )
    async def trial_integrity_verification(
        request: Request,
        kind: MatraixTrialKind,
        trial_id: UUID,
        session: TrialArchiveSession,
    ) -> MatraixTrialIntegrityVerification:
        if request.query_params:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="MatrAIx Trial integrity verification does not accept query fields",
            )
        try:
            return await verify_trial_integrity(session, kind, trial_id)
        except (
            MatraixSurveyTrialNotFoundError,
            MatraixChatTrialNotFoundError,
            MatraixWebTrialNotFoundError,
            MatraixLinuxTrialNotFoundError,
        ) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router


__all__ = ["create_matraix_trial_archive_router", "require_trial_archive_session"]
