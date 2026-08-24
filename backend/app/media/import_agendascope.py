"""Idempotently import the AgendaScope media read model into SandOwl.

Run with ``python -m app.media.import_agendascope``. The source transaction is
explicitly read-only; credentials and DSNs are never included in output.
"""

import asyncio
import ipaddress
import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import unquote
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, SecretStr, TypeAdapter, ValidationError
from sqlalchemy import Table, bindparam, delete, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.database import ApplicationBase
from app.media import models as media_models
from app.media.locking import try_acquire_import_lock

del media_models

BATCH_SIZE = 1_000
POSTGRESQL_DEFAULT_PORT = 5_432
SOURCE_URL_VARIABLE = "AGENDASCOPE_DATABASE_URL"
TARGET_URL_VARIABLE = "DATABASE_URL"
EXPECTED_SOURCE_DATABASE_VARIABLE = "AGENDASCOPE_EXPECTED_DATABASE_NAME"
EXPECTED_SOURCE_REVISION_VARIABLE = "AGENDASCOPE_EXPECTED_SCHEMA_REVISION"

type ImportDatabaseUrl = AnyUrl


class ImportConfigurationError(ValueError):
    """Raised when importer-only configuration is absent or unsafe."""


class SourceSchemaError(RuntimeError):
    """Raised when AgendaScope does not expose the expected explicit columns."""


class ImportRuntimeError(RuntimeError):
    """Raised for an import failure without exposing connection credentials."""


class ImportAlreadyRunningError(RuntimeError):
    """Raised when a second refresh would overlap the active refresh."""


