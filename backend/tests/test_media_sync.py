"""Media sync contracts, configuration, and credential-free failure tests."""

import asyncio
import inspect
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from app.api.media import require_media_sync_status_session
from app.media import sync_repository
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
    load_import_settings,
)
from app.media.locking import release_import_lock, try_acquire_import_lock
from app.media.models import MediaArticleRecord
from app.media.sync_contracts import (
    MediaSyncRun,
    MediaSyncRunError,
    MediaSyncRunStatus,
    MediaSyncTableCount,
    MediaSyncTableName,
    MediaSyncTrigger,
    MediaSyncWatermarks,
)
from app.media.sync_models import MediaSyncRunRecord
from app.media.sync_repository import _failure_for, run_scheduled_media_sync
from app.media.sync_worker import load_worker_settings

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")
REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]


def _watermarks(now: datetime) -> MediaSyncWatermarks:
    return MediaSyncWatermarks(
        latest_source_updated_at=now,
        latest_article_crawled_at=now,
        latest_topic_updated_at=now,
        latest_topic_article_assigned_at=now,
        latest_snapshot_created_at=now,
        latest_snapshot_window_end=now,
        latest_propagation_updated_at=None,
    )


def _all_table_counts() -> tuple[MediaSyncTableCount, ...]:
    return tuple(
        MediaSyncTableCount(
            table_name=table_name,
            read_count=3,
            inserted_count=1,
            updated_count=1,
            skipped_count=1,
        )
        for table_name in MediaSyncTableName
    )


def test_succeeded_sync_contract_requires_complete_accounting() -> None:
    now = datetime.now(UTC)

    run = MediaSyncRun(
        id=uuid4(),
        trigger=MediaSyncTrigger.SCHEDULED,
        status=MediaSyncRunStatus.SUCCEEDED,
        worker_id="sendowl-sync-1",
        started_at=now,
        completed_at=now + timedelta(seconds=2),
        next_scheduled_at=now + timedelta(minutes=5),
        source_observed_at=now,
        source_watermarks=_watermarks(now),
        table_counts=_all_table_counts(),
        error=None,
    )

    assert run.status is MediaSyncRunStatus.SUCCEEDED
    assert len(run.table_counts) == len(MediaSyncTableName)


def test_failed_sync_contract_preserves_only_controlled_error() -> None:
    now = datetime.now(UTC)

    run = MediaSyncRun(
        id=uuid4(),
        trigger=MediaSyncTrigger.SCHEDULED,
        status=MediaSyncRunStatus.FAILED,
        worker_id="sendowl-sync-1",
        started_at=now,
        completed_at=now,
        next_scheduled_at=None,
        source_observed_at=None,
        source_watermarks=None,
        table_counts=(),
        error=MediaSyncRunError(
            code="source_schema_incompatible",
            message="The expected source migration was not observed.",
        ),
    )

    assert run.error is not None
    assert run.error.code == "source_schema_incompatible"


def test_sync_contract_rejects_next_schedule_for_failed_run() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValidationError, match="publish a next timestamp"):
        MediaSyncRun(
            id=uuid4(),
            trigger=MediaSyncTrigger.SCHEDULED,
            status=MediaSyncRunStatus.FAILED,
            worker_id="sendowl-sync-1",
            started_at=now,
            completed_at=now,
            next_scheduled_at=now + timedelta(minutes=5),
            source_observed_at=None,
            source_watermarks=None,
            table_counts=(),
            error=MediaSyncRunError(code="sync_cancelled", message="Cancelled."),
        )


def test_sync_table_count_rejects_unaccounted_rows() -> None:
    with pytest.raises(ValidationError, match="account for every source row"):
        MediaSyncTableCount(
            table_name=MediaSyncTableName.ARTICLES,
            read_count=3,
            inserted_count=1,
            updated_count=1,
            skipped_count=0,
        )


