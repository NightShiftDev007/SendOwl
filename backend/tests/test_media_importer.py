"""Importer safety, idempotency, and optional PostgreSQL behavior tests."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

from app.media.import_agendascope import (
    IMPORT_ADVISORY_LOCK_KEY,
    IMPORT_SPECS,
    BatchImportCount,
    ImportConfigurationError,
    ImportRuntimeError,
    ImportSpec,
    SourceSchemaError,
    _acquire_import_lock,
    _async_url,
    _build_upsert_statement,
    _count_batch_rows,
    _ensure_distinct_connected_databases,
    _read_connected_database_identity,
    _target_table,
    _validate_postgresql_url,
    _validate_target_columns,
    load_import_settings,
)

TEST_POSTGRES_DATABASE_URL = os.environ.get("TEST_POSTGRES_DATABASE_URL")


@pytest.mark.parametrize(
    ("source_url", "target_url"),
    (
        (
            "postgresql://source:source-secret@DB.Example.COM/adc",
            "postgresql+asyncpg://target:target-secret@db.example.com:5432/adc",
        ),
        (
            "postgresql+psycopg://source:source-secret@db.example.com./%61dc?sslmode=require",
            "postgresql://target:target-secret@DB.EXAMPLE.COM:5432/adc",
        ),
        (
            "postgresql://source:source-secret@[2001:0db8::1]/adc",
            "postgresql+asyncpg://target:target-secret@[2001:db8::1]:5432/adc",
        ),
    ),
)
def test_importer_rejects_equivalent_logical_database_urls(
    source_url: str,
    target_url: str,
) -> None:
    with pytest.raises(ImportConfigurationError, match="must be different") as raised:
        load_import_settings(
            {
                "AGENDASCOPE_DATABASE_URL": source_url,
                "DATABASE_URL": target_url,
            }
        )

    message = str(raised.value)
    assert "source-secret" not in message
    assert "target-secret" not in message


def test_importer_accepts_distinct_database_names_on_the_same_server() -> None:
    settings = load_import_settings(
        {
            "AGENDASCOPE_DATABASE_URL": "postgresql://source:secret@db:5432/agendascope",
            "DATABASE_URL": "postgresql+asyncpg://target:secret@DB/decision_center",
        }
    )

    assert settings.source_url.path == "/agendascope"
    assert settings.target_url.path == "/decision_center"


def test_unchanged_rows_are_counted_as_skipped() -> None:
    count = _count_batch_rows(
        source_keys=(("new",), ("changed",), ("unchanged",)),
        existing_keys=frozenset({("changed",), ("unchanged",)}),
        affected_keys=frozenset({("new",), ("changed",)}),
        source_table="articles",
    )

    assert count == BatchImportCount(inserted=1, updated=1, skipped=1)


def test_repeated_batch_is_entirely_skipped() -> None:
    source_keys = (("first",), ("second",))

    count = _count_batch_rows(
        source_keys=source_keys,
        existing_keys=frozenset(source_keys),
        affected_keys=frozenset(),
        source_table="articles",
    )

    assert count == BatchImportCount(inserted=0, updated=0, skipped=2)


def test_duplicate_source_conflict_keys_fail_explicitly() -> None:
    with pytest.raises(SourceSchemaError, match="duplicate conflict keys"):
        _count_batch_rows(
            source_keys=(("duplicate",), ("duplicate",)),
            existing_keys=frozenset(),
            affected_keys=frozenset(),
            source_table="articles",
        )


def test_upsert_updates_only_distinct_values() -> None:
    spec = IMPORT_SPECS[0]
    target = _target_table(spec)
    statement = _build_upsert_statement(
        target,
        spec,
        [{"id": "source-id", "name": "Source"}],
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert " ON CONFLICT " in compiled
    assert " DO UPDATE SET " in compiled
    assert " IS DISTINCT FROM " in compiled


async def _exercise_postgresql_import_guards(database_url: str) -> None:
    validated_url = _validate_postgresql_url(database_url, "TEST_POSTGRES_DATABASE_URL")
    engine = create_async_engine(_async_url(validated_url), pool_pre_ping=True)
    missing_spec = ImportSpec(
        source_table="missing_source",
        target_table="media_importer_test_table_that_does_not_exist",
        columns=("id",),
        conflict_columns=("id",),
    )
    try:
        async with engine.connect() as first_connection, engine.connect() as second_connection:
            first_transaction = await first_connection.begin()
            try:
                await _acquire_import_lock(first_connection)
                first_identity = await _read_connected_database_identity(first_connection)
                second_identity = await _read_connected_database_identity(second_connection)
                with pytest.raises(ImportConfigurationError, match="same PostgreSQL database"):
                    _ensure_distinct_connected_databases(first_identity, second_identity)

                second_lock_result = await second_connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                    {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
                )
                assert second_lock_result.scalar_one() is False
                await second_connection.rollback()

                with pytest.raises(ImportRuntimeError, match="run the Alembic migrations"):
                    await _validate_target_columns(first_connection, missing_spec)
                source_spec = IMPORT_SPECS[0]
                await _validate_target_columns(first_connection, source_spec)
                source_table = _target_table(source_spec)
                source_id = uuid4()
                now = datetime.now(UTC)
                source_row: dict[str, object] = {
                    "id": source_id,
                    "name": "Importer integration source",
                    "name_zh": None,
                    "country_code": "CN",
                    "homepage_url": "https://example.com/importer-integration",
                    "media_type": "online",
                    "language": "zh",
                    "status": "active",
                    "last_success_at": None,
                    "created_at": now,
                    "updated_at": now,
                }

                inserted_result = await first_connection.execute(
                    _build_upsert_statement(source_table, source_spec, [source_row]).returning(
                        source_table.c.id
                    )
                )
                assert inserted_result.scalar_one() == source_id

                unchanged_result = await first_connection.execute(
                    _build_upsert_statement(source_table, source_spec, [source_row]).returning(
                        source_table.c.id
                    )
                )
                assert unchanged_result.scalar_one_or_none() is None

                changed_row = {**source_row, "name": "Changed importer integration source"}
                updated_result = await first_connection.execute(
                    _build_upsert_statement(source_table, source_spec, [changed_row]).returning(
                        source_table.c.id
                    )
                )
                assert updated_result.scalar_one() == source_id
            finally:
                await first_transaction.rollback()

            async with second_connection.begin():
                released_lock_result = await second_connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                    {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
                )
                assert released_lock_result.scalar_one() is True
                persisted_result = await second_connection.execute(
                    text("SELECT id FROM media_sources WHERE id = :source_id"),
                    {"source_id": source_id},
                )
                assert persisted_result.scalar_one_or_none() is None
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    TEST_POSTGRES_DATABASE_URL is None,
    reason="TEST_POSTGRES_DATABASE_URL is required for the PostgreSQL importer guard test",
)
def test_postgresql_identity_lock_and_migration_guard() -> None:
    assert TEST_POSTGRES_DATABASE_URL is not None
    asyncio.run(_exercise_postgresql_import_guards(TEST_POSTGRES_DATABASE_URL))
