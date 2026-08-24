"""Add immutable Project-bound Chat and Web evaluation targets.

Revision ID: 20260818_core_0057
Revises: 20260818_core_0056
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0057"
down_revision: str | None = "20260818_core_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_evaluation_targets",
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
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('chat','web')",
            name="ck_research_evaluation_targets_kind",
        ),
        sa.CheckConstraint(
            "schema_version='sandowl-research-evaluation-target/v1'",
            name="ck_research_evaluation_targets_schema",
        ),
        sa.CheckConstraint(
            "target_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_evaluation_targets_digest",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json)='object'",
            name="ck_research_evaluation_targets_payload",
        ),
        sa.CheckConstraint(
            "sealed_at >= created_at",
            name="ck_research_evaluation_targets_sealed_time",
        ),
        sa.UniqueConstraint(
            "research_simulation_run_id",
            "kind",
            name="uq_research_evaluation_targets_run_kind",
        ),
    )
    op.create_index(
        "ix_research_evaluation_targets_project",
        "research_evaluation_targets",
        ["research_project_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_research_evaluation_target_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Research Evaluation targets are immutable'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_evaluation_target_immutable
        BEFORE UPDATE OR DELETE ON research_evaluation_targets
        FOR EACH ROW EXECUTE FUNCTION reject_research_evaluation_target_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS research_evaluation_target_immutable ON research_evaluation_targets"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_research_evaluation_target_mutation()")
    op.drop_index(
        "ix_research_evaluation_targets_project",
        table_name="research_evaluation_targets",
    )
    op.drop_table("research_evaluation_targets")
