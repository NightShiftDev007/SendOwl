"""PostgreSQL records for immutable deterministic reports."""

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


class DecisionReportRecord(ApplicationBase):
    __tablename__ = "decision_reports"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("semantic_experiments.id"), nullable=False
    )
    experiment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False
    )
    scenario_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 300", name="ck_decision_reports_title"),
        CheckConstraint(
            "experiment_sha256 ~ '^[a-f0-9]{64}$' AND scenario_sha256 ~ '^[a-f0-9]{64}$' "
            "AND cohort_sha256 ~ '^[a-f0-9]{64}$' AND report_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_decision_reports_digests",
        ),
        CheckConstraint(
            "generator_version = 'deterministic-findings/v1'",
            name="ck_decision_reports_generator",
        ),
        UniqueConstraint("experiment_id", name="uq_decision_reports_experiment"),
        UniqueConstraint("report_sha256", name="uq_decision_reports_sha256"),
        Index("ix_decision_reports_created_at", "created_at"),
    )


class DecisionReportSectionRecord(ApplicationBase):
    __tablename__ = "decision_report_sections"

    report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 3", name="ck_decision_report_sections_position"),
        CheckConstraint(
            "kind IN ('scope', 'comparison', 'limitations', 'provenance')",
            name="ck_decision_report_sections_kind",
        ),
        CheckConstraint(
            "length(body_markdown) BETWEEN 1 AND 40000", name="ck_decision_report_sections_body"
        ),
    )
