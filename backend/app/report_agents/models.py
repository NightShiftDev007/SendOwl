"""PostgreSQL records for bounded ReportAgent evidence runs."""

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


class ReportAgentEvidenceRunRecord(ApplicationBase):
    __tablename__ = "report_agent_evidence_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    world_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    research_simulation_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
    )
    research_run_report_sha256: Mapped[str | None] = mapped_column(String(64))
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    outline_json: Mapped[str] = mapped_column(Text, nullable=False)
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    run_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "max_tool_calls BETWEEN 1 AND 20",
            name="ck_report_agent_run_tool_budget",
        ),
        UniqueConstraint("run_sha256", name="uq_report_agent_run_sha256"),
        Index("ix_report_agent_runs_snapshot_created", "world_snapshot_id", "created_at"),
    )


class ReportAgentEvidenceToolCallRecord(ApplicationBase):
    __tablename__ = "report_agent_evidence_tool_calls"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("report_agent_evidence_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_text: Mapped[str | None] = mapped_column(Text)
    call_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "position BETWEEN 0 AND 19",
            name="ck_report_agent_tool_call_position",
        ),
        UniqueConstraint("run_id", "position", name="uq_report_agent_tool_call_position"),
        UniqueConstraint("call_sha256", name="uq_report_agent_tool_call_sha256"),
    )


class ReportAgentCitedDraftRecord(ApplicationBase):
    __tablename__ = "report_agent_cited_drafts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("report_agent_evidence_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_call_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_calls_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_of_draft_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("report_agent_cited_drafts.id", ondelete="RESTRICT"),
    )
    retry_of_input_sha256: Mapped[str | None] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(300))
    sections_json: Mapped[str | None] = mapped_column(Text)
    draft_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(
            "(attempt_number=1 AND retry_of_draft_id IS NULL "
            "AND retry_of_input_sha256 IS NULL) OR "
            "(attempt_number BETWEEN 2 AND 5 AND retry_of_draft_id IS NOT NULL "
            "AND retry_of_input_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_report_agent_draft_retry_lineage",
        ),
        UniqueConstraint(
            "input_sha256",
            "attempt_number",
            name="uq_report_agent_draft_input_attempt",
        ),
        UniqueConstraint("retry_of_draft_id", name="uq_report_agent_draft_retry_parent"),
        Index("ix_report_agent_drafts_run_created", "run_id", "created_at"),
        Index(
            "uq_report_agent_draft_root_input",
            "input_sha256",
            unique=True,
            postgresql_where=attempt_number == 1,
        ),
    )
