"""HTTP boundary for persistent world models and immutable snapshots."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.world_models.contracts import (
    ModelDetail,
    SnapshotDetail,
    SnapshotEvidenceContent,
    WorldModelCreateRequest,
    WorldModelsResponse,
    WorldSnapshotCreateRequest,
)
from app.world_models.errors import (
    SnapshotEvidenceLimitError,
    SnapshotEvidenceSelectionError,
    WorldModelNotFoundError,
    WorldSnapshotEvidenceNotFoundError,
    WorldSnapshotNotFoundError,
    WorldSnapshotRevisionConflictError,
)
from app.world_models.graph import get_evidence_world_graph
from app.world_models.graph_contracts import EvidenceWorldGraph
from app.world_models.repository import (
    append_world_snapshot,
    create_world_model,
    get_world_model,
    get_world_snapshot,
    get_world_snapshot_evidence_content,
    list_world_models,
)

WORLD_MODELS_UNAVAILABLE_DETAIL = (
    "World model data is unavailable because DATABASE_URL is not configured"
)


async def require_world_model_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one database session or fail explicitly when persistence is unavailable."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=WORLD_MODELS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


WorldModelSession = Annotated[AsyncSession, Depends(require_world_model_session)]


def _not_found(
    error: (
        WorldModelNotFoundError | WorldSnapshotNotFoundError | WorldSnapshotEvidenceNotFoundError
    ),
) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _invalid_evidence(
    error: SnapshotEvidenceSelectionError | SnapshotEvidenceLimitError,
) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def _revision_conflict(error: WorldSnapshotRevisionConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def create_world_models_router() -> APIRouter:
    """Create append-only world-model routes."""
    router = APIRouter(prefix="/api/v2/world-models", tags=["world-models"])

    @router.post("", response_model=ModelDetail, status_code=status.HTTP_201_CREATED)
    async def add_world_model(
        request: WorldModelCreateRequest,
        session: WorldModelSession,
    ) -> ModelDetail:
        """Atomically create one model and version-one snapshot."""
        try:
            return await create_world_model(session, request)
        except SnapshotEvidenceSelectionError as error:
            raise _invalid_evidence(error) from error
        except SnapshotEvidenceLimitError as error:
            raise _invalid_evidence(error) from error
        except WorldSnapshotRevisionConflictError as error:
            raise _revision_conflict(error) from error

    @router.get("", response_model=WorldModelsResponse)
    async def world_models(session: WorldModelSession) -> WorldModelsResponse:
        """List persistent models and their latest immutable version."""
        return await list_world_models(session)

    @router.get("/{model_id}", response_model=ModelDetail)
    async def world_model(model_id: UUID, session: WorldModelSession) -> ModelDetail:
        """Return model history and the complete latest frozen snapshot."""
        try:
            return await get_world_model(session, model_id)
        except WorldModelNotFoundError as error:
            raise _not_found(error) from error

    @router.post(
        "/{model_id}/snapshots",
        response_model=SnapshotDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_snapshot(
        model_id: UUID,
        request: WorldSnapshotCreateRequest,
        session: WorldModelSession,
    ) -> SnapshotDetail:
        """Lock the model and append exactly one next-version snapshot."""
        try:
            return await append_world_snapshot(session, model_id, request)
        except WorldModelNotFoundError as error:
            raise _not_found(error) from error
        except SnapshotEvidenceSelectionError as error:
            raise _invalid_evidence(error) from error
        except SnapshotEvidenceLimitError as error:
            raise _invalid_evidence(error) from error
        except WorldSnapshotRevisionConflictError as error:
            raise _revision_conflict(error) from error

    @router.get("/{model_id}/snapshots/{snapshot_id}", response_model=SnapshotDetail)
    async def snapshot(
        model_id: UUID,
        snapshot_id: UUID,
        session: WorldModelSession,
    ) -> SnapshotDetail:
        """Return one immutable snapshot without joining mutable source tables."""
        try:
            return await get_world_snapshot(session, model_id, snapshot_id)
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise _not_found(error) from error

    @router.get(
        "/{model_id}/snapshots/{snapshot_id}/evidence-graph",
        response_model=EvidenceWorldGraph,
    )
    async def evidence_graph(
        model_id: UUID,
        snapshot_id: UUID,
        session: WorldModelSession,
    ) -> EvidenceWorldGraph:
        """Project direct frozen evidence relationships without Zep or inferred facts."""
        try:
            return await get_evidence_world_graph(session, model_id, snapshot_id)
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise _not_found(error) from error

    @router.get(
        "/{model_id}/snapshots/{snapshot_id}/evidence/{article_id}/content",
        response_model=SnapshotEvidenceContent,
    )
    async def snapshot_evidence_content(
        model_id: UUID,
        snapshot_id: UUID,
        article_id: UUID,
        session: WorldModelSession,
    ) -> SnapshotEvidenceContent:
        """Return exact text from frozen snapshot storage after digest verification."""
        try:
            return await get_world_snapshot_evidence_content(
                session,
                model_id,
                snapshot_id,
                article_id,
            )
        except (
            WorldModelNotFoundError,
            WorldSnapshotNotFoundError,
            WorldSnapshotEvidenceNotFoundError,
        ) as error:
            raise _not_found(error) from error

    return router
