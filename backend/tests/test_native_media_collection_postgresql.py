"""PostgreSQL integration for SandOwl-owned media collection."""

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.database import normalize_async_database_url
from app.media.collection.contracts import NativeMediaSourceCreateRequest
from app.media.collection.discovery import DiscoveredArticle
from app.media.collection.extraction import ContentStatus, ExtractedArticleContent
from app.media.collection.repository import (
    complete_native_collection_success,
    create_native_media_source,
    get_native_media_collection_status,
    heartbeat_native_collection_worker,
    list_due_native_media_sources,
    start_native_collection_run,
)
from app.media.collection.service import NativeCollectedArticle, NativeCollectionBatch
from app.media.models import MediaArticleRecord, MediaTopicArticleRecord, MediaTopicRecord

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


async def _exercise_native_collection(database_url: str) -> None:
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    config = await create_native_media_source(
                        session,
                        NativeMediaSourceCreateRequest(
                            name="Native collection integration source",
                            country_code="CN",
                            homepage_url="https://native-collection.example.test/",
                            media_type="online",
                            language="zh",
                            collection_mode="rss",
                            feed_url="https://native-collection.example.test/feed.xml",
                            poll_interval_seconds=300,
                        ),
                    )
                    due = await list_due_native_media_sources(session, 5)
                    assert tuple(item.id for item in due) == (str(config.source_id),)
                    started_at = datetime.now(UTC)
                    await heartbeat_native_collection_worker(
                        session,
                        "native-collection-integration-worker",
                        started_at,
                    )
                    run = await start_native_collection_run(
                        session,
                        config.source_id,
                        "native-collection-integration-worker",
                    )
                    assert run is not None
                    batch = NativeCollectionBatch(
                        fetched_url="https://native-collection.example.test/feed.xml",
                        etag='"v1"',
                        last_modified=None,
                        articles=(
                            NativeCollectedArticle(
                                discovered=DiscoveredArticle(
                                    url="https://native-collection.example.test/article-1",
                                    title="原生采集集成报道",
                                    summary="原生采集直接写入 SandOwl。",
                                    published_at=started_at,
                                ),
                                extraction=ExtractedArticleContent(
                                    content="这是一篇由 SandOwl 原生采集链写入的测试报道。" * 8,
                                    summary="原生采集直接写入 SandOwl。",
                                    method="integration",
                                    status=ContentStatus.FULL,
                                    failures=(),
                                ),
                                fetch_error=None,
                            ),
                        ),
                        discovered_count=1,
                        not_modified=False,
                        collected_at=datetime.now(UTC),
                    )
                    await complete_native_collection_success(session, run.id, batch)
                    article = (
                        await session.execute(
                            select(MediaArticleRecord).where(
                                MediaArticleRecord.source_id == config.source_id
                            )
                        )
                    ).scalar_one()
                    assert article.title == "原生采集集成报道"
                    assert article.source_present is True
                    topic = (
                        await session.execute(
                            select(MediaTopicRecord)
                            .join(
                                MediaTopicArticleRecord,
                                MediaTopicArticleRecord.topic_id == MediaTopicRecord.id,
                            )
                            .where(MediaTopicArticleRecord.article_id == article.id)
                        )
                    ).scalar_one()
                    assert topic.origin == "native_collection"
                    assert topic.lifecycle_state == "nascent"
                    status = await get_native_media_collection_status(session)
                    assert status.worker_online is True
                    assert status.enabled_source_count == 1
                    assert status.latest_runs[0].status == "succeeded"
                    assert status.latest_runs[0].articles_inserted == 1
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for native collection integration",
)
def test_native_media_collection_executes_against_postgresql() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_native_collection(TEST_POSTGRES_DATABASE_URL))
