"""HTTP boundary for persistent decision task context."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.decision_threads.contracts import (
    DecisionThreadContextCreate,
    DecisionThreadCreateRequest,
    DecisionThreadDetail,
    DecisionThreadDraftCreateRequest,
    DecisionThreadsResponse,
)
from app.decision_threads.errors import DecisionThreadNotFoundError, DecisionThreadSelectionError
from app.decision_threads.repository import (
    append_decision_thread_revision,
    create_decision_thread,
    create_decision_thread_draft,
    get_decision_thread,
    list_decision_threads,
)
from app.legacy_adc import reject_legacy_adc_write
from app.populations.errors import PopulationCohortNotFoundError
from app.scenarios.errors import ScenarioNotFoundError
from app.semantic_experiments.errors import SemanticExperimentNotFoundError
from app.world_models.errors import WorldModelNotFoundError, WorldSnapshotNotFoundError


async def require_decision_thread_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Decision threads are unavailable because DATABASE_URL is not configured",
        )
    async with connector.session() as session:
        yield session


DecisionThreadSession = Annotated[AsyncSession, Depends(require_decision_thread_session)]


def create_decision_threads_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/decision-threads", tags=["decision-threads"])
    missing_errors = (
        DecisionThreadNotFoundError,
        WorldModelNotFoundError,
        WorldSnapshotNotFoundError,
        ScenarioNotFoundError,
        PopulationCohortNotFoundError,
        SemanticExperimentNotFoundError,
    )

    @router.get("", response_model=DecisionThreadsResponse)
    async def index(session: DecisionThreadSession) -> DecisionThreadsResponse:
        return await list_decision_threads(session)

    @router.post(
        "",
        response_model=DecisionThreadDetail,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def create(
        request: DecisionThreadCreateRequest,
        session: DecisionThreadSession,
    ) -> DecisionThreadDetail:
        try:
            return await create_decision_thread(session, request)
        except missing_errors as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except DecisionThreadSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error

    @router.post(
        "/drafts",
        response_model=DecisionThreadDetail,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def create_draft(
        request: DecisionThreadDraftCreateRequest,
        session: DecisionThreadSession,
    ) -> DecisionThreadDetail:
        return await create_decision_thread_draft(session, request)

    @router.get("/{thread_id}", response_model=DecisionThreadDetail)
    async def detail(thread_id: UUID, session: DecisionThreadSession) -> DecisionThreadDetail:
        try:
            return await get_decision_thread(session, thread_id)
        except DecisionThreadNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/{thread_id}/revisions",
        response_model=DecisionThreadDetail,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(reject_legacy_adc_write)],
    )
    async def append_revision(
        thread_id: UUID,
        request: DecisionThreadContextCreate,
        session: DecisionThreadSession,
    ) -> DecisionThreadDetail:
        try:
            return await append_decision_thread_revision(session, thread_id, request)
        except missing_errors as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except DecisionThreadSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error

    return router
