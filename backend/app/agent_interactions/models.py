"""PostgreSQL queue record for native Agent Interaction."""

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


class AgentInteractionRecord(ApplicationBase):
    __tablename__ = "agent_interactions"

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
    report_agent_run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("report_agent_evidence_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_agent_run_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_agent_draft_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("report_agent_cited_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_agent_draft_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    interaction_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_interaction_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_interactions.id", ondelete="RESTRICT"),
    )
    parent_interaction_sha256: Mapped[str | None] = mapped_column(String(64))
    parent_answer_sha256: Mapped[str | None] = mapped_column(String(64))
    conversation_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    answer_markdown: Mapped[str | None] = mapped_column(Text)
    citations_json: Mapped[str | None] = mapped_column(Text)
    answer_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_agent_interactions_question",
        ),
        CheckConstraint("conversation_depth BETWEEN 0 AND 4", name="ck_agent_interactions_depth"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_agent_interactions_status",
        ),
        CheckConstraint(
            "prompt_schema_version IN "
            "('sandowl-agent-interaction/v1','sandowl-agent-interaction/v2')",
            name="ck_agent_interactions_prompt_schema",
        ),
        UniqueConstraint("interaction_sha256", name="uq_agent_interactions_sha256"),
        Index("ix_agent_interactions_draft_created", "report_agent_draft_id", "created_at"),
    )
