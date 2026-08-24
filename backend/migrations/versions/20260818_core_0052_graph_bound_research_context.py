"""Bind native research projects and runs to immutable semantic context.

Revision ID: 20260818_core_0052
Revises: 20260817_core_0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0052"
down_revision: str | None = "20260817_core_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_V1 = "sandowl-research-project/v1"
PROJECT_V2 = "sandowl-research-project/v2"
PROJECT_V3 = "sandowl-research-project/v3"
RUN_V1 = "sandowl-research-simulation-run/v1"
RUN_V2 = "sandowl-research-simulation-run/v2"
RUN_V3 = "sandowl-research-simulation-run/v3"


def upgrade() -> None:
    op.add_column(
        "research_projects",
        sa.Column("world_graph_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("research_projects", sa.Column("graph_sha256", sa.String(length=64)))
    op.add_column("research_projects", sa.Column("graph_node_count", sa.Integer()))
    op.add_column("research_projects", sa.Column("graph_edge_count", sa.Integer()))
    op.create_foreign_key(
        "fk_research_projects_world_graph",
        "research_projects",
        "semantic_world_graphs",
        ["world_graph_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_research_projects_schema_shape", "research_projects", type_="check")
    op.create_check_constraint(
        "ck_research_projects_schema_shape",
        "research_projects",
        f"(schema_version = '{PROJECT_V1}' "
        "AND cohort_id IS NOT NULL AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
        "AND persona_count BETWEEN 1 AND 100 "
        "AND length(btrim(simulation_requirement)) BETWEEN 1 AND 4000 "
        "AND world_graph_id IS NULL AND graph_sha256 IS NULL "
        "AND graph_node_count IS NULL AND graph_edge_count IS NULL) OR "
        f"(schema_version = '{PROJECT_V2}' "
        "AND cohort_id IS NULL AND cohort_sha256 IS NULL "
        "AND persona_count IS NULL AND simulation_requirement IS NULL "
        "AND world_graph_id IS NULL AND graph_sha256 IS NULL "
        "AND graph_node_count IS NULL AND graph_edge_count IS NULL) OR "
        f"(schema_version = '{PROJECT_V3}' "
        "AND cohort_id IS NULL AND cohort_sha256 IS NULL "
        "AND persona_count IS NULL AND simulation_requirement IS NULL "
        "AND world_graph_id IS NOT NULL AND graph_sha256 ~ '^[a-f0-9]{64}$' "
        "AND graph_node_count BETWEEN 1 AND 500 "
        "AND graph_edge_count BETWEEN 0 AND 2000)",
    )

    op.add_column(
        "research_simulation_runs",
        sa.Column("simulation_context", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "research_simulation_runs",
        sa.Column("simulation_context_sha256", sa.String(length=64)),
    )
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


def downgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM research_projects WHERE schema_version = '{PROJECT_V3}')
               OR EXISTS (
                   SELECT 1 FROM research_simulation_runs WHERE schema_version = '{RUN_V3}'
               ) THEN
                RAISE EXCEPTION 'cannot downgrade while graph-bound research resources exist';
            END IF;
        END $$
        """
    )
    op.drop_constraint("ck_research_runs_context_shape", "research_simulation_runs", type_="check")
    op.drop_constraint("ck_research_runs_schema_version", "research_simulation_runs", type_="check")
    op.create_check_constraint(
        "ck_research_runs_schema_version",
        "research_simulation_runs",
        f"schema_version IN ('{RUN_V1}', '{RUN_V2}')",
    )
    op.drop_column("research_simulation_runs", "simulation_context_sha256")
    op.drop_column("research_simulation_runs", "simulation_context")

    op.drop_constraint("ck_research_projects_schema_shape", "research_projects", type_="check")
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
    op.drop_constraint("fk_research_projects_world_graph", "research_projects", type_="foreignkey")
    op.drop_column("research_projects", "graph_edge_count")
    op.drop_column("research_projects", "graph_node_count")
    op.drop_column("research_projects", "graph_sha256")
    op.drop_column("research_projects", "world_graph_id")
