"""Read-only HTTP boundary for imported AgendaScope media data."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import pycountry
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DatabaseConnector
from app.media.contracts import (
    MediaArticlesResponse,
    MediaArticleSummary,
    MediaFirstUtterancesResponse,
    MediaOverviewResponse,
    MediaPropagationResponse,
    MediaSourceEvidenceResponse,
    MediaSourcesResponse,
    MediaTopicsResponse,
    MediaTopicTimelineResponse,
)
from app.media.errors import (
    MediaArticleNotFoundError,
    MediaSourceEvidencePageOutOfRangeError,
    MediaSourceNotFoundError,
    MediaTopicNotFoundError,
)
from app.media.repository import (
    MediaArticleFilters,
    get_article,
    get_overview,
    get_source_evidence,
    get_topic_timeline,
    list_articles,
    list_propagation_events,
    list_sources,
    list_topic_first_utterances,
    list_topics,
    utc_now,
)
from app.media.sync_contracts import MediaSyncStatusResponse
from app.media.sync_repository import get_media_sync_status

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


async def require_media_sync_status_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one repeatable-read, read-only snapshot for the multi-query status view."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=MEDIA_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


MediaSyncStatusSession = Annotated[
    AsyncSession,
    Depends(require_media_sync_status_session),
]


async def require_media_source_evidence_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one repeatable-read, read-only snapshot for a source evidence page."""
    connector: DatabaseConnector | None = getattr(request.app.state, "database", None)
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=MEDIA_UNAVAILABLE_DETAIL,
        )
    async with connector.session() as session:
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


MediaSourceEvidenceSession = Annotated[
    AsyncSession,
    Depends(require_media_source_evidence_session),
]


MEDIA_SOURCE_EVIDENCE_QUERY_FIELDS = frozenset({"page", "page_size"})


def validate_media_source_evidence_query_shape(request: Request) -> None:
    """Reject ambiguous query strings before loading a source evidence page."""
    unknown = sorted(set(request.query_params) - MEDIA_SOURCE_EVIDENCE_QUERY_FIELDS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported media source evidence query fields: {', '.join(unknown)}",
        )
    repeated = tuple(
        field for field in ("page", "page_size") if len(request.query_params.getlist(field)) > 1
    )
    if repeated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"media source evidence query fields must not repeat: {', '.join(repeated)}",
        )


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


def normalize_media_country_query(country: str | None) -> str | None:
    """Normalize one optional ISO 3166-1 alpha-2 query or reject it explicitly."""
    if country is None:
        return None
    normalized_country = country.upper()
    if pycountry.countries.get(alpha_2=normalized_country) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="country must be an assigned ISO 3166-1 alpha-2 code",
        )
    return normalized_country


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

    @router.get("/articles/{article_id}", response_model=MediaArticleSummary)
    async def article(
        article_id: UUID,
        request: Request,
        session: MediaSession,
    ) -> MediaArticleSummary:
        """Resolve one exact article identity and its current evidence revision."""
        if request.query_params:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="media article detail does not accept query parameters",
            )
        try:
            return await get_article(session, article_id)
        except MediaArticleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/topics", response_model=MediaTopicsResponse)
    async def topics(
        session: MediaSession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> MediaTopicsResponse:
        """List imported active topics."""
        return await list_topics(session, page, page_size)

    @router.get("/topics/{topic_id}/timeline", response_model=MediaTopicTimelineResponse)
    async def topic_timeline(
        topic_id: UUID,
        session: MediaSession,
        country: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2}$")] = None,
        limit: Annotated[int, Query(ge=2, le=500)] = 96,
    ) -> MediaTopicTimelineResponse:
        """Return real country-indexed or explicitly aggregated topic salience history."""
        normalized_country = normalize_media_country_query(country)
        try:
            return await get_topic_timeline(session, topic_id, normalized_country, limit)
        except MediaTopicNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get(
        "/topics/{topic_id}/first-utterances",
        response_model=MediaFirstUtterancesResponse,
    )
    async def topic_first_utterances(
        topic_id: UUID,
        session: MediaSession,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MediaFirstUtterancesResponse:
        """Return evidence-bound positive first-utterance observations without reasoning."""
        try:
            return await list_topic_first_utterances(session, topic_id, limit)
        except MediaTopicNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    @router.get("/sources", response_model=MediaSourcesResponse)
    async def sources(session: MediaSession) -> MediaSourcesResponse:
        """List imported media sources and their status distribution."""
        return await list_sources(session)

    @router.get(
        "/sources/{source_id}/evidence",
        response_model=MediaSourceEvidenceResponse,
    )
    async def source_evidence(
        source_id: UUID,
        request: Request,
        session: MediaSourceEvidenceSession,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MediaSourceEvidenceResponse:
        """Return a bounded source-local evidence view without full article content."""
        validate_media_source_evidence_query_shape(request)
        try:
            return await get_source_evidence(session, source_id, page, page_size)
        except MediaSourceNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        except MediaSourceEvidencePageOutOfRangeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error

    @router.get("/sync-status", response_model=MediaSyncStatusResponse)
    async def sync_status(session: MediaSyncStatusSession) -> MediaSyncStatusResponse:
        """Expose refresh freshness and failures without source credentials."""
        return await get_media_sync_status(session, utc_now())

    @router.get("/propagation", response_model=MediaPropagationResponse)
    async def propagation(
        session: MediaSession,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> MediaPropagationResponse:
        """Return imported AgendaScope propagation chains without synthetic edges."""
        return await list_propagation_events(session, limit)

    return router
