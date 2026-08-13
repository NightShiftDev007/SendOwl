"""PostgreSQL records for persistent decision identities and immutable revisions."""

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


class DecisionThreadRecord(ApplicationBase):
    __tablename__ = "decision_threads"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    decision_question: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 300", name="ck_decision_threads_title"),
        CheckConstraint(
            "length(btrim(decision_question)) BETWEEN 1 AND 2000",
            name="ck_decision_threads_question",
        ),
        Index("ix_decision_threads_created_at", "created_at"),
    )


class DecisionThreadRevisionRecord(ApplicationBase):
    __tablename__ = "decision_thread_revisions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    thread_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("decision_threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("world_models.id"), nullable=False
    )
    world_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("world_snapshots.id"), nullable=False
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("scenarios.id")
    )
    scenario_sha256: Mapped[str | None] = mapped_column(String(64))
    cohort_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id")
    )
    cohort_sha256: Mapped[str | None] = mapped_column(String(64))
    semantic_experiment_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("semantic_experiments.id")
    )
    experiment_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_decision_thread_revisions_version"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
            "((scenario_id IS NULL AND scenario_sha256 IS NULL) OR "
            "(scenario_id IS NOT NULL AND scenario_sha256 ~ '^[a-f0-9]{64}$')) AND "
            "((cohort_id IS NULL AND cohort_sha256 IS NULL) OR "
            "(cohort_id IS NOT NULL AND cohort_sha256 ~ '^[a-f0-9]{64}$')) AND "
            "((semantic_experiment_id IS NULL AND experiment_sha256 IS NULL) OR "
            "(semantic_experiment_id IS NOT NULL AND experiment_sha256 ~ '^[a-f0-9]{64}$'))",
            name="ck_decision_thread_revisions_digests",
        ),
        CheckConstraint(
            "semantic_experiment_id IS NULL OR (scenario_id IS NOT NULL AND cohort_id IS NOT NULL)",
            name="ck_decision_thread_revisions_dependencies",
        ),
        UniqueConstraint("thread_id", "version", name="uq_decision_thread_revisions_version"),
        Index("ix_decision_thread_revisions_thread_version", "thread_id", "version"),
    )
