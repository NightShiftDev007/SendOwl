"""HTTP boundary for immutable Evidence Bundle projections."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.evidence.contracts import (
    EvidenceBundleContent,
    EvidenceBundleDetail,
    EvidenceBundlesResponse,
)
from app.evidence.errors import EvidenceBundleItemNotFoundError, EvidenceBundleNotFoundError
from app.evidence.repository import (
    get_evidence_bundle,
    get_evidence_bundle_content,
    list_evidence_bundles,
)

EVIDENCE_BUNDLES_UNAVAILABLE_DETAIL = (
    "Evidence bundles are unavailable because DATABASE_URL is not configured"
)


async def require_evidence_bundle_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EVIDENCE_BUNDLES_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


EvidenceBundleSession = Annotated[AsyncSession, Depends(require_evidence_bundle_session)]


def create_evidence_bundles_router() -> APIRouter:
    """Create read-only routes backed solely by sealed world snapshots."""
    router = APIRouter(prefix="/api/v2/evidence-bundles", tags=["evidence-bundles"])

    @router.get("", response_model=EvidenceBundlesResponse)
    async def index(session: EvidenceBundleSession) -> EvidenceBundlesResponse:
        return await list_evidence_bundles(session)

    @router.get("/{bundle_id}", response_model=EvidenceBundleDetail)
    async def detail(bundle_id: UUID, session: EvidenceBundleSession) -> EvidenceBundleDetail:
        try:
            return await get_evidence_bundle(session, bundle_id)
        except EvidenceBundleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/{bundle_id}/items/{article_id}/content",
        response_model=EvidenceBundleContent,
    )
    async def content(
        bundle_id: UUID,
        article_id: UUID,
        session: EvidenceBundleSession,
    ) -> EvidenceBundleContent:
        try:
            return await get_evidence_bundle_content(session, bundle_id, article_id)
        except (EvidenceBundleNotFoundError, EvidenceBundleItemNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router


__all__ = ["create_evidence_bundles_router", "require_evidence_bundle_session"]
