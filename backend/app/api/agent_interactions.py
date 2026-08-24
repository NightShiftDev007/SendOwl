"""HTTP boundary for native Agent Interaction."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_interactions.contracts import (
    AgentInteraction,
    AgentInteractionContext,
    AgentInteractionRequest,
    AgentInteractionsResponse,
)
from app.agent_interactions.errors import (
    AgentInteractionNotFoundError,
    AgentInteractionUnavailableError,
)
from app.agent_interactions.repository import (
    enqueue_agent_interaction,
    get_agent_interaction,
    get_agent_interaction_context,
    list_agent_interactions,
)
from app.database import DatabaseConnector
from app.report_agents.errors import ReportAgentDraftNotFoundError

UNAVAILABLE_DETAIL = "Agent Interaction is unavailable because DATABASE_URL is not configured"


async def require_agent_interaction_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


AgentInteractionSession = Annotated[AsyncSession, Depends(require_agent_interaction_session)]


def create_agent_interactions_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2", tags=["agent-interactions"])

    @router.post(
        "/report-agent/drafts/{draft_id}/interactions",
        response_model=AgentInteraction,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create(
        draft_id: UUID,
        request: AgentInteractionRequest,
        session: AgentInteractionSession,
    ) -> AgentInteraction:
        try:
            return await enqueue_agent_interaction(session, draft_id, request)
        except (AgentInteractionNotFoundError, ReportAgentDraftNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except AgentInteractionUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/report-agent/drafts/{draft_id}/interactions",
        response_model=AgentInteractionsResponse,
    )
    async def index(draft_id: UUID, session: AgentInteractionSession) -> AgentInteractionsResponse:
        try:
            return await list_agent_interactions(session, draft_id)
        except ReportAgentDraftNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except AgentInteractionUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/agent-interactions/{interaction_id}", response_model=AgentInteraction)
    async def detail(interaction_id: UUID, session: AgentInteractionSession) -> AgentInteraction:
        try:
            return await get_agent_interaction(session, interaction_id)
        except AgentInteractionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/agent-interactions/{interaction_id}/context",
        response_model=AgentInteractionContext,
    )
    async def context(
        interaction_id: UUID, session: AgentInteractionSession
    ) -> AgentInteractionContext:
        try:
            return await get_agent_interaction_context(session, interaction_id)
        except AgentInteractionNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except AgentInteractionUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    return router


__all__ = ["create_agent_interactions_router", "require_agent_interaction_session"]
