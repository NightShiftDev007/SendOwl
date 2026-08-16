"""Normalized PostgreSQL records for bounded MatrAIx Playwright evaluations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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


class MatraixWebEvaluationRecord(ApplicationBase):
    __tablename__ = "matraix_web_evaluations"

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
    executor_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    executor_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    web_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_cohort_sha"),
        CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_dataset_sha"),
        CheckConstraint("persona_count BETWEEN 1 AND 4", name="ck_web_eval_persona_count"),
        CheckConstraint("task_id='matraix/quotes-playwright-choice'", name="ck_web_eval_task_id"),
        CheckConstraint("task_version='1.0.0'", name="ck_web_eval_task_version"),
        CheckConstraint(
            "task_schema_version='matraix-web-task/quote-choice-v1'",
            name="ck_web_eval_task_schema",
        ),
        CheckConstraint(
            "task_spec_sha256='f5be8a4a377764ac77f80e3178720e914b4b069875dc5b8f3bbd6ff3508525ad'",
            name="ck_web_eval_task_sha",
        ),
        CheckConstraint(
            "executor_schema_version='matraix-web-browser-executor/v1'",
            name="ck_web_eval_executor_schema",
        ),
        CheckConstraint(
            "executor_spec_sha256="
            "'36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7'",
            name="ck_web_eval_executor_sha",
        ),
        CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_web_eval_model",
        ),
        CheckConstraint("web_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_config_sha"),
        CheckConstraint(
            "prompt_schema_version='matraix-web-quotes-choice/v1'",
            name="ck_web_eval_prompt_schema",
        ),
        CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_sha"),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_web_eval_sealed_time",
        ),
        UniqueConstraint("evaluation_sha256", name="uq_web_eval_sha"),
        Index("ix_web_evaluations_created", "created_at"),
    )


class MatraixWebTrialRecord(ApplicationBase):
    __tablename__ = "matraix_web_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    evaluation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_web_evaluations.id", ondelete="CASCADE"),
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
    web_config_sha256: Mapped[str | None] = mapped_column(String(64))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(64))
    trace_sha256: Mapped[str | None] = mapped_column(String(64))
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    decision_subject_id: Mapped[str | None] = mapped_column(String(64))
    decision_subject_label: Mapped[str | None] = mapped_column(Text)
    basis_primary: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    task_author: Mapped[str | None] = mapped_column(String(200))
    need_constraint_satisfaction: Mapped[str | None] = mapped_column(String(16))
    personal_preference_satisfaction: Mapped[str | None] = mapped_column(String(16))
    overall_experience_rating: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("persona_position BETWEEN 0 AND 3", name="ck_web_trial_position"),
        CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_web_trial_persona_external_id",
        ),
        CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200 "
            "AND persona_display_name !~ E'[\\r\\n]'",
            name="ck_web_trial_persona_name",
        ),
        CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_trial_profile_sha"
        ),
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_trial_sha"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_web_trial_status"
        ),
        CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version='1.0.0' AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND web_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version='matraix-web-quotes-choice/v1' "
            "AND trace_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' "
            "AND decision_subject_id ~ '^[a-f0-9]{64}$' "
            "AND decision_subject_label IS NOT NULL AND basis_primary IS NOT NULL "
            "AND reason IS NOT NULL AND task_author IS NOT NULL "
            "AND need_constraint_satisfaction IS NOT NULL "
            "AND personal_preference_satisfaction IS NOT NULL "
            "AND overall_experience_rating IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_web_trial_state_shape",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_web_trial_started_time"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_web_trial_completed_time",
        ),
        CheckConstraint(
            "decision_subject_label IS NULL OR "
            "length(btrim(decision_subject_label)) BETWEEN 1 AND 2000",
            name="ck_web_trial_subject_label",
        ),
        CheckConstraint(
            "basis_primary IS NULL OR basis_primary IN "
            "('price','quality','features','convenience','taste','trust','familiarity',"
            "'novelty','fit','other')",
            name="ck_web_trial_basis",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) BETWEEN 20 AND 2000",
            name="ck_web_trial_reason",
        ),
        CheckConstraint(
            "task_author IS NULL OR length(btrim(task_author)) BETWEEN 1 AND 200",
            name="ck_web_trial_author",
        ),
        CheckConstraint(
            "need_constraint_satisfaction IS NULL OR "
            "need_constraint_satisfaction IN ('yes','partially','no')",
            name="ck_web_trial_need",
        ),
        CheckConstraint(
            "personal_preference_satisfaction IS NULL OR "
            "personal_preference_satisfaction IN ('yes','partially','no')",
            name="ck_web_trial_preference",
        ),
        CheckConstraint(
            "overall_experience_rating IS NULL OR overall_experience_rating BETWEEN 1 AND 10",
            name="ck_web_trial_rating",
        ),
        UniqueConstraint("trial_sha256", name="uq_web_trial_sha"),
        UniqueConstraint("evaluation_id", "persona_position", name="uq_web_trial_eval_position"),
        UniqueConstraint("evaluation_id", "persona_id", name="uq_web_trial_eval_persona"),
        Index("ix_web_trials_status_created", "status", "created_at"),
    )


class MatraixWebPageRecord(ApplicationBase):
    __tablename__ = "matraix_web_pages"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_web_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    screenshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trial_id", "position"),
        CheckConstraint("position BETWEEN 0 AND 2", name="ck_web_page_position"),
        CheckConstraint(
            "url ~ '^https://quotes\\.toscrape\\.com/(page/[1-9][0-9]*/)?$'",
            name="ck_web_page_url",
        ),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="ck_web_page_title"),
        CheckConstraint("screenshot_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_page_screenshot_sha"),
    )


class MatraixWebQuoteRecord(ApplicationBase):
    __tablename__ = "matraix_web_quotes"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_web_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    page_position: Mapped[int] = mapped_column(Integer, nullable=False)
    quote_id: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(128)), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trial_id", "position"),
        CheckConstraint("position BETWEEN 0 AND 59", name="ck_web_quote_position"),
        CheckConstraint("page_position BETWEEN 0 AND 2", name="ck_web_quote_page_position"),
        CheckConstraint("quote_id ~ '^[a-f0-9]{64}$'", name="ck_web_quote_id"),
        CheckConstraint("length(btrim(text)) BETWEEN 1 AND 2000", name="ck_web_quote_text"),
        CheckConstraint("length(btrim(author)) BETWEEN 1 AND 200", name="ck_web_quote_author"),
        ForeignKeyConstraint(
            ("trial_id", "page_position"),
            ("matraix_web_pages.trial_id", "matraix_web_pages.position"),
            ondelete="CASCADE",
        ),
        UniqueConstraint("trial_id", "quote_id", name="uq_web_quote_trial_id"),
    )
