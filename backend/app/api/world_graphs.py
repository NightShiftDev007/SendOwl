"""HTTP boundary for queued, evidence-backed semantic world graphs."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.populations.errors import PopulationDatasetNotFoundError
from app.world_graphs.contracts import (
    GraphPersonaCohortCreateRequest,
    GraphPersonaCohortCreation,
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdgeHistory,
    SemanticWorldGraphEvidenceTimeline,
    SemanticWorldGraphPersonaMatches,
    SemanticWorldGraphSearchResponse,
    SemanticWorldGraphSlice,
    SemanticWorldGraphsResponse,
    WorldGraphSliceDirection,
)
from app.world_graphs.errors import (
    WorldGraphEdgeNotFoundError,
    WorldGraphNodeNotFoundError,
    WorldGraphNotFoundError,
    WorldGraphNotReadyError,
    WorldGraphPersonaSelectionError,
    WorldGraphUnavailableError,
)
from app.world_graphs.repository import (
    create_graph_persona_cohort,
    enqueue_semantic_world_graph,
    get_semantic_world_graph,
    get_semantic_world_graph_edge_history,
    get_semantic_world_graph_persona_matches,
    get_semantic_world_graph_slice,
    get_semantic_world_graph_timeline,
    list_snapshot_semantic_world_graphs,
    search_world_graph,
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
        if request.method == "GET":
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


WorldGraphSession = Annotated[AsyncSession, Depends(require_world_graph_session)]
WorldGraphRootNode = Annotated[UUID, Query()]
WorldGraphDirection = Annotated[WorldGraphSliceDirection, Query()]
WorldGraphHops = Annotated[int, Query(ge=1, le=3)]
WorldGraphMaxNodes = Annotated[int, Query(ge=2, le=100)]
WorldGraphSearchLimit = Annotated[int, Query(ge=1, le=50)]
WorldGraphPersonaLimit = Annotated[int, Query(ge=1, le=20)]


def _validate_search_query(request: Request, raw_query: str) -> str:
    unknown = sorted(set(request.query_params) - {"q", "limit"})
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported semantic world graph search fields: {', '.join(unknown)}",
        )
    repeated = tuple(
        field for field in ("q", "limit") if len(request.query_params.getlist(field)) > 1
    )
    if repeated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"semantic world graph search fields must not repeat: {', '.join(repeated)}",
        )
    query = raw_query.strip()
    if len(query) < 2 or len(query) > 100 or "\r" in query or "\n" in query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="semantic world graph search q must be one line containing 2..100 characters",
        )
    return query


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

    @router.get(
        "/api/v2/world-graphs/{graph_id}/search",
        response_model=SemanticWorldGraphSearchResponse,
    )
    async def graph_search(
        request: Request,
        graph_id: UUID,
        session: WorldGraphSession,
        q: Annotated[str, Query(min_length=2, max_length=100)],
        limit: WorldGraphSearchLimit = 20,
    ) -> SemanticWorldGraphSearchResponse:
        query = _validate_search_query(request, q)
        try:
            return await search_world_graph(session, graph_id, query, limit)
        except WorldGraphNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/world-graphs/{graph_id}/edges/{edge_id}/history",
        response_model=SemanticWorldGraphEdgeHistory,
    )
    async def graph_edge_history(
        request: Request,
        graph_id: UUID,
        edge_id: UUID,
        session: WorldGraphSession,
    ) -> SemanticWorldGraphEdgeHistory:
        if request.query_params:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="semantic world graph edge history does not accept query fields",
            )
        try:
            return await get_semantic_world_graph_edge_history(session, graph_id, edge_id)
        except (WorldGraphNotFoundError, WorldGraphEdgeNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/world-graphs/{graph_id}/nodes/{node_id}/persona-matches",
        response_model=SemanticWorldGraphPersonaMatches,
    )
    async def graph_persona_matches(
        request: Request,
        graph_id: UUID,
        node_id: UUID,
        session: WorldGraphSession,
        dataset_id: Annotated[UUID, Query()],
        limit: WorldGraphPersonaLimit = 20,
    ) -> SemanticWorldGraphPersonaMatches:
        unknown = sorted(set(request.query_params) - {"dataset_id", "limit"})
        repeated = tuple(
            field
            for field in ("dataset_id", "limit")
            if len(request.query_params.getlist(field)) > 1
        )
        if unknown or repeated:
            detail = (
                f"unsupported Persona match query fields: {', '.join(unknown)}"
                if unknown
                else f"Persona match query fields must not repeat: {', '.join(repeated)}"
            )
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
        try:
            return await get_semantic_world_graph_persona_matches(
                session,
                graph_id,
                node_id,
                dataset_id,
                limit,
            )
        except (
            WorldGraphNotFoundError,
            WorldGraphNodeNotFoundError,
            PopulationDatasetNotFoundError,
        ) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except WorldGraphNotReadyError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.post(
        "/api/v2/world-graphs/{graph_id}/nodes/{node_id}/cohorts",
        response_model=GraphPersonaCohortCreation,
        status_code=status.HTTP_201_CREATED,
    )
    async def graph_persona_cohort(
        request: Request,
        graph_id: UUID,
        node_id: UUID,
        body: GraphPersonaCohortCreateRequest,
        session: WorldGraphSession,
    ) -> GraphPersonaCohortCreation:
        if request.query_params:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="graph Persona cohort creation does not accept query fields",
            )
        try:
            return await create_graph_persona_cohort(session, graph_id, node_id, body)
        except (
            WorldGraphNotFoundError,
            WorldGraphNodeNotFoundError,
            PopulationDatasetNotFoundError,
        ) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except (WorldGraphNotReadyError, WorldGraphPersonaSelectionError) as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    return router
