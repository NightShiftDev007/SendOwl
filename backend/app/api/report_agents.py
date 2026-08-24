"""HTTP boundary for bounded, audited ReportAgent evidence tools."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.report_agents.contracts import (
    ReportAgentCitedDraft,
    ReportAgentDraftsResponse,
    ReportAgentEvidenceDirectoryResult,
    ReportAgentMediaReadResult,
    ReportAgentPolicyReadResult,
    ReportAgentRun,
    ReportAgentRunRequest,
)
from app.report_agents.errors import (
    ReportAgentDraftNotFoundError,
    ReportAgentDraftRetryError,
    ReportAgentDraftUnavailableError,
    ReportAgentRunNotFoundError,
    ReportAgentScopeError,
    ReportAgentToolBudgetExhaustedError,
)
from app.report_agents.repository import (
    create_report_agent_run,
    enqueue_report_agent_draft,
    get_report_agent_draft,
    get_report_agent_run,
    list_report_agent_drafts,
    list_report_agent_evidence,
    read_report_agent_media,
    read_report_agent_policy,
    retry_report_agent_draft,
)

REPORT_AGENTS_UNAVAILABLE_DETAIL = (
    "ReportAgent evidence tools are unavailable because DATABASE_URL is not configured"
)


async def require_report_agent_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=REPORT_AGENTS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


ReportAgentSession = Annotated[AsyncSession, Depends(require_report_agent_session)]


def create_report_agents_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/report-agent", tags=["report-agent"])

    @router.post(
        "/runs",
        response_model=ReportAgentRun,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_run(
        request: ReportAgentRunRequest,
        session: ReportAgentSession,
    ) -> ReportAgentRun:
        try:
            return await create_report_agent_run(session, request)
        except ReportAgentScopeError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/runs/{run_id}", response_model=ReportAgentRun)
    async def get_run(run_id: UUID, session: ReportAgentSession) -> ReportAgentRun:
        try:
            return await get_report_agent_run(session, run_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/runs/{run_id}/drafts",
        response_model=ReportAgentCitedDraft,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_draft(
        run_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentCitedDraft:
        try:
            return await enqueue_report_agent_draft(session, run_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportAgentDraftUnavailableError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.get("/runs/{run_id}/drafts", response_model=ReportAgentDraftsResponse)
    async def list_drafts(
        run_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentDraftsResponse:
        try:
            return await list_report_agent_drafts(session, run_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/drafts/{draft_id}", response_model=ReportAgentCitedDraft)
    async def get_draft(
        draft_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentCitedDraft:
        try:
            return await get_report_agent_draft(session, draft_id)
        except ReportAgentDraftNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/drafts/{draft_id}/retry",
        response_model=ReportAgentCitedDraft,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_draft(
        draft_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentCitedDraft:
        try:
            return await retry_report_agent_draft(session, draft_id)
        except ReportAgentDraftNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportAgentDraftRetryError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    @router.post(
        "/runs/{run_id}/tools/list-evidence",
        response_model=ReportAgentEvidenceDirectoryResult,
    )
    async def list_evidence(
        run_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentEvidenceDirectoryResult:
        try:
            return await list_report_agent_evidence(session, run_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportAgentScopeError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ReportAgentToolBudgetExhaustedError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(error),
            ) from error

    @router.post(
        "/runs/{run_id}/tools/read-media/{article_id}",
        response_model=ReportAgentMediaReadResult,
    )
    async def read_media(
        run_id: UUID,
        article_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentMediaReadResult:
        try:
            return await read_report_agent_media(session, run_id, article_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportAgentScopeError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ReportAgentToolBudgetExhaustedError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(error),
            ) from error

    @router.post(
        "/runs/{run_id}/tools/read-policy/{policy_version_id}",
        response_model=ReportAgentPolicyReadResult,
    )
    async def read_policy(
        run_id: UUID,
        policy_version_id: UUID,
        session: ReportAgentSession,
    ) -> ReportAgentPolicyReadResult:
        try:
            return await read_report_agent_policy(session, run_id, policy_version_id)
        except ReportAgentRunNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except ReportAgentScopeError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        except ReportAgentToolBudgetExhaustedError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(error),
            ) from error

    return router


__all__ = ["create_report_agents_router", "require_report_agent_session"]
