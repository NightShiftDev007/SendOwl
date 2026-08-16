"""Normalized PostgreSQL records for durable MatrAIx chatbot evaluations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class MatraixChatEvaluationRecord(ApplicationBase):
    """One content-addressed task/Cohort/config evaluation assembled then sealed."""

    __tablename__ = "matraix_chat_evaluations"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_title: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_version: Mapped[str] = mapped_column(String(32), nullable=False)
    task_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    task_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sut_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    chat_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_of_evaluation_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_chat_evaluations.id", ondelete="RESTRICT"),
    )
    retry_of_evaluation_sha256: Mapped[str | None] = mapped_column(String(64))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_cohort_sha"),
        CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_dataset_sha"),
        CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_chat_eval_persona_count"),
        CheckConstraint(
            "task_id IN ('matraix/acme-support-order-4521', 'matraix/acme-support-mcp-order-4521')",
            name="ck_chat_eval_task_id",
        ),
        CheckConstraint("task_version = '1.0.0'", name="ck_chat_eval_task_version"),
        CheckConstraint(
            "task_schema_version = 'matraix-chat-task/acme-support-v1'",
            name="ck_chat_eval_task_schema",
        ),
        CheckConstraint(
            "(task_id='matraix/acme-support-order-4521' AND "
            "task_spec_sha256="
            "'4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1') OR "
            "(task_id='matraix/acme-support-mcp-order-4521' AND "
            "task_spec_sha256='cd92b749ac08d0a229c3ea6191c52f03c096b03aff1689f5da04e7ec2daabd98')",
            name="ck_chat_eval_task_spec_sha",
        ),
        CheckConstraint(
            "(task_id='matraix/acme-support-order-4521' AND "
            "sut_spec_sha256="
            "'b3609ac5ab58a4994c497f276d4689b8272150a9251676ddef84ebe9e8bdc980') OR "
            "(task_id='matraix/acme-support-mcp-order-4521' AND "
            "sut_spec_sha256='5fbc2623be9df873de0c025edd1f2dcbf9d0b24672d627f1e063002c9e9587e1')",
            name="ck_chat_eval_sut_spec_sha",
        ),
        CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_chat_eval_model_name",
        ),
        CheckConstraint("chat_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_config_sha"),
        CheckConstraint(
            "prompt_schema_version = 'matraix-chat-acme-support/v1'",
            name="ck_chat_eval_prompt_schema",
        ),
        CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_sha"),
        CheckConstraint(
            "(attempt_number=1 AND retry_of_evaluation_id IS NULL "
            "AND retry_of_evaluation_sha256 IS NULL) OR "
            "(attempt_number BETWEEN 2 AND 5 AND retry_of_evaluation_id IS NOT NULL "
            "AND retry_of_evaluation_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_chat_eval_attempt_lineage",
        ),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_chat_eval_sealed_time",
        ),
        UniqueConstraint("evaluation_sha256", name="uq_chat_eval_sha"),
        UniqueConstraint("retry_of_evaluation_id", name="uq_chat_eval_retry_parent"),
        Index("ix_chat_evaluations_created", "created_at"),
    )


class MatraixChatTrialRecord(ApplicationBase):
    """One Persona execution with a durable strict lifecycle."""

    __tablename__ = "matraix_chat_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_chat_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    persona_position: Mapped[int] = mapped_column(Integer, nullable=False)
    persona_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("personas.id"), nullable=False
    )
    persona_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    persona_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    persona_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    trial_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    runner_version: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(200))
    chat_config_sha256: Mapped[str | None] = mapped_column(String(64))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(64))
    transcript_sha256: Mapped[str | None] = mapped_column(String(64))
    feedback_sha256: Mapped[str | None] = mapped_column(String(64))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    outcome_status: Mapped[str | None] = mapped_column(String(32))
    next_step_owner: Mapped[str | None] = mapped_column(String(16))
    conversation_path: Mapped[str | None] = mapped_column(String(32))
    resolution_progression: Mapped[str | None] = mapped_column(String(32))
    message_count: Mapped[int | None] = mapped_column(Integer)
    customer_turn_count: Mapped[int | None] = mapped_column(Integer)
    support_turn_count: Mapped[int | None] = mapped_column(Integer)
    clarification_question_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("persona_position BETWEEN 0 AND 7", name="ck_chat_trial_position"),
        CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_chat_trial_persona_external_id",
        ),
        CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200 "
            "AND persona_display_name !~ E'[\\r\\n]'",
            name="ck_chat_trial_persona_display_name",
        ),
        CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_chat_trial_profile_sha",
        ),
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_trial_sha"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_chat_trial_status",
        ),
        CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND chat_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND transcript_sha256 IS NULL AND feedback_sha256 IS NULL "
            "AND result_sha256 IS NULL AND outcome_status IS NULL "
            "AND next_step_owner IS NULL AND conversation_path IS NULL "
            "AND resolution_progression IS NULL AND message_count IS NULL "
            "AND customer_turn_count IS NULL AND support_turn_count IS NULL "
            "AND clarification_question_count IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND runner_version IS NULL "
            "AND model_name IS NULL AND chat_config_sha256 IS NULL "
            "AND prompt_schema_version IS NULL AND transcript_sha256 IS NULL "
            "AND feedback_sha256 IS NULL AND result_sha256 IS NULL "
            "AND outcome_status IS NULL AND next_step_owner IS NULL "
            "AND conversation_path IS NULL AND resolution_progression IS NULL "
            "AND message_count IS NULL AND customer_turn_count IS NULL "
            "AND support_turn_count IS NULL AND clarification_question_count IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version='1.0.0' AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version='matraix-chat-acme-support/v1' "
            "AND transcript_sha256 ~ '^[a-f0-9]{64}$' "
            "AND feedback_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' "
            "AND outcome_status IN ('resolved','partially_resolved','unresolved') "
            "AND next_step_owner IN ('user','support','none') "
            "AND conversation_path IN "
            "('clarify_then_resolve','clarify_then_partial','stalled') "
            "AND resolution_progression IN ('single_response','looped','advanced') "
            "AND message_count BETWEEN 4 AND 40 AND message_count % 2 = 0 "
            "AND customer_turn_count BETWEEN 2 AND 20 "
            "AND support_turn_count = customer_turn_count "
            "AND message_count = customer_turn_count + support_turn_count "
            "AND clarification_question_count BETWEEN 0 AND support_turn_count "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND chat_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND transcript_sha256 IS NULL AND feedback_sha256 IS NULL "
            "AND result_sha256 IS NULL AND outcome_status IS NULL "
            "AND next_step_owner IS NULL AND conversation_path IS NULL "
            "AND resolution_progression IS NULL AND message_count IS NULL "
            "AND customer_turn_count IS NULL AND support_turn_count IS NULL "
            "AND clarification_question_count IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_chat_trial_state_shape",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_chat_trial_started_time"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_chat_trial_completed_time",
        ),
        UniqueConstraint("trial_sha256", name="uq_chat_trial_sha"),
        UniqueConstraint("evaluation_id", "persona_position", name="uq_chat_trial_eval_position"),
        UniqueConstraint("evaluation_id", "persona_id", name="uq_chat_trial_eval_persona"),
        Index("ix_chat_trials_status_created", "status", "created_at"),
    )


class MatraixChatMessageRecord(ApplicationBase):
    """One append-only real customer or support turn."""

    __tablename__ = "matraix_chat_messages"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_chat_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trial_id", "position"),
        CheckConstraint("position BETWEEN 0 AND 39", name="ck_chat_message_position"),
        CheckConstraint("role IN ('customer','support')", name="ck_chat_message_role"),
        CheckConstraint(
            "content = btrim(content) AND length(btrim(content)) BETWEEN 1 AND 8000 "
            "AND content ~ '[^[:space:]]'",
            name="ck_chat_message_content",
        ),
        Index("ix_chat_messages_trial_position", "trial_id", "position"),
    )


class MatraixChatFeedbackRecord(ApplicationBase):
    """One append-only typed synthetic Persona self-report."""

    __tablename__ = "matraix_chat_feedback"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_chat_trials.id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    need_constraint_satisfaction: Mapped[str] = mapped_column(String(16), nullable=False)
    personal_preference_satisfaction: Mapped[str] = mapped_column(String(16), nullable=False)
    overall_experience_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    asked_useful_clarification_questions: Mapped[bool] = mapped_column(Boolean, nullable=False)
    clarifying_notes: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "schema_version = 'matraix-chat-feedback/acme-support-v1'",
            name="ck_chat_feedback_schema",
        ),
        CheckConstraint(
            "need_constraint_satisfaction IN ('yes','partially','no')",
            name="ck_chat_feedback_need",
        ),
        CheckConstraint(
            "personal_preference_satisfaction IN ('yes','partially','no')",
            name="ck_chat_feedback_preference",
        ),
        CheckConstraint(
            "overall_experience_rating BETWEEN 1 AND 10",
            name="ck_chat_feedback_rating",
        ),
        CheckConstraint(
            "reason = btrim(reason) AND length(btrim(reason)) BETWEEN 1 AND 2000 "
            "AND reason ~ '[^[:space:]]'",
            name="ck_chat_feedback_reason",
        ),
        CheckConstraint(
            "clarifying_notes = btrim(clarifying_notes) "
            "AND length(btrim(clarifying_notes)) BETWEEN 1 AND 2000 "
            "AND clarifying_notes ~ '[^[:space:]]'",
            name="ck_chat_feedback_notes",
        ),
    )


__all__ = [
    "MatraixChatEvaluationRecord",
    "MatraixChatFeedbackRecord",
    "MatraixChatMessageRecord",
    "MatraixChatTrialRecord",
]
