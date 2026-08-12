"""PostgreSQL records for persisted monitored-company identities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class CompanyRecord(ApplicationBase):
    """Canonical identity for one monitored company."""

    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_companies_created_at", "created_at"),)


class CompanyAliasRecord(ApplicationBase):
    """Globally unique normalized match name owned by one company.

    The canonical company name is stored as the position-zero alias so canonical
    names and user-supplied aliases share one global conflict constraint.
    """

    __tablename__ = "company_aliases"

    normalized_value: Mapped[str] = mapped_column(String(900), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_company_aliases_position"),
        Index("ix_company_aliases_company_position", "company_id", "position", unique=True),
    )