def test_worker_requires_explicit_source_attestation_and_safe_cadence() -> None:
    base_environment = {
        "AGENDASCOPE_DATABASE_URL": "postgresql://reader:secret@source/agendascope",
        "DATABASE_URL": "postgresql://writer:secret@target/sendowl",
        "AGENDASCOPE_EXPECTED_DATABASE_NAME": "agendascope",
        "AGENDASCOPE_EXPECTED_SCHEMA_REVISION": "0020_create_facts_layer",
        "MEDIA_SYNC_WORKER_ID": "sendowl-compose-media-sync-worker",
        "MEDIA_SYNC_INTERVAL_SECONDS": "300",
    }

    settings = load_worker_settings(base_environment)

    assert settings.interval_seconds == 300
    assert settings.worker_id == "sendowl-compose-media-sync-worker"

    with pytest.raises(ImportConfigurationError, match="AGENDASCOPE_EXPECTED_SCHEMA_REVISION"):
        load_worker_settings(
            {
                key: value
                for key, value in base_environment.items()
                if key != "AGENDASCOPE_EXPECTED_SCHEMA_REVISION"
            }
        )
    with pytest.raises(ImportConfigurationError, match="MEDIA_SYNC_INTERVAL_SECONDS"):
        load_worker_settings({**base_environment, "MEDIA_SYNC_INTERVAL_SECONDS": "59"})
    with pytest.raises(ImportConfigurationError, match="stable identifier"):
        load_worker_settings({**base_environment, "MEDIA_SYNC_WORKER_ID": "unsafe worker"})


def test_sync_status_dependency_starts_read_only_repeatable_read_snapshot() -> None:
    source = inspect.getsource(require_media_sync_status_session)

    assert source.index("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY") < source.index(
        "yield session"
    )


def test_source_engine_is_read_only_from_connection_start() -> None:
    settings = load_import_settings(
        {
            "AGENDASCOPE_DATABASE_URL": "postgresql://reader:secret@source/agendascope",
            "DATABASE_URL": "postgresql://writer:secret@target/sendowl",
            "AGENDASCOPE_EXPECTED_DATABASE_NAME": "agendascope",
            "AGENDASCOPE_EXPECTED_SCHEMA_REVISION": "0020_create_facts_layer",
        }
    )

    with patch.object(sync_repository, "create_async_engine") as engine_factory:
        sync_repository._source_engine(settings)

    engine_factory.assert_called_once_with(
        "postgresql+asyncpg://reader:secret@source/agendascope",
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "application_name": "sendowl-media-sync",
                "default_transaction_read_only": "on",
            }
        },
    )


def test_media_sync_compose_service_is_optional_and_does_not_restart() -> None:
    compose_source = (REPOSITORY_DIRECTORY / "compose.yaml").read_text(encoding="utf-8")
    worker_source = compose_source.split("  media-sync-worker:", maxsplit=1)[1].split(
        "\n  frontend:", maxsplit=1
    )[0]

    assert "profiles:\n      - media-sync" in worker_source
    assert 'restart: "no"' in worker_source
    assert "healthcheck:\n      disable: true" in worker_source
    assert "ports:" not in worker_source


def test_source_schema_failure_is_controlled_and_never_includes_urls() -> None:
    failure = _failure_for(SourceSchemaError("AgendaScope source migration head is incompatible"))

    assert failure.code == "source_schema_incompatible"
    assert "postgresql://" not in failure.message


def test_table_import_count_fixture_accounts_for_every_row() -> None:
    count = TableImportCount(read=6, inserted=1, updated=2, skipped=3)

    assert count.read == count.inserted + count.updated + count.skipped


def _postgresql_sync_settings(database_url: str) -> ImportSettings:
    return load_import_settings(
        {
            "AGENDASCOPE_DATABASE_URL": "postgresql://reader:secret@127.0.0.1:1/unreachable",
            "DATABASE_URL": database_url,
            "AGENDASCOPE_EXPECTED_DATABASE_NAME": "agendascope",
            "AGENDASCOPE_EXPECTED_SCHEMA_REVISION": "0020_create_facts_layer",
        }
    )


