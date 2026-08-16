"""PostgreSQL queue records for evidence-bound report questions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class ReportQuestionRecord(ApplicationBase):
    __tablename__ = "report_questions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("decision_reports.id"), nullable=False
    )
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("semantic_world_graphs.id"), nullable=False
    )
    graph_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_question_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("report_questions.id", ondelete="RESTRICT")
    )
    parent_question_sha256: Mapped[str | None] = mapped_column(String(64))
    parent_answer_sha256: Mapped[str | None] = mapped_column(String(64))
    conversation_depth: Mapped[int] = mapped_column(nullable=False, default=0)
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
            "length(btrim(question)) BETWEEN 2 AND 1000", name="ck_report_questions_text"
        ),
        CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND graph_sha256 ~ '^[a-f0-9]{64}$' "
            "AND question_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_report_questions_input_digests",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_report_questions_status",
        ),
        CheckConstraint(
            "prompt_schema_version IN ('report-evidence-qa/v1', 'report-evidence-qa/v2')",
            name="ck_report_questions_prompt_schema",
        ),
        CheckConstraint(
            "(conversation_depth = 0 AND parent_question_id IS NULL "
            "AND parent_question_sha256 IS NULL AND parent_answer_sha256 IS NULL "
            "AND prompt_schema_version = 'report-evidence-qa/v1') OR "
            "(conversation_depth BETWEEN 1 AND 4 AND parent_question_id IS NOT NULL "
            "AND parent_question_sha256 ~ '^[a-f0-9]{64}$' "
            "AND parent_answer_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version = 'report-evidence-qa/v2')",
            name="ck_report_questions_lineage",
        ),
        CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND length(answer_markdown) BETWEEN 1 AND 800 "
            "AND length(citations_json) >= 2 AND answer_sha256 ~ '^[a-f0-9]{64}$' "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_report_questions_lifecycle",
        ),
        UniqueConstraint("question_sha256", name="uq_report_questions_sha256"),
        Index("ix_report_questions_report_created", "report_id", "created_at"),
    )
