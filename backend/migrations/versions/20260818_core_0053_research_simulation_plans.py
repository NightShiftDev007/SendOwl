"""Add immutable native simulation plans and longer event schedules.

Revision ID: 20260818_core_0053
Revises: 20260818_core_0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0053"
down_revision: str | None = "20260818_core_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN_V1 = "sandowl-research-simulation-run/v1"
RUN_V2 = "sandowl-research-simulation-run/v2"
RUN_V3 = "sandowl-research-simulation-run/v3"
RUN_V4 = "sandowl-research-simulation-run/v4"


def upgrade() -> None:
    op.add_column(
        "research_simulation_runs",
        sa.Column("simulation_plan", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "research_simulation_runs",
        sa.Column("simulation_plan_sha256", sa.String(length=64)),
    )
    op.drop_constraint("ck_research_runs_context_shape", "research_simulation_runs", type_="check")
    op.drop_constraint("ck_research_runs_schema_version", "research_simulation_runs", type_="check")
    op.create_check_constraint(
        "ck_research_runs_schema_version",
        "research_simulation_runs",
        f"schema_version IN ('{RUN_V1}', '{RUN_V2}', '{RUN_V3}', '{RUN_V4}')",
    )
    op.create_check_constraint(
        "ck_research_runs_context_shape",
        "research_simulation_runs",
        f"(schema_version IN ('{RUN_V1}', '{RUN_V2}') "
        "AND simulation_context IS NULL AND simulation_context_sha256 IS NULL "
        "AND simulation_plan IS NULL AND simulation_plan_sha256 IS NULL) OR "
        f"(schema_version = '{RUN_V3}' AND jsonb_typeof(simulation_context) = 'object' "
        "AND simulation_context_sha256 ~ '^[a-f0-9]{64}$' "
        "AND simulation_plan IS NULL AND simulation_plan_sha256 IS NULL) OR "
        f"(schema_version = '{RUN_V4}' AND jsonb_typeof(simulation_context) = 'object' "
        "AND simulation_context_sha256 ~ '^[a-f0-9]{64}$' "
        "AND jsonb_typeof(simulation_plan) = 'object' "
        "AND simulation_plan_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.drop_constraint("ck_research_run_events_round", "research_run_events", type_="check")
    op.create_check_constraint(
        "ck_research_run_events_round",
        "research_run_events",
        "round BETWEEN 1 AND 6",
    )
    op.drop_constraint(
        "ck_research_runs_execution_input", "research_simulation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_research_runs_execution_input",
        "research_simulation_runs",
        "status = 'configured' OR (rounds BETWEEN 1 AND 6 "
        "AND minutes_per_round BETWEEN 15 AND 480 "
        "AND length(btrim(initial_post)) BETWEEN 1 AND 4000 "
        "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND prompt_schema_version = 'matraix-semantic-profile/v1')",
    )
    op.create_table(
        "research_run_graph_memory",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("previous_sha256", sa.String(length=64)),
        sa.Column("memory", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("memory_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("round BETWEEN 1 AND 6", name="ck_research_graph_memory_round"),
        sa.CheckConstraint(
            "(round = 1 AND previous_sha256 IS NULL) OR "
            "(round > 1 AND previous_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_research_graph_memory_previous",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(memory) = 'object' AND memory_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_graph_memory_shape",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "round"),
        sa.UniqueConstraint("memory_sha256", name="uq_research_graph_memory_sha256"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_research_run_graph_memory_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'research run graph memory is append-only' USING ERRCODE='55000';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER research_run_graph_memory_immutable "
        "BEFORE UPDATE OR DELETE ON research_run_graph_memory "
        "FOR EACH ROW EXECUTE FUNCTION reject_research_run_graph_memory_mutation()"
    )
    op.create_table(
        "research_run_persona_interviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_simulation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("graph_memory_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_position", sa.Integer(), nullable=False),
        sa.Column("persona_external_id", sa.String(length=128), nullable=False),
        sa.Column("persona_display_name", sa.String(length=200), nullable=False),
        sa.Column("persona_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("interview_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_worker_id", sa.String(length=128)),
        sa.Column("answer_markdown", sa.Text()),
        sa.Column("citations_json", sa.Text()),
        sa.Column("answer_sha256", sa.String(length=64)),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.String(length=500)),
        sa.CheckConstraint(
            "persona_position BETWEEN 0 AND 7", name="ck_research_interviews_position"
        ),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_research_interviews_question",
        ),
        sa.CheckConstraint(
            "length(source_text) BETWEEN 1 AND 80000", name="ck_research_interviews_source"
        ),
        sa.CheckConstraint(
            "run_spec_sha256 ~ '^[a-f0-9]{64}$' AND "
            "graph_memory_sha256 ~ '^[a-f0-9]{64}$' AND "
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND "
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$' AND "
            "source_sha256 ~ '^[a-f0-9]{64}$' AND "
            "interview_sha256 ~ '^[a-f0-9]{64}$' AND "
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_interviews_digests",
        ),
        sa.CheckConstraint(
            "prompt_schema_version='sandowl-run-persona-interview/v1'",
            name="ck_research_interviews_schema",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_research_interviews_status",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_research_interviews_started",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_research_interviews_completed",
        ),
        sa.CheckConstraint(
            "(status='queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL "
            "AND length(answer_markdown) BETWEEN 1 AND 2000 "
            "AND length(citations_json) >= 3 AND answer_sha256 ~ '^[a-f0-9]{64}$' "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND citations_json IS NULL AND answer_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_research_interviews_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["research_project_id"], ["research_projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_simulation_run_id"],
            ["research_simulation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("interview_sha256", name="uq_research_interviews_sha256"),
    )
    op.create_index(
        "ix_research_interviews_run_created",
        "research_run_persona_interviews",
        ["research_simulation_run_id", "created_at"],
    )
    op.create_table(
        "research_run_persona_interview_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_simulation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("graph_memory_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("session_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "persona_count BETWEEN 2 AND 8", name="ck_research_interview_sessions_count"
        ),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_research_interview_sessions_question",
        ),
        sa.CheckConstraint(
            "run_spec_sha256 ~ '^[a-f0-9]{64}$' AND "
            "graph_memory_sha256 ~ '^[a-f0-9]{64}$' AND "
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND "
            "session_sha256 ~ '^[a-f0-9]{64}$' AND "
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_interview_sessions_digests",
        ),
        sa.CheckConstraint(
            "prompt_schema_version='sandowl-run-persona-interview-session/v1'",
            name="ck_research_interview_sessions_schema",
        ),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_research_interview_sessions_sealed",
        ),
        sa.ForeignKeyConstraint(
            ["research_project_id"], ["research_projects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["research_simulation_run_id"],
            ["research_simulation_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_sha256", name="uq_research_interview_sessions_sha256"),
    )
    op.create_index(
        "ix_research_interview_sessions_run_created",
        "research_run_persona_interview_sessions",
        ["research_simulation_run_id", "created_at"],
    )
    op.create_table(
        "research_run_persona_interview_session_members",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 7",
            name="ck_research_interview_session_members_position",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["research_run_persona_interview_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["interview_id"],
            ["research_run_persona_interviews.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("session_id", "position"),
        sa.UniqueConstraint(
            "session_id", "persona_id", name="uq_research_interview_session_persona"
        ),
        sa.UniqueConstraint(
            "session_id", "interview_id", name="uq_research_interview_session_interview"
        ),
    )


def downgrade() -> None:
    op.drop_table("research_run_persona_interview_session_members")
    op.drop_index(
        "ix_research_interview_sessions_run_created",
        table_name="research_run_persona_interview_sessions",
    )
    op.drop_table("research_run_persona_interview_sessions")
    op.drop_index(
        "ix_research_interviews_run_created",
        table_name="research_run_persona_interviews",
    )
    op.drop_table("research_run_persona_interviews")
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM research_simulation_runs WHERE schema_version = '{RUN_V4}'
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while planned research runs exist';
            END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER research_run_graph_memory_immutable ON research_run_graph_memory")
    op.execute("DROP FUNCTION reject_research_run_graph_memory_mutation()")
    op.drop_table("research_run_graph_memory")
    op.drop_constraint(
        "ck_research_runs_execution_input", "research_simulation_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_research_runs_execution_input",
        "research_simulation_runs",
        "status = 'configured' OR (rounds BETWEEN 1 AND 3 "
        "AND minutes_per_round BETWEEN 15 AND 240 "
        "AND length(btrim(initial_post)) BETWEEN 1 AND 4000 "
        "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND prompt_schema_version = 'matraix-semantic-profile/v1')",
    )
    op.drop_constraint("ck_research_run_events_round", "research_run_events", type_="check")
    op.create_check_constraint(
        "ck_research_run_events_round",
        "research_run_events",
        "round BETWEEN 1 AND 3",
    )
    op.drop_constraint("ck_research_runs_context_shape", "research_simulation_runs", type_="check")
    op.drop_constraint("ck_research_runs_schema_version", "research_simulation_runs", type_="check")
    op.create_check_constraint(
        "ck_research_runs_schema_version",
        "research_simulation_runs",
        f"schema_version IN ('{RUN_V1}', '{RUN_V2}', '{RUN_V3}')",
    )
    op.create_check_constraint(
        "ck_research_runs_context_shape",
        "research_simulation_runs",
        f"(schema_version IN ('{RUN_V1}', '{RUN_V2}') "
        "AND simulation_context IS NULL AND simulation_context_sha256 IS NULL) OR "
        f"(schema_version = '{RUN_V3}' AND jsonb_typeof(simulation_context) = 'object' "
        "AND simulation_context_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.drop_column("research_simulation_runs", "simulation_plan_sha256")
    op.drop_column("research_simulation_runs", "simulation_plan")