async def _exercise_concurrent_skip(database_url: str) -> None:
    settings = _postgresql_sync_settings(database_url)
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    worker_id = f"media-sync-concurrency-{uuid4()}"
    run_id = None
    try:
        async with engine.connect() as holder:
            assert await try_acquire_import_lock(holder) is True
            await holder.commit()
            try:
                execution = await run_scheduled_media_sync(settings, worker_id, 300)
                run_id = execution.run_id
                assert execution.status is MediaSyncRunStatus.SKIPPED_CONCURRENT
                assert execution.import_result is None
            finally:
                await release_import_lock(holder)
                await holder.commit()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            record = await session.scalar(
                select(MediaSyncRunRecord).where(MediaSyncRunRecord.id == run_id)
            )
            assert record is not None
            assert record.status == MediaSyncRunStatus.SKIPPED_CONCURRENT.value
            assert record.error_code is None
    finally:
        if run_id is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    delete(MediaSyncRunRecord).where(MediaSyncRunRecord.id == run_id)
                )
        await engine.dispose()


async def _exercise_database_rejects_failed_next_schedule(database_url: str) -> None:
    settings = _postgresql_sync_settings(database_url)
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    now = datetime.now(UTC)
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as connection:
                await connection.execute(
                    insert(MediaSyncRunRecord).values(
                        id=uuid4(),
                        trigger=MediaSyncTrigger.SCHEDULED.value,
                        status=MediaSyncRunStatus.FAILED.value,
                        worker_id=f"media-sync-invalid-schedule-{uuid4()}",
                        started_at=now,
                        completed_at=now,
                        next_scheduled_at=now + timedelta(minutes=5),
                        source_observed_at=None,
                        error_code="sync_cancelled",
                        error_message="Cancelled.",
                    )
                )
    finally:
        await engine.dispose()


async def _exercise_failed_refresh_preserves_media(database_url: str) -> None:
    settings = _postgresql_sync_settings(database_url)
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    worker_id = f"media-sync-failure-{uuid4()}"
    run_id = None
    try:
        async with engine.connect() as connection:
            articles_before = int(
                (await connection.scalar(select(func.count(MediaArticleRecord.id)))) or 0
            )
        with pytest.raises(ImportRuntimeError):
            await run_scheduled_media_sync(settings, worker_id, 300)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            record = await session.scalar(
                select(MediaSyncRunRecord)
                .where(MediaSyncRunRecord.worker_id == worker_id)
                .order_by(MediaSyncRunRecord.started_at.desc())
                .limit(1)
            )
            assert record is not None
            run_id = record.id
            assert record.status == MediaSyncRunStatus.FAILED.value
            assert record.error_code == "unexpected_import_failure"
            assert "postgresql://" not in (record.error_message or "")
            articles_after = int(
                (await session.scalar(select(func.count(MediaArticleRecord.id)))) or 0
            )
            assert articles_after == articles_before
    finally:
        if run_id is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    delete(MediaSyncRunRecord).where(MediaSyncRunRecord.id == run_id)
                )
        await engine.dispose()


