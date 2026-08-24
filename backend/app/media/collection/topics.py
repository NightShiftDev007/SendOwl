"""Deterministic native topic lifecycle and cross-country propagation projection."""

import re
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.models import (
    MediaArticleRecord,
    MediaPropagationEdgeRecord,
    MediaPropagationEventRecord,
    MediaSourceRecord,
    MediaTopicArticleRecord,
    MediaTopicRecord,
    MediaTopicSnapshotRecord,
)

_WORD = re.compile(r"[A-Za-z0-9]{2,}|[\u3400-\u9fff]")


def _tokens(value: str) -> frozenset[str]:
    raw = tuple(token.casefold() for token in _WORD.findall(value))
    latin = tuple(token for token in raw if len(token) > 1)
    cjk = tuple(token for token in raw if len(token) == 1)
    cjk_bigrams = tuple("".join(cjk[index : index + 2]) for index in range(len(cjk) - 1))
    return frozenset((*latin, *cjk_bigrams))


def title_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


async def _native_topic_for_article(
    session: AsyncSession,
    article: MediaArticleRecord,
) -> MediaTopicRecord:
    candidates = tuple(
        (
            await session.execute(
                select(MediaTopicRecord)
                .where(MediaTopicRecord.origin == "native_collection")
                .order_by(MediaTopicRecord.last_seen_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    ranked = tuple(
        sorted(
            (
                (title_similarity(article.title, candidate.name), candidate)
                for candidate in candidates
            ),
            key=lambda item: (-item[0], str(item[1].id)),
        )
    )
    if ranked and ranked[0][0] >= 0.32:
        return ranked[0][1]
    now = article.crawled_at
    topic = MediaTopicRecord(
        id=uuid4(),
        name=article.title[:300],
        name_zh=article.title[:300] if article.language.startswith("zh") else None,
        summary_zh=article.summary if article.language.startswith("zh") else None,
        topic_category=None,
        status="emerging",
        lifecycle_state="nascent",
        first_seen_at=article.published_at,
        last_seen_at=article.published_at,
        created_at=now,
        updated_at=now,
        origin="native_collection",
    )
    session.add(topic)
    await session.flush((topic,))
    return topic


async def _update_lifecycle(
    session: AsyncSession,
    topic: MediaTopicRecord,
    observed_at,
) -> int:
    count = int(
        await session.scalar(
            select(func.count(MediaTopicArticleRecord.article_id)).where(
                MediaTopicArticleRecord.topic_id == topic.id
            )
        )
        or 0
    )
    topic.last_seen_at = max(topic.last_seen_at, observed_at)
    topic.updated_at = observed_at
    if count >= 10:
        topic.status = "stable"
        topic.lifecycle_state = "confirmed"
    elif count >= 3:
        topic.status = "heating"
        topic.lifecycle_state = "forming"
    return count


async def _update_snapshot(
    session: AsyncSession,
    topic: MediaTopicRecord,
    article: MediaArticleRecord,
    topic_count: int,
) -> None:
    country = article.country_code
    if country is None:
        return
    window_start = article.crawled_at.replace(minute=0, second=0, microsecond=0)
    snapshot = await session.scalar(
        select(MediaTopicSnapshotRecord).where(
            MediaTopicSnapshotRecord.country_code == country,
            MediaTopicSnapshotRecord.topic_id == topic.id,
            MediaTopicSnapshotRecord.window_start == window_start,
            MediaTopicSnapshotRecord.granularity == "hour",
        )
    )
    if snapshot is None:
        session.add(
            MediaTopicSnapshotRecord(
                id=uuid4(),
                country_code=country,
                topic_id=topic.id,
                window_start=window_start,
                window_end=window_start + timedelta(hours=1),
                granularity="hour",
                article_count=1,
                salience_score=Decimal(topic_count),
                salience_rank=1,
                created_at=article.crawled_at,
            )
        )
    else:
        snapshot.article_count += 1
        snapshot.salience_score = Decimal(topic_count)


async def _update_propagation(session: AsyncSession, topic: MediaTopicRecord) -> None:
    rows = tuple(
        (
            await session.execute(
                select(MediaArticleRecord, MediaSourceRecord)
                .join(
                    MediaTopicArticleRecord,
                    MediaTopicArticleRecord.article_id == MediaArticleRecord.id,
                )
                .join(MediaSourceRecord, MediaSourceRecord.id == MediaArticleRecord.source_id)
                .where(MediaTopicArticleRecord.topic_id == topic.id)
                .order_by(MediaArticleRecord.published_at, MediaArticleRecord.id)
            )
        ).all()
    )
    first_by_country: dict[str, tuple[MediaArticleRecord, MediaSourceRecord]] = {}
    for article, source in rows:
        if article.country_code is not None:
            first_by_country.setdefault(article.country_code, (article, source))
    if len(first_by_country) < 2:
        return
    origin_article, origin_source = min(
        first_by_country.values(), key=lambda item: (item[0].published_at, str(item[0].id))
    )
    event = await session.scalar(
        select(MediaPropagationEventRecord).where(
            MediaPropagationEventRecord.topic_id == topic.id,
            MediaPropagationEventRecord.detection_method == "native_lexical",
        )
    )
    now = max(article.crawled_at for article, _source in rows)
    if event is None:
        event = MediaPropagationEventRecord(
            id=uuid4(),
            topic_id=topic.id,
            status="suspected",
            confidence="suspected",
            origin_country_code=origin_article.country_code,
            origin_source_id=origin_source.id,
            origin_at=origin_article.published_at,
            origin_confidence="medium",
            detection_method="native_lexical",
            source_updated_at=now,
            imported_at=now,
        )
        session.add(event)
        await session.flush((event,))
    existing_destinations = set(
        (
            await session.execute(
                select(MediaPropagationEdgeRecord.to_country_code).where(
                    MediaPropagationEdgeRecord.event_id == event.id
                )
            )
        ).scalars()
    )
    next_position = len(existing_destinations)
    for country, (article, source) in sorted(first_by_country.items()):
        if country == origin_article.country_code or country in existing_destinations:
            continue
        lag = max(
            Decimal("0"),
            Decimal(
                str((article.published_at - origin_article.published_at).total_seconds() / 3600)
            ),
        )
        session.add(
            MediaPropagationEdgeRecord(
                event_id=event.id,
                position=next_position,
                from_country_code=origin_article.country_code,
                to_country_code=country,
                lag_hours=lag,
                first_media_name=source.name,
                first_article_id=article.id,
                first_published_at=article.published_at,
                source_follower_id=None,
                follower_source_id=source.id,
                observation_source="native_collection",
            )
        )
        next_position += 1
    event.source_updated_at = now
    if len(first_by_country) >= 3:
        event.status = "confirmed"
        event.confidence = "confirmed"


async def assign_native_article_context(
    session: AsyncSession,
    article: MediaArticleRecord,
) -> None:
    topic = await _native_topic_for_article(session, article)
    session.add(
        MediaTopicArticleRecord(
            topic_id=topic.id,
            article_id=article.id,
            weight=Decimal("1.000"),
            assign_method="online",
            assigned_at=article.crawled_at,
        )
    )
    await session.flush()
    count = await _update_lifecycle(session, topic, article.published_at)
    await _update_snapshot(session, topic, article, count)
    await _update_propagation(session, topic)
