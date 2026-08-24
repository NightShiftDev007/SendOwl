"""PostgreSQL lifecycle records for SandOwl-owned media collection."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class NativeMediaCollectionRunRecord(ApplicationBase):
    __tablename__ = "native_media_collection_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    articles_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    articles_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    articles_existing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','succeeded','failed','skipped')",
            name="ck_native_media_collection_runs_status",
        ),
        CheckConstraint(
            "config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_native_media_collection_runs_digest",
        ),
        CheckConstraint(
            "articles_discovered >= 0 AND articles_inserted >= 0 AND articles_existing >= 0",
            name="ck_native_media_collection_runs_counts",
        ),
        Index("ix_native_media_collection_runs_source_started", "source_id", "started_at"),
        Index("ix_native_media_collection_runs_status_started", "status", "started_at"),
    )


class NativeMediaCollectionAlertRecord(ApplicationBase):
    __tablename__ = "native_media_collection_alerts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "kind IN ('consecutive_failures','no_content')",
            name="ck_native_media_collection_alerts_kind",
        ),
        CheckConstraint(
            "severity IN ('warning','critical')",
            name="ck_native_media_collection_alerts_severity",
        ),
        Index("ix_native_media_collection_alerts_active", "source_id", "resolved_at"),
    )


class NativeMediaCollectionWorkerHeartbeatRecord(ApplicationBase):
    __tablename__ = "native_media_collection_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "worker_version='1.0.0'",
            name="ck_native_media_collection_worker_version",
        ),
        CheckConstraint(
            "last_seen_at >= started_at",
            name="ck_native_media_collection_worker_time",
        ),
    )
