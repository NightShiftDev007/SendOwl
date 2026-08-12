"""Strict public contracts for imported media intelligence."""

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, Field, HttpUrl, StringConstraints

from app.shared.contracts import ContractModel, Identifier, LanguageCode, NonEmptyText


class MediaSourceKind(StrEnum):
    """Supported transport categories without collector implementation details."""

    RSS = "rss"
    WEB = "web"
    API = "api"


class MediaSource(ContractModel):
    """Stable identity and provenance for one media source."""

    source_id: Identifier
    name: NonEmptyText
    canonical_url: HttpUrl
    kind: MediaSourceKind


class MediaArticle(ContractModel):
    """Immutable article snapshot accepted from an external collector."""

    article_id: Identifier
    source: MediaSource
    url: HttpUrl
    title: NonEmptyText
    author: NonEmptyText | None
    content: NonEmptyText
    language: LanguageCode
    published_at: AwareDatetime
    captured_at: AwareDatetime


type NonNegativeInt = Annotated[int, Field(ge=0)]
type Latitude = Annotated[float, Field(ge=-90, le=90)]
type Longitude = Annotated[float, Field(ge=-180, le=180)]
type CountryCode = Annotated[
    str,
    StringConstraints(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$"),
]
type ArticleExcerpt = Annotated[
    str,
    StringConstraints(min_length=1, max_length=280, strip_whitespace=True),
]


class MediaArticleSummary(ContractModel):
    """One article projection used by media browsing and overview views."""

    id: UUID
    title: NonEmptyText
    source_name: NonEmptyText
    published_at: AwareDatetime
    excerpt: ArticleExcerpt
    original_url: HttpUrl
    country_code: CountryCode | None
    topic_id: UUID | None
    topic: NonEmptyText


class MediaCountryNode(ContractModel):
    """Country-level article activity positioned for the overview globe."""

    country_code: CountryCode
    lat: Latitude
    lon: Longitude
    article_count: NonNegativeInt
    topic_id: UUID | None
    topic: NonEmptyText


class MediaHotTopic(ContractModel):
    """One currently active topic and its rolling article count."""

    topic_id: UUID | None
    topic: NonEmptyText
    article_count: NonNegativeInt


class MediaOverviewResponse(ContractModel):
    """Complete first-load payload for the media overview."""

    generated_at: AwareDatetime
    source_count: NonNegativeInt
    article_count: NonNegativeInt
    topic_count: NonNegativeInt
    country_nodes: tuple[MediaCountryNode, ...]
    hot_topics: tuple[MediaHotTopic, ...]
    latest_articles: tuple[MediaArticleSummary, ...]


class MediaCountryFacet(ContractModel):
    """Country facet for the active article search result set."""

    country_code: CountryCode
    article_count: NonNegativeInt


class MediaTopicFacet(ContractModel):
    """Topic facet for the active article search result set."""

    topic_id: UUID | None
    topic: NonEmptyText
    article_count: NonNegativeInt


class MediaArticleFacets(ContractModel):
    """Available refinements computed from the filtered article result set."""

    countries: tuple[MediaCountryFacet, ...]
    topics: tuple[MediaTopicFacet, ...]


class MediaArticlesResponse(ContractModel):
    """Paginated media article search results."""

    items: tuple[MediaArticleSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: NonNegativeInt
    facets: MediaArticleFacets


class MediaTopicSummary(ContractModel):
    """Read-only topic projection for scenario discovery."""

    id: UUID
    topic: NonEmptyText
    summary: str | None
    category: str | None
    status: str
    article_count: NonNegativeInt
    last_seen_at: AwareDatetime


class MediaTopicsResponse(ContractModel):
    """Paginated active imported topics ordered by unique-article activity."""

    items: tuple[MediaTopicSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: NonNegativeInt


class MediaSourceSummary(ContractModel):
    """Read-only media source health projection."""

    id: UUID
    name: NonEmptyText
    country_code: CountryCode
    homepage_url: HttpUrl
    media_type: str
    language: str
    status: str
    last_success_at: AwareDatetime | None


class MediaSourcesResponse(ContractModel):
    """Imported source catalog and explicit status distribution."""

    items: tuple[MediaSourceSummary, ...]
    total: NonNegativeInt
    status_counts: dict[str, NonNegativeInt]
