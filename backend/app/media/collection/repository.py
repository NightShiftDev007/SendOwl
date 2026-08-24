"""Persistence and governance for SandOwl-owned media collection."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.collection.contracts import (
    NativeMediaCollectionAlert,
    NativeMediaCollectionConfig,
    NativeMediaCollectionConfigRequest,
    NativeMediaCollectionRun,
    NativeMediaCollectionStatus,
    NativeMediaSourceCreateRequest,
)
from app.media.collection.hashing import calculate_collection_config_sha256
from app.media.collection.models import (
    NativeMediaCollectionAlertRecord,
    NativeMediaCollectionRunRecord,
    NativeMediaCollectionWorkerHeartbeatRecord,
)
from app.media.collection.service import NativeCollectionBatch, NativeCollectionSource
from app.media.collection.topics import assign_native_article_context
from app.media.collection.urls import calculate_url_sha256, normalize_url
from app.media.errors import MediaSourceNotFoundError
from app.media.models import MediaArticleRecord, MediaSourceRecord

WORKER_VERSION = "1.0.0"
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 180


def _config(record: MediaSourceRecord) -> NativeMediaCollectionConfig:
    digest = record.collection_config_sha256 or calculate_collection_config_sha256(
        record.collection_mode,
        record.homepage_url,
        record.feed_url,
        record.poll_interval_seconds,
    )
    return NativeMediaCollectionConfig(
        source_id=record.id,
        enabled=record.native_collection_enabled,
        collection_mode=record.collection_mode,
        feed_url=record.feed_url,
        poll_interval_seconds=record.poll_interval_seconds,
        config_sha256=digest,
        last_attempt_at=record.last_collection_attempt_at,
        last_success_at=record.last_collection_success_at,
        consecutive_failures=record.consecutive_collection_failures,
    )


async def create_native_media_source(
    session: AsyncSession,
    request: NativeMediaSourceCreateRequest,
) -> NativeMediaCollectionConfig:
    normalized_homepage = normalize_url(request.homepage_url)
    existing = await session.scalar(
        select(MediaSourceRecord.id).where(MediaSourceRecord.homepage_url == normalized_homepage)
    )
    if existing is not None:
        raise ValueError("a media source with this homepage_url already exists")
    now = datetime.now(UTC)
    digest = calculate_collection_config_sha256(
        request.collection_mode,
        normalized_homepage,
        request.feed_url,
        request.poll_interval_seconds,
    )
    record = MediaSourceRecord(
        id=uuid4(),
        name=request.name,
        name_zh=None,
        country_code=request.country_code,
        homepage_url=normalized_homepage,
        media_type=request.media_type,
        language=request.language,
        status="active",
        last_success_at=None,
        created_at=now,
        updated_at=now,
        native_collection_enabled=True,
        collection_mode=request.collection_mode,
        feed_url=(normalize_url(request.feed_url) if request.feed_url is not None else None),
        poll_interval_seconds=request.poll_interval_seconds,
        collection_config={},
        collection_config_sha256=digest,
        last_collection_attempt_at=None,
        last_collection_success_at=None,
        consecutive_collection_failures=0,
    )
    session.add(record)
    await session.commit()
    return _config(record)


async def configure_native_media_collection(
    session: AsyncSession,
    source_id: UUID,
    request: NativeMediaCollectionConfigRequest,
) -> NativeMediaCollectionConfig:
    record = await session.get(MediaSourceRecord, source_id)
    if record is None:
        raise MediaSourceNotFoundError(f"media source {source_id} does not exist")
    feed_url = normalize_url(request.feed_url) if request.feed_url is not None else None
    record.native_collection_enabled = request.enabled
    record.collection_mode = request.collection_mode
    record.feed_url = feed_url
    record.poll_interval_seconds = request.poll_interval_seconds
    record.collection_config_sha256 = calculate_collection_config_sha256(
        request.collection_mode,
        record.homepage_url,
        feed_url,
        request.poll_interval_seconds,
    )
    record.updated_at = datetime.now(UTC)
    await session.commit()
    return _config(record)


async def get_native_media_collection_config(
    session: AsyncSession,
    source_id: UUID,
) -> NativeMediaCollectionConfig:
    record = await session.get(MediaSourceRecord, source_id)
    if record is None:
        raise MediaSourceNotFoundError(f"media source {source_id} does not exist")
    return _config(record)


def _due(record: MediaSourceRecord, now: datetime) -> bool:
    return record.last_collection_attempt_at is None or (
        record.last_collection_attempt_at + timedelta(seconds=record.poll_interval_seconds) <= now
    )


async def list_due_native_media_sources(
    session: AsyncSession,
    limit: int,
) -> tuple[NativeCollectionSource, ...]:
    now = datetime.now(UTC)
    records = tuple(
        (
            await session.execute(
                select(MediaSourceRecord)
                .where(
                    MediaSourceRecord.native_collection_enabled.is_(True),
                    MediaSourceRecord.status.in_(("active", "degraded")),
                )
                .order_by(
                    MediaSourceRecord.last_collection_attempt_at.asc().nullsfirst(),
                    MediaSourceRecord.id,
                )
                .limit(limit * 4)
            )
        )
        .scalars()
        .all()
    )
    return tuple(
        NativeCollectionSource(
            id=str(record.id),
            homepage_url=record.homepage_url,
            feed_url=record.feed_url,
            collection_mode=record.collection_mode,
            language=record.language,
            country_code=record.country_code,
            etag=(record.collection_config or {}).get("etag"),
            last_modified=(record.collection_config or {}).get("last_modified"),
        )
        for record in records
        if _due(record, now)
    )[:limit]


async def start_native_collection_run(
    session: AsyncSession,
    source_id: UUID,
    worker_id: str,
) -> NativeMediaCollectionRunRecord | None:
    locked = bool(
        await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:identity, 0))"),
            {"identity": f"native-media:{source_id}"},
        )
    )
    if not locked:
        return None
    source = await session.get(MediaSourceRecord, source_id)
    now = datetime.now(UTC)
    if source is None or not source.native_collection_enabled or not _due(source, now):
        return None
    digest = source.collection_config_sha256 or calculate_collection_config_sha256(
        source.collection_mode,
        source.homepage_url,
        source.feed_url,
        source.poll_interval_seconds,
    )
    source.last_collection_attempt_at = now
    run = NativeMediaCollectionRunRecord(
        id=uuid4(),
        source_id=source.id,
        status="running",
        worker_id=worker_id,
        config_sha256=digest,
        scheduled_at=now,
        started_at=now,
        completed_at=None,
        articles_discovered=0,
        articles_inserted=0,
        articles_existing=0,
        error_code=None,
        error_message=None,
    )
    session.add(run)
    await session.commit()
    return run


async def complete_native_collection_success(
    session: AsyncSession,
    run_id: UUID,
    batch: NativeCollectionBatch,
) -> None:
    run = await session.get(NativeMediaCollectionRunRecord, run_id)
    if run is None or run.status != "running":
        raise RuntimeError(f"native collection run {run_id} is not running")
    source = await session.get(MediaSourceRecord, run.source_id)
    if source is None:
        raise RuntimeError(f"native collection source {run.source_id} disappeared")
    hashes = tuple(calculate_url_sha256(item.discovered.url) for item in batch.articles)
    existing_hashes = (
        set(
            (
                await session.execute(
                    select(MediaArticleRecord.url_hash).where(
                        MediaArticleRecord.url_hash.in_(hashes)
                    )
                )
            ).scalars()
        )
        if hashes
        else set()
    )
    inserted = 0
    for item, url_hash in zip(batch.articles, hashes, strict=True):
        if url_hash in existing_hashes:
            await session.execute(
                update(MediaArticleRecord)
                .where(MediaArticleRecord.url_hash == url_hash)
                .values(
                    source_present=True,
                    source_last_observed_at=batch.collected_at,
                    source_absent_at=None,
                )
            )
            continue
        article_record = MediaArticleRecord(
            id=uuid4(),
            source_id=source.id,
            url=item.discovered.url,
            url_hash=url_hash,
            title=item.discovered.title,
            content=item.extraction.content,
            summary=item.extraction.summary,
            language=source.language,
            published_at=item.discovered.published_at or batch.collected_at,
            crawled_at=batch.collected_at,
            country_code=source.country_code,
            is_duplicate=False,
            created_at=batch.collected_at,
            source_present=True,
            source_last_observed_at=batch.collected_at,
            source_absent_at=None,
        )
        session.add(article_record)
        await session.flush((article_record,))
        await assign_native_article_context(session, article_record)
        inserted += 1
    source.collection_config = {
        **(source.collection_config or {}),
        "etag": batch.etag,
        "last_modified": batch.last_modified,
    }
    source.last_collection_success_at = batch.collected_at
    source.last_success_at = batch.collected_at
    source.consecutive_collection_failures = 0
    source.status = "active"
    run.status = "succeeded"
    run.completed_at = batch.collected_at
    run.articles_discovered = batch.discovered_count
    run.articles_inserted = inserted
    run.articles_existing = len(batch.articles) - inserted
    if batch.discovered_count > 0:
        await session.execute(
            update(NativeMediaCollectionAlertRecord)
            .where(
                NativeMediaCollectionAlertRecord.source_id == source.id,
                NativeMediaCollectionAlertRecord.resolved_at.is_(None),
            )
            .values(resolved_at=batch.collected_at)
        )
    else:
        await _ensure_alert(session, source.id, "no_content", "warning", "本轮采集未发现文章。")
    await session.commit()


async def _ensure_alert(
    session: AsyncSession,
    source_id: UUID,
    kind: str,
    severity: str,
    message: str,
) -> None:
    existing = await session.scalar(
        select(NativeMediaCollectionAlertRecord.id).where(
            NativeMediaCollectionAlertRecord.source_id == source_id,
            NativeMediaCollectionAlertRecord.kind == kind,
            NativeMediaCollectionAlertRecord.resolved_at.is_(None),
        )
    )
    if existing is None:
        session.add(
            NativeMediaCollectionAlertRecord(
                id=uuid4(),
                source_id=source_id,
                kind=kind,
                severity=severity,
                message=message,
                observed_at=datetime.now(UTC),
                resolved_at=None,
            )
        )


async def complete_native_collection_failure(
    session: AsyncSession,
    run_id: UUID,
    error: Exception,
) -> None:
    run = await session.get(NativeMediaCollectionRunRecord, run_id)
    if run is None or run.status != "running":
        raise RuntimeError(f"native collection run {run_id} is not running")
    source = await session.get(MediaSourceRecord, run.source_id)
    if source is None:
        raise RuntimeError(f"native collection source {run.source_id} disappeared")
    now = datetime.now(UTC)
    source.consecutive_collection_failures += 1
    if source.consecutive_collection_failures >= 3:
        source.status = "degraded"
        await _ensure_alert(
            session,
            source.id,
            "consecutive_failures",
            "critical" if source.consecutive_collection_failures >= 10 else "warning",
            f"媒体源已连续失败 {source.consecutive_collection_failures} 次。",
        )
    run.status = "failed"
    run.completed_at = now
    run.error_code = type(error).__name__.casefold()[:128]
    run.error_message = str(error)[:2000] or type(error).__name__
    await session.commit()


async def heartbeat_native_collection_worker(
    session: AsyncSession,
    worker_id: str,
    started_at: datetime,
) -> None:
    now = datetime.now(UTC)
    statement = insert(NativeMediaCollectionWorkerHeartbeatRecord).values(
        worker_id=worker_id,
        worker_version=WORKER_VERSION,
        started_at=started_at,
        last_seen_at=now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=(NativeMediaCollectionWorkerHeartbeatRecord.worker_id,),
        set_={"last_seen_at": now, "worker_version": WORKER_VERSION},
    )
    await session.execute(statement)
    await session.commit()


def _run(record: NativeMediaCollectionRunRecord) -> NativeMediaCollectionRun:
    return NativeMediaCollectionRun(
        id=record.id,
        source_id=record.source_id,
        status=record.status,
        worker_id=record.worker_id,
        config_sha256=record.config_sha256,
        scheduled_at=record.scheduled_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        articles_discovered=record.articles_discovered,
        articles_inserted=record.articles_inserted,
        articles_existing=record.articles_existing,
        error_code=record.error_code,
        error_message=record.error_message,
    )


async def get_native_media_collection_status(
    session: AsyncSession,
) -> NativeMediaCollectionStatus:
    now = datetime.now(UTC)
    enabled_records = tuple(
        (
            await session.execute(
                select(MediaSourceRecord).where(
                    MediaSourceRecord.native_collection_enabled.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    latest_runs = tuple(
        (
            await session.execute(
                select(NativeMediaCollectionRunRecord)
                .order_by(NativeMediaCollectionRunRecord.started_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    alerts = tuple(
        (
            await session.execute(
                select(NativeMediaCollectionAlertRecord)
                .where(NativeMediaCollectionAlertRecord.resolved_at.is_(None))
                .order_by(NativeMediaCollectionAlertRecord.observed_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    cutoff = now - timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS)
    worker_online = bool(
        await session.scalar(
            select(func.count(NativeMediaCollectionWorkerHeartbeatRecord.worker_id)).where(
                NativeMediaCollectionWorkerHeartbeatRecord.last_seen_at >= cutoff
            )
        )
    )
    return NativeMediaCollectionStatus(
        generated_at=now,
        worker_online=worker_online,
        enabled_source_count=len(enabled_records),
        due_source_count=sum(_due(record, now) for record in enabled_records),
        latest_runs=tuple(_run(record) for record in latest_runs),
        active_alerts=tuple(
            NativeMediaCollectionAlert(
                id=record.id,
                source_id=record.source_id,
                kind=record.kind,
                severity=record.severity,
                message=record.message,
                observed_at=record.observed_at,
            )
            for record in alerts
        ),
        limitations=(
            "SandOwl 原生采集仅访问显式启用的公开 HTTP(S) 来源，并阻止私网地址。",
            "历史 AgendaScope 数据保留只读兼容；原生采集不依赖外部 AgendaScope 数据库。",
        ),
    )
