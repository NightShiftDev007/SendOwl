"""Normalized records for immutable MatrAIx batch registries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class MatraixBatchRegistryRecord(ApplicationBase):
    __tablename__ = "matraix_batch_registries"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    registry_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "title=btrim(title) AND length(title) BETWEEN 1 AND 200 AND title !~ E'[\\r\\n]'",
            name="ck_batch_registry_title",
        ),
        CheckConstraint("registry_sha256 ~ '^[a-f0-9]{64}$'", name="ck_batch_registry_sha"),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at", name="ck_batch_registry_sealed_time"
        ),
        UniqueConstraint("registry_sha256", name="uq_batch_registry_sha"),
        Index("ix_batch_registries_created", "created_at"),
    )


class MatraixBatchRegistryItemRecord(ApplicationBase):
    __tablename__ = "matraix_batch_registry_items"

    registry_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_batch_registries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    parent_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 19", name="ck_batch_registry_item_position"),
        CheckConstraint(
            "kind IN ('survey','chat','web','linux')", name="ck_batch_registry_item_kind"
        ),
        CheckConstraint(
            "parent_sha256 ~ '^[a-f0-9]{64}$'", name="ck_batch_registry_item_parent_sha"
        ),
        UniqueConstraint("registry_id", "kind", "parent_id", name="uq_batch_registry_item_source"),
        Index("ix_batch_registry_items_parent", "kind", "parent_id"),
    )


__all__ = ["MatraixBatchRegistryItemRecord", "MatraixBatchRegistryRecord"]
