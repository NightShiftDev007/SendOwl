"""Execute independent research runs and seal their reports.

Revision ID: 20260816_core_0045
Revises: 20260816_core_0044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0045"
down_revision: str | None = "20260816_core_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_research_runs_status", "research_simulation_runs", type_="check")
    op.add_column("research_simulation_runs", sa.Column("rounds", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("minutes_per_round", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("initial_post", sa.Text()))
    op.add_column("research_simulation_runs", sa.Column("model_name", sa.String(length=200)))
    op.add_column(
        "research_simulation_runs", sa.Column("semantic_config_sha256", sa.String(length=64))
    )
    op.add_column(
        "research_simulation_runs", sa.Column("prompt_schema_version", sa.String(length=64))
    )
    op.add_column(
        "research_simulation_runs", sa.Column("claimed_by_worker_id", sa.String(length=128))
    )
    op.add_column("research_simulation_runs", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("research_simulation_runs", sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.add_column("research_simulation_runs", sa.Column("artifact_sha256", sa.String(length=64)))
    op.add_column("research_simulation_runs", sa.Column("artifact_size_bytes", sa.BigInteger()))
    op.add_column("research_simulation_runs", sa.Column("user_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("initial_post_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("generated_post_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("comment_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("reaction_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("do_nothing_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("observed_action_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("rounds_completed", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("limitations", postgresql.ARRAY(sa.Text())))
    op.add_column("research_simulation_runs", sa.Column("error_code", sa.String(length=128)))
    op.add_column("research_simulation_runs", sa.Column("error_message", sa.Text()))
    op.create_check_constraint(
        "ck_research_runs_status",
        "research_simulation_runs",
        "status IN ('configured', 'queued', 'running', 'succeeded', 'failed')",
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
    op.create_unique_constraint(
        "uq_research_runs_spec_sha256", "research_simulation_runs", ["run_spec_sha256"]
    )

    op.create_table(
        "research_run_events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True)),
        sa.Column("agent_position", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("post_id", sa.String(length=128)),
        sa.Column("comment_id", sa.String(length=128)),
        sa.Column("target_post_id", sa.String(length=128)),
        sa.Column("observed_at_raw", sa.String(length=200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_research_run_events_sequence"),
        sa.CheckConstraint("round BETWEEN 1 AND 3", name="ck_research_run_events_round"),
        sa.ForeignKeyConstraint(["run_id"], ["research_simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "sequence"),
    )
    op.create_index(
        "ix_research_run_events_run_sequence",
        "research_run_events",
        ["run_id", "sequence"],
    )

    op.create_table(
        "research_run_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$'", name="ck_research_run_reports_sha256"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_simulation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_research_run_reports_run"),
        sa.UniqueConstraint("report_sha256", name="uq_research_run_reports_sha256"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_research_run_report_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'sealed research run reports are immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_run_reports_immutable
        BEFORE UPDATE OR DELETE ON research_run_reports
        FOR EACH ROW EXECUTE FUNCTION reject_research_run_report_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER research_run_reports_immutable ON research_run_reports")
    op.execute("DROP FUNCTION reject_research_run_report_mutation()")
    op.drop_table("research_run_reports")
    op.drop_index("ix_research_run_events_run_sequence", table_name="research_run_events")
    op.drop_table("research_run_events")
    op.drop_constraint("uq_research_runs_spec_sha256", "research_simulation_runs", type_="unique")
    op.drop_constraint(
        "ck_research_runs_execution_input", "research_simulation_runs", type_="check"
    )
    op.drop_constraint("ck_research_runs_status", "research_simulation_runs", type_="check")
    for column in (
        "error_message",
        "error_code",
        "limitations",
        "rounds_completed",
        "observed_action_count",
        "do_nothing_count",
        "reaction_count",
        "comment_count",
        "generated_post_count",
        "initial_post_count",
        "user_count",
        "artifact_size_bytes",
        "artifact_sha256",
        "completed_at",
        "started_at",
        "claimed_by_worker_id",
        "prompt_schema_version",
        "semantic_config_sha256",
        "model_name",
        "initial_post",
        "minutes_per_round",
        "rounds",
    ):
        op.drop_column("research_simulation_runs", column)
    op.create_check_constraint(
        "ck_research_runs_status", "research_simulation_runs", "status = 'configured'"
    )