async def _exercise_cancelled_refresh(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = _postgresql_sync_settings(database_url)
    settings = ImportSettings(
        source_url=base_settings.target_url,
        target_url=base_settings.target_url,
        expected_source_database_name=base_settings.expected_source_database_name,
        expected_source_schema_revision=base_settings.expected_source_schema_revision,
    )
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    independent_engine = create_async_engine(
        _async_url(settings.target_url),
        pool_pre_ping=True,
        pool_size=1,
    )
    worker_id = f"media-sync-cancel-{uuid4()}"
    import_started = asyncio.Event()
    failure_started = asyncio.Event()
    allow_failure = asyncio.Event()
    run_id = None
    complete_failure = sync_repository._complete_failure

    async def suspended_import(
        import_settings: ImportSettings,
        source_connection: AsyncConnection,
        target_connection: AsyncConnection,
    ) -> ImportSnapshot:
        del import_settings, source_connection, target_connection
        import_started.set()
        await asyncio.Future()
        raise AssertionError("cancelled import unexpectedly resumed")

    monkeypatch.setattr(sync_repository, "import_agendascope_transaction", suspended_import)

    async def delayed_complete_failure(
        target_engine: AsyncEngine,
        cancelled_run_id: UUID,
        plan: sync_repository.SyncRunPlan,
        failure: sync_repository.SyncFailure,
        completed_at: datetime,
    ) -> None:
        failure_started.set()
        await allow_failure.wait()
        await complete_failure(
            target_engine,
            cancelled_run_id,
            plan,
            failure,
            completed_at,
        )

    monkeypatch.setattr(sync_repository, "_complete_failure", delayed_complete_failure)
    try:
        async with engine.connect() as connection:
            articles_before = int(
                (await connection.scalar(select(func.count(MediaArticleRecord.id)))) or 0
            )
        task = asyncio.create_task(run_scheduled_media_sync(settings, worker_id, 300))
        await asyncio.wait_for(import_started.wait(), timeout=5)
        task.cancel()
        await asyncio.wait_for(failure_started.wait(), timeout=5)
        task.cancel()
        await asyncio.sleep(0)
        allow_failure.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with AsyncSession(engine, expire_on_commit=False) as session:
            record = await session.scalar(
                select(MediaSyncRunRecord)
                .where(MediaSyncRunRecord.worker_id == worker_id)
                .order_by(MediaSyncRunRecord.started_at.desc())
                .limit(1)
            )
            assert record is not None
            run_id = record.id
            assert record.status == MediaSyncRunStatus.FAILED.value
            assert record.error_code == "sync_cancelled"
            assert record.next_scheduled_at is None
            articles_after = int(
                (await session.scalar(select(func.count(MediaArticleRecord.id)))) or 0
            )
            assert articles_after == articles_before
        async with independent_engine.connect() as connection:
            assert await try_acquire_import_lock(connection) is True
            await connection.commit()
            await release_import_lock(connection)
            await connection.commit()
    finally:
        if run_id is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    delete(MediaSyncRunRecord).where(MediaSyncRunRecord.id == run_id)
                )
        await engine.dispose()
        await independent_engine.dispose()


async def _exercise_release_failure_preserves_primary_error(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _postgresql_sync_settings(database_url)
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    worker_id = f"media-sync-release-failure-{uuid4()}"
    run_id = None

    async def fail_release(connection: AsyncConnection) -> None:
        del connection
        raise ImportRuntimeError("injected lock release failure")

    monkeypatch.setattr(sync_repository, "release_import_lock", fail_release)
    try:
        with pytest.raises(ImportRuntimeError) as raised:
            await run_scheduled_media_sync(settings, worker_id, 300)
        assert "could not release its target lock" not in str(raised.value)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            record = await session.scalar(
                select(MediaSyncRunRecord)
                .where(MediaSyncRunRecord.worker_id == worker_id)
                .order_by(MediaSyncRunRecord.started_at.desc())
                .limit(1)
            )
            assert record is not None
            run_id = record.id
            assert record.status == MediaSyncRunStatus.FAILED.value
        async with engine.connect() as connection:
            assert await try_acquire_import_lock(connection) is True
            await connection.commit()
            await release_import_lock(connection)
            await connection.commit()
    finally:
        if run_id is not None:
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    delete(MediaSyncRunRecord).where(MediaSyncRunRecord.id == run_id)
                )
        await engine.dispose()


def _empty_import_snapshot(observed_at: datetime) -> ImportSnapshot:
    count = TableImportCount(read=0, inserted=0, updated=0, skipped=0)
    return ImportSnapshot(
        result=ImportResult(
            sources=count,
            articles=count,
            topics=count,
            topic_articles=count,
            topic_snapshots=count,
            propagation_events=count,
            propagation_edges=count,
            first_utterances=count,
        ),
        watermarks=SourceWatermarks(
            source_observed_at=observed_at,
            latest_source_updated_at=None,
            latest_article_crawled_at=None,
            latest_topic_updated_at=None,
            latest_topic_article_assigned_at=None,
            latest_snapshot_created_at=None,
            latest_snapshot_window_end=None,
            latest_propagation_updated_at=None,
        ),
    )


