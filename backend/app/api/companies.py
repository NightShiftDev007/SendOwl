"""HTTP boundary for monitored companies and deterministic media coverage."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.contracts import (
    CompaniesResponse,
    CompanyCoverageResponse,
    CompanyCreateRequest,
    CompanyItem,
)
from app.companies.errors import CompanyAliasConflictError, CompanyNotFoundError
from app.companies.repository import create_company, get_company_coverage, list_companies
from app.database import DatabaseConnector

COMPANIES_UNAVAILABLE_DETAIL = "Company data is unavailable because DATABASE_URL is not configured"


async def require_company_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one database session or fail explicitly when companies are unavailable."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=COMPANIES_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


CompanySession = Annotated[AsyncSession, Depends(require_company_session)]


def create_companies_router() -> APIRouter:
    """Create strict monitored-company routes."""
    router = APIRouter(prefix="/api/v2/companies", tags=["companies"])

    @router.get("", response_model=CompaniesResponse)
    async def companies(session: CompanySession) -> CompaniesResponse:
        """List persisted monitored companies."""
        return await list_companies(session)

    @router.post("", response_model=CompanyItem, status_code=status.HTTP_201_CREATED)
    async def add_company(
        request: CompanyCreateRequest,
        session: CompanySession,
    ) -> CompanyItem:
        """Create one globally unambiguous monitored-company identity."""
        try:
            return await create_company(session, request)
        except CompanyAliasConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @router.get("/{company_id}/coverage", response_model=CompanyCoverageResponse)
    async def coverage(
        company_id: UUID,
        session: CompanySession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> CompanyCoverageResponse:
        """Return exact article evidence for one monitored company."""
        try:
            return await get_company_coverage(session, company_id, page, page_size)
        except CompanyNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    return router
