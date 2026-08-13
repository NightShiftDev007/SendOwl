"""Normalized PostgreSQL records for durable MatrAIx survey experiments."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class MatraixSurveyExperimentRecord(ApplicationBase):
    """Content-addressed Scenario/Cohort survey assembled then sealed."""

    __tablename__ = "matraix_survey_experiments"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False
    )
    scenario_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_title: Mapped[str] = mapped_column(String(300), nullable=False)
    decision_question: Mapped[str] = mapped_column(Text, nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_title: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    baseline_position: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_name: Mapped[str] = mapped_column(String(200), nullable=False)
    baseline_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    alternative_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    alternative_position: Mapped[int] = mapped_column(Integer, nullable=False)
    alternative_name: Mapped[str] = mapped_column(String(200), nullable=False)
    alternative_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    instrument_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    survey_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ("scenario_id", "baseline_id"),
            ("scenario_variants.scenario_id", "scenario_variants.id"),
        ),
        ForeignKeyConstraint(
            ("scenario_id", "alternative_id"),
            ("scenario_variants.scenario_id", "scenario_variants.id"),
        ),
        CheckConstraint("scenario_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_scenario_sha"),
        CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_cohort_sha"),
        CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_dataset_sha"),
        CheckConstraint("instrument_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_instrument_sha"),
        CheckConstraint("survey_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_config_sha"),
        CheckConstraint("experiment_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_experiment_sha"),
        CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_survey_persona_count"),
        CheckConstraint("baseline_position = 0", name="ck_survey_baseline_position"),
        CheckConstraint(
            "alternative_position BETWEEN 1 AND 5", name="ck_survey_alternative_position"
        ),
        CheckConstraint(
            "instrument_schema_version = 'scenario-preference/v1'",
            name="ck_survey_instrument_schema",
        ),
        CheckConstraint(
            "prompt_schema_version = 'matraix-survey-scenario-preference/v1'",
            name="ck_survey_prompt_schema",
        ),
        CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_survey_model_name",
        ),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_survey_experiment_sealed_time",
        ),
        UniqueConstraint("experiment_sha256", name="uq_survey_experiment_sha"),
        Index("ix_survey_experiments_created", "created_at"),
    )


class MatraixSurveyTrialRecord(ApplicationBase):
    """One Persona execution with strict queued/running/terminal state."""

    __tablename__ = "matraix_survey_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_survey_experiments.id", ondelete="CASCADE"),
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
    survey_config_sha256: Mapped[str | None] = mapped_column(String(64))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(64))
    answers_sha256: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("persona_position BETWEEN 0 AND 7", name="ck_survey_trial_position"),
        CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_survey_trial_persona_external_id",
        ),
        CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_trial_profile_sha"
        ),
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_trial_sha"),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_survey_trial_status",
        ),
        CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND survey_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND answers_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND runner_version IS NULL "
            "AND model_name IS NULL AND survey_config_sha256 IS NULL "
            "AND prompt_schema_version IS NULL AND answers_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version='1.0.0' AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND survey_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version='matraix-survey-scenario-preference/v1' "
            "AND answers_sha256 ~ '^[a-f0-9]{64}$' "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND survey_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND answers_sha256 IS NULL AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_survey_trial_state_shape",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_survey_trial_started_time",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_survey_trial_completed_time",
        ),
        UniqueConstraint("trial_sha256", name="uq_survey_trial_sha"),
        UniqueConstraint(
            "experiment_id", "persona_position", name="uq_survey_trial_persona_position"
        ),
        UniqueConstraint("experiment_id", "persona_id", name="uq_survey_trial_persona"),
        Index("ix_survey_trials_status_created", "status", "created_at"),
    )


class MatraixSurveyAnswerRecord(ApplicationBase):
    """One append-only typed answer owned by a running Survey trial."""

    __tablename__ = "matraix_survey_answers"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("matraix_survey_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_position: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    choice_value: Mapped[str | None] = mapped_column(String(32))
    likert_value: Mapped[int | None] = mapped_column(Integer)
    free_text_value: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trial_id", "question_position"),
        CheckConstraint(
            "(question_position=0 AND question_id='preferred_variant' "
            "AND answer_type='single_choice' AND choice_value IN ('baseline','alternative') "
            "AND likert_value IS NULL AND free_text_value IS NULL) OR "
            "(question_position=1 AND question_id='alternative_support' "
            "AND answer_type='likert' AND choice_value IS NULL "
            "AND likert_value BETWEEN 1 AND 5 AND free_text_value IS NULL) OR "
            "(question_position=2 AND question_id='primary_reason' "
            "AND answer_type='free_text' AND choice_value IS NULL "
            "AND likert_value IS NULL AND length(btrim(free_text_value)) BETWEEN 1 AND 2000)",
            name="ck_survey_answer_typed_shape",
        ),
        Index("ix_survey_answers_trial_position", "trial_id", "question_position"),
    )


__all__ = [
    "MatraixSurveyAnswerRecord",
    "MatraixSurveyExperimentRecord",
    "MatraixSurveyTrialRecord",
]
