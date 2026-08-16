"""Atomic AgendaScope refresh execution and durable status queries."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from app.media.import_agendascope import (
    ImportConfigurationError,
    ImportResult,
    ImportRuntimeError,
    ImportSettings,
    ImportSnapshot,
    SourceSchemaError,
    SourceWatermarks,
    TableImportCount,
    _async_url,
    import_agendascope_transaction,
)
from app.media.locking import (
    MediaImportLockError,
    release_import_lock,
    try_acquire_import_lock,
)
from app.media.models import (
    MediaArticleRecord,
    MediaPropagationEventRecord,
    MediaSourceRecord,
    MediaTopicArticleRecord,
    MediaTopicRecord,
    MediaTopicSnapshotRecord,
)
from app.media.sync_contracts import (
    MediaArticleReconciliation,
    MediaSyncRun,
    MediaSyncRunError,
    MediaSyncRunStatus,
    MediaSyncStatusResponse,
    MediaSyncTableCount,
    MediaSyncTableName,
    MediaSyncTrigger,
    MediaSyncWatermarks,
)
from app.media.sync_models import MediaSyncRunRecord, MediaSyncRunTableRecord

MANUAL_SYNC_WORKER_ID = "sendowl-media-import-cli"
LOGGER = logging.getLogger("sendowl.media_sync")
SYNC_STATUS_LIMITATIONS = (
    "Each refresh scans all supported AgendaScope source rows and only writes changed target rows.",
    "Articles absent from a complete source scan are hidden in SendOwl without deleting "
    "frozen evidence; other source deletions are not reconciled.",
    "Business-time watermarks do not prove semantic completeness or real-time coverage.",
)


@dataclass(frozen=True, slots=True)
class MediaSyncExecution:
    """One completed runner invocation and optional import accounting."""

    run_id: UUID
    status: MediaSyncRunStatus
    import_result: ImportResult | None


@dataclass(frozen=True, slots=True)
class SyncRunPlan:
    """Explicit trigger context for one refresh attempt."""

    trigger: MediaSyncTrigger
    worker_id: str
    interval_seconds: int | None


@dataclass(frozen=True, slots=True)
class SyncFailure:
    """Credential-free failure persisted and exposed by the API."""

    code: str
    message: str


def utc_now() -> datetime:
    """Return a timezone-aware timestamp at a sync boundary."""
    return datetime.now(UTC)


def _target_engine(settings: ImportSettings) -> AsyncEngine:
    return create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)


def _source_engine(settings: ImportSettings) -> AsyncEngine:
    return create_async_engine(
        _async_url(settings.source_url),
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": "sendowl-media-sync",
                "default_transaction_read_only": "on",
            }
        },
    )


def _next_scheduled_at(plan: SyncRunPlan, completed_at: datetime) -> datetime | None:
    if plan.trigger is MediaSyncTrigger.MANUAL:
        if plan.interval_seconds is not None:
            raise ImportConfigurationError("Manual media sync cannot declare a schedule interval")
        return None
    if plan.interval_seconds is None:
        raise ImportConfigurationError("Scheduled media sync requires an explicit interval")
    return completed_at + timedelta(seconds=plan.interval_seconds)


def _failure_for(error: Exception) -> SyncFailure:
    if isinstance(error, SourceSchemaError):
        failure = SyncFailure(code="source_schema_incompatible", message=str(error))
    elif isinstance(error, ImportConfigurationError):
        failure = SyncFailure(code="unsafe_import_configuration", message=str(error))
    elif isinstance(error, (ImportRuntimeError, SQLAlchemyError, MediaImportLockError)):
        failure = SyncFailure(
            code="database_operation_failed",
            message=(
                "AgendaScope media refresh failed during a database operation; verify the "
                "dedicated source read role, target write access, and compatible schemas."
            ),
        )
    else:
        failure = SyncFailure(
            code="unexpected_import_failure",
            message=(
                "AgendaScope media refresh failed unexpectedly with error type "
                f"{type(error).__name__}; inspect worker diagnostics without exposing credentials."
            ),
        )
    if len(failure.message) > 500:
        return SyncFailure(
            code=failure.code,
            message=(
                "AgendaScope media refresh failed with a credential-free message "
                "over 500 characters."
            ),
        )
    return failure


def _table_results(result: ImportResult) -> tuple[tuple[MediaSyncTableName, TableImportCount], ...]:
    return (
        (MediaSyncTableName.SOURCES, result.sources),
        (MediaSyncTableName.ARTICLES, result.articles),
        (MediaSyncTableName.TOPICS, result.topics),
        (MediaSyncTableName.TOPIC_ARTICLES, result.topic_articles),
        (MediaSyncTableName.TOPIC_SNAPSHOTS, result.topic_snapshots),
        (MediaSyncTableName.PROPAGATION_EVENTS, result.propagation_events),
        (MediaSyncTableName.PROPAGATION_EDGES, result.propagation_edges),
        (MediaSyncTableName.FIRST_UTTERANCES, result.first_utterances),
    )


def _watermark_values(watermarks: SourceWatermarks) -> dict[str, datetime | None]:
    return {
        "source_observed_at": watermarks.source_observed_at,
        "source_latest_source_updated_at": watermarks.latest_source_updated_at,
        "source_latest_article_crawled_at": watermarks.latest_article_crawled_at,
        "source_latest_topic_updated_at": watermarks.latest_topic_updated_at,
        "source_latest_topic_article_assigned_at": (watermarks.latest_topic_article_assigned_at),
        "source_latest_snapshot_created_at": watermarks.latest_snapshot_created_at,
        "source_latest_snapshot_window_end": watermarks.latest_snapshot_window_end,
        "source_latest_propagation_updated_at": (watermarks.latest_propagation_updated_at),
    }


async def _mark_stale_runs(
    connection: AsyncConnection,
    completed_at: datetime,
) -> None:
    await connection.execute(
        update(MediaSyncRunRecord)
        .where(MediaSyncRunRecord.status == MediaSyncRunStatus.RUNNING.value)
        .values(
            status=MediaSyncRunStatus.FAILED.value,
            completed_at=completed_at,
            error_code="worker_process_restarted",
            error_message=(
                "A previous media sync process ended before its run reached a terminal state."
            ),
        )
    )


async def _insert_running_run(
    connection: AsyncConnection,
    run_id: UUID,
    plan: SyncRunPlan,
    started_at: datetime,
) -> None:
    await connection.execute(
        insert(MediaSyncRunRecord).values(
            id=run_id,
            trigger=plan.trigger.value,
            status=MediaSyncRunStatus.RUNNING.value,
            worker_id=plan.worker_id,
            started_at=started_at,
            completed_at=None,
            next_scheduled_at=None,
            source_observed_at=None,
            error_code=None,
            error_message=None,
        )
    )


async def _insert_skipped_run(
    connection: AsyncConnection,
    run_id: UUID,
    plan: SyncRunPlan,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    await connection.execute(
        insert(MediaSyncRunRecord).values(
            id=run_id,
            trigger=plan.trigger.value,
            status=MediaSyncRunStatus.SKIPPED_CONCURRENT.value,
            worker_id=plan.worker_id,
            started_at=started_at,
            completed_at=completed_at,
            next_scheduled_at=_next_scheduled_at(plan, completed_at),
            source_observed_at=None,
            error_code=None,
            error_message=None,
        )
    )


async def _complete_success(
    connection: AsyncConnection,
    run_id: UUID,
    plan: SyncRunPlan,
    snapshot: ImportSnapshot,
    completed_at: datetime,
) -> None:
    await connection.execute(
        insert(MediaSyncRunTableRecord),
        [
            {
                "run_id": run_id,
                "table_name": table_name.value,
                "read_count": count.read,
                "inserted_count": count.inserted,
                "updated_count": count.updated,
                "skipped_count": count.skipped,
            }
            for table_name, count in _table_results(snapshot.result)
        ],
    )
    update_result = await connection.execute(
        update(MediaSyncRunRecord)
        .where(
            MediaSyncRunRecord.id == run_id,
            MediaSyncRunRecord.status == MediaSyncRunStatus.RUNNING.value,
        )
        .values(
            status=MediaSyncRunStatus.SUCCEEDED.value,
            completed_at=completed_at,
            next_scheduled_at=_next_scheduled_at(plan, completed_at),
            **_watermark_values(snapshot.watermarks),
        )
    )
    if update_result.rowcount != 1:
        raise ImportRuntimeError("Media sync run changed before its success could be committed")


async def _complete_failure(
    engine: AsyncEngine,
    run_id: UUID,
    plan: SyncRunPlan,
    failure: SyncFailure,
    completed_at: datetime,
) -> None:
    async with engine.begin() as connection:
        update_result = await connection.execute(
            update(MediaSyncRunRecord)
            .where(
                MediaSyncRunRecord.id == run_id,
                MediaSyncRunRecord.status == MediaSyncRunStatus.RUNNING.value,
            )
            .values(
                status=MediaSyncRunStatus.FAILED.value,
                completed_at=completed_at,
                next_scheduled_at=None,
                error_code=failure.code,
                error_message=failure.message,
            )
        )
        if update_result.rowcount != 1:
            raise ImportRuntimeError("Media sync run changed before its failure could be recorded")


async def _complete_cancelled_failure(
    engine: AsyncEngine,
    run_id: UUID,
    plan: SyncRunPlan,
    completed_at: datetime,
) -> None:
    """Persist cancellation even when the caller repeats its cancellation request."""
    completion_task = asyncio.create_task(
        _complete_failure(
            engine,
            run_id,
            plan,
            SyncFailure(
                code="sync_cancelled",
                message="AgendaScope media refresh was cancelled before it completed.",
            ),
            completed_at,
        )
    )
    while not completion_task.done():
        try:
            await asyncio.shield(completion_task)
        except asyncio.CancelledError:
            continue
    if completion_task.cancelled():
        raise ImportRuntimeError("Cancelled media sync terminal-state write was itself cancelled")
    completion_error = completion_task.exception()
    if completion_error is not None:
        raise completion_error


async def _execute_locked_sync(
    settings: ImportSettings,
    target_engine: AsyncEngine,
    target_connection: AsyncConnection,
    run_id: UUID,
    plan: SyncRunPlan,
) -> MediaSyncExecution:
    source_engine = _source_engine(settings)
    try:
        async with source_engine.connect() as source_connection, target_connection.begin():
            snapshot = await import_agendascope_transaction(
                settings,
                source_connection,
                target_connection,
            )
            await _complete_success(
                target_connection,
                run_id,
                plan,
                snapshot,
                utc_now(),
            )
        return MediaSyncExecution(
            run_id=run_id,
            status=MediaSyncRunStatus.SUCCEEDED,
            import_result=snapshot.result,
        )
    except asyncio.CancelledError:
        try:
            await _complete_cancelled_failure(target_engine, run_id, plan, utc_now())
        except Exception as failure_error:
            LOGGER.warning(
                "cancelled media sync could not persist its terminal state",
                extra={
                    "error_type": type(failure_error).__name__,
                    "run_id": str(run_id),
                    "worker_id": plan.worker_id,
                },
            )
        raise
    except Exception as error:
        failure = _failure_for(error)
        await _complete_failure(target_engine, run_id, plan, failure, utc_now())
        if isinstance(error, (ImportConfigurationError, SourceSchemaError, ImportRuntimeError)):
            raise
        if isinstance(error, (SQLAlchemyError, MediaImportLockError)):
            raise ImportRuntimeError(failure.message) from error
        raise ImportRuntimeError(failure.message) from error
    finally:
        await source_engine.dispose()


async def _run_media_sync(settings: ImportSettings, plan: SyncRunPlan) -> MediaSyncExecution:
    target_engine = _target_engine(settings)
    run_id = uuid4()
    started_at = utc_now()
    try:
        async with target_engine.connect() as target_connection:
            acquired = await try_acquire_import_lock(target_connection)
            await target_connection.commit()
            if not acquired:
                completed_at = utc_now()
                async with target_connection.begin():
                    await _insert_skipped_run(
                        target_connection,
                        run_id,
                        plan,
                        started_at,
                        completed_at,
                    )
                return MediaSyncExecution(
                    run_id=run_id,
                    status=MediaSyncRunStatus.SKIPPED_CONCURRENT,
                    import_result=None,
                )
            primary_error: Exception | asyncio.CancelledError | None = None
            committed_success = False
            try:
                async with target_connection.begin():
                    await _mark_stale_runs(target_connection, started_at)
                    await _insert_running_run(target_connection, run_id, plan, started_at)
                execution = await _execute_locked_sync(
                    settings,
                    target_engine,
                    target_connection,
                    run_id,
                    plan,
                )
                committed_success = True
                return execution
            except asyncio.CancelledError as error:
                primary_error = error
                raise
            except Exception as error:
                primary_error = error
                raise
            finally:
                try:
                    if target_connection.in_transaction():
                        await target_connection.rollback()
                    await release_import_lock(target_connection)
                    await target_connection.commit()
                except Exception as cleanup_error:
                    try:
                        await target_connection.invalidate()
                    except Exception as invalidate_error:
                        LOGGER.critical(
                            "media sync target connection invalidation failed",
                            extra={
                                "cleanup_error_type": type(cleanup_error).__name__,
                                "invalidate_error_type": type(invalidate_error).__name__,
                                "run_id": str(run_id),
                                "worker_id": plan.worker_id,
                            },
                        )
                    if committed_success:
                        LOGGER.critical(
                            "media sync lock cleanup failed after committed success",
                            extra={
                                "cleanup_error_type": type(cleanup_error).__name__,
                                "run_id": str(run_id),
                                "worker_id": plan.worker_id,
                            },
                        )
                    elif primary_error is None:
                        raise ImportRuntimeError(
                            "AgendaScope media sync completed but could not release its target lock"
                        ) from cleanup_error
                    else:
                        LOGGER.warning(
                            "media sync lock cleanup failed after a primary error",
                            extra={
                                "cleanup_error_type": type(cleanup_error).__name__,
                                "primary_error_type": type(primary_error).__name__,
                                "run_id": str(run_id),
                                "worker_id": plan.worker_id,
                            },
                        )
    except (ImportConfigurationError, SourceSchemaError, ImportRuntimeError):
        raise
    except (SQLAlchemyError, MediaImportLockError) as error:
        raise ImportRuntimeError(
            "AgendaScope media sync could not use the target database safely"
        ) from error
    finally:
        await target_engine.dispose()


async def run_manual_media_sync(settings: ImportSettings) -> MediaSyncExecution:
    """Execute one non-blocking manual refresh with durable observability."""
    return await _run_media_sync(
        settings,
        SyncRunPlan(
            trigger=MediaSyncTrigger.MANUAL,
            worker_id=MANUAL_SYNC_WORKER_ID,
            interval_seconds=None,
        ),
    )


async def run_scheduled_media_sync(
    settings: ImportSettings,
    worker_id: str,
    interval_seconds: int,
) -> MediaSyncExecution:
    """Execute one scheduled refresh attempt without waiting behind another run."""
    return await _run_media_sync(
        settings,
        SyncRunPlan(
            trigger=MediaSyncTrigger.SCHEDULED,
            worker_id=worker_id,
            interval_seconds=interval_seconds,
        ),
    )


def _contract_watermarks(record: MediaSyncRunRecord) -> MediaSyncWatermarks:
    return MediaSyncWatermarks(
        latest_source_updated_at=record.source_latest_source_updated_at,
        latest_article_crawled_at=record.source_latest_article_crawled_at,
        latest_topic_updated_at=record.source_latest_topic_updated_at,
        latest_topic_article_assigned_at=record.source_latest_topic_article_assigned_at,
        latest_snapshot_created_at=record.source_latest_snapshot_created_at,
        latest_snapshot_window_end=record.source_latest_snapshot_window_end,
        latest_propagation_updated_at=record.source_latest_propagation_updated_at,
    )


async def _run_contract(session: AsyncSession, record: MediaSyncRunRecord) -> MediaSyncRun:
    count_records = tuple(
        (
            await session.scalars(
                select(MediaSyncRunTableRecord).where(MediaSyncRunTableRecord.run_id == record.id)
            )
        ).all()
    )
    count_by_name = {count.table_name: count for count in count_records}
    table_counts = tuple(
        MediaSyncTableCount(
            table_name=table_name,
            read_count=count_by_name[table_name.value].read_count,
            inserted_count=count_by_name[table_name.value].inserted_count,
            updated_count=count_by_name[table_name.value].updated_count,
            skipped_count=count_by_name[table_name.value].skipped_count,
        )
        for table_name in MediaSyncTableName
        if table_name.value in count_by_name
    )
    error = (
        MediaSyncRunError(code=record.error_code, message=record.error_message)
        if record.error_code is not None and record.error_message is not None
        else None
    )
    succeeded = record.status == MediaSyncRunStatus.SUCCEEDED.value
    return MediaSyncRun(
        id=record.id,
        trigger=MediaSyncTrigger(record.trigger),
        status=MediaSyncRunStatus(record.status),
        worker_id=record.worker_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        next_scheduled_at=record.next_scheduled_at,
        source_observed_at=record.source_observed_at,
        source_watermarks=_contract_watermarks(record) if succeeded else None,
        table_counts=table_counts,
        error=error,
    )


async def _target_watermarks(session: AsyncSession) -> MediaSyncWatermarks:
    row = (
        await session.execute(
            select(
                select(func.max(MediaSourceRecord.updated_at)).scalar_subquery(),
                select(func.max(MediaArticleRecord.crawled_at)).scalar_subquery(),
                select(func.max(MediaTopicRecord.updated_at)).scalar_subquery(),
                select(func.max(MediaTopicArticleRecord.assigned_at)).scalar_subquery(),
                select(func.max(MediaTopicSnapshotRecord.created_at)).scalar_subquery(),
                select(func.max(MediaTopicSnapshotRecord.window_end)).scalar_subquery(),
                select(func.max(MediaPropagationEventRecord.source_updated_at)).scalar_subquery(),
            )
        )
    ).one()
    return MediaSyncWatermarks(
        latest_source_updated_at=row[0],
        latest_article_crawled_at=row[1],
        latest_topic_updated_at=row[2],
        latest_topic_article_assigned_at=row[3],
        latest_snapshot_created_at=row[4],
        latest_snapshot_window_end=row[5],
        latest_propagation_updated_at=row[6],
    )


async def _article_reconciliation(session: AsyncSession) -> MediaArticleReconciliation:
    row = (
        await session.execute(
            select(
                func.count(MediaArticleRecord.id)
                .filter(MediaArticleRecord.source_present.is_(True))
                .label("present_count"),
                func.count(MediaArticleRecord.id)
                .filter(MediaArticleRecord.source_present.is_(False))
                .label("absent_count"),
                func.max(MediaArticleRecord.source_absent_at).label("latest_absent_at"),
            )
        )
    ).one()
    return MediaArticleReconciliation(
        present_count=int(row.present_count),
        absent_count=int(row.absent_count),
        latest_absent_at=row.latest_absent_at,
    )


async def get_media_sync_status(
    session: AsyncSession,
    generated_at: datetime,
) -> MediaSyncStatusResponse:
    """Return durable refresh history while preserving the last success on failure."""
    latest_record = await session.scalar(
        select(MediaSyncRunRecord)
        .order_by(MediaSyncRunRecord.started_at.desc(), MediaSyncRunRecord.id.desc())
        .limit(1)
    )
    latest_success_record = await session.scalar(
        select(MediaSyncRunRecord)
        .where(MediaSyncRunRecord.status == MediaSyncRunStatus.SUCCEEDED.value)
        .order_by(MediaSyncRunRecord.started_at.desc(), MediaSyncRunRecord.id.desc())
        .limit(1)
    )
    return MediaSyncStatusResponse(
        generated_at=generated_at,
        mode="periodic_snapshot_refresh",
        latest_run=(
            await _run_contract(session, latest_record) if latest_record is not None else None
        ),
        latest_success=(
            await _run_contract(session, latest_success_record)
            if latest_success_record is not None
            else None
        ),
        target_watermarks=await _target_watermarks(session),
        article_reconciliation=await _article_reconciliation(session),
        limitations=SYNC_STATUS_LIMITATIONS,
    )
