"""PostgreSQL records for persistent world models and immutable snapshots."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class WorldModelRecord(ApplicationBase):
    """Persistent identity whose history consists only of appended snapshots."""

    __tablename__ = "world_models"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="ck_world_models_title"),
        Index("ix_world_models_created_at", "created_at"),
    )


class WorldSnapshotRecord(ApplicationBase):
    """Content-addressed immutable model version."""

    __tablename__ = "world_snapshots"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    verification: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_world_snapshots_version"),
        CheckConstraint(
            "verification = 'human_confirmed'",
            name="ck_world_snapshots_verification",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_world_snapshots_sha256",
        ),
        UniqueConstraint("world_model_id", "version", name="uq_world_snapshots_model_version"),
        Index("ix_world_snapshots_model_version", "world_model_id", "version"),
    )


class WorldSnapshotEvidenceRecord(ApplicationBase):
    """Complete selected article copy owned only by one immutable snapshot."""

    __tablename__ = "world_snapshot_evidence"

    snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_snapshots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    captured_text: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    excerpt: Mapped[str] = mapped_column(String(280), nullable=False)
    captured_text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_world_snapshot_evidence_position"),
        CheckConstraint(
            "length(btrim(source_name)) > 0",
            name="ck_world_snapshot_evidence_source_name",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="ck_world_snapshot_evidence_title"),
        CheckConstraint(
            "length(btrim(excerpt)) BETWEEN 1 AND 280",
            name="ck_world_snapshot_evidence_excerpt",
        ),
        CheckConstraint(
            "captured_text_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_world_snapshot_evidence_sha256",
        ),
        UniqueConstraint("snapshot_id", "article_id", name="uq_world_snapshot_evidence_article"),
        Index("ix_world_snapshot_evidence_article", "article_id"),
    )
