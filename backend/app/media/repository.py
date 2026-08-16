"""Read-only SQLAlchemy queries for imported AgendaScope media data."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from pydantic import Field
from sqlalchemy import Integer, Select, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.evidence.revisions import calculate_evidence_revision_sha256
from app.media.contracts import (
    MediaArticleFacets,
    MediaArticlesResponse,
    MediaArticleSummary,
    MediaCountryFacet,
    MediaCountryNode,
    MediaFirstUtteranceObservation,
    MediaFirstUtterancesResponse,
    MediaHotTopic,
    MediaOverviewResponse,
    MediaPropagationEdge,
    MediaPropagationEvent,
    MediaPropagationResponse,
    MediaSourceEvidenceResponse,
    MediaSourcesResponse,
    MediaSourceSummary,
    MediaTopicFacet,
    MediaTopicLatestCountry,
    MediaTopicsResponse,
    MediaTopicSummary,
    MediaTopicTimelinePoint,
    MediaTopicTimelineResponse,
)
from app.media.countries import country_centroid
from app.media.errors import (
    MediaArticleNotFoundError,
    MediaSourceEvidencePageOutOfRangeError,
    MediaSourceNotFoundError,
    MediaTopicNotFoundError,
)
from app.media.models import (
    MediaArticleRecord,
    MediaFirstUtteranceRecord,
    MediaPropagationEdgeRecord,
    MediaPropagationEventRecord,
    MediaSourceRecord,
    MediaTopicArticleRecord,
    MediaTopicRecord,
    MediaTopicSnapshotRecord,
)

UNCLASSIFIED_TOPIC = "未归类"
LATEST_ARTICLE_LIMIT = 12
HOT_TOPIC_LIMIT = 10
TOPIC_FACET_LIMIT = 50
EXCERPT_LENGTH = 280
LATEST_TOPIC_COUNTRY_LIMIT = 12
COUNTRY_TIMELINE_LIMITATIONS = (
    "article_count, salience_score, and salience_rank preserve AgendaScope's "
    "country-indexed snapshot values.",
    "Media salience is an observed coverage signal, not causal inference or a forecast.",
)
AGGREGATED_TIMELINE_LIMITATIONS = (
    "article_count is a country-indexed sum across country snapshots and may count one "
    "article in multiple countries.",
    "salience_score is summed across country snapshots; salience_rank is unavailable for "
    "cross-country aggregation.",
    "Media salience is an observed coverage signal, not causal inference or a forecast.",
)
FIRST_UTTERANCE_LIMITATIONS = (
    "Each item is a positive AgendaScope model judgment whose exact quote was verified "
    "against the imported source article.",
    "The observation is model-assisted evidence discovery, not an authoritative claim that "
    "no earlier public utterance exists.",
    "Model reasoning is intentionally not imported or exposed.",
)


@dataclass(frozen=True, slots=True)
class MediaArticleFilters:
    """Validated repository filter set for an article search."""

    q: str | None
    country: str | None
    topic_id: UUID | None


def escaped_ilike_contains_pattern(value: str) -> str:
    """Build a literal PostgreSQL ILIKE contains pattern with wildcard escaping."""
    if not isinstance(value, str):
        raise TypeError(f"value must be str, got {type(value).__name__}")
    escaped_value = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped_value}%"


def representative_topic_subquery():
    """Select one deterministic topic for every article without dropping unclassified rows."""
    ranked_topics = (
        select(
            MediaTopicArticleRecord.article_id.label("article_id"),
            MediaTopicRecord.id.label("topic_id"),
            func.coalesce(MediaTopicRecord.name_zh, MediaTopicRecord.name).label("topic"),
            func.row_number()
            .over(
                partition_by=MediaTopicArticleRecord.article_id,
                order_by=(
                    MediaTopicArticleRecord.weight.desc(),
                    MediaTopicArticleRecord.assigned_at.desc(),
                    MediaTopicArticleRecord.topic_id.asc(),
                ),
            )
            .label("rank"),
        )
        .join(MediaTopicRecord, MediaTopicRecord.id == MediaTopicArticleRecord.topic_id)
        .subquery()
    )
    return (
        select(ranked_topics.c.article_id, ranked_topics.c.topic_id, ranked_topics.c.topic)
        .where(ranked_topics.c.rank == 1)
        .subquery()
    )


def _article_filter_conditions(
    filters: MediaArticleFilters,
    representative_topic,
) -> tuple[object, ...]:
    """Build reusable SQL conditions for result and facet queries."""
    conditions: list[object] = [
        MediaArticleRecord.is_duplicate.is_(False),
        MediaArticleRecord.source_present.is_(True),
    ]
    if filters.q is not None:
        pattern = escaped_ilike_contains_pattern(filters.q)
        conditions.append(
            or_(
                MediaArticleRecord.title.ilike(pattern, escape="\\"),
                MediaArticleRecord.content.ilike(pattern, escape="\\"),
                MediaArticleRecord.summary.ilike(pattern, escape="\\"),
            )
        )
    if filters.country is not None:
        conditions.append(MediaArticleRecord.country_code == filters.country)
    if filters.topic_id is not None:
        conditions.append(representative_topic.c.topic_id == filters.topic_id)
    return tuple(conditions)


def article_projection(representative_topic) -> Select[tuple[object, ...]]:
    """Build the strict public article projection."""
    return (
        select(
            MediaArticleRecord.id,
            MediaArticleRecord.title,
            MediaArticleRecord.content,
            MediaArticleRecord.summary,
            MediaArticleRecord.source_id,
            MediaSourceRecord.name.label("source_name"),
            MediaArticleRecord.published_at,
            MediaArticleRecord.crawled_at,
            func.coalesce(
                func.nullif(
                    func.btrim(func.substr(MediaArticleRecord.summary, 1, EXCERPT_LENGTH)),
                    "",
                ),
                func.nullif(
                    func.btrim(func.substr(MediaArticleRecord.content, 1, EXCERPT_LENGTH)),
                    "",
                ),
                func.btrim(func.substr(MediaArticleRecord.title, 1, EXCERPT_LENGTH)),
            ).label("excerpt"),
            MediaArticleRecord.url.label("original_url"),
            MediaArticleRecord.country_code,
            representative_topic.c.topic_id,
            func.coalesce(representative_topic.c.topic, UNCLASSIFIED_TOPIC).label("topic"),
        )
        .join(MediaSourceRecord, MediaSourceRecord.id == MediaArticleRecord.source_id)
        .outerjoin(
            representative_topic,
            representative_topic.c.article_id == MediaArticleRecord.id,
        )
        .where(
            MediaArticleRecord.is_duplicate.is_(False),
            MediaArticleRecord.source_present.is_(True),
        )
    )


def article_summary(row: object) -> MediaArticleSummary:
    """Validate one database projection at the domain boundary."""
    mapping = row._mapping
    return MediaArticleSummary(
        id=mapping["id"],
        title=mapping["title"],
        source_name=mapping["source_name"],
        published_at=mapping["published_at"],
        excerpt=mapping["excerpt"],
        original_url=mapping["original_url"],
        country_code=mapping["country_code"],
        topic_id=mapping["topic_id"],
        topic=mapping["topic"],
        evidence_revision_sha256=calculate_evidence_revision_sha256(
            mapping["title"],
            mapping["content"],
            mapping["summary"],
            mapping["original_url"],
            mapping["published_at"],
            mapping["crawled_at"],
            mapping["country_code"],
            mapping["source_id"],
            mapping["source_name"],
        ),
    )


def _classified_country_topic_counts(
    representative_topic: Subquery,
    cutoff: datetime,
) -> Subquery:
    """Count unique recent articles by country and classified representative topic."""
    return (
        select(
            MediaArticleRecord.country_code.label("country_code"),
            representative_topic.c.topic_id.label("topic_id"),
            representative_topic.c.topic.label("topic"),
            func.count(MediaArticleRecord.id).label("article_count"),
        )
        .join(representative_topic, representative_topic.c.article_id == MediaArticleRecord.id)
        .where(
            MediaArticleRecord.published_at >= cutoff,
            MediaArticleRecord.country_code.is_not(None),
            MediaArticleRecord.is_duplicate.is_(False),
            MediaArticleRecord.source_present.is_(True),
        )
        .group_by(
            MediaArticleRecord.country_code,
            representative_topic.c.topic_id,
            representative_topic.c.topic,
        )
        .subquery()
    )


def _classified_hot_topics(
    representative_topic: Subquery,
    cutoff: datetime,
) -> Select[tuple[UUID, str, int]]:
    """Rank only classified representative topics by unique recent article activity."""
    return (
        select(
            representative_topic.c.topic_id,
            representative_topic.c.topic.label("topic"),
            func.count(MediaArticleRecord.id).label("article_count"),
        )
        .join(representative_topic, representative_topic.c.article_id == MediaArticleRecord.id)
        .where(
            MediaArticleRecord.published_at >= cutoff,
            MediaArticleRecord.is_duplicate.is_(False),
            MediaArticleRecord.source_present.is_(True),
        )
        .group_by(representative_topic.c.topic_id, representative_topic.c.topic)
        .order_by(
            func.count(MediaArticleRecord.id).desc(),
            representative_topic.c.topic,
            representative_topic.c.topic_id,
        )
        .limit(HOT_TOPIC_LIMIT)
    )


async def get_overview(session: AsyncSession, generated_at: datetime) -> MediaOverviewResponse:
    """Load the complete media overview using explicit aggregate queries."""
    representative_topic = representative_topic_subquery()
    cutoff = generated_at - timedelta(hours=24)
    counts = (
        await session.execute(
            select(
                select(func.count()).select_from(MediaSourceRecord).scalar_subquery(),
                select(func.count())
                .select_from(MediaArticleRecord)
                .where(
                    MediaArticleRecord.published_at >= cutoff,
                    MediaArticleRecord.is_duplicate.is_(False),
                    MediaArticleRecord.source_present.is_(True),
                )
                .scalar_subquery(),
                select(func.count(func.distinct(MediaTopicArticleRecord.topic_id)))
                .select_from(MediaTopicArticleRecord)
                .join(
                    MediaArticleRecord,
                    MediaArticleRecord.id == MediaTopicArticleRecord.article_id,
                )
                .where(
                    MediaArticleRecord.is_duplicate.is_(False),
                    MediaArticleRecord.source_present.is_(True),
                )
                .scalar_subquery(),
            )
        )
    ).one()

    country_rows = (
        await session.execute(
            select(
                MediaArticleRecord.country_code,
                func.count(MediaArticleRecord.id).label("article_count"),
            )
            .where(
                MediaArticleRecord.published_at >= cutoff,
                MediaArticleRecord.country_code.is_not(None),
                MediaArticleRecord.is_duplicate.is_(False),
                MediaArticleRecord.source_present.is_(True),
            )
            .group_by(MediaArticleRecord.country_code)
            .order_by(func.count(MediaArticleRecord.id).desc(), MediaArticleRecord.country_code)
        )
    ).all()
    country_topic_counts = _classified_country_topic_counts(representative_topic, cutoff)
    ranked_country_topics = select(
        country_topic_counts.c.country_code,
        country_topic_counts.c.topic_id,
        country_topic_counts.c.topic,
        func.row_number()
        .over(
            partition_by=country_topic_counts.c.country_code,
            order_by=(
                country_topic_counts.c.article_count.desc(),
                country_topic_counts.c.topic,
                country_topic_counts.c.topic_id,
            ),
        )
        .label("rank"),
    ).subquery()
    top_topic_rows = (
        await session.execute(
            select(
                ranked_country_topics.c.country_code,
                ranked_country_topics.c.topic_id,
                ranked_country_topics.c.topic,
            ).where(ranked_country_topics.c.rank == 1)
        )
    ).all()
    top_topic_by_country = {
        str(row.country_code): (row.topic_id, str(row.topic) if row.topic is not None else None)
        for row in top_topic_rows
    }
    country_nodes: list[MediaCountryNode] = []
    for row in country_rows:
        country_code = str(row.country_code)
        centroid = country_centroid(country_code)
        topic_id, topic = top_topic_by_country.get(country_code, (None, None))
        country_nodes.append(
            MediaCountryNode(
                country_code=country_code,
                lat=centroid[0],
                lon=centroid[1],
                article_count=int(row.article_count),
                topic_id=topic_id,
                topic=topic or UNCLASSIFIED_TOPIC,
            )
        )

    hot_rows = (await session.execute(_classified_hot_topics(representative_topic, cutoff))).all()
    latest_rows = (
        await session.execute(
            article_projection(representative_topic)
            .order_by(MediaArticleRecord.published_at.desc(), MediaArticleRecord.id.desc())
            .limit(LATEST_ARTICLE_LIMIT)
        )
    ).all()

    return MediaOverviewResponse(
        generated_at=generated_at,
        source_count=int(counts[0]),
        article_count=int(counts[1]),
        topic_count=int(counts[2]),
        country_nodes=tuple(country_nodes),
        hot_topics=tuple(
            MediaHotTopic(
                topic_id=row.topic_id,
                topic=str(row.topic),
                article_count=int(row.article_count),
            )
            for row in hot_rows
        ),
        latest_articles=tuple(article_summary(row) for row in latest_rows),
    )


async def list_articles(
    session: AsyncSession,
    filters: MediaArticleFilters,
    page: Annotated[int, Field(ge=1)],
    page_size: Annotated[int, Field(ge=1, le=100)],
) -> MediaArticlesResponse:
    """Search articles and return facets computed from the same filtered set."""
    representative_topic = representative_topic_subquery()
    conditions = _article_filter_conditions(filters, representative_topic)
    base = article_projection(representative_topic).where(*conditions)
    total = int(
        (await session.scalar(select(func.count()).select_from(base.order_by(None).subquery())))
        or 0
    )
    rows = (
        await session.execute(
            base.order_by(MediaArticleRecord.published_at.desc(), MediaArticleRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    country_rows = (
        await session.execute(
            select(
                MediaArticleRecord.country_code,
                func.count(MediaArticleRecord.id).label("article_count"),
            )
            .outerjoin(
                representative_topic,
                representative_topic.c.article_id == MediaArticleRecord.id,
            )
            .where(*conditions, MediaArticleRecord.country_code.is_not(None))
            .group_by(MediaArticleRecord.country_code)
            .order_by(func.count(MediaArticleRecord.id).desc(), MediaArticleRecord.country_code)
        )
    ).all()
    topic_facet = func.coalesce(representative_topic.c.topic, UNCLASSIFIED_TOPIC)
    topic_rows = (
        await session.execute(
            select(
                representative_topic.c.topic_id,
                topic_facet.label("topic"),
                func.count(MediaArticleRecord.id).label("article_count"),
            )
            .outerjoin(
                representative_topic,
                representative_topic.c.article_id == MediaArticleRecord.id,
            )
            .where(*conditions)
            .group_by(representative_topic.c.topic_id, topic_facet)
            .order_by(func.count(MediaArticleRecord.id).desc(), "topic")
            .limit(TOPIC_FACET_LIMIT)
        )
    ).all()
    return MediaArticlesResponse(
        items=tuple(article_summary(row) for row in rows),
        page=page,
        page_size=page_size,
        total=total,
        facets=MediaArticleFacets(
            countries=tuple(
                MediaCountryFacet(
                    country_code=str(row.country_code),
                    article_count=int(row.article_count),
                )
                for row in country_rows
            ),
            topics=tuple(
                MediaTopicFacet(
                    topic_id=row.topic_id,
                    topic=str(row.topic),
                    article_count=int(row.article_count),
                )
                for row in topic_rows
            ),
        ),
    )


async def get_article(session: AsyncSession, article_id: UUID) -> MediaArticleSummary:
    """Load one non-duplicate article with its current evidence revision."""
    representative_topic = representative_topic_subquery()
    row = (
        await session.execute(
            article_projection(representative_topic).where(MediaArticleRecord.id == article_id)
        )
    ).one_or_none()
    if row is None:
        raise MediaArticleNotFoundError(f"media article {article_id} was not found")
    return article_summary(row)


async def list_topics(
    session: AsyncSession,
    page: Annotated[int, Field(ge=1)],
    page_size: Annotated[int, Field(ge=1, le=100)],
) -> MediaTopicsResponse:
    """List active topics with counts derived only from unique articles."""
    counts = (
        select(
            MediaTopicArticleRecord.topic_id,
            func.count(MediaTopicArticleRecord.article_id).label("article_count"),
        )
        .join(MediaArticleRecord, MediaArticleRecord.id == MediaTopicArticleRecord.article_id)
        .where(
            MediaArticleRecord.is_duplicate.is_(False),
            MediaArticleRecord.source_present.is_(True),
        )
        .group_by(MediaTopicArticleRecord.topic_id)
        .subquery()
    )
    total = int(
        (
            await session.scalar(
                select(func.count())
                .select_from(MediaTopicRecord)
                .where(MediaTopicRecord.status != "archived")
            )
        )
        or 0
    )
    rows = (
        await session.execute(
            select(
                MediaTopicRecord.id,
                func.coalesce(MediaTopicRecord.name_zh, MediaTopicRecord.name).label("topic"),
                MediaTopicRecord.summary_zh.label("summary"),
                MediaTopicRecord.topic_category.label("category"),
                MediaTopicRecord.status,
                func.coalesce(counts.c.article_count, 0).label("article_count"),
                MediaTopicRecord.last_seen_at,
            )
            .outerjoin(counts, counts.c.topic_id == MediaTopicRecord.id)
            .where(MediaTopicRecord.status != "archived")
            .order_by(
                counts.c.article_count.desc().nullslast(),
                MediaTopicRecord.last_seen_at.desc(),
                MediaTopicRecord.id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MediaTopicsResponse(
        items=tuple(
            MediaTopicSummary.model_validate(dict(row._mapping), strict=True) for row in rows
        ),
        page=page,
        page_size=page_size,
        total=total,
    )


def topic_timeline_points_statement(
    topic_id: UUID,
    country: str | None,
    limit: int,
) -> Select[tuple[object, ...]]:
    """Select the latest bounded timeline buckets, then expose them oldest first."""
    if country is None:
        timeline = (
            select(
                MediaTopicSnapshotRecord.window_start.label("window_start"),
                MediaTopicSnapshotRecord.window_end.label("window_end"),
                MediaTopicSnapshotRecord.granularity.label("granularity"),
                func.sum(MediaTopicSnapshotRecord.article_count).label("article_count"),
                func.sum(MediaTopicSnapshotRecord.salience_score).label("salience_score"),
                cast(literal(None), Integer).label("salience_rank"),
            )
            .where(MediaTopicSnapshotRecord.topic_id == topic_id)
            .group_by(
                MediaTopicSnapshotRecord.window_start,
                MediaTopicSnapshotRecord.window_end,
                MediaTopicSnapshotRecord.granularity,
            )
            .order_by(
                MediaTopicSnapshotRecord.window_start.desc(),
                MediaTopicSnapshotRecord.window_end.desc(),
                MediaTopicSnapshotRecord.granularity.asc(),
            )
            .limit(limit)
            .subquery()
        )
    else:
        timeline = (
            select(
                MediaTopicSnapshotRecord.window_start.label("window_start"),
                MediaTopicSnapshotRecord.window_end.label("window_end"),
                MediaTopicSnapshotRecord.granularity.label("granularity"),
                MediaTopicSnapshotRecord.article_count.label("article_count"),
                MediaTopicSnapshotRecord.salience_score.label("salience_score"),
                MediaTopicSnapshotRecord.salience_rank.label("salience_rank"),
            )
            .where(
                MediaTopicSnapshotRecord.topic_id == topic_id,
                MediaTopicSnapshotRecord.country_code == country,
            )
            .order_by(
                MediaTopicSnapshotRecord.window_start.desc(),
                MediaTopicSnapshotRecord.window_end.desc(),
                MediaTopicSnapshotRecord.granularity.asc(),
            )
            .limit(limit)
            .subquery()
        )
    return select(
        timeline.c.window_start,
        timeline.c.window_end,
        timeline.c.granularity,
        timeline.c.article_count,
        timeline.c.salience_score,
        timeline.c.salience_rank,
    ).order_by(
        timeline.c.window_start.asc(),
        timeline.c.window_end.asc(),
        timeline.c.granularity.asc(),
    )


def topic_latest_countries_statement(
    topic_id: UUID,
) -> Select[tuple[object, ...]]:
    """Rank the latest snapshot per country by its observed salience."""
    ranked = select(
        MediaTopicSnapshotRecord.country_code,
        MediaTopicSnapshotRecord.window_start,
        MediaTopicSnapshotRecord.window_end,
        MediaTopicSnapshotRecord.granularity,
        MediaTopicSnapshotRecord.article_count,
        MediaTopicSnapshotRecord.salience_score,
        MediaTopicSnapshotRecord.salience_rank,
        func.row_number()
        .over(
            partition_by=MediaTopicSnapshotRecord.country_code,
            order_by=(
                MediaTopicSnapshotRecord.window_start.desc(),
                MediaTopicSnapshotRecord.window_end.desc(),
                MediaTopicSnapshotRecord.id.desc(),
            ),
        )
        .label("snapshot_recency"),
    ).where(MediaTopicSnapshotRecord.topic_id == topic_id)
    latest = ranked.subquery()
    return (
        select(
            latest.c.country_code,
            latest.c.window_start,
            latest.c.window_end,
            latest.c.granularity,
            latest.c.article_count,
            latest.c.salience_score,
            latest.c.salience_rank,
        )
        .where(latest.c.snapshot_recency == 1)
        .order_by(
            latest.c.salience_score.desc(),
            latest.c.article_count.desc(),
            latest.c.country_code.asc(),
        )
        .limit(LATEST_TOPIC_COUNTRY_LIMIT)
    )


async def get_topic_timeline(
    session: AsyncSession,
    topic_id: UUID,
    country: str | None,
    limit: int,
) -> MediaTopicTimelineResponse:
    """Load one real imported topic timeline without inventing missing observations."""
    topic_row = (
        await session.execute(
            select(
                MediaTopicRecord.id,
                func.coalesce(MediaTopicRecord.name_zh, MediaTopicRecord.name).label("topic"),
            ).where(MediaTopicRecord.id == topic_id)
        )
    ).one_or_none()
    if topic_row is None:
        raise MediaTopicNotFoundError(f"media topic {topic_id} does not exist")

    point_rows = (
        await session.execute(topic_timeline_points_statement(topic_id, country, limit))
    ).all()
    country_rows = (await session.execute(topic_latest_countries_statement(topic_id))).all()
    return MediaTopicTimelineResponse(
        topic_id=topic_row.id,
        topic=str(topic_row.topic),
        selected_country=country,
        points=tuple(
            MediaTopicTimelinePoint.model_validate(
                {
                    **dict(row._mapping),
                    "salience_score": float(row.salience_score),
                },
                strict=True,
            )
            for row in point_rows
        ),
        latest_countries=tuple(
            MediaTopicLatestCountry.model_validate(
                {
                    **dict(row._mapping),
                    "salience_score": float(row.salience_score),
                },
                strict=True,
            )
            for row in country_rows
        ),
        generated_at=utc_now(),
        limitations=(
            AGGREGATED_TIMELINE_LIMITATIONS if country is None else COUNTRY_TIMELINE_LIMITATIONS
        ),
    )


async def list_sources(session: AsyncSession) -> MediaSourcesResponse:
    """List sources and an explicit status distribution."""
    rows = (
        await session.execute(
            select(
                MediaSourceRecord.id,
                MediaSourceRecord.name,
                MediaSourceRecord.country_code,
                MediaSourceRecord.homepage_url,
                MediaSourceRecord.media_type,
                MediaSourceRecord.language,
                MediaSourceRecord.status,
                MediaSourceRecord.last_success_at,
            ).order_by(MediaSourceRecord.country_code, MediaSourceRecord.name)
        )
    ).all()
    status_rows = (
        await session.execute(
            select(MediaSourceRecord.status, func.count(MediaSourceRecord.id).label("count"))
            .group_by(MediaSourceRecord.status)
            .order_by(MediaSourceRecord.status)
        )
    ).all()
    return MediaSourcesResponse(
        items=tuple(
            MediaSourceSummary.model_validate(dict(row._mapping), strict=True) for row in rows
        ),
        total=len(rows),
        status_counts={str(row.status): int(row.count) for row in status_rows},
    )


async def get_source_evidence(
    session: AsyncSession,
    source_id: UUID,
    page: Annotated[int, Field(ge=1)],
    page_size: Annotated[int, Field(ge=1, le=100)],
) -> MediaSourceEvidenceResponse:
    """Read one source's bounded unique-article evidence from one database snapshot."""
    observed_at = await session.scalar(select(func.current_timestamp()))
    if observed_at is None:
        raise RuntimeError("PostgreSQL did not return CURRENT_TIMESTAMP for source evidence")
    source_row = (
        await session.execute(
            select(
                MediaSourceRecord.id,
                MediaSourceRecord.name,
                MediaSourceRecord.country_code,
                MediaSourceRecord.homepage_url,
                MediaSourceRecord.media_type,
                MediaSourceRecord.language,
                MediaSourceRecord.status,
                MediaSourceRecord.last_success_at,
            ).where(MediaSourceRecord.id == source_id)
        )
    ).one_or_none()
    if source_row is None:
        raise MediaSourceNotFoundError(f"media source {source_id} does not exist")

    source = MediaSourceSummary.model_validate(dict(source_row._mapping), strict=True)
    count_row = (
        await session.execute(
            select(
                func.count(MediaArticleRecord.id).label("article_total"),
                func.min(MediaArticleRecord.published_at).label("first_published_at"),
                func.max(MediaArticleRecord.published_at).label("latest_published_at"),
            ).where(
                MediaArticleRecord.source_id == source_id,
                MediaArticleRecord.is_duplicate.is_(False),
                MediaArticleRecord.source_present.is_(True),
            )
        )
    ).one()
    total = int(count_row.article_total)
    if (total == 0 and page > 1) or (total > 0 and (page - 1) * page_size >= total):
        raise MediaSourceEvidencePageOutOfRangeError(
            f"media source evidence page {page} is out of range for {total} items"
        )

    representative_topic = representative_topic_subquery()
    rows = (
        await session.execute(
            article_projection(representative_topic)
            .where(MediaArticleRecord.source_id == source_id)
            .order_by(MediaArticleRecord.published_at.desc(), MediaArticleRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MediaSourceEvidenceResponse(
        source=source,
        article_total=total,
        first_published_at=count_row.first_published_at,
        latest_published_at=count_row.latest_published_at,
        items=tuple(article_summary(row) for row in rows),
        page=page,
        page_size=page_size,
        total=total,
        observed_at=observed_at,
    )


async def list_propagation_events(
    session: AsyncSession,
    limit: int,
) -> MediaPropagationResponse:
    """List latest non-dismissed AgendaScope propagation chains without inference."""
    total = int(
        (
            await session.scalar(
                select(func.count(MediaPropagationEventRecord.id)).where(
                    MediaPropagationEventRecord.status != "dismissed"
                )
            )
        )
        or 0
    )
    event_rows = (
        await session.execute(
            select(
                MediaPropagationEventRecord.id,
                MediaPropagationEventRecord.topic_id,
                func.coalesce(MediaTopicRecord.name_zh, MediaTopicRecord.name).label("topic"),
                MediaPropagationEventRecord.status,
                MediaPropagationEventRecord.confidence,
                MediaPropagationEventRecord.origin_country_code,
                MediaSourceRecord.name.label("origin_source_name"),
                MediaPropagationEventRecord.origin_at,
                MediaPropagationEventRecord.origin_confidence,
                MediaPropagationEventRecord.detection_method,
            )
            .join(MediaTopicRecord, MediaTopicRecord.id == MediaPropagationEventRecord.topic_id)
            .outerjoin(
                MediaSourceRecord,
                MediaSourceRecord.id == MediaPropagationEventRecord.origin_source_id,
            )
            .where(MediaPropagationEventRecord.status != "dismissed")
            .order_by(
                MediaPropagationEventRecord.origin_at.desc(),
                MediaPropagationEventRecord.id.asc(),
            )
            .limit(limit)
        )
    ).all()
    event_ids = tuple(row.id for row in event_rows)
    edge_rows = (
        (
            await session.execute(
                select(
                    MediaPropagationEdgeRecord.event_id,
                    MediaPropagationEdgeRecord.position,
                    MediaPropagationEdgeRecord.from_country_code,
                    MediaPropagationEdgeRecord.to_country_code,
                    MediaPropagationEdgeRecord.lag_hours,
                    MediaPropagationEdgeRecord.first_media_name,
                    MediaPropagationEdgeRecord.first_article_id,
                    MediaPropagationEdgeRecord.first_published_at,
                    MediaPropagationEdgeRecord.source_follower_id,
                    MediaPropagationEdgeRecord.follower_source_id,
                    MediaPropagationEdgeRecord.observation_source,
                )
                .where(MediaPropagationEdgeRecord.event_id.in_(event_ids))
                .order_by(
                    MediaPropagationEdgeRecord.event_id,
                    MediaPropagationEdgeRecord.position,
                )
            )
        ).all()
        if event_ids
        else []
    )
    edges_by_event: dict[UUID, list[MediaPropagationEdge]] = {}
    for row in edge_rows:
        edges_by_event.setdefault(row.event_id, []).append(
            MediaPropagationEdge.model_validate(
                {
                    "position": row.position,
                    "from_country_code": row.from_country_code,
                    "to_country_code": row.to_country_code,
                    "lag_hours": float(row.lag_hours),
                    "first_media_name": row.first_media_name,
                    "first_article_id": row.first_article_id,
                    "first_published_at": row.first_published_at,
                    "source_follower_id": row.source_follower_id,
                    "follower_source_id": row.follower_source_id,
                    "observation_source": row.observation_source,
                },
                strict=True,
            )
        )
    return MediaPropagationResponse(
        generated_at=utc_now(),
        items=tuple(
            MediaPropagationEvent.model_validate(
                {
                    **dict(row._mapping),
                    "edges": tuple(edges_by_event.get(row.id, [])),
                },
                strict=True,
            )
            for row in event_rows
        ),
        total=total,
    )


async def list_topic_first_utterances(
    session: AsyncSession,
    topic_id: UUID,
    limit: int,
) -> MediaFirstUtterancesResponse:
    """List bounded, article-verifiable positive observations for one topic."""
    topic_row = (
        await session.execute(
            select(
                MediaTopicRecord.id,
                func.coalesce(MediaTopicRecord.name_zh, MediaTopicRecord.name).label("topic"),
            ).where(MediaTopicRecord.id == topic_id)
        )
    ).one_or_none()
    if topic_row is None:
        raise MediaTopicNotFoundError(f"media topic {topic_id} does not exist")
    total = int(
        (
            await session.scalar(
                select(func.count(MediaFirstUtteranceRecord.id)).where(
                    MediaFirstUtteranceRecord.topic_id == topic_id
                )
            )
        )
        or 0
    )
    representative_topic = representative_topic_subquery()
    rows = (
        await session.execute(
            article_projection(representative_topic)
            .add_columns(
                MediaFirstUtteranceRecord.id.label("observation_id"),
                MediaFirstUtteranceRecord.entity_id,
                MediaFirstUtteranceRecord.entity_name,
                MediaFirstUtteranceRecord.entity_type,
                MediaFirstUtteranceRecord.country_code.label("observation_country_code"),
                MediaFirstUtteranceRecord.occurred_at,
                MediaFirstUtteranceRecord.evidence_quote,
                MediaFirstUtteranceRecord.confidence,
                MediaFirstUtteranceRecord.model_name,
                MediaFirstUtteranceRecord.prompt_version,
                MediaFirstUtteranceRecord.source_created_at,
            )
            .join(
                MediaFirstUtteranceRecord,
                MediaFirstUtteranceRecord.article_id == MediaArticleRecord.id,
            )
            .where(MediaFirstUtteranceRecord.topic_id == topic_id)
            .order_by(
                MediaFirstUtteranceRecord.occurred_at.desc().nullslast(),
                MediaFirstUtteranceRecord.source_created_at.desc(),
                MediaFirstUtteranceRecord.id.asc(),
            )
            .limit(limit)
        )
    ).all()
    return MediaFirstUtterancesResponse(
        topic_id=topic_id,
        topic=str(topic_row.topic),
        items=tuple(
            MediaFirstUtteranceObservation(
                id=row.observation_id,
                entity_id=row.entity_id,
                entity_name=row.entity_name,
                entity_type=row.entity_type,
                country_code=row.observation_country_code,
                occurred_at=row.occurred_at,
                evidence_quote=row.evidence_quote,
                confidence=row.confidence,
                model_name=row.model_name,
                prompt_version=row.prompt_version,
                source_created_at=row.source_created_at,
                article=article_summary(row),
            )
            for row in rows
        ),
        total=total,
        generated_at=utc_now(),
        limitations=FIRST_UTTERANCE_LIMITATIONS,
    )


def utc_now() -> datetime:
    """Return a timezone-aware timestamp for a repository request boundary."""
    return datetime.now(UTC)
