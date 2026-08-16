"""HTTP boundary for immutable Policy evidence."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.policy_evidence.contracts import (
    PolicyDocumentCaptureRequest,
    PolicyDocumentDetail,
    PolicyDocumentsResponse,
    PolicyVersionCaptureRequest,
    PolicyVersionContent,
)
from app.policy_evidence.errors import (
    PolicyDocumentNotFoundError,
    PolicyEvidenceSelectionError,
    PolicyVersionNotFoundError,
)
from app.policy_evidence.repository import (
    append_policy_version,
    capture_policy_document,
    get_policy_document,
    get_policy_version_content,
    list_policy_documents,
)
from app.shared.pagination import parse_page_request

POLICY_EVIDENCE_UNAVAILABLE_DETAIL = (
    "Policy evidence is unavailable because DATABASE_URL is not configured"
)


async def require_policy_evidence_session(request: Request) -> AsyncIterator[AsyncSession]:
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=POLICY_EVIDENCE_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


PolicyEvidenceSession = Annotated[AsyncSession, Depends(require_policy_evidence_session)]


def create_policy_evidence_router() -> APIRouter:
    router = APIRouter(prefix="/api/v2/policy-documents", tags=["policy-evidence"])

    @router.post("", response_model=PolicyDocumentDetail, status_code=status.HTTP_201_CREATED)
    async def capture_document(
        body: PolicyDocumentCaptureRequest,
        session: PolicyEvidenceSession,
    ) -> PolicyDocumentDetail:
        try:
            return await capture_policy_document(session, body)
        except PolicyEvidenceSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("", response_model=PolicyDocumentsResponse)
    async def documents(
        request: Request,
        session: PolicyEvidenceSession,
    ) -> PolicyDocumentsResponse:
        pagination = parse_page_request(request, 20, 50)
        try:
            return await list_policy_documents(session, pagination.page, pagination.page_size)
        except PolicyEvidenceSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("/{document_id}", response_model=PolicyDocumentDetail)
    async def document(
        document_id: UUID,
        session: PolicyEvidenceSession,
    ) -> PolicyDocumentDetail:
        try:
            return await get_policy_document(session, document_id)
        except PolicyDocumentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.post(
        "/{document_id}/versions",
        response_model=PolicyDocumentDetail,
        status_code=status.HTTP_201_CREATED,
    )
    async def capture_version(
        document_id: UUID,
        body: PolicyVersionCaptureRequest,
        session: PolicyEvidenceSession,
    ) -> PolicyDocumentDetail:
        try:
            return await append_policy_version(session, document_id, body)
        except PolicyDocumentNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PolicyEvidenceSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get(
        "/{document_id}/versions/{version_id}/content",
        response_model=PolicyVersionContent,
    )
    async def version_content(
        document_id: UUID,
        version_id: UUID,
        session: PolicyEvidenceSession,
    ) -> PolicyVersionContent:
        try:
            return await get_policy_version_content(session, document_id, version_id)
        except (PolicyDocumentNotFoundError, PolicyVersionNotFoundError) as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router


__all__ = ["create_policy_evidence_router", "require_policy_evidence_session"]
