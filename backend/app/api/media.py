"""Read-only HTTP boundary for imported AgendaScope media data."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.media.contracts import (
    MediaArticlesResponse,
    MediaOverviewResponse,
    MediaSourcesResponse,
    MediaTopicsResponse,
)
from app.media.repository import (
    MediaArticleFilters,
    get_overview,
    list_articles,
    list_sources,
    list_topics,
    utc_now,
)

MEDIA_UNAVAILABLE_DETAIL = "Media data is unavailable because DATABASE_URL is not configured"


async def require_media_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one database session or fail explicitly when media is unavailable."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=MEDIA_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        yield session


MediaSession = Annotated[AsyncSession, Depends(require_media_session)]


def normalize_media_search_query(q: str | None) -> str | None:
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


def create_media_router() -> APIRouter:
    """Create strict read-only media routes."""
    router = APIRouter(prefix="/api/v2/media", tags=["media"])

    @router.get("/overview", response_model=MediaOverviewResponse)
    async def overview(session: MediaSession) -> MediaOverviewResponse:
        """Return a complete media activity overview."""
        return await get_overview(session, utc_now())

    @router.get("/articles", response_model=MediaArticlesResponse)
    async def articles(
        session: MediaSession,
        q: Annotated[str | None, Query()] = None,
        country: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")] = None,
        topic_id: Annotated[UUID | None, Query()] = None,
        legacy_topic: Annotated[
            str | None,
            Query(alias="topic", include_in_schema=False),
        ] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MediaArticlesResponse:
        """Search and filter imported articles without mutating media state."""
        if legacy_topic is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="topic name filtering is unsupported; provide the stable topic_id UUID",
            )
        filters = MediaArticleFilters(
            q=normalize_media_search_query(q),
            country=country.upper() if country is not None else None,
            topic_id=topic_id,
        )
        return await list_articles(session, filters, page, page_size)

    @router.get("/topics", response_model=MediaTopicsResponse)
    async def topics(
        session: MediaSession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> MediaTopicsResponse:
        """List imported active topics."""
        return await list_topics(session, page, page_size)

    @router.get("/sources", response_model=MediaSourcesResponse)
    async def sources(session: MediaSession) -> MediaSourcesResponse:
        """List imported media sources and their status distribution."""
        return await list_sources(session)

    return router
