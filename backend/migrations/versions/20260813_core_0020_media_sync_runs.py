"""Track isolated AgendaScope media snapshot refreshes.

Revision ID: 20260813_core_0020
Revises: 20260813_core_0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0020"
down_revision: str | None = "20260813_core_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_latest_source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_latest_article_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_latest_topic_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_latest_topic_article_assigned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("source_latest_snapshot_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_latest_snapshot_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_latest_propagation_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('manual','scheduled')",
            name="ck_media_sync_runs_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','skipped_concurrent')",
            name="ck_media_sync_runs_status",
        ),
        sa.CheckConstraint(
            "length(btrim(worker_id)) BETWEEN 1 AND 128 "
            "AND worker_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_media_sync_runs_worker_id",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_media_sync_runs_time_order",
        ),
        sa.CheckConstraint(
            "((trigger = 'scheduled' AND status IN ('succeeded','skipped_concurrent') "
            "AND next_scheduled_at IS NOT NULL) OR "
            "((trigger = 'manual' OR status IN ('running','failed')) "
            "AND next_scheduled_at IS NULL))",
            name="ck_media_sync_runs_schedule",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND completed_at IS NULL "
            "AND source_observed_at IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL "
            "AND source_observed_at IS NOT NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL "
            "AND source_observed_at IS NULL AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 500) OR "
            "(status = 'skipped_concurrent' AND completed_at IS NOT NULL "
            "AND source_observed_at IS NULL AND error_code IS NULL AND error_message IS NULL)",
            name="ck_media_sync_runs_lifecycle",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_sync_runs_started_at",
        "media_sync_runs",
        [sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_media_sync_runs_status_started_at",
        "media_sync_runs",
        ["status", sa.text("started_at DESC")],
    )

    op.create_table(
        "media_sync_run_tables",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_name", sa.String(length=32), nullable=False),
        sa.Column("read_count", sa.Integer(), nullable=False),
        sa.Column("inserted_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "table_name IN ('sources','articles','topics','topic_articles','topic_snapshots',"
            "'propagation_events','propagation_edges')",
            name="ck_media_sync_run_tables_name",
        ),
        sa.CheckConstraint(
            "read_count >= 0 AND inserted_count >= 0 AND updated_count >= 0 AND skipped_count >= 0",
            name="ck_media_sync_run_tables_nonnegative",
        ),
        sa.CheckConstraint(
            "read_count = inserted_count + updated_count + skipped_count",
            name="ck_media_sync_run_tables_accounting",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["media_sync_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "table_name"),
    )


def downgrade() -> None:
    op.drop_table("media_sync_run_tables")
    op.drop_index("ix_media_sync_runs_status_started_at", table_name="media_sync_runs")
    op.drop_index("ix_media_sync_runs_started_at", table_name="media_sync_runs")
    op.drop_table("media_sync_runs")
