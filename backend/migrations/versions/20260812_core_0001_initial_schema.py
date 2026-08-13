"""Create the initial core application schema on an empty target.

Revision ID: 20260812_core_0001
Revises:
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TARGET_MEDIA_TABLES: tuple[str, ...] = (
    "media_sources",
    "media_articles",
    "media_topics",
    "media_topic_articles",
    "media_topic_snapshots",
)

TRIGRAM_INDEX_COLUMNS: dict[str, str] = {
    "ix_media_articles_title_trgm": "title",
    "ix_media_articles_content_trgm": "content",
    "ix_media_articles_summary_trgm": "summary",
}


def _reject_preexisting_target_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = tuple(
        table_name for table_name in TARGET_MEDIA_TABLES if inspector.has_table(table_name)
    )
    if existing_tables:
        raise RuntimeError(
            "Core migration 20260812_core_0001 requires an empty target schema; "
            f"refusing to adopt pre-existing tables: {', '.join(existing_tables)}"
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


def upgrade() -> None:
    _reject_preexisting_target_tables()

    _create_media_sources()
    _create_media_articles()
    _create_media_topics()
    _create_media_topic_articles()
    _create_media_topic_snapshots()

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    for index_name, column_name in TRIGRAM_INDEX_COLUMNS.items():
        op.execute(
            f"CREATE INDEX {index_name} ON media_articles USING gin ({column_name} gin_trgm_ops)"
        )


def downgrade() -> None:
    for index_name in reversed(tuple(TRIGRAM_INDEX_COLUMNS)):
        op.drop_index(index_name, table_name="media_articles")
    op.drop_table("media_topic_snapshots")
    op.drop_table("media_topic_articles")
    op.drop_table("media_topics")
    op.drop_table("media_articles")
    op.drop_table("media_sources")
