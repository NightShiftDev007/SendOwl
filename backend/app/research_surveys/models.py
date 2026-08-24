"""PostgreSQL records for native single-context research surveys."""

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


class ResearchSurveyRecord(ApplicationBase):
    __tablename__ = "research_surveys"

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
    project_title: Mapped[str] = mapped_column(String(300), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    project_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    initial_post: Mapped[str] = mapped_column(Text, nullable=False)
    run_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id", ondelete="RESTRICT"), nullable=False
    )
    cohort_title: Mapped[str] = mapped_column(String(200), nullable=False)
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    survey_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    survey_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_research_surveys_persona_count"),
        CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' "
            "AND run_spec_sha256 ~ '^[a-f0-9]{64}$' "
            "AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND dataset_sha256 ~ '^[a-f0-9]{64}$' "
            "AND instrument_sha256 ~ '^[a-f0-9]{64}$' "
            "AND survey_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND survey_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_surveys_digests",
        ),
        CheckConstraint(
            "instrument_schema_version = 'single-context-observation/v1'",
            name="ck_research_surveys_instrument",
        ),
        CheckConstraint(
            "prompt_schema_version = 'sandowl-research-survey/v1'",
            name="ck_research_surveys_prompt",
        ),
        UniqueConstraint("survey_sha256", name="uq_research_surveys_sha256"),
        UniqueConstraint("research_simulation_run_id", name="uq_research_surveys_run"),
        Index("ix_research_surveys_created", "created_at"),
    )


class ResearchSurveyTrialRecord(ApplicationBase):
    __tablename__ = "research_survey_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    survey_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_surveys.id", ondelete="CASCADE"),
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
        CheckConstraint(
            "persona_position BETWEEN 0 AND 7", name="ck_research_survey_trials_position"
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_research_survey_trials_status",
        ),
        CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$' AND trial_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_survey_trials_digests",
        ),
        UniqueConstraint("trial_sha256", name="uq_research_survey_trials_sha256"),
        UniqueConstraint(
            "survey_id", "persona_position", name="uq_research_survey_trials_position"
        ),
        UniqueConstraint("survey_id", "persona_id", name="uq_research_survey_trials_persona"),
        Index("ix_research_survey_trials_status_created", "status", "created_at"),
    )


class ResearchSurveyAnswerRecord(ApplicationBase):
    __tablename__ = "research_survey_answers"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_survey_trials.id", ondelete="CASCADE"),
        primary_key=True,
    )
    question_position: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    choice_value: Mapped[str | None] = mapped_column(String(32))
    likert_value: Mapped[int | None] = mapped_column(Integer)
    free_text_value: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(question_position=0 AND question_id='context_clarity' "
            "AND answer_type='likert' AND likert_value BETWEEN 1 AND 5 "
            "AND choice_value IS NULL AND free_text_value IS NULL) OR "
            "(question_position=1 AND question_id='attention_priority' "
            "AND answer_type='single_choice' "
            "AND choice_value IN ('evidence','process','timing','impact') "
            "AND likert_value IS NULL AND free_text_value IS NULL) OR "
            "(question_position=2 AND question_id='unanswered_question' "
            "AND answer_type='free_text' "
            "AND length(btrim(free_text_value)) BETWEEN 1 AND 2000 "
            "AND choice_value IS NULL AND likert_value IS NULL)",
            name="ck_research_survey_answers_shape",
        ),
    )