async def _exercise_success_release_failure_does_not_retry(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_settings = _postgresql_sync_settings(database_url)
    settings = ImportSettings(
        source_url=base_settings.target_url,
        target_url=base_settings.target_url,
        expected_source_database_name=base_settings.expected_source_database_name,
        expected_source_schema_revision=base_settings.expected_source_schema_revision,
    )
    engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    independent_engine = create_async_engine(
        _async_url(settings.target_url),
        pool_pre_ping=True,
        pool_size=1,
    )
    worker_id = f"media-sync-success-release-failure-{uuid4()}"
    stale_worker_id = f"media-sync-stale-other-worker-{uuid4()}"
    stale_run_id = uuid4()
    run_id = None

    async def successful_import(
        import_settings: ImportSettings,
        source_connection: AsyncConnection,
        target_connection: AsyncConnection,
    ) -> ImportSnapshot:
        del import_settings, source_connection, target_connection
        return _empty_import_snapshot(datetime.now(UTC))

    async def fail_release(connection: AsyncConnection) -> None:
        del connection
        raise ImportRuntimeError("injected lock release failure after success")

    monkeypatch.setattr(sync_repository, "import_agendascope_transaction", successful_import)
    monkeypatch.setattr(sync_repository, "release_import_lock", fail_release)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(MediaSyncRunRecord).values(
                    id=stale_run_id,
                    trigger=MediaSyncTrigger.MANUAL.value,
                    status=MediaSyncRunStatus.RUNNING.value,
                    worker_id=stale_worker_id,
                    started_at=datetime.now(UTC) - timedelta(minutes=1),
                    completed_at=None,
                    next_scheduled_at=None,
                    source_observed_at=None,
                    error_code=None,
                    error_message=None,
                )
            )
        execution = await run_scheduled_media_sync(settings, worker_id, 300)
        run_id = execution.run_id
        assert execution.status is MediaSyncRunStatus.SUCCEEDED
        async with AsyncSession(engine, expire_on_commit=False) as session:
            records = tuple(
                (
                    await session.scalars(
                        select(MediaSyncRunRecord).where(
                            MediaSyncRunRecord.id.in_((run_id, stale_run_id))
                        )
                    )
                ).all()
            )
            record_by_id = {record.id: record for record in records}
            assert record_by_id[run_id].status == MediaSyncRunStatus.SUCCEEDED.value
            assert record_by_id[stale_run_id].status == MediaSyncRunStatus.FAILED.value
            assert record_by_id[stale_run_id].error_code == "worker_process_restarted"
        async with independent_engine.connect() as connection:
            assert await try_acquire_import_lock(connection) is True
            await connection.commit()
            await release_import_lock(connection)
            await connection.commit()
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(
                delete(MediaSyncRunRecord).where(
                    MediaSyncRunRecord.id.in_(
                        tuple(identifier for identifier in (run_id, stale_run_id) if identifier)
                    )
                )
            )
        await engine.dispose()
        await independent_engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for media sync concurrency tests",
)
def test_postgresql_media_sync_skips_overlapping_runs() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_concurrent_skip(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for media sync lifecycle tests",
)
def test_postgresql_rejects_failed_run_with_next_schedule() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_database_rejects_failed_next_schedule(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for media sync failure tests",
)
def test_postgresql_failed_refresh_preserves_media_snapshot() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_failed_refresh_preserves_media(TEST_POSTGRES_DATABASE_URL))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for media sync cancellation tests",
)
def test_postgresql_cancelled_refresh_is_terminal_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_cancelled_refresh(TEST_POSTGRES_DATABASE_URL, monkeypatch))


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for media sync cleanup tests",
)
def test_postgresql_lock_release_failure_preserves_primary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(
        _exercise_release_failure_preserves_primary_error(
            TEST_POSTGRES_DATABASE_URL,
            monkeypatch,
        )
    )


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for committed sync cleanup tests",
)
def test_postgresql_committed_success_survives_lock_release_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(
        _exercise_success_release_failure_does_not_retry(
            TEST_POSTGRES_DATABASE_URL,
            monkeypatch,
        )
    )
