"""HTTP boundary for queued, evidence-backed semantic world graphs."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEvidenceTimeline,
    SemanticWorldGraphSlice,
    SemanticWorldGraphsResponse,
    WorldGraphSliceDirection,
)
from app.world_graphs.errors import (
    WorldGraphNodeNotFoundError,
    WorldGraphNotFoundError,
    WorldGraphNotReadyError,
    WorldGraphUnavailableError,
)
from app.world_graphs.repository import (
    enqueue_semantic_world_graph,
    get_semantic_world_graph,
    get_semantic_world_graph_slice,
    get_semantic_world_graph_timeline,
    list_snapshot_semantic_world_graphs,
)
from app.world_models.errors import WorldModelNotFoundError, WorldSnapshotNotFoundError

WORLD_GRAPHS_UNAVAILABLE_DETAIL = (
    "Semantic world graph data is unavailable because DATABASE_URL is not configured"
)


async def require_world_graph_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=WORLD_GRAPHS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


WorldGraphSession = Annotated[AsyncSession, Depends(require_world_graph_session)]
WorldGraphRootNode = Annotated[UUID, Query()]
WorldGraphDirection = Annotated[WorldGraphSliceDirection, Query()]
WorldGraphHops = Annotated[int, Query(ge=1, le=3)]
WorldGraphMaxNodes = Annotated[int, Query(ge=2, le=100)]


def create_world_graphs_router() -> APIRouter:
    router = APIRouter(tags=["world-graphs"])

    @router.post(
        "/api/v2/world-models/{world_model_id}/snapshots/{snapshot_id}/semantic-graphs",
        response_model=SemanticWorldGraphDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_graph(
        world_model_id: UUID,
        snapshot_id: UUID,
        session: WorldGraphSession,
    ) -> SemanticWorldGraphDetail:
        try:
            return await enqueue_semantic_world_graph(session, world_model_id, snapshot_id)
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/world-models/{world_model_id}/snapshots/{snapshot_id}/semantic-graphs",
        response_model=SemanticWorldGraphsResponse,
    )
    async def snapshot_graphs(
        world_model_id: UUID,
        snapshot_id: UUID,
        session: WorldGraphSession,
    ) -> SemanticWorldGraphsResponse:
        try:
            return await list_snapshot_semantic_world_graphs(
                session,
                world_model_id,
                snapshot_id,
            )
        except (WorldModelNotFoundError, WorldSnapshotNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/world-graphs/{graph_id}",
        response_model=SemanticWorldGraphDetail,
    )
    async def graph(graph_id: UUID, session: WorldGraphSession) -> SemanticWorldGraphDetail:
        try:
            return await get_semantic_world_graph(session, graph_id)
        except WorldGraphNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/world-graphs/{graph_id}/slice",
        response_model=SemanticWorldGraphSlice,
    )
    async def graph_slice(
        graph_id: UUID,
        session: WorldGraphSession,
        root_node_id: WorldGraphRootNode,
        direction: WorldGraphDirection,
        hops: WorldGraphHops,
        max_nodes: WorldGraphMaxNodes,
    ) -> SemanticWorldGraphSlice:
        try:
            return await get_semantic_world_graph_slice(
                session,
                graph_id,
                root_node_id,
                direction,
                hops,
                max_nodes,
            )
        except (WorldGraphNotFoundError, WorldGraphNodeNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/world-graphs/{graph_id}/evidence-timeline",
        response_model=SemanticWorldGraphEvidenceTimeline,
    )
    async def graph_timeline(
        graph_id: UUID,
        session: WorldGraphSession,
    ) -> SemanticWorldGraphEvidenceTimeline:
        try:
            return await get_semantic_world_graph_timeline(session, graph_id)
        except WorldGraphNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    return router
