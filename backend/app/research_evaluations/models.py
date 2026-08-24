"""Durable immutable task bundles for Project-bound evaluations."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class ResearchEvaluationTaskBundleRecord(ApplicationBase):
    """One sealed evaluation input compiled before any paid execution."""

    __tablename__ = "research_evaluation_task_bundles"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    research_project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    research_simulation_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cohorts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("kind='survey'", name="ck_research_evaluation_bundles_kind"),
        CheckConstraint(
            "schema_version='sandowl-research-evaluation-task-bundle/v1'",
            name="ck_research_evaluation_bundles_schema",
        ),
        CheckConstraint(
            "bundle_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_evaluation_bundles_digest",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json)='object'",
            name="ck_research_evaluation_bundles_payload",
        ),
        CheckConstraint(
            "sealed_at >= created_at",
            name="ck_research_evaluation_bundles_sealed_time",
        ),
        UniqueConstraint(
            "research_simulation_run_id",
            "kind",
            name="uq_research_evaluation_bundles_run_kind",
        ),
        Index("ix_research_evaluation_bundles_project", "research_project_id", "created_at"),
    )


class ResearchEvaluationTargetRecord(ApplicationBase):
    """One immutable Chat or Web SUT definition, without execution authority."""

    __tablename__ = "research_evaluation_targets"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    research_project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    research_simulation_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("cohorts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    target_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('chat','web','app')",
            name="ck_research_evaluation_targets_kind",
        ),
        CheckConstraint(
            "schema_version='sandowl-research-evaluation-target/v1'",
            name="ck_research_evaluation_targets_schema",
        ),
        CheckConstraint(
            "target_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_evaluation_targets_digest",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json)='object'",
            name="ck_research_evaluation_targets_payload",
        ),
        CheckConstraint(
            "sealed_at >= created_at",
            name="ck_research_evaluation_targets_sealed_time",
        ),
        UniqueConstraint(
            "research_simulation_run_id",
            "kind",
            name="uq_research_evaluation_targets_run_kind",
        ),
        Index("ix_research_evaluation_targets_project", "research_project_id", "created_at"),
    )


class ResearchEvaluationJobRecord(ApplicationBase):
    """One durable Harbor dispatch bound to an immutable target and cohort."""

    __tablename__ = "research_evaluation_jobs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    research_project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("research_projects.id"), nullable=False
    )
    research_simulation_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("research_simulation_runs.id"), nullable=False
    )
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_evaluation_targets.id"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    job_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    retry_of_job_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_evaluation_jobs.id", ondelete="RESTRICT"),
    )
    retry_of_job_sha256: Mapped[str | None] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    remote_run_id: Mapped[str | None] = mapped_column(String(128))
    trajectory_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    trajectory_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    verifier_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    verifier_sha256: Mapped[str | None] = mapped_column(String(64))
    reward_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    reward_sha256: Mapped[str | None] = mapped_column(String(64))
    reward_value: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("kind IN ('chat','web','app')", name="ck_research_evaluation_jobs_kind"),
        CheckConstraint(
            "status IN ('queued','dispatching','running','succeeded','failed','cancelled')",
            name="ck_research_evaluation_jobs_status",
        ),
        CheckConstraint(
            "job_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_evaluation_jobs_digest",
        ),
        CheckConstraint(
            "(attempt_number=1 AND retry_of_job_id IS NULL "
            "AND retry_of_job_sha256 IS NULL) OR "
            "(attempt_number BETWEEN 2 AND 5 AND retry_of_job_id IS NOT NULL "
            "AND retry_of_job_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_research_evaluation_jobs_retry_lineage",
        ),
        CheckConstraint(
            "reward_value IS NULL OR (reward_value >= 0 AND reward_value <= 1)",
            name="ck_research_evaluation_jobs_reward",
        ),
        Index("ix_research_evaluation_jobs_status_created", "status", "created_at"),
        UniqueConstraint("retry_of_job_id", name="uq_research_evaluation_job_retry_parent"),
    )
