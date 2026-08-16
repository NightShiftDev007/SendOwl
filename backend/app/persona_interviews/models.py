"""PostgreSQL records for report-grounded Persona interviews."""

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


class PersonaInterviewRecord(ApplicationBase):
    __tablename__ = "persona_report_interviews"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("decision_reports.id"), nullable=False
    )
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("personas.id"), nullable=False
    )
    persona_position: Mapped[int] = mapped_column(Integer, nullable=False)
    persona_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    persona_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    persona_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    interview_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    answer_markdown: Mapped[str | None] = mapped_column(Text)
    cited_section_positions_json: Mapped[str | None] = mapped_column(Text)
    answer_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("persona_position BETWEEN 0 AND 99", name="ck_persona_interviews_position"),
        CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_persona_interviews_question",
        ),
        CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND persona_profile_sha256 ~ '^[a-f0-9]{64}$' "
            "AND interview_sha256 ~ '^[a-f0-9]{64}$' "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_interviews_digests",
        ),
        CheckConstraint(
            "prompt_schema_version='persona-report-interview/v1'",
            name="ck_persona_interviews_prompt_schema",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_persona_interviews_status",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_persona_interviews_started_time",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_persona_interviews_completed_time",
        ),
        CheckConstraint(
            "(status='queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND length(answer_markdown) BETWEEN 1 AND 2000 "
            "AND length(cited_section_positions_json) >= 3 "
            "AND answer_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_persona_interviews_lifecycle",
        ),
        UniqueConstraint("interview_sha256", name="uq_persona_interviews_sha256"),
        Index("ix_persona_interviews_report_created", "report_id", "created_at"),
    )


class PersonaInterviewSessionRecord(ApplicationBase):
    __tablename__ = "persona_interview_sessions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    report_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("decision_reports.id"), nullable=False
    )
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    session_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_persona_interview_sessions_question",
        ),
        CheckConstraint(
            "persona_count BETWEEN 2 AND 8", name="ck_persona_interview_sessions_count"
        ),
        CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND session_sha256 ~ '^[a-f0-9]{64}$' "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_interview_sessions_digests",
        ),
        CheckConstraint(
            "prompt_schema_version='persona-report-interview-session/v1'",
            name="ck_persona_interview_sessions_schema",
        ),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_persona_interview_sessions_sealed_time",
        ),
        UniqueConstraint("session_sha256", name="uq_persona_interview_sessions_sha256"),
        Index("ix_persona_interview_sessions_report_created", "report_id", "created_at"),
    )


class PersonaInterviewSessionMemberRecord(ApplicationBase):
    __tablename__ = "persona_interview_session_members"

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("persona_interview_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("personas.id"), nullable=False
    )
    interview_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("persona_report_interviews.id"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "position BETWEEN 0 AND 7", name="ck_persona_interview_session_members_position"
        ),
        UniqueConstraint("session_id", "persona_id", name="uq_session_member_persona"),
        UniqueConstraint("session_id", "interview_id", name="uq_session_member_interview"),
    )
