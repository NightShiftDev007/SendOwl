"""PostgreSQL records for immutable Policy evidence."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
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


class PolicySourceRecord(ApplicationBase):
    __tablename__ = "policy_sources"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    authority_name: Mapped[str] = mapped_column(String(300), nullable=False)
    jurisdiction_code: Mapped[str] = mapped_column(String(16), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PolicyDocumentRecord(ApplicationBase):
    __tablename__ = "policy_documents"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_identifier: Mapped[str] = mapped_column(String(256), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "canonical_identifier",
            name="uq_policy_document_source_identifier",
        ),
    )


class PolicyDocumentVersionRecord(ApplicationBase):
    __tablename__ = "policy_document_versions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("policy_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_policy_version_document_position"),
        CheckConstraint("version BETWEEN 1 AND 100", name="ck_policy_version_position"),
        CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR effective_until > effective_from",
            name="ck_policy_version_effectivity",
        ),
        CheckConstraint(
            "verification='human_confirmed'",
            name="ck_policy_version_verification",
        ),
        Index("ix_policy_versions_publication_date", "publication_date"),
        Index("ix_policy_versions_effective_from", "effective_from"),
    )
