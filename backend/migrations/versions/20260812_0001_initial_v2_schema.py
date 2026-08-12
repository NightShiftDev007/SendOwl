"""Create or safely adopt the initial V2 application schema.

Revision ID: 20260812_0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Callable, Mapping, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

revision: str = "20260812_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

type ColumnExpectation = tuple[str, bool]
type ForeignKeyExpectation = tuple[tuple[str, ...], str, tuple[str, ...], str | None]
type IndexExpectation = tuple[tuple[str, ...], bool]

EXPECTED_COLUMNS: dict[str, dict[str, ColumnExpectation]] = {
    "media_sources": {
        "id": ("uuid", False),
        "name": ("varchar(200)", False),
        "name_zh": ("varchar(200)", True),
        "country_code": ("varchar(2)", False),
        "homepage_url": ("varchar(500)", False),
        "media_type": ("varchar(20)", False),
        "language": ("varchar(10)", False),
        "status": ("varchar(10)", False),
        "last_success_at": ("timestamp(timezone=True)", True),
        "created_at": ("timestamp(timezone=True)", False),
        "updated_at": ("timestamp(timezone=True)", False),
    },
    "media_articles": {
        "id": ("uuid", False),
        "source_id": ("uuid", False),
        "url": ("varchar(1000)", False),
        "url_hash": ("varchar(64)", False),
        "title": ("text", False),
        "content": ("text", True),
        "summary": ("text", True),
        "language": ("varchar(10)", False),
        "published_at": ("timestamp(timezone=True)", False),
        "crawled_at": ("timestamp(timezone=True)", False),
        "country_code": ("varchar(2)", True),
        "is_duplicate": ("boolean", False),
        "created_at": ("timestamp(timezone=True)", False),
    },
    "media_topics": {
        "id": ("uuid", False),
        "name": ("varchar(300)", False),
        "name_zh": ("varchar(300)", True),
        "summary_zh": ("text", True),
        "topic_category": ("varchar(50)", True),
        "status": ("varchar(15)", False),
        "lifecycle_state": ("varchar(15)", False),
        "first_seen_at": ("timestamp(timezone=True)", False),
        "last_seen_at": ("timestamp(timezone=True)", False),
        "created_at": ("timestamp(timezone=True)", False),
        "updated_at": ("timestamp(timezone=True)", False),
    },
    "media_topic_articles": {
        "topic_id": ("uuid", False),
        "article_id": ("uuid", False),
        "weight": ("numeric(4,3)", False),
        "assign_method": ("varchar(15)", False),
        "assigned_at": ("timestamp(timezone=True)", False),
    },
    "media_topic_snapshots": {
        "id": ("uuid", False),
        "country_code": ("varchar(2)", False),
        "topic_id": ("uuid", False),
        "window_start": ("timestamp(timezone=True)", False),
        "window_end": ("timestamp(timezone=True)", False),
        "granularity": ("varchar(5)", False),
        "article_count": ("integer", False),
        "salience_score": ("numeric(10,4)", False),
        "salience_rank": ("integer", False),
        "created_at": ("timestamp(timezone=True)", False),
    },
    "companies": {
        "id": ("uuid", False),
        "canonical_name": ("varchar(300)", False),
        "created_at": ("timestamp(timezone=True)", False),
    },
    "company_aliases": {
        "normalized_value": ("varchar(900)", False),
        "company_id": ("uuid", False),
        "value": ("varchar(300)", False),
        "is_canonical": ("boolean", False),
        "position": ("integer", False),
    },
}

EXPECTED_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "media_sources": ("id",),
    "media_articles": ("id",),
    "media_topics": ("id",),
    "media_topic_articles": ("topic_id", "article_id"),
    "media_topic_snapshots": ("id",),
    "companies": ("id",),
    "company_aliases": ("normalized_value",),
}

EXPECTED_FOREIGN_KEYS: dict[str, set[ForeignKeyExpectation]] = {
    "media_sources": set(),
    "media_articles": {(("source_id",), "media_sources", ("id",), None)},
    "media_topics": set(),
    "media_topic_articles": {
        (("topic_id",), "media_topics", ("id",), "CASCADE"),
        (("article_id",), "media_articles", ("id",), "CASCADE"),
    },
    "media_topic_snapshots": {
        (("topic_id",), "media_topics", ("id",), "CASCADE"),
    },
    "companies": set(),
    "company_aliases": {
        (("company_id",), "companies", ("id",), "CASCADE"),
    },
}

EXPECTED_UNIQUE_CONSTRAINTS: dict[str, set[tuple[str, ...]]] = {
    "media_sources": set(),
    "media_articles": {("url_hash",)},
    "media_topics": set(),
    "media_topic_articles": set(),
    "media_topic_snapshots": {
        ("country_code", "topic_id", "window_start", "granularity"),
    },
    "companies": set(),
    "company_aliases": set(),
}

EXPECTED_CHECK_CONSTRAINTS: dict[str, set[str]] = {
    "media_sources": {
        "ck_media_sources_media_type",
        "ck_media_sources_status",
    },
    "media_articles": set(),
    "media_topics": {
        "ck_media_topics_status",
        "ck_media_topics_lifecycle",
    },
    "media_topic_articles": {"ck_media_topic_articles_assign_method"},
    "media_topic_snapshots": {
        "ck_media_topic_snapshots_window",
        "ck_media_topic_snapshots_granularity",
        "ck_media_topic_snapshots_article_count",
        "ck_media_topic_snapshots_rank",
    },
    "companies": set(),
    "company_aliases": {"ck_company_aliases_position"},
}

EXPECTED_INDEXES: dict[str, dict[str, IndexExpectation]] = {
    "media_sources": {
        "ix_media_sources_country_status": (("country_code", "status"), False),
    },
    "media_articles": {
        "ix_media_articles_published_at": (("published_at",), False),
        "ix_media_articles_country": (("country_code",), False),
        "ix_media_articles_source": (("source_id",), False),
    },
    "media_topics": {
        "ix_media_topics_last_seen": (("last_seen_at",), False),
    },
    "media_topic_articles": {
        "ix_media_topic_articles_article": (("article_id",), False),
    },
    "media_topic_snapshots": {
        "ix_media_topic_snapshots_topic_window": (("topic_id", "window_start"), False),
        "ix_media_topic_snapshots_country_window": (("country_code", "window_start"), False),
    },
    "companies": {
        "ix_companies_created_at": (("created_at",), False),
    },
    "company_aliases": {
        "ix_company_aliases_company_position": (("company_id", "position"), True),
    },
}

TRIGRAM_INDEX_COLUMNS: dict[str, str] = {
    "ix_media_articles_title_trgm": "title",
    "ix_media_articles_content_trgm": "content",
    "ix_media_articles_summary_trgm": "summary",
}


def _database_type_signature(column_type: sa.types.TypeEngine[object]) -> str:
    if isinstance(column_type, postgresql.UUID):
        return "uuid"
    if isinstance(column_type, sa.Text):
        return "text"
    if isinstance(column_type, sa.String):
        return f"varchar({column_type.length})"
    if isinstance(column_type, sa.DateTime):
        return f"timestamp(timezone={column_type.timezone})"
    if isinstance(column_type, sa.Numeric):
        return f"numeric({column_type.precision},{column_type.scale})"
    if isinstance(column_type, sa.Boolean):
        return "boolean"
    if isinstance(column_type, sa.Integer):
        return "integer"
    return str(column_type).lower()


def _normalized_on_delete(options: Mapping[str, object]) -> str | None:
    value = options.get("ondelete")
    if value is None:
        return None
    return str(value).upper()


def _validate_existing_table(inspector: sa.Inspector, table_name: str) -> None:
    actual_columns = {
        str(column["name"]): (
            _database_type_signature(column["type"]),
            bool(column["nullable"]),
        )
        for column in inspector.get_columns(table_name)
    }
    expected_columns = EXPECTED_COLUMNS[table_name]
    if actual_columns != expected_columns:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: column definitions differ; "
            f"expected={expected_columns!r}, actual={actual_columns!r}"
        )

    primary_key = inspector.get_pk_constraint(table_name)
    actual_primary_key = tuple(primary_key.get("constrained_columns") or ())
    if actual_primary_key != EXPECTED_PRIMARY_KEYS[table_name]:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: primary key differs; "
            f"expected={EXPECTED_PRIMARY_KEYS[table_name]!r}, actual={actual_primary_key!r}"
        )

    actual_foreign_keys = {
        (
            tuple(foreign_key["constrained_columns"]),
            str(foreign_key["referred_table"]),
            tuple(foreign_key["referred_columns"]),
            _normalized_on_delete(foreign_key.get("options") or {}),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    if actual_foreign_keys != EXPECTED_FOREIGN_KEYS[table_name]:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: foreign keys differ; "
            f"expected={EXPECTED_FOREIGN_KEYS[table_name]!r}, actual={actual_foreign_keys!r}"
        )

    actual_unique_constraints = {
        tuple(unique_constraint["column_names"])
        for unique_constraint in inspector.get_unique_constraints(table_name)
    }
    if actual_unique_constraints != EXPECTED_UNIQUE_CONSTRAINTS[table_name]:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: unique constraints differ; "
            f"expected={EXPECTED_UNIQUE_CONSTRAINTS[table_name]!r}, "
            f"actual={actual_unique_constraints!r}"
        )

    actual_check_constraints = {
        str(check_constraint["name"])
        for check_constraint in inspector.get_check_constraints(table_name)
    }
    if actual_check_constraints != EXPECTED_CHECK_CONSTRAINTS[table_name]:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: check constraints differ; "
            f"expected={EXPECTED_CHECK_CONSTRAINTS[table_name]!r}, "
            f"actual={actual_check_constraints!r}"
        )

    actual_indexes = {
        str(index["name"]): (
            tuple(str(column) for column in index["column_names"]),
            bool(index["unique"]),
        )
        for index in inspector.get_indexes(table_name)
        if index.get("duplicates_constraint") is None
        and str(index["name"]) not in TRIGRAM_INDEX_COLUMNS
    }
    if actual_indexes != EXPECTED_INDEXES[table_name]:
        raise RuntimeError(
            f"Cannot adopt existing table {table_name!r}: indexes differ; "
            f"expected={EXPECTED_INDEXES[table_name]!r}, actual={actual_indexes!r}"
        )


def _create_media_sources() -> None:
    op.create_table(
        "media_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_zh", sa.String(length=200), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("homepage_url", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('newspaper','agency','broadcast','online')",
            name="ck_media_sources_media_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','degraded','failed','disabled')",
            name="ck_media_sources_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_sources_country_status",
        "media_sources",
        ["country_code", "status"],
        unique=False,
    )


def _create_media_articles() -> None:
    op.create_table(
        "media_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["media_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_hash"),
    )
    op.create_index(
        "ix_media_articles_published_at",
        "media_articles",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        "ix_media_articles_country",
        "media_articles",
        ["country_code"],
        unique=False,
    )
    op.create_index(
        "ix_media_articles_source",
        "media_articles",
        ["source_id"],
        unique=False,
    )


def _create_media_topics() -> None:
    op.create_table(
        "media_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("name_zh", sa.String(length=300), nullable=True),
        sa.Column("summary_zh", sa.Text(), nullable=True),
        sa.Column("topic_category", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=15), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=15), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('emerging','heating','stable','declining','archived')",
            name="ck_media_topics_status",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('nascent','forming','confirmed','evolving','archived')",
            name="ck_media_topics_lifecycle",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_topics_last_seen",
        "media_topics",
        ["last_seen_at"],
        unique=False,
    )


def _create_media_topic_articles() -> None:
    op.create_table(
        "media_topic_articles",
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("assign_method", sa.String(length=15), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "assign_method IN ('online','recluster','merge','manual')",
            name="ck_media_topic_articles_assign_method",
        ),
        sa.ForeignKeyConstraint(["article_id"], ["media_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["media_topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("topic_id", "article_id"),
    )
    op.create_index(
        "ix_media_topic_articles_article",
        "media_topic_articles",
        ["article_id"],
        unique=False,
    )


def _create_media_topic_snapshots() -> None:
    op.create_table(
        "media_topic_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granularity", sa.String(length=5), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("salience_score", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("salience_rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "window_end > window_start",
            name="ck_media_topic_snapshots_window",
        ),
        sa.CheckConstraint(
            "granularity IN ('hour','day','week')",
            name="ck_media_topic_snapshots_granularity",
        ),
        sa.CheckConstraint(
            "article_count >= 0",
            name="ck_media_topic_snapshots_article_count",
        ),
        sa.CheckConstraint(
            "salience_rank >= 1",
            name="ck_media_topic_snapshots_rank",
        ),
        sa.ForeignKeyConstraint(["topic_id"], ["media_topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "country_code",
            "topic_id",
            "window_start",
            "granularity",
            name="uq_media_topic_snapshots_scope",
        ),
    )
    op.create_index(
        "ix_media_topic_snapshots_topic_window",
        "media_topic_snapshots",
        ["topic_id", "window_start"],
        unique=False,
    )
    op.create_index(
        "ix_media_topic_snapshots_country_window",
        "media_topic_snapshots",
        ["country_code", "window_start"],
        unique=False,
    )


def _create_companies() -> None:
    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_name", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_companies_created_at",
        "companies",
        ["created_at"],
        unique=False,
    )


def _create_company_aliases() -> None:
    op.create_table(
        "company_aliases",
        sa.Column("normalized_value", sa.String(length=900), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("is_canonical", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_company_aliases_position"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("normalized_value"),
    )
    op.create_index(
        "ix_company_aliases_company_position",
        "company_aliases",
        ["company_id", "position"],
        unique=True,
    )


def _ensure_trigram_index(connection: Connection, index_name: str, column_name: str) -> None:
    existing_definition = connection.execute(
        sa.text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'media_articles'
              AND indexname = :index_name
            """
        ),
        {"index_name": index_name},
    ).scalar_one_or_none()
    if existing_definition is None:
        op.execute(
            f"CREATE INDEX {index_name} ON media_articles USING gin ({column_name} gin_trgm_ops)"
        )
        return

    normalized_definition = " ".join(str(existing_definition).lower().replace('"', "").split())
    required_fragment = f"using gin ({column_name} gin_trgm_ops)"
    if required_fragment not in normalized_definition:
        raise RuntimeError(
            f"Cannot adopt existing index {index_name!r}: expected {required_fragment!r}; "
            f"actual={normalized_definition!r}"
        )


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    create_tables: tuple[tuple[str, Callable[[], None]], ...] = (
        ("media_sources", _create_media_sources),
        ("media_articles", _create_media_articles),
        ("media_topics", _create_media_topics),
        ("media_topic_articles", _create_media_topic_articles),
        ("media_topic_snapshots", _create_media_topic_snapshots),
        ("companies", _create_companies),
        ("company_aliases", _create_company_aliases),
    )
    for table_name, create_table in create_tables:
        if inspector.has_table(table_name):
            _validate_existing_table(inspector, table_name)
        else:
            create_table()

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index_name, column_name in TRIGRAM_INDEX_COLUMNS.items():
        _ensure_trigram_index(connection, index_name, column_name)


def downgrade() -> None:
    for index_name in reversed(tuple(TRIGRAM_INDEX_COLUMNS)):
        op.drop_index(index_name, table_name="media_articles")
    op.drop_table("company_aliases")
    op.drop_table("companies")
    op.drop_table("media_topic_snapshots")
    op.drop_table("media_topic_articles")
    op.drop_table("media_topics")
    op.drop_table("media_articles")
    op.drop_table("media_sources")
