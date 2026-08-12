"""Idempotently import the AgendaScope media read model into AI Decision Center.

Run with ``python -m app.media.import_agendascope``. The source transaction is
explicitly read-only; credentials and DSNs are never included in output.
"""

import asyncio
import ipaddress
import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from urllib.parse import unquote

from pydantic import AnyUrl, BaseModel, ConfigDict, TypeAdapter, ValidationError
from sqlalchemy import Table, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.database import ApplicationBase
from app.media import models as media_models
from app.media.locking import IMPORT_ADVISORY_LOCK_KEY

del media_models

BATCH_SIZE = 1_000
POSTGRESQL_DEFAULT_PORT = 5_432
SOURCE_URL_VARIABLE = "AGENDASCOPE_DATABASE_URL"
TARGET_URL_VARIABLE = "DATABASE_URL"

type ImportDatabaseUrl = AnyUrl


class ImportConfigurationError(ValueError):
    """Raised when importer-only configuration is absent or unsafe."""


class SourceSchemaError(RuntimeError):
    """Raised when AgendaScope does not expose the expected explicit columns."""


class ImportRuntimeError(RuntimeError):
    """Raised for an import failure without exposing connection credentials."""


class ImportSettings(BaseModel):
    """Validated source and target connection settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_url: ImportDatabaseUrl
    target_url: ImportDatabaseUrl


@dataclass(frozen=True, slots=True)
class TableImportCount:
    """Structured accounting for one imported table."""

    read: int
    inserted: int
    updated: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Complete structured importer result."""

    sources: TableImportCount
    articles: TableImportCount
    topics: TableImportCount
    topic_articles: TableImportCount
    topic_snapshots: TableImportCount


@dataclass(frozen=True, slots=True)
class ImportSpec:
    """Explicit source-to-target table contract."""

    source_table: str
    target_table: str
    columns: tuple[str, ...]
    conflict_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicalDatabaseAddress:
    """Credential-independent database address used for configuration checks."""

    host: str
    port: int
    database_name: str


@dataclass(frozen=True, slots=True)
class ConnectedDatabaseIdentity:
    """PostgreSQL-reported database endpoint identity."""

    database_name: str
    server_address: str | None
    server_port: int | None


@dataclass(frozen=True, slots=True)
class BatchImportCount:
    """Affected-row accounting for one source batch."""

    inserted: int
    updated: int
    skipped: int


