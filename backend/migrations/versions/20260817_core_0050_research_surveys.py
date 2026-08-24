"""Add native single-context research surveys.

Revision ID: 20260817_core_0050
Revises: 20260817_core_0049
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_core_0050"
down_revision: str | None = "20260817_core_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_simulation_worker_survey_config", "simulation_worker_heartbeats", type_="check"
    )
    op.execute(
        "UPDATE simulation_worker_heartbeats SET survey_runtime_ready=false, "
        "survey_model_name=NULL, survey_config_sha256=NULL, "
        "survey_prompt_schema_version=NULL WHERE survey_runtime_ready IS TRUE"
    )
    op.create_check_constraint(
        "ck_simulation_worker_survey_config",
        "simulation_worker_heartbeats",
        "(survey_runtime_ready AND worker_domain = 'evaluation' AND length(btrim(survey_model_name)) BETWEEN 1 AND 200 AND survey_model_name !~ E'[\\r\\n]' AND survey_config_sha256 ~ '^[a-f0-9]{64}$' AND survey_prompt_schema_version = 'sandowl-research-survey/v1') OR (NOT survey_runtime_ready AND survey_model_name IS NULL AND survey_config_sha256 IS NULL AND survey_prompt_schema_version IS NULL)",
    )
    op.create_table(
        "research_surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_simulation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("project_title", sa.String(300), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("project_sha256", sa.String(64), nullable=False),
        sa.Column("simulation_requirement", sa.Text(), nullable=False),
        sa.Column("initial_post", sa.Text(), nullable=False),
        sa.Column("run_spec_sha256", sa.String(64), nullable=False),
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cohort_title", sa.String(200), nullable=False),
        sa.Column("cohort_sha256", sa.String(64), nullable=False),
        sa.Column("dataset_sha256", sa.String(64), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("instrument_schema_version", sa.String(64), nullable=False),
        sa.Column("instrument_sha256", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("survey_config_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(64), nullable=False),
        sa.Column("survey_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "persona_count BETWEEN 1 AND 8", name="ck_research_surveys_persona_count"
        ),
        sa.CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' AND run_spec_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' AND dataset_sha256 ~ '^[a-f0-9]{64}$' AND instrument_sha256 ~ '^[a-f0-9]{64}$' AND survey_config_sha256 ~ '^[a-f0-9]{64}$' AND survey_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_surveys_digests",
        ),
        sa.CheckConstraint(
            "instrument_schema_version = 'single-context-observation/v1'",
            name="ck_research_surveys_instrument",
        ),
        sa.CheckConstraint(
            "prompt_schema_version = 'sandowl-research-survey/v1'",
            name="ck_research_surveys_prompt",
        ),
        sa.UniqueConstraint("survey_sha256", name="uq_research_surveys_sha256"),
        sa.UniqueConstraint("research_simulation_run_id", name="uq_research_surveys_run"),
    )
    op.create_index("ix_research_surveys_created", "research_surveys", ["created_at"])
    op.create_table(
        "research_survey_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_surveys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("persona_position", sa.Integer(), nullable=False),
        sa.Column(
            "persona_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("personas.id"),
            nullable=False,
        ),
        sa.Column("persona_external_id", sa.String(128), nullable=False),
        sa.Column("persona_display_name", sa.String(200), nullable=False),
        sa.Column("persona_profile_sha256", sa.String(64), nullable=False),
        sa.Column("trial_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("runner_version", sa.String(32)),
        sa.Column("model_name", sa.String(200)),
        sa.Column("survey_config_sha256", sa.String(64)),
        sa.Column("prompt_schema_version", sa.String(64)),
        sa.Column("answers_sha256", sa.String(64)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "persona_position BETWEEN 0 AND 7", name="ck_research_survey_trials_position"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_research_survey_trials_status",
        ),
        sa.CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$' AND trial_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_survey_trials_digests",
        ),
        sa.UniqueConstraint("trial_sha256", name="uq_research_survey_trials_sha256"),
        sa.UniqueConstraint(
            "survey_id", "persona_position", name="uq_research_survey_trials_position"
        ),
        sa.UniqueConstraint("survey_id", "persona_id", name="uq_research_survey_trials_persona"),
    )
    op.create_index(
        "ix_research_survey_trials_status_created",
        "research_survey_trials",
        ["status", "created_at"],
    )
    op.create_table(
        "research_survey_answers",
        sa.Column(
            "trial_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_survey_trials.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("question_position", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("answer_type", sa.String(32), nullable=False),
        sa.Column("choice_value", sa.String(32)),
        sa.Column("likert_value", sa.Integer()),
        sa.Column("free_text_value", sa.Text()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(question_position=0 AND question_id='context_clarity' AND answer_type='likert' AND likert_value BETWEEN 1 AND 5 AND choice_value IS NULL AND free_text_value IS NULL) OR (question_position=1 AND question_id='attention_priority' AND answer_type='single_choice' AND choice_value IN ('evidence','process','timing','impact') AND likert_value IS NULL AND free_text_value IS NULL) OR (question_position=2 AND question_id='unanswered_question' AND answer_type='free_text' AND length(btrim(free_text_value)) BETWEEN 1 AND 2000 AND choice_value IS NULL AND likert_value IS NULL)",
            name="ck_research_survey_answers_shape",
        ),
    )


def downgrade() -> None:
    op.drop_table("research_survey_answers")
    op.drop_index("ix_research_survey_trials_status_created", table_name="research_survey_trials")
    op.drop_table("research_survey_trials")
    op.drop_index("ix_research_surveys_created", table_name="research_surveys")
    op.drop_table("research_surveys")
    op.drop_constraint(
        "ck_simulation_worker_survey_config", "simulation_worker_heartbeats", type_="check"
    )
    op.execute(
        "UPDATE simulation_worker_heartbeats SET survey_runtime_ready=false, "
        "survey_model_name=NULL, survey_config_sha256=NULL, "
        "survey_prompt_schema_version=NULL WHERE survey_runtime_ready IS TRUE"
    )
    op.create_check_constraint(
        "ck_simulation_worker_survey_config",
        "simulation_worker_heartbeats",
        "(survey_runtime_ready AND worker_domain = 'evaluation' AND length(btrim(survey_model_name)) BETWEEN 1 AND 200 AND survey_model_name !~ E'[\\r\\n]' AND survey_config_sha256 ~ '^[a-f0-9]{64}$' AND survey_prompt_schema_version = 'matraix-survey-scenario-preference/v1') OR (NOT survey_runtime_ready AND survey_model_name IS NULL AND survey_config_sha256 IS NULL AND survey_prompt_schema_version IS NULL)",
    )
