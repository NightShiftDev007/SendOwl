"""Add SandOwl-owned media source collection lifecycle.

Revision ID: 20260818_core_0058
Revises: 20260818_core_0057
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0058"
down_revision: str | None = "20260818_core_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_topics",
        sa.Column("origin", sa.String(24), nullable=False, server_default="legacy_import"),
    )
    op.create_check_constraint(
        "ck_media_topics_origin",
        "media_topics",
        "origin IN ('legacy_import','native_collection')",
    )
    op.drop_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        "(observation_source='legacy_projection' AND source_follower_id IS NULL) OR "
        "(observation_source='structured_followers' AND source_follower_id IS NOT NULL "
        "AND follower_source_id IS NOT NULL) OR "
        "(observation_source='native_collection' AND source_follower_id IS NULL "
        "AND follower_source_id IS NOT NULL)",
    )
    op.add_column(
        "media_sources",
        sa.Column(
            "native_collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "media_sources",
        sa.Column("collection_mode", sa.String(8), nullable=False, server_default="web"),
    )
    op.add_column("media_sources", sa.Column("feed_url", sa.String(500)))
    op.add_column(
        "media_sources",
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False, server_default="900"),
    )
    op.add_column(
        "media_sources",
        sa.Column(
            "collection_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("media_sources", sa.Column("collection_config_sha256", sa.String(64)))
    op.add_column(
        "media_sources", sa.Column("last_collection_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "media_sources", sa.Column("last_collection_success_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "media_sources",
        sa.Column(
            "consecutive_collection_failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.create_check_constraint(
        "ck_media_sources_collection_mode",
        "media_sources",
        "collection_mode IN ('rss','web')",
    )
    op.create_check_constraint(
        "ck_media_sources_collection_interval",
        "media_sources",
        "poll_interval_seconds BETWEEN 300 AND 86400",
    )
    op.create_check_constraint(
        "ck_media_sources_collection_failures",
        "media_sources",
        "consecutive_collection_failures >= 0",
    )
    op.create_check_constraint(
        "ck_media_sources_collection_feed",
        "media_sources",
        "(collection_mode='rss' AND feed_url IS NOT NULL) OR collection_mode='web'",
    )
    op.create_check_constraint(
        "ck_media_sources_collection_digest",
        "media_sources",
        "collection_config_sha256 IS NULL OR collection_config_sha256 ~ '^[a-f0-9]{64}$'",
    )
    op.create_index(
        "ix_media_sources_native_collection",
        "media_sources",
        ["native_collection_enabled", "last_collection_attempt_at"],
    )
    op.create_table(
        "native_media_collection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("config_sha256", sa.String(64), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("articles_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("articles_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("articles_existing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')",
            name="ck_native_media_collection_runs_status",
        ),
        sa.CheckConstraint(
            "config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_native_media_collection_runs_digest",
        ),
        sa.CheckConstraint(
            "articles_discovered >= 0 AND articles_inserted >= 0 AND articles_existing >= 0",
            name="ck_native_media_collection_runs_counts",
        ),
    )
    op.create_index(
        "ix_native_media_collection_runs_source_started",
        "native_media_collection_runs",
        ["source_id", "started_at"],
    )
    op.create_index(
        "ix_native_media_collection_runs_status_started",
        "native_media_collection_runs",
        ["status", "started_at"],
    )
    op.create_table(
        "native_media_collection_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('consecutive_failures','no_content')",
            name="ck_native_media_collection_alerts_kind",
        ),
        sa.CheckConstraint(
            "severity IN ('warning','critical')",
            name="ck_native_media_collection_alerts_severity",
        ),
    )
    op.create_index(
        "ix_native_media_collection_alerts_active",
        "native_media_collection_alerts",
        ["source_id", "resolved_at"],
    )
    op.create_table(
        "native_media_collection_worker_heartbeats",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("worker_version", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "worker_version='1.0.0'",
            name="ck_native_media_collection_worker_version",
        ),
        sa.CheckConstraint(
            "last_seen_at >= started_at",
            name="ck_native_media_collection_worker_time",
        ),
    )


def downgrade() -> None:
    op.drop_table("native_media_collection_worker_heartbeats")
    op.drop_index(
        "ix_native_media_collection_alerts_active", table_name="native_media_collection_alerts"
    )
    op.drop_table("native_media_collection_alerts")
    op.drop_index(
        "ix_native_media_collection_runs_status_started", table_name="native_media_collection_runs"
    )
    op.drop_index(
        "ix_native_media_collection_runs_source_started", table_name="native_media_collection_runs"
    )
    op.drop_table("native_media_collection_runs")
    op.drop_index("ix_media_sources_native_collection", table_name="media_sources")
    for name in (
        "ck_media_sources_collection_digest",
        "ck_media_sources_collection_feed",
        "ck_media_sources_collection_failures",
        "ck_media_sources_collection_interval",
        "ck_media_sources_collection_mode",
    ):
        op.drop_constraint(name, "media_sources", type_="check")
    for name in (
        "consecutive_collection_failures",
        "last_collection_success_at",
        "last_collection_attempt_at",
        "collection_config_sha256",
        "collection_config",
        "poll_interval_seconds",
        "feed_url",
        "collection_mode",
        "native_collection_enabled",
    ):
        op.drop_column("media_sources", name)
    op.drop_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        type_="check",
    )
    op.create_check_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        "(observation_source='legacy_projection' AND source_follower_id IS NULL) OR "
        "(observation_source='structured_followers' AND source_follower_id IS NOT NULL "
        "AND follower_source_id IS NOT NULL)",
    )
    op.drop_constraint("ck_media_topics_origin", "media_topics", type_="check")
    op.drop_column("media_topics", "origin")
