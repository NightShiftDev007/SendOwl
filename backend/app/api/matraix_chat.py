"""HTTP boundary for durable MatrAIx source-sample chatbot evaluations."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.matraix_chat.contracts import (
    MatraixChatEvaluationCreateRequest,
    MatraixChatEvaluationDetail,
    MatraixChatEvaluationsResponse,
    MatraixChatReadiness,
    MatraixChatTasksResponse,
    MatraixChatTrial,
)
from app.matraix_chat.errors import (
    MatraixChatEvaluationNotFoundError,
    MatraixChatSelectionError,
    MatraixChatTrialNotFoundError,
    MatraixChatUnavailableError,
)
from app.matraix_chat.repository import (
    create_chat_evaluation,
    get_chat_evaluation,
    get_chat_evaluation_progress,
    get_chat_readiness,
    get_chat_trial,
    list_chat_evaluations,
    list_chat_tasks,
    retry_chat_evaluation,
)
from app.matraix_chat.trajectory import (
    MatraixChatAtifProjection,
    MatraixChatTrajectoryUnavailableError,
    project_chat_trial_atif,
)
from app.populations.errors import PopulationCohortNotFoundError
from app.shared.pagination import parse_page_request
from app.shared.progress import ParentProgress

CHAT_UNAVAILABLE_DETAIL = "MatrAIx Chat data is unavailable because DATABASE_URL is not configured"


async def require_chat_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=CHAT_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


ChatSession = Annotated[AsyncSession, Depends(require_chat_session)]


def create_matraix_chat_router() -> APIRouter:
    router = APIRouter(tags=["matraix-chat"])

    @router.get(
        "/api/v2/matraix/chat-tasks",
        response_model=MatraixChatTasksResponse,
    )
    async def chat_tasks() -> MatraixChatTasksResponse:
        return list_chat_tasks()

    @router.post(
        "/api/v2/matraix/chat-evaluations",
        response_model=MatraixChatEvaluationDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def enqueue_chat_evaluation(
        request: MatraixChatEvaluationCreateRequest,
        session: ChatSession,
    ) -> MatraixChatEvaluationDetail:
        try:
            return await create_chat_evaluation(session, request)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixChatSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        except MatraixChatUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/chat-evaluations",
        response_model=MatraixChatEvaluationsResponse,
    )
    async def chat_evaluations(
        request: Request,
        session: ChatSession,
    ) -> MatraixChatEvaluationsResponse:
        pagination = parse_page_request(request, 20, 50)
        try:
            return await list_chat_evaluations(
                session,
                pagination.page,
                pagination.page_size,
            )
        except MatraixChatSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.post(
        "/api/v2/matraix/chat-evaluations/{evaluation_id}/retry",
        response_model=MatraixChatEvaluationDetail,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_evaluation(
        evaluation_id: UUID,
        session: ChatSession,
    ) -> MatraixChatEvaluationDetail:
        try:
            return await retry_chat_evaluation(session, evaluation_id)
        except MatraixChatEvaluationNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixChatSelectionError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except MatraixChatUnavailableError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @router.get(
        "/api/v2/matraix/chat-evaluations/{evaluation_id}/progress",
        response_model=ParentProgress,
    )
    async def chat_evaluation_progress(
        evaluation_id: UUID,
        session: ChatSession,
    ) -> ParentProgress:
        try:
            return await get_chat_evaluation_progress(session, evaluation_id)
        except MatraixChatEvaluationNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/chat-evaluations/{evaluation_id}",
        response_model=MatraixChatEvaluationDetail,
    )
    async def chat_evaluation(
        evaluation_id: UUID,
        session: ChatSession,
    ) -> MatraixChatEvaluationDetail:
        try:
            return await get_chat_evaluation(session, evaluation_id)
        except MatraixChatEvaluationNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/chat-trials/{trial_id}",
        response_model=MatraixChatTrial,
    )
    async def chat_trial(trial_id: UUID, session: ChatSession) -> MatraixChatTrial:
        try:
            return await get_chat_trial(session, trial_id)
        except MatraixChatTrialNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/chat-trials/{trial_id}/trajectory",
        response_model=MatraixChatAtifProjection,
    )
    async def chat_trial_trajectory(
        trial_id: UUID,
        session: ChatSession,
    ) -> MatraixChatAtifProjection:
        try:
            return project_chat_trial_atif(await get_chat_trial(session, trial_id))
        except MatraixChatTrialNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MatraixChatTrajectoryUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get(
        "/api/v2/matraix/chat-readiness",
        response_model=MatraixChatReadiness,
    )
    async def chat_readiness(session: ChatSession) -> MatraixChatReadiness:
        return await get_chat_readiness(session)

    return router
