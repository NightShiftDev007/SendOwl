"""Add App targets and durable Harbor evaluation jobs.

Revision ID: 20260818_core_0059
Revises: 20260818_core_0058
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0059"
down_revision: str | None = "20260818_core_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_research_evaluation_targets_kind",
        "research_evaluation_targets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_research_evaluation_targets_kind",
        "research_evaluation_targets",
        "kind IN ('chat','web','app')",
    )
    op.create_table(
        "research_evaluation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_projects.id"),
            nullable=False,
        ),
        sa.Column(
            "research_simulation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_simulation_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "cohort_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cohorts.id"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_evaluation_targets.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("job_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("remote_run_id", sa.String(128)),
        sa.Column("trajectory_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("trajectory_sha256", sa.String(64)),
        sa.Column("artifact_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("artifact_sha256", sa.String(64)),
        sa.Column("verifier_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("verifier_sha256", sa.String(64)),
        sa.Column("reward_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("reward_sha256", sa.String(64)),
        sa.Column("reward_value", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "kind IN ('chat','web','app')",
            name="ck_research_evaluation_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued','dispatching','running','succeeded','failed','cancelled')",
            name="ck_research_evaluation_jobs_status",
        ),
        sa.CheckConstraint(
            "job_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_evaluation_jobs_digest",
        ),
        sa.CheckConstraint(
            "reward_value IS NULL OR (reward_value >= 0 AND reward_value <= 1)",
            name="ck_research_evaluation_jobs_reward",
        ),
    )
    op.create_index(
        "ix_research_evaluation_jobs_status_created",
        "research_evaluation_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_evaluation_jobs_status_created",
        table_name="research_evaluation_jobs",
    )
    op.drop_table("research_evaluation_jobs")
    op.drop_constraint(
        "ck_research_evaluation_targets_kind",
        "research_evaluation_targets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_research_evaluation_targets_kind",
        "research_evaluation_targets",
        "kind IN ('chat','web')",
    )
