"""HTTP boundary for immutable MatrAIx populations."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.populations.contracts import (
    CohortCreateRequest,
    CohortDetail,
    CohortsResponse,
    DatasetsResponse,
    PersonasResponse,
)
from app.populations.errors import (
    PopulationCohortNotFoundError,
    PopulationDatasetNotFoundError,
    PopulationPersonaSelectionError,
)
from app.populations.repository import (
    create_cohort,
    get_cohort,
    list_cohorts,
    list_datasets,
    list_personas,
)

POPULATIONS_UNAVAILABLE_DETAIL = (
    "Population data is unavailable because DATABASE_URL is not configured"
)


async def require_population_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one database session or fail explicitly when persistence is unavailable."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=POPULATIONS_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


PopulationSession = Annotated[AsyncSession, Depends(require_population_session)]


def normalize_persona_search_query(q: str | None) -> str | None:
    """Normalize an optional query and reject unusable post-trim lengths."""
    if q is None:
        return None
    normalized_query = q.strip()
    if len(normalized_query) < 2 or len(normalized_query) > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="q must contain between 2 and 100 non-whitespace characters after trimming",
        )
    return normalized_query


def create_populations_router() -> APIRouter:
    """Create immutable dataset, persona, and cohort routes."""
    router = APIRouter(prefix="/api/v2/populations", tags=["populations"])

    @router.get("/datasets", response_model=DatasetsResponse)
    async def datasets(session: PopulationSession) -> DatasetsResponse:
        """List frozen MatrAIx dataset versions."""
        return await list_datasets(session)

    @router.get("/datasets/{dataset_id}/personas", response_model=PersonasResponse)
    async def personas(
        dataset_id: UUID,
        session: PopulationSession,
        q: Annotated[str | None, Query()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> PersonasResponse:
        """Search one dataset version by persona ID, display name, or source."""
        try:
            return await list_personas(
                session,
                dataset_id,
                normalize_persona_search_query(q),
                page,
                page_size,
            )
        except PopulationDatasetNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/cohorts", response_model=CohortsResponse)
    async def cohorts(session: PopulationSession) -> CohortsResponse:
        """List immutable cohort summaries."""
        return await list_cohorts(session)

    @router.post("/cohorts", response_model=CohortDetail, status_code=status.HTTP_201_CREATED)
    async def add_cohort(
        request: CohortCreateRequest,
        session: PopulationSession,
    ) -> CohortDetail:
        """Create and atomically seal one ordered, content-addressed cohort."""
        try:
            return await create_cohort(session, request)
        except PopulationDatasetNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except PopulationPersonaSelectionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("/cohorts/{cohort_id}", response_model=CohortDetail)
    async def cohort(cohort_id: UUID, session: PopulationSession) -> CohortDetail:
        """Return one complete immutable cohort after integrity verification."""
        try:
            return await get_cohort(session, cohort_id)
        except PopulationCohortNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return router