IMPORT_SPECS = (
    ImportSpec(
        source_table="sources",
        target_table="media_sources",
        columns=(
            "id",
            "name",
            "name_zh",
            "country_code",
            "homepage_url",
            "media_type",
            "language",
            "status",
            "last_success_at",
            "created_at",
            "updated_at",
        ),
        conflict_columns=("id",),
    ),
    ImportSpec(
        source_table="articles",
        target_table="media_articles",
        columns=(
            "id",
            "source_id",
            "url",
            "url_hash",
            "title",
            "content",
            "summary",
            "language",
            "published_at",
            "crawled_at",
            "country_code",
            "is_duplicate",
            "created_at",
        ),
        conflict_columns=("id",),
    ),
    ImportSpec(
        source_table="topics",
        target_table="media_topics",
        columns=(
            "id",
            "name",
            "name_zh",
            "summary_zh",
            "topic_category",
            "status",
            "lifecycle_state",
            "first_seen_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ),
        conflict_columns=("id",),
    ),
    ImportSpec(
        source_table="topic_articles",
        target_table="media_topic_articles",
        columns=("topic_id", "article_id", "weight", "assign_method", "assigned_at"),
        conflict_columns=("topic_id", "article_id"),
    ),
    ImportSpec(
        source_table="topic_snapshots",
        target_table="media_topic_snapshots",
        columns=(
            "id",
            "country_code",
            "topic_id",
            "window_start",
            "window_end",
            "granularity",
            "article_count",
            "salience_score",
            "salience_rank",
            "created_at",
        ),
        conflict_columns=("id",),
    ),
)


def _read_required_environment_value(
    environment: Mapping[str, str],
    variable_name: str,
) -> str:
    value = environment.get(variable_name)
    if value is None or not value.strip():
        raise ImportConfigurationError(f"{variable_name} must be configured for the media import")
    return value


def _validate_postgresql_url(value: str, variable_name: str) -> ImportDatabaseUrl:
    adapter = TypeAdapter(
        AnyUrl,
        config=ConfigDict(strict=True),
    )
    try:
        url = adapter.validate_python(value)
    except ValidationError as error:
        raise ImportConfigurationError(f"{variable_name} must be a valid URL") from error
    if url.scheme not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise ImportConfigurationError(f"{variable_name} must use PostgreSQL")
    if url.host is None or url.path in (None, "", "/"):
        raise ImportConfigurationError(
            f"{variable_name} must include an explicit host and database name"
        )
    return url


def _normalize_database_host(host: str) -> str:
    normalized_host = host.casefold().rstrip(".")
    address_candidate = normalized_host.removeprefix("[").removesuffix("]")
    try:
        return ipaddress.ip_address(address_candidate).compressed
    except ValueError:
        return normalized_host.encode("idna").decode("ascii")


def _logical_database_address(url: ImportDatabaseUrl) -> LogicalDatabaseAddress:
    if url.host is None or url.path in (None, "", "/"):
        raise ImportConfigurationError("PostgreSQL URL must include a host and database name")
    return LogicalDatabaseAddress(
        host=_normalize_database_host(url.host),
        port=url.port if url.port is not None else POSTGRESQL_DEFAULT_PORT,
        database_name=unquote(url.path.removeprefix("/")),
    )


def load_import_settings(environment: Mapping[str, str]) -> ImportSettings:
    """Load both explicit DSNs without logging their values."""
    source_url = _validate_postgresql_url(
        _read_required_environment_value(environment, SOURCE_URL_VARIABLE),
        SOURCE_URL_VARIABLE,
    )
    target_url = _validate_postgresql_url(
        _read_required_environment_value(environment, TARGET_URL_VARIABLE),
        TARGET_URL_VARIABLE,
    )
    if _logical_database_address(source_url) == _logical_database_address(target_url):
        raise ImportConfigurationError("AgendaScope source and target databases must be different")
    return ImportSettings(source_url=source_url, target_url=target_url)


def _async_url(url: ImportDatabaseUrl) -> str:
    value = str(url)
    if value.startswith("postgresql+asyncpg://"):
        return value
    if value.startswith("postgresql+psycopg://"):
        return value.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return value.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _validate_source_columns(connection: AsyncConnection, spec: ImportSpec) -> None:
    """Validate only the explicitly supported AgendaScope columns."""
    result = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name"
        ),
        {"table_name": spec.source_table},
    )
    available_columns = {str(column_name) for column_name in result.scalars()}
    missing = sorted(set(spec.columns) - available_columns)
    if missing:
        joined = ", ".join(missing)
        raise SourceSchemaError(
            f"AgendaScope table {spec.source_table!r} is missing required columns: {joined}"
        )


async def _validate_target_columns(connection: AsyncConnection, spec: ImportSpec) -> None:
    """Require the Alembic-managed target table and all importer columns."""
    result = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name"
        ),
        {"table_name": spec.target_table},
    )
    available_columns = {str(column_name) for column_name in result.scalars()}
    if not available_columns:
        raise ImportRuntimeError(
            f"Target media table {spec.target_table!r} does not exist; "
            "run the Alembic migrations before importing"
        )
    missing = sorted(set(spec.columns) - available_columns)
    if missing:
        joined = ", ".join(missing)
        raise ImportRuntimeError(
            f"Target media table {spec.target_table!r} is missing required columns: {joined}; "
            "run the Alembic migrations before importing"
        )


