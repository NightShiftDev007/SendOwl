"""Add single-run research projects without ADC comparison semantics.

Revision ID: 20260816_core_0044
Revises: 20260816_core_0043
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0044"
down_revision: str | None = "20260816_core_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("simulation_requirement", sa.Text(), nullable=False),
        sa.Column("project_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300",
            name="ck_research_projects_title",
        ),
        sa.CheckConstraint(
            "length(btrim(research_question)) BETWEEN 1 AND 2000",
            name="ck_research_projects_question",
        ),
        sa.CheckConstraint(
            "length(btrim(simulation_requirement)) BETWEEN 1 AND 4000",
            name="ck_research_projects_requirement",
        ),
        sa.CheckConstraint(
            "persona_count BETWEEN 1 AND 100",
            name="ck_research_projects_personas",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND "
            "project_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_projects_digests",
        ),
        sa.ForeignKeyConstraint(["world_model_id"], ["world_models.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["world_snapshot_id"], ["world_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_sha256", name="uq_research_projects_sha256"),
    )
    op.create_index(
        "ix_research_projects_created_at",
        "research_projects",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "research_simulation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_sha256", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("run_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "seed BETWEEN 0 AND 2147483647",
            name="ck_research_runs_seed",
        ),
        sa.CheckConstraint(
            "engine = 'camel-oasis' AND engine_version = '0.2.5'",
            name="ck_research_runs_engine",
        ),
        sa.CheckConstraint("status = 'configured'", name="ck_research_runs_status"),
        sa.CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' AND run_spec_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_runs_digests",
        ),
        sa.ForeignKeyConstraint(
            ["research_project_id"], ["research_projects.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_runs_project_created",
        "research_simulation_runs",
        ["research_project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_research_runs_spec_sha256",
        "research_simulation_runs",
        ["run_spec_sha256"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_research_project_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'sealed research projects are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_projects_immutable
        BEFORE UPDATE OR DELETE ON research_projects
        FOR EACH ROW EXECUTE FUNCTION reject_research_project_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_projects_no_truncate
        BEFORE TRUNCATE ON research_projects
        FOR EACH STATEMENT EXECUTE FUNCTION reject_research_project_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER research_projects_no_truncate ON research_projects")
    op.execute("DROP TRIGGER research_projects_immutable ON research_projects")
    op.execute("DROP FUNCTION reject_research_project_mutation()")
    op.drop_index("ix_research_runs_spec_sha256", table_name="research_simulation_runs")
    op.drop_index("ix_research_runs_project_created", table_name="research_simulation_runs")
    op.drop_table("research_simulation_runs")
    op.drop_index("ix_research_projects_created_at", table_name="research_projects")
    op.drop_table("research_projects")
