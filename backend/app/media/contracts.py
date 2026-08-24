"""Strict public contracts for imported media intelligence."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, FiniteFloat, HttpUrl, StringConstraints

from app.shared.contracts import (
    ContractModel,
    Identifier,
    LanguageCode,
    NonEmptyText,
    Sha256Digest,
)


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
type NonNegativeFiniteFloat = Annotated[FiniteFloat, Field(ge=0)]
type PositiveSnapshotRank = Annotated[int, Field(ge=1)]
type MediaTopicSnapshotGranularity = Annotated[
    str,
    StringConstraints(pattern=r"^(hour|day|week)$"),
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
    evidence_revision_sha256: Sha256Digest


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


class MediaTopicTimelinePoint(ContractModel):
    """One country snapshot or one explicit cross-country aggregate bucket."""

    window_start: AwareDatetime
    window_end: AwareDatetime
    granularity: MediaTopicSnapshotGranularity
    article_count: NonNegativeInt
    salience_score: NonNegativeFiniteFloat
    salience_rank: PositiveSnapshotRank | None


class MediaTopicLatestCountry(ContractModel):
    """Latest available country snapshot for one topic."""

    country_code: CountryCode
    window_start: AwareDatetime
    window_end: AwareDatetime
    granularity: MediaTopicSnapshotGranularity
    article_count: NonNegativeInt
    salience_score: NonNegativeFiniteFloat
    salience_rank: PositiveSnapshotRank


class MediaTopicTimelineResponse(ContractModel):
    """Bounded topic salience history with an explicit aggregation boundary."""

    topic_id: UUID
    topic: NonEmptyText
    selected_country: CountryCode | None
    points: tuple[MediaTopicTimelinePoint, ...]
    latest_countries: Annotated[tuple[MediaTopicLatestCountry, ...], Field(max_length=12)]
    generated_at: AwareDatetime
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]


class MediaFirstUtteranceObservation(ContractModel):
    """One positive model-assisted observation with exact article evidence."""

    id: UUID
    entity_id: UUID
    entity_name: Annotated[NonEmptyText, Field(max_length=200)]
    entity_type: Annotated[
        str,
        StringConstraints(pattern=r"^(person|thinktank|intl_org|gov_body)$"),
    ]
    country_code: CountryCode
    occurred_at: AwareDatetime | None
    evidence_quote: Annotated[NonEmptyText, Field(max_length=2000)]
    confidence: Literal["high"]
    model_name: Annotated[NonEmptyText, Field(max_length=200)]
    prompt_version: Annotated[NonEmptyText, Field(max_length=100)]
    source_created_at: AwareDatetime
    article: MediaArticleSummary


class MediaFirstUtterancesResponse(ContractModel):
    """Bounded first-utterance observations for one imported topic."""

    topic_id: UUID
    topic: NonEmptyText
    items: tuple[MediaFirstUtteranceObservation, ...]
    total: NonNegativeInt
    generated_at: AwareDatetime
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]


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


class MediaSourceEvidenceResponse(ContractModel):
    """One source and its bounded, non-duplicate article evidence projection."""

    source: MediaSourceSummary
    article_total: NonNegativeInt
    first_published_at: AwareDatetime | None
    latest_published_at: AwareDatetime | None
    items: tuple[MediaArticleSummary, ...]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=100)]
    total: NonNegativeInt
    observed_at: AwareDatetime

    def model_post_init(self, __context: object) -> None:
        """Reject response metadata that cannot describe the returned evidence page."""
        if self.article_total != self.total:
            raise ValueError("article_total must equal total for a source evidence response")
        if len(self.items) > self.page_size or self.total < len(self.items):
            raise ValueError("source evidence page counts are inconsistent")
        if (self.first_published_at is None) != (self.latest_published_at is None):
            raise ValueError(
                "first and latest publication timestamps must both be present or absent"
            )
        if (
            self.first_published_at is not None
            and self.latest_published_at is not None
            and self.first_published_at > self.latest_published_at
        ):
            raise ValueError("first_published_at must not follow latest_published_at")


class MediaPropagationEdge(ContractModel):
    """One structured source observation from an imported AgendaScope event."""

    position: NonNegativeInt
    from_country_code: CountryCode
    to_country_code: CountryCode
    lag_hours: Annotated[float, Field(ge=0)]
    first_media_name: NonEmptyText | None
    first_article_id: UUID | None
    first_published_at: AwareDatetime | None
    source_follower_id: UUID | None
    follower_source_id: UUID | None
    observation_source: Annotated[
        str,
        StringConstraints(pattern=r"^(legacy_projection|structured_followers|native_collection)$"),
    ]

    def model_post_init(self, __context: object) -> None:
        """Require structured observations to retain their source identities."""
        if self.observation_source == "structured_followers":
            if self.source_follower_id is None or self.follower_source_id is None:
                raise ValueError("structured propagation edges require follower identities")
        elif self.observation_source == "native_collection":
            if self.source_follower_id is not None or self.follower_source_id is None:
                raise ValueError(
                    "native collection edges require a source identity without an import record"
                )
        elif self.source_follower_id is not None:
            raise ValueError("non-structured propagation edges cannot claim a follower record id")


class MediaPropagationEvent(ContractModel):
    """Imported propagation event with ordered observed edges and provenance status."""

    id: UUID
    topic_id: UUID
    topic: NonEmptyText
    status: Annotated[
        str,
        StringConstraints(pattern=r"^(watching|suspected|confirmed|dismissed|revised|archived)$"),
    ]
    confidence: Annotated[
        str,
        StringConstraints(pattern=r"^(watching|suspected|confirmed)$"),
    ]
    origin_country_code: CountryCode
    origin_source_name: NonEmptyText | None
    origin_at: AwareDatetime
    origin_confidence: Annotated[str, StringConstraints(pattern=r"^(high|medium|low)$")]
    detection_method: NonEmptyText
    edges: tuple[MediaPropagationEdge, ...]


class MediaPropagationResponse(ContractModel):
    """Latest imported propagation events; an empty list means no chain was detected."""

    generated_at: AwareDatetime
    items: tuple[MediaPropagationEvent, ...]
    total: NonNegativeInt