async def _read_connected_database_identity(
    connection: AsyncConnection,
) -> ConnectedDatabaseIdentity:
    result = await connection.execute(
        text(
            "SELECT current_database() AS database_name, "
            "inet_server_addr()::text AS server_address, "
            "inet_server_port() AS server_port"
        )
    )
    row = result.mappings().one()
    database_name = row["database_name"]
    server_address = row["server_address"]
    server_port = row["server_port"]
    if not isinstance(database_name, str) or not database_name:
        raise ImportRuntimeError("PostgreSQL returned an invalid current database identity")
    if server_address is not None and not isinstance(server_address, str):
        raise ImportRuntimeError("PostgreSQL returned an invalid server address identity")
    if server_port is not None and not isinstance(server_port, int):
        raise ImportRuntimeError("PostgreSQL returned an invalid server port identity")
    return ConnectedDatabaseIdentity(
        database_name=database_name,
        server_address=server_address,
        server_port=server_port,
    )


def _ensure_distinct_connected_databases(
    source_identity: ConnectedDatabaseIdentity,
    target_identity: ConnectedDatabaseIdentity,
) -> None:
    if source_identity == target_identity:
        raise ImportConfigurationError(
            "AgendaScope source and target resolve to the same PostgreSQL database"
        )


async def _acquire_import_lock(connection: AsyncConnection) -> None:
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": IMPORT_ADVISORY_LOCK_KEY},
    )


async def _stream_source_rows(
    connection: AsyncConnection,
    spec: ImportSpec,
) -> AsyncIterator[list[dict[str, object]]]:
    """Stream explicit source columns in bounded batches."""
    column_sql = ", ".join(f'"{column}"' for column in spec.columns)
    statement = text(f'SELECT {column_sql} FROM "{spec.source_table}"')
    result = await connection.stream(statement.execution_options(yield_per=BATCH_SIZE))
    batch: list[dict[str, object]] = []
    async for row in result.mappings():
        batch.append({column: row[column] for column in spec.columns})
        if len(batch) == BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _target_table(spec: ImportSpec) -> Table:
    table = ApplicationBase.metadata.tables.get(spec.target_table)
    if table is None:
        raise ImportRuntimeError(f"Target media table {spec.target_table!r} is not registered")
    return table


def _row_key(
    row: Mapping[str, object],
    conflict_columns: tuple[str, ...],
) -> tuple[object, ...]:
    return tuple(row[column] for column in conflict_columns)


def _build_upsert_statement(
    target: Table,
    spec: ImportSpec,
    rows: list[dict[str, object]],
) -> Insert:
    update_columns = tuple(
        column for column in spec.columns if column not in set(spec.conflict_columns)
    )
    statement = insert(target).values(rows)
    if not update_columns:
        return statement.on_conflict_do_nothing(
            index_elements=[target.c[column] for column in spec.conflict_columns]
        )
    changed_condition = or_(
        *(
            target.c[column].is_distinct_from(statement.excluded[column])
            for column in update_columns
        )
    )
    return statement.on_conflict_do_update(
        index_elements=[target.c[column] for column in spec.conflict_columns],
        set_={column: statement.excluded[column] for column in update_columns},
        where=changed_condition,
    )


def _count_batch_rows(
    source_keys: tuple[tuple[object, ...], ...],
    existing_keys: frozenset[tuple[object, ...]],
    affected_keys: frozenset[tuple[object, ...]],
    source_table: str,
) -> BatchImportCount:
    distinct_source_keys = frozenset(source_keys)
    if len(distinct_source_keys) != len(source_keys):
        raise SourceSchemaError(
            f"AgendaScope table {source_table!r} returned duplicate conflict keys in one batch"
        )
    unexpected_keys = affected_keys - distinct_source_keys
    if unexpected_keys:
        raise ImportRuntimeError(
            f"Target media table for {source_table!r} returned unexpected affected rows"
        )
    inserted = len(affected_keys - existing_keys)
    updated = len(affected_keys & existing_keys)
    skipped = len(source_keys) - inserted - updated
    return BatchImportCount(inserted=inserted, updated=updated, skipped=skipped)


