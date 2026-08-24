"""Separate Project / Graph context from one simulation-run design.

Revision ID: 20260816_core_0046
Revises: 20260816_core_0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0046"
down_revision: str | None = "20260816_core_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_V1 = "sandowl-research-project/v1"
PROJECT_V2 = "sandowl-research-project/v2"
RUN_V1 = "sandowl-research-simulation-run/v1"
RUN_V2 = "sandowl-research-simulation-run/v2"


def upgrade() -> None:
    op.add_column(
        "research_projects",
        sa.Column(
            "schema_version",
            sa.String(length=64),
            nullable=False,
            server_default=PROJECT_V1,
        ),
    )
    op.drop_constraint("ck_research_projects_requirement", "research_projects", type_="check")
    op.drop_constraint("ck_research_projects_personas", "research_projects", type_="check")
    op.drop_constraint("ck_research_projects_digests", "research_projects", type_="check")
    for column in ("cohort_id", "cohort_sha256", "persona_count", "simulation_requirement"):
        op.alter_column("research_projects", column, nullable=True)
    op.create_check_constraint(
        "ck_research_projects_digests",
        "research_projects",
        "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND project_sha256 ~ '^[a-f0-9]{64}$'",
    )
    op.create_check_constraint(
        "ck_research_projects_schema_shape",
        "research_projects",
        f"(schema_version = '{PROJECT_V1}' "
        "AND cohort_id IS NOT NULL AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
        "AND persona_count BETWEEN 1 AND 100 "
        "AND length(btrim(simulation_requirement)) BETWEEN 1 AND 4000) OR "
        f"(schema_version = '{PROJECT_V2}' "
        "AND cohort_id IS NULL AND cohort_sha256 IS NULL "
        "AND persona_count IS NULL AND simulation_requirement IS NULL)",
    )
    op.alter_column("research_projects", "schema_version", server_default=None)

    op.add_column(
        "research_simulation_runs",
        sa.Column("schema_version", sa.String(length=64), nullable=False, server_default=RUN_V1),
    )
    op.add_column(
        "research_simulation_runs",
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("research_simulation_runs", sa.Column("cohort_sha256", sa.String(length=64)))
    op.add_column("research_simulation_runs", sa.Column("persona_count", sa.Integer()))
    op.add_column("research_simulation_runs", sa.Column("simulation_requirement", sa.Text()))
    op.execute(
        """
        UPDATE research_simulation_runs AS run
        SET cohort_id = project.cohort_id,
            cohort_sha256 = project.cohort_sha256,
            persona_count = project.persona_count,
            simulation_requirement = project.simulation_requirement
        FROM research_projects AS project
        WHERE project.id = run.research_project_id
        """
    )
    for column in ("cohort_id", "cohort_sha256", "persona_count", "simulation_requirement"):
        op.alter_column("research_simulation_runs", column, nullable=False)
    op.create_foreign_key(
        "fk_research_runs_cohort",
        "research_simulation_runs",
        "cohorts",
        ["cohort_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_research_runs_schema_version",
        "research_simulation_runs",
        f"schema_version IN ('{RUN_V1}', '{RUN_V2}')",
    )
    op.create_check_constraint(
        "ck_research_runs_design",
        "research_simulation_runs",
        "cohort_sha256 ~ '^[a-f0-9]{64}$' AND persona_count BETWEEN 1 AND 100 "
        "AND length(btrim(simulation_requirement)) BETWEEN 1 AND 4000",
    )
    op.alter_column("research_simulation_runs", "schema_version", server_default=None)


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM research_projects WHERE schema_version = '{PROJECT_V2}')
               OR EXISTS (SELECT 1 FROM research_simulation_runs WHERE schema_version = '{RUN_V2}')
            THEN
                RAISE EXCEPTION 'cannot downgrade while v2 research projects or runs exist';
            END IF;
        END;
        $$
        """
    )
    op.drop_constraint("ck_research_runs_design", "research_simulation_runs", type_="check")
    op.drop_constraint("ck_research_runs_schema_version", "research_simulation_runs", type_="check")
    op.drop_constraint("fk_research_runs_cohort", "research_simulation_runs", type_="foreignkey")
    for column in (
        "simulation_requirement",
        "persona_count",
        "cohort_sha256",
        "cohort_id",
        "schema_version",
    ):
        op.drop_column("research_simulation_runs", column)

    op.drop_constraint("ck_research_projects_schema_shape", "research_projects", type_="check")
    op.drop_constraint("ck_research_projects_digests", "research_projects", type_="check")
    for column in ("cohort_id", "cohort_sha256", "persona_count", "simulation_requirement"):
        op.alter_column("research_projects", column, nullable=False)
    op.drop_column("research_projects", "schema_version")
    op.create_check_constraint(
        "ck_research_projects_requirement",
        "research_projects",
        "length(btrim(simulation_requirement)) BETWEEN 1 AND 4000",
    )
    op.create_check_constraint(
        "ck_research_projects_personas",
        "research_projects",
        "persona_count BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        "ck_research_projects_digests",
        "research_projects",
        "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
        "cohort_sha256 ~ '^[a-f0-9]{64}$' AND project_sha256 ~ '^[a-f0-9]{64}$'",
    )
