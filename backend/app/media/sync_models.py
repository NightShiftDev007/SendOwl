"""Durable observability records for AgendaScope media snapshot refreshes."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class MediaSyncRunRecord(ApplicationBase):
    """One manual or scheduled refresh attempt without source credentials."""

    __tablename__ = "media_sync_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_latest_source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_latest_article_crawled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_latest_topic_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_latest_topic_article_assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_latest_snapshot_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_latest_snapshot_window_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_latest_propagation_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(
            "trigger IN ('manual','scheduled')",
            name="ck_media_sync_runs_trigger",
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed','skipped_concurrent')",
            name="ck_media_sync_runs_status",
        ),
        CheckConstraint(
            "length(btrim(worker_id)) BETWEEN 1 AND 128 "
            "AND worker_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_media_sync_runs_worker_id",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_media_sync_runs_time_order",
        ),
        CheckConstraint(
            "((trigger = 'scheduled' AND status IN ('succeeded','skipped_concurrent') "
            "AND next_scheduled_at IS NOT NULL) OR "
            "((trigger = 'manual' OR status IN ('running','failed')) "
            "AND next_scheduled_at IS NULL))",
            name="ck_media_sync_runs_schedule",
        ),
        CheckConstraint(
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
        Index("ix_media_sync_runs_started_at", text("started_at DESC")),
        Index("ix_media_sync_runs_status_started_at", "status", text("started_at DESC")),
    )


class MediaSyncRunTableRecord(ApplicationBase):
    """Strict per-table accounting for one successful refresh."""

    __tablename__ = "media_sync_run_tables"

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_sync_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    table_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    read_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "table_name IN ('sources','articles','topics','topic_articles','topic_snapshots',"
            "'propagation_events','propagation_edges','first_utterances')",
            name="ck_media_sync_run_tables_name",
        ),
        CheckConstraint(
            "read_count >= 0 AND inserted_count >= 0 AND updated_count >= 0 AND skipped_count >= 0",
            name="ck_media_sync_run_tables_nonnegative",
        ),
        CheckConstraint(
            "read_count = inserted_count + updated_count + skipped_count",
            name="ck_media_sync_run_tables_accounting",
        ),
    )