async def _import_table(
    source_connection: AsyncConnection,
    target_connection: AsyncConnection,
    spec: ImportSpec,
) -> TableImportCount:
    """Upsert only changed rows and account for every source row."""
    target = _target_table(spec)
    read_count = 0
    inserted_count = 0
    updated_count = 0
    skipped_count = 0
    async for rows in _stream_source_rows(source_connection, spec):
        read_count += len(rows)
        source_keys = tuple(_row_key(row, spec.conflict_columns) for row in rows)
        conflict_keys = frozenset(source_keys)
        if len(conflict_keys) != len(source_keys):
            raise SourceSchemaError(
                f"AgendaScope table {spec.source_table!r} returned duplicate conflict keys "
                "in one batch"
            )
        if len(spec.conflict_columns) == 1:
            conflict_column = target.c[spec.conflict_columns[0]]
            existing_keys = frozenset(
                (row[0],)
                for row in (
                    await target_connection.execute(
                        select(conflict_column).where(
                            conflict_column.in_(key[0] for key in conflict_keys)
                        )
                    )
                ).all()
            )
        else:
            conflict_columns = tuple(target.c[column] for column in spec.conflict_columns)
            existing_keys = frozenset(
                tuple(row)
                for row in (
                    await target_connection.execute(
                        select(*conflict_columns).where(
                            tuple_(*conflict_columns).in_(conflict_keys)
                        )
                    )
                ).all()
            )
        statement = _build_upsert_statement(target, spec, rows).returning(
            *(target.c[column] for column in spec.conflict_columns)
        )
        affected_result = await target_connection.execute(statement)
        affected_keys = frozenset(tuple(row) for row in affected_result.all())
        batch_count = _count_batch_rows(
            source_keys,
            existing_keys,
            affected_keys,
            spec.source_table,
        )
        inserted_count += batch_count.inserted
        updated_count += batch_count.updated
        skipped_count += batch_count.skipped
    return TableImportCount(
        read=read_count,
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
    )


async def import_agendascope(settings: ImportSettings) -> ImportResult:
    """Validate migrated target tables and import all five tables in FK order."""
    source_engine = create_async_engine(_async_url(settings.source_url), pool_pre_ping=True)
    target_engine = create_async_engine(_async_url(settings.target_url), pool_pre_ping=True)
    counts: dict[str, TableImportCount] = {}
    try:
        async with (
            source_engine.connect() as source_connection,
            target_engine.connect() as target_connection,
            target_connection.begin(),
        ):
            await _acquire_import_lock(target_connection)
            target_identity = await _read_connected_database_identity(target_connection)
            source_transaction = await source_connection.begin()
            try:
                await source_connection.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                source_identity = await _read_connected_database_identity(source_connection)
                _ensure_distinct_connected_databases(source_identity, target_identity)
                for spec in IMPORT_SPECS:
                    await _validate_target_columns(target_connection, spec)
                for spec in IMPORT_SPECS:
                    await _validate_source_columns(source_connection, spec)
                for spec in IMPORT_SPECS:
                    counts[spec.source_table] = await _import_table(
                        source_connection,
                        target_connection,
                        spec,
                    )
            finally:
                await source_transaction.rollback()
    except SQLAlchemyError as error:
        raise ImportRuntimeError(
            "AgendaScope media import failed during a database operation; "
            "verify source read access, target write access, and schema compatibility"
        ) from error
    finally:
        await source_engine.dispose()
        await target_engine.dispose()
    return ImportResult(
        sources=counts["sources"],
        articles=counts["articles"],
        topics=counts["topics"],
        topic_articles=counts["topic_articles"],
        topic_snapshots=counts["topic_snapshots"],
    )


async def _run() -> int:
    try:
        settings = load_import_settings(os.environ)
        result = await import_agendascope(settings)
    except (ImportConfigurationError, SourceSchemaError, ImportRuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {"status": "ok", "tables": asdict(result)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main() -> None:
    """Run the importer and terminate with a process-appropriate status."""
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