class ImportSettings(BaseModel):
    """Validated source and target connection settings with redacted credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_url: SecretStr
    target_url: SecretStr
    expected_source_database_name: str
    expected_source_schema_revision: str


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
    propagation_events: TableImportCount
    propagation_edges: TableImportCount
    first_utterances: TableImportCount


@dataclass(frozen=True, slots=True)
class SourceWatermarks:
    """Source business timestamps observed in one repeatable-read snapshot."""

    source_observed_at: datetime
    latest_source_updated_at: datetime | None
    latest_article_crawled_at: datetime | None
    latest_topic_updated_at: datetime | None
    latest_topic_article_assigned_at: datetime | None
    latest_snapshot_created_at: datetime | None
    latest_snapshot_window_end: datetime | None
    latest_propagation_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class ImportSnapshot:
    """Successful import accounting bound to its exact source snapshot."""

    result: ImportResult
    watermarks: SourceWatermarks


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

FIRST_UTTERANCE_SPEC = ImportSpec(
    source_table="llm_judgements:first_utterance",
    target_table="media_first_utterances",
    columns=(
        "id",
        "topic_id",
        "entity_id",
        "entity_name",
        "entity_type",
        "country_code",
        "article_id",
        "occurred_at",
        "evidence_quote",
        "confidence",
        "model_name",
        "prompt_version",
        "source_created_at",
    ),
    conflict_columns=("id",),
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
    source_value = _read_required_environment_value(environment, SOURCE_URL_VARIABLE)
    target_value = _read_required_environment_value(environment, TARGET_URL_VARIABLE)
    source_url = _validate_postgresql_url(
        source_value,
        SOURCE_URL_VARIABLE,
    )
    target_url = _validate_postgresql_url(
        target_value,
        TARGET_URL_VARIABLE,
    )
    if _logical_database_address(source_url) == _logical_database_address(target_url):
        raise ImportConfigurationError("AgendaScope source and target databases must be different")
    expected_source_database_name = _read_required_environment_value(
        environment,
        EXPECTED_SOURCE_DATABASE_VARIABLE,
    )
    if len(expected_source_database_name) > 63:
        raise ImportConfigurationError(
            f"{EXPECTED_SOURCE_DATABASE_VARIABLE} must contain at most 63 characters"
        )
    expected_source_schema_revision = _read_required_environment_value(
        environment,
        EXPECTED_SOURCE_REVISION_VARIABLE,
    )
    if len(expected_source_schema_revision) > 128:
        raise ImportConfigurationError(
            f"{EXPECTED_SOURCE_REVISION_VARIABLE} must contain at most 128 characters"
        )
    return ImportSettings(
        source_url=SecretStr(source_value),
        target_url=SecretStr(target_value),
        expected_source_database_name=expected_source_database_name,
        expected_source_schema_revision=expected_source_schema_revision,
    )


def _async_url(url: SecretStr) -> str:
    value = url.get_secret_value()
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


async def _validate_source_attestation(
    connection: AsyncConnection,
    source_identity: ConnectedDatabaseIdentity,
    settings: ImportSettings,
) -> None:
    """Require the operator-declared AgendaScope database and migration head."""
    if source_identity.database_name != settings.expected_source_database_name:
        raise SourceSchemaError(
            "AgendaScope source database identity does not match "
            f"{EXPECTED_SOURCE_DATABASE_VARIABLE}"
        )
    revision_result = await connection.execute(text("SELECT version_num FROM alembic_version"))
    revisions = tuple(str(revision) for revision in revision_result.scalars())
    expected_revisions = (settings.expected_source_schema_revision,)
    if revisions != expected_revisions:
        raise SourceSchemaError(
            "AgendaScope source migration head does not match "
            f"{EXPECTED_SOURCE_REVISION_VARIABLE}; expected exactly one declared revision"
        )


def _optional_watermark(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise SourceSchemaError(f"AgendaScope {field_name} watermark must be a timestamp")
    return value


async def _read_source_watermarks(connection: AsyncConnection) -> SourceWatermarks:
    """Read business-time maxima from the same repeatable-read source snapshot."""
    row = (
        (
            await connection.execute(
                text(
                    "SELECT transaction_timestamp() AS source_observed_at, "
                    "(SELECT max(updated_at) FROM sources) AS latest_source_updated_at, "
                    "(SELECT max(crawled_at) FROM articles) AS latest_article_crawled_at, "
                    "(SELECT max(updated_at) FROM topics) AS latest_topic_updated_at, "
                    "(SELECT max(assigned_at) FROM topic_articles) "
                    "AS latest_topic_article_assigned_at, "
                    "(SELECT max(created_at) FROM topic_snapshots) "
                    "AS latest_snapshot_created_at, "
                    "(SELECT max(window_end) FROM topic_snapshots) AS latest_snapshot_window_end, "
                    "(SELECT max(updated_at) FROM agenda_events) "
                    "AS latest_propagation_updated_at"
                )
            )
        )
        .mappings()
        .one()
    )
    source_observed_at = row["source_observed_at"]
    if not isinstance(source_observed_at, datetime):
        raise SourceSchemaError("AgendaScope source transaction timestamp is invalid")
    return SourceWatermarks(
        source_observed_at=source_observed_at,
        latest_source_updated_at=_optional_watermark(
            row["latest_source_updated_at"],
            "sources.updated_at",
        ),
        latest_article_crawled_at=_optional_watermark(
            row["latest_article_crawled_at"],
            "articles.crawled_at",
        ),
        latest_topic_updated_at=_optional_watermark(
            row["latest_topic_updated_at"],
            "topics.updated_at",
        ),
        latest_topic_article_assigned_at=_optional_watermark(
            row["latest_topic_article_assigned_at"],
            "topic_articles.assigned_at",
        ),
        latest_snapshot_created_at=_optional_watermark(
            row["latest_snapshot_created_at"],
            "topic_snapshots.created_at",
        ),
        latest_snapshot_window_end=_optional_watermark(
            row["latest_snapshot_window_end"],
            "topic_snapshots.window_end",
        ),
        latest_propagation_updated_at=_optional_watermark(
            row["latest_propagation_updated_at"],
            "agenda_events.updated_at",
        ),
    )


async def _acquire_import_lock(connection: AsyncConnection) -> None:
    """Acquire the non-blocking session lock for direct integration tests."""
    if not await try_acquire_import_lock(connection):
        raise ImportAlreadyRunningError("Another AgendaScope media refresh is already running")


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
    source_observed_at: datetime | None,
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
        if spec.source_table == "articles":
            if source_observed_at is None:
                raise ImportRuntimeError("Article reconciliation requires source_observed_at")
            await target_connection.execute(
                update(target)
                .where(target.c.id.in_(key[0] for key in conflict_keys))
                .values(
                    source_present=True,
                    source_last_observed_at=source_observed_at,
                    source_absent_at=None,
                )
            )
    return TableImportCount(
        read=read_count,
        inserted=inserted_count,
        updated=updated_count,
        skipped=skipped_count,
    )


async def _reconcile_absent_articles(
    target_connection: AsyncConnection,
    source_observed_at: datetime,
) -> int:
    """Hide source-absent articles while preserving frozen SandOwl evidence rows."""
    target = _target_table(next(spec for spec in IMPORT_SPECS if spec.source_table == "articles"))
    result = await target_connection.execute(
        update(target)
        .where(
            target.c.source_present.is_(True),
            or_(
                target.c.source_last_observed_at.is_(None),
                target.c.source_last_observed_at != source_observed_at,
            ),
        )
        .values(source_present=False, source_absent_at=source_observed_at)
    )
    return int(result.rowcount or 0)


def _validated_first_utterance_row(row: Mapping[str, object]) -> dict[str, object]:
    """Project one positive judgment while rejecting unverifiable source evidence."""
    uuid_fields = ("id", "topic_id", "entity_id", "article_id")
    if any(not isinstance(row[field], UUID) for field in uuid_fields):
        raise SourceSchemaError("AgendaScope first-utterance identities must be UUIDs")
    entity_name = row["entity_name"]
    entity_type = row["entity_type"]
    country_code = row["country_code"]
    evidence_quote = row["evidence_quote"]
    confidence = row["confidence"]
    model_name = row["model_name"]
    prompt_version = row["prompt_version"]
    source_created_at = row["source_created_at"]
    occurred_at = row["occurred_at"]
    if not isinstance(entity_name, str) or not 1 <= len(entity_name.strip()) <= 200:
        raise SourceSchemaError("AgendaScope first-utterance entity_name is invalid")
    if entity_type not in ("person", "thinktank", "intl_org", "gov_body"):
        raise SourceSchemaError("AgendaScope first-utterance entity_type is invalid")
    if (
        not isinstance(country_code, str)
        or len(country_code) != 2
        or not country_code.isalpha()
        or not country_code.isupper()
    ):
        raise SourceSchemaError("AgendaScope first-utterance country_code is invalid")
    if not isinstance(evidence_quote, str) or not 1 <= len(evidence_quote.strip()) <= 2_000:
        raise SourceSchemaError("AgendaScope first-utterance evidence_quote is invalid")
    if row["evidence_verified"] is not True:
        raise SourceSchemaError(
            "AgendaScope first-utterance evidence_quote is absent from its source article"
        )
    if confidence != "high":
        raise SourceSchemaError("AgendaScope positive first-utterance confidence must be high")
    if not isinstance(model_name, str) or not 1 <= len(model_name.strip()) <= 200:
        raise SourceSchemaError("AgendaScope first-utterance model_name is invalid")
    if not isinstance(prompt_version, str) or not 1 <= len(prompt_version.strip()) <= 100:
        raise SourceSchemaError("AgendaScope first-utterance prompt_version is invalid")
    if not isinstance(source_created_at, datetime):
        raise SourceSchemaError("AgendaScope first-utterance created_at is invalid")
    if occurred_at is not None and not isinstance(occurred_at, datetime):
        raise SourceSchemaError("AgendaScope first-utterance occurred_at is invalid")
    return {column: row[column] for column in FIRST_UTTERANCE_SPEC.columns}


async def _import_first_utterances(
    source_connection: AsyncConnection,
    target_connection: AsyncConnection,
) -> TableImportCount:
    """Import only positive, article-verifiable judgments without model reasoning."""
    target = _target_table(FIRST_UTTERANCE_SPEC)
    statement = text(
        "SELECT judgement.id, (judgement.input_payload->>'topic_id')::uuid AS topic_id, "
        "(judgement.input_payload->>'entity_id')::uuid AS entity_id, "
        "judgement.input_payload->>'entity_name' AS entity_name, "
        "judgement.input_payload->>'entity_type' AS entity_type, "
        "judgement.input_payload->>'country_code' AS country_code, "
        "article.id AS article_id, "
        "CASE WHEN pg_input_is_valid(judgement.output_payload->>'occurred_at', "
        "'timestamp with time zone') THEN "
        "(judgement.output_payload->>'occurred_at')::timestamptz ELSE NULL END AS occurred_at, "
        "judgement.output_payload->>'evidence_quote' AS evidence_quote, "
        "judgement.output_payload->>'confidence' AS confidence, judgement.model_name, "
        "judgement.prompt_version, judgement.created_at AS source_created_at, "
        "position(judgement.output_payload->>'evidence_quote' IN "
        "coalesce(article.content,'') || E'\\n' || article.title) > 0 AS evidence_verified "
        "FROM llm_judgements AS judgement "
        "JOIN articles AS article "
        "ON article.id=(judgement.input_payload->>'candidate_article_id')::uuid "
        "WHERE judgement.task_type='first_utterance' AND judgement.success "
        "AND judgement.output_payload->>'is_first_utterance'='true' "
        "ORDER BY judgement.id"
    )
    result = await source_connection.stream(statement.execution_options(yield_per=BATCH_SIZE))
    counts = BatchImportCount(inserted=0, updated=0, skipped=0)
    read_count = 0
    batch: list[dict[str, object]] = []

    async def import_batch(rows: list[dict[str, object]]) -> BatchImportCount:
        source_keys = tuple(_row_key(row, FIRST_UTTERANCE_SPEC.conflict_columns) for row in rows)
        ids = tuple(key[0] for key in source_keys)
        existing_keys = frozenset(
            (existing_id,)
            for existing_id in (
                await target_connection.scalars(select(target.c.id).where(target.c.id.in_(ids)))
            )
        )
        affected_keys = frozenset(
            tuple(affected)
            for affected in (
                await target_connection.execute(
                    _build_upsert_statement(target, FIRST_UTTERANCE_SPEC, rows).returning(
                        target.c.id
                    )
                )
            ).all()
        )
        return _count_batch_rows(
            source_keys,
            existing_keys,
            affected_keys,
            FIRST_UTTERANCE_SPEC.source_table,
        )

    async for source_row in result.mappings():
        batch.append(_validated_first_utterance_row(source_row))
        read_count += 1
        if len(batch) == BATCH_SIZE:
            imported = await import_batch(batch)
            counts = BatchImportCount(
                counts.inserted + imported.inserted,
                counts.updated + imported.updated,
                counts.skipped + imported.skipped,
            )
            batch = []
    if batch:
        imported = await import_batch(batch)
        counts = BatchImportCount(
            counts.inserted + imported.inserted,
            counts.updated + imported.updated,
            counts.skipped + imported.skipped,
        )
    return TableImportCount(read_count, counts.inserted, counts.updated, counts.skipped)


def _required_country_code(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value.strip()) != 2 or not value.strip().isalpha():
        raise SourceSchemaError(f"AgendaScope propagation {field_name} must be an ISO alpha-2 code")
    return value.strip().upper()


def _optional_uuid(value: object, field_name: str) -> UUID | None:
    if value is None or value == "":
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise SourceSchemaError(f"AgendaScope propagation {field_name} must be a UUID") from error


def _optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise SourceSchemaError(f"AgendaScope propagation {field_name} must be an ISO datetime")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SourceSchemaError(
            f"AgendaScope propagation {field_name} must be an ISO datetime"
        ) from error


def _required_uuid(value: object, field_name: str) -> UUID:
    parsed = _optional_uuid(value, field_name)
    if parsed is None:
        raise SourceSchemaError(f"AgendaScope propagation {field_name} must be a UUID")
    return parsed


def _required_datetime(value: object, field_name: str) -> datetime:
    parsed = _optional_datetime(value, field_name)
    if parsed is None:
        raise SourceSchemaError(f"AgendaScope propagation {field_name} must be a timestamp")
    return parsed


def _propagation_edges(event_row: Mapping[str, object]) -> list[dict[str, object]]:
    sequence = event_row["follower_sequence"]
    if not isinstance(sequence, list):
        raise SourceSchemaError("AgendaScope propagation follower_sequence must be a JSON array")
    event_id = event_row["id"]
    origin_country = _required_country_code(event_row["origin_country_code"], "origin_country_code")
    seen_countries: set[str] = set()
    edges: list[dict[str, object]] = []
    for position, item in enumerate(sequence):
        if not isinstance(item, dict):
            raise SourceSchemaError(
                "AgendaScope propagation follower_sequence items must be objects"
            )
        destination = _required_country_code(item.get("country_code"), "country_code")
        if destination in seen_countries:
            raise SourceSchemaError(
                "AgendaScope propagation follower_sequence must not repeat a country"
            )
        seen_countries.add(destination)
        lag_value = item.get("lag_hours")
        if not isinstance(lag_value, (int, float)) or isinstance(lag_value, bool) or lag_value < 0:
            raise SourceSchemaError("AgendaScope propagation lag_hours must be non-negative")
        media_name = item.get("first_media_name")
        if media_name is not None and (not isinstance(media_name, str) or not media_name.strip()):
            raise SourceSchemaError(
                "AgendaScope propagation first_media_name must be non-empty when present"
            )
        edges.append(
            {
                "event_id": event_id,
                "position": position,
                "from_country_code": origin_country,
                "to_country_code": destination,
                "lag_hours": lag_value,
                "first_media_name": media_name.strip() if isinstance(media_name, str) else None,
                "first_article_id": _optional_uuid(
                    item.get("first_article_id"), "first_article_id"
                ),
                "first_published_at": _optional_datetime(
                    item.get("first_published_at"), "first_published_at"
                ),
                "source_follower_id": None,
                "follower_source_id": None,
                "observation_source": "legacy_projection",
            }
        )
    return edges


def _structured_propagation_edge(
    event_row: Mapping[str, object],
    follower_row: Mapping[str, object],
) -> dict[str, object]:
    """Project one authoritative AgendaScope follower row without inventing fields."""
    sequence_no = follower_row["sequence_no"]
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 0:
        raise SourceSchemaError("AgendaScope propagation sequence_no must be non-negative")
    lag_seconds = follower_row["lag_seconds"]
    if lag_seconds is None:
        followed_at = _required_datetime(follower_row["followed_at"], "followed_at")
        origin_at = _required_datetime(event_row["origin_at"], "origin_at")
        lag_seconds = int((followed_at - origin_at).total_seconds())
    if not isinstance(lag_seconds, int) or isinstance(lag_seconds, bool) or lag_seconds < 0:
        raise SourceSchemaError("AgendaScope propagation lag_seconds must be non-negative")
    source_name = follower_row["source_name"]
    if not isinstance(source_name, str) or not source_name.strip():
        raise SourceSchemaError("AgendaScope propagation source_name must be non-empty")
    return {
        "event_id": _required_uuid(event_row["id"], "event_id"),
        "position": sequence_no,
        "from_country_code": _required_country_code(
            event_row["origin_country_code"], "origin_country_code"
        ),
        "to_country_code": _required_country_code(follower_row["country_code"], "country_code"),
        "lag_hours": Decimal(lag_seconds) / Decimal(3_600),
        "first_media_name": source_name.strip(),
        "first_article_id": _optional_uuid(follower_row["article_id"], "article_id"),
        "first_published_at": _required_datetime(follower_row["followed_at"], "followed_at"),
        "source_follower_id": _required_uuid(follower_row["id"], "source_follower_id"),
        "follower_source_id": _required_uuid(follower_row["source_id"], "follower_source_id"),
        "observation_source": "structured_followers",
    }


async def _structured_followers_by_event(
    source_connection: AsyncConnection,
    event_ids: tuple[UUID, ...],
) -> dict[UUID, list[dict[str, object]]]:
    statement = text(
        "SELECT follower.id, follower.event_id, follower.source_id, follower.article_id, "
        "follower.country_code, follower.followed_at, follower.lag_seconds, "
        "follower.sequence_no, COALESCE(source.name_zh, source.name) AS source_name "
        "FROM agenda_event_followers AS follower "
        "JOIN sources AS source ON source.id=follower.source_id "
        "WHERE follower.event_id IN :event_ids "
        "ORDER BY follower.event_id, follower.sequence_no, follower.followed_at, follower.id"
    ).bindparams(bindparam("event_ids", expanding=True))
    rows = (await source_connection.execute(statement, {"event_ids": event_ids})).mappings()
    grouped: dict[UUID, list[dict[str, object]]] = {}
    for row in rows:
        event_id = _required_uuid(row["event_id"], "event_id")
        grouped.setdefault(event_id, []).append(dict(row))
    return grouped


async def _import_propagation(
    source_connection: AsyncConnection,
    target_connection: AsyncConnection,
) -> tuple[TableImportCount, TableImportCount]:
    event_columns = (
        "id",
        "topic_id",
        "status",
        "confidence",
        "origin_country_code",
        "origin_source_id",
        "origin_at",
        "origin_confidence",
        "detection_method",
        "follower_sequence",
        "updated_at",
    )
    source_spec = ImportSpec(
        source_table="agenda_events",
        target_table="media_propagation_events",
        columns=event_columns,
        conflict_columns=("id",),
    )
    target_spec = ImportSpec(
        source_table="agenda_events",
        target_table="media_propagation_events",
        columns=(
            "id",
            "topic_id",
            "status",
            "confidence",
            "origin_country_code",
            "origin_source_id",
            "origin_at",
            "origin_confidence",
            "detection_method",
            "source_updated_at",
            "imported_at",
        ),
        conflict_columns=("id",),
    )
    await _validate_source_columns(source_connection, source_spec)
    await _validate_target_columns(target_connection, target_spec)
    edge_spec = ImportSpec(
        source_table="agenda_event_followers",
        target_table="media_propagation_edges",
        columns=(
            "event_id",
            "position",
            "from_country_code",
            "to_country_code",
            "lag_hours",
            "first_media_name",
            "first_article_id",
            "first_published_at",
            "source_follower_id",
            "follower_source_id",
            "observation_source",
        ),
        conflict_columns=("event_id", "position"),
    )
    await _validate_target_columns(target_connection, edge_spec)
    follower_source_spec = ImportSpec(
        source_table="agenda_event_followers",
        target_table="media_propagation_edges",
        columns=(
            "id",
            "event_id",
            "source_id",
            "article_id",
            "country_code",
            "followed_at",
            "lag_seconds",
            "sequence_no",
        ),
        conflict_columns=("id",),
    )
    await _validate_source_columns(source_connection, follower_source_spec)
    event_target = _target_table(target_spec)
    edge_target = _target_table(edge_spec)
    event_read = event_inserted = event_updated = event_skipped = 0
    edge_read = edge_inserted = edge_updated = edge_skipped = 0
    async for source_rows in _stream_source_rows(source_connection, source_spec):
        target_rows: list[dict[str, object]] = []
        edge_rows: list[dict[str, object]] = []
        event_ids = tuple(_required_uuid(row["id"], "event_id") for row in source_rows)
        structured_by_event = await _structured_followers_by_event(
            source_connection,
            event_ids,
        )
        for source_row in source_rows:
            target_rows.append(
                {
                    **{column: source_row[column] for column in event_columns[:-2]},
                    "origin_country_code": _required_country_code(
                        source_row["origin_country_code"], "origin_country_code"
                    ),
                    "source_updated_at": source_row["updated_at"],
                    "imported_at": source_row["updated_at"],
                }
            )
            event_id = _required_uuid(source_row["id"], "event_id")
            structured_rows = structured_by_event.get(event_id, [])
            edge_rows.extend(
                _structured_propagation_edge(source_row, follower_row)
                for follower_row in structured_rows
            )
            if not structured_rows:
                edge_rows.extend(_propagation_edges(source_row))
        event_read += len(target_rows)
        edge_read += len(edge_rows)
        keys = tuple((row["id"],) for row in target_rows)
        existing = frozenset(
            (row[0],)
            for row in (
                await target_connection.execute(
                    select(event_target.c.id).where(
                        event_target.c.id.in_(row["id"] for row in target_rows)
                    )
                )
            ).all()
        )
        affected = frozenset(
            tuple(row)
            for row in (
                await target_connection.execute(
                    _build_upsert_statement(event_target, target_spec, target_rows).returning(
                        event_target.c.id
                    )
                )
            ).all()
        )
        counts = _count_batch_rows(keys, existing, affected, "agenda_events")
        event_inserted += counts.inserted
        event_updated += counts.updated
        event_skipped += counts.skipped
        event_ids = tuple(row["id"] for row in target_rows)
        edge_keys = tuple(_row_key(row, edge_spec.conflict_columns) for row in edge_rows)
        existing_edge_keys = frozenset(
            tuple(row)
            for row in (
                await target_connection.execute(
                    select(edge_target.c.event_id, edge_target.c.position).where(
                        edge_target.c.event_id.in_(event_ids)
                    )
                )
            ).all()
        )
        if edge_rows:
            affected_edge_keys = frozenset(
                tuple(row)
                for row in (
                    await target_connection.execute(
                        _build_upsert_statement(edge_target, edge_spec, edge_rows).returning(
                            edge_target.c.event_id,
                            edge_target.c.position,
                        )
                    )
                ).all()
            )
            await target_connection.execute(
                delete(edge_target).where(
                    edge_target.c.event_id.in_(event_ids),
                    tuple_(edge_target.c.event_id, edge_target.c.position).not_in(edge_keys),
                )
            )
            edge_counts = _count_batch_rows(
                edge_keys,
                existing_edge_keys,
                affected_edge_keys,
                "agenda_event_followers",
            )
            edge_inserted += edge_counts.inserted
            edge_updated += edge_counts.updated
            edge_skipped += edge_counts.skipped
        else:
            await target_connection.execute(
                delete(edge_target).where(edge_target.c.event_id.in_(event_ids))
            )
    return (
        TableImportCount(event_read, event_inserted, event_updated, event_skipped),
        TableImportCount(edge_read, edge_inserted, edge_updated, edge_skipped),
    )


async def import_agendascope_transaction(
    settings: ImportSettings,
    source_connection: AsyncConnection,
    target_connection: AsyncConnection,
) -> ImportSnapshot:
    """Import one attested source snapshot inside the caller-owned target transaction."""
    counts: dict[str, TableImportCount] = {}
    target_identity = await _read_connected_database_identity(target_connection)
    source_transaction = await source_connection.begin()
    try:
        await source_connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        source_identity = await _read_connected_database_identity(source_connection)
        _ensure_distinct_connected_databases(source_identity, target_identity)
        await _validate_source_attestation(source_connection, source_identity, settings)
        for spec in IMPORT_SPECS:
            await _validate_target_columns(target_connection, spec)
        await _validate_target_columns(target_connection, FIRST_UTTERANCE_SPEC)
        for spec in IMPORT_SPECS:
            await _validate_source_columns(source_connection, spec)
        watermarks = await _read_source_watermarks(source_connection)
        for spec in IMPORT_SPECS:
            counts[spec.source_table] = await _import_table(
                source_connection,
                target_connection,
                spec,
                watermarks.source_observed_at if spec.source_table == "articles" else None,
            )
        await _reconcile_absent_articles(target_connection, watermarks.source_observed_at)
        propagation_events, propagation_edges = await _import_propagation(
            source_connection,
            target_connection,
        )
        first_utterances = await _import_first_utterances(
            source_connection,
            target_connection,
        )
    finally:
        await source_transaction.rollback()
    return ImportSnapshot(
        result=ImportResult(
            sources=counts["sources"],
            articles=counts["articles"],
            topics=counts["topics"],
            topic_articles=counts["topic_articles"],
            topic_snapshots=counts["topic_snapshots"],
            propagation_events=propagation_events,
            propagation_edges=propagation_edges,
            first_utterances=first_utterances,
        ),
        watermarks=watermarks,
    )


async def import_agendascope(settings: ImportSettings) -> ImportResult:
    """Run one durable manual refresh and return its strict table accounting."""
    from app.media.sync_repository import run_manual_media_sync

    execution = await run_manual_media_sync(settings)
    if execution.import_result is None:
        raise ImportAlreadyRunningError("Another AgendaScope media refresh is already running")
    return execution.import_result


async def _run() -> int:
    try:
        settings = load_import_settings(os.environ)
        result = await import_agendascope(settings)
    except (
        ImportAlreadyRunningError,
        ImportConfigurationError,
        SourceSchemaError,
        ImportRuntimeError,
    ) as error:
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
