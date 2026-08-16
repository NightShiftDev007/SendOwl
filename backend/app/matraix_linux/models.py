"""PostgreSQL records for fixed MatrAIx Linux artifact trials and sealed parents."""

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


class MatraixLinuxEvaluationRecord(ApplicationBase):
    __tablename__ = "matraix_linux_evaluations"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_linux_trials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    trial_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_eval_trial_sha"),
        CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_eval_sha"),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_linux_eval_sealed_time",
        ),
        UniqueConstraint("trial_id", name="uq_linux_eval_trial"),
        UniqueConstraint("evaluation_sha256", name="uq_linux_eval_sha"),
        Index("ix_linux_evaluations_created", "created_at"),
    )


class MatraixLinuxTrialRecord(ApplicationBase):
    __tablename__ = "matraix_linux_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_title: Mapped[str] = mapped_column(String(200), nullable=False)
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("personas.id"), nullable=False
    )
    persona_position: Mapped[int] = mapped_column(Integer, nullable=False)
    persona_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    persona_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    persona_profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_version: Mapped[str] = mapped_column(String(32), nullable=False)
    task_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    task_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    runner_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runner_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    linux_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    trial_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_runner_version: Mapped[str | None] = mapped_column(String(32))
    result_artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    result_cleaned_list_sha256: Mapped[str | None] = mapped_column(String(64))
    result_submission_sha256: Mapped[str | None] = mapped_column(String(64))
    result_feedback_sha256: Mapped[str | None] = mapped_column(String(64))
    result_verifier_sha256: Mapped[str | None] = mapped_column(String(64))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    result_reason: Mapped[str | None] = mapped_column(Text)
    result_need_satisfaction: Mapped[str | None] = mapped_column(String(16))
    result_preference_satisfaction: Mapped[str | None] = mapped_column(String(16))
    result_rating: Mapped[int | None] = mapped_column(Integer)
    result_feedback_reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("length(btrim(cohort_title)) BETWEEN 1 AND 200", name="ck_linux_cohort"),
        CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_linux_cohort_hashes",
        ),
        CheckConstraint("persona_position BETWEEN 0 AND 99", name="ck_linux_persona_position"),
        CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_linux_persona_external_id",
        ),
        CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200",
            name="ck_linux_persona_name",
        ),
        CheckConstraint("persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_persona_sha"),
        CheckConstraint("task_id='matraix/linux-note-to-csv'", name="ck_linux_task_id"),
        CheckConstraint("task_version='1.0.0'", name="ck_linux_task_version"),
        CheckConstraint(
            "task_schema_version='matraix-linux-task/note-to-csv-v1'",
            name="ck_linux_task_schema",
        ),
        CheckConstraint(
            "task_spec_sha256='0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9'",
            name="ck_linux_task_sha",
        ),
        CheckConstraint(
            "runner_schema_version='matraix-linux-artifact-runner/v1'",
            name="ck_linux_runner_schema",
        ),
        CheckConstraint(
            "runner_spec_sha256='ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354'",
            name="ck_linux_runner_sha",
        ),
        CheckConstraint("length(btrim(model_name)) BETWEEN 1 AND 200", name="ck_linux_model"),
        CheckConstraint("linux_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_config_sha"),
        CheckConstraint(
            "prompt_schema_version='matraix-linux-note-to-csv/v1'",
            name="ck_linux_prompt_schema",
        ),
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_trial_sha"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_linux_status"
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_linux_started_at"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="ck_linux_completed_at"
        ),
        CheckConstraint(
            "result_need_satisfaction IS NULL OR result_need_satisfaction IN "
            "('yes','partially','no')",
            name="ck_linux_need",
        ),
        CheckConstraint(
            "result_preference_satisfaction IS NULL OR result_preference_satisfaction IN "
            "('yes','partially','no')",
            name="ck_linux_preference",
        ),
        CheckConstraint(
            "result_rating IS NULL OR result_rating BETWEEN 1 AND 10", name="ck_linux_rating"
        ),
        CheckConstraint(
            "status='succeeded' OR (result_runner_version IS NULL "
            "AND result_artifact_sha256 IS NULL AND result_cleaned_list_sha256 IS NULL "
            "AND result_submission_sha256 IS NULL AND result_feedback_sha256 IS NULL "
            "AND result_verifier_sha256 IS NULL AND result_sha256 IS NULL "
            "AND result_reason IS NULL AND result_need_satisfaction IS NULL "
            "AND result_preference_satisfaction IS NULL AND result_rating IS NULL "
            "AND result_feedback_reason IS NULL)",
            name="ck_linux_non_success_results_empty",
        ),
        CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR "
            "(status='running' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR "
            "(status='succeeded' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result_runner_version='1.0.0' "
            "AND result_artifact_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_cleaned_list_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_submission_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_feedback_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_verifier_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' AND result_reason IS NOT NULL "
            "AND result_need_satisfaction IS NOT NULL "
            "AND result_preference_satisfaction IS NOT NULL AND result_rating IS NOT NULL "
            "AND result_feedback_reason IS NOT NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='failed' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_linux_lifecycle",
        ),
        Index("ix_linux_trials_created", "created_at"),
        Index("ix_linux_trials_status_created", "status", "created_at"),
    )
