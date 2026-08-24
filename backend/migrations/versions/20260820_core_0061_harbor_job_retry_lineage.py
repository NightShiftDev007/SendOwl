"""Add immutable retry lineage to Harbor evaluation jobs.

Revision ID: 20260820_core_0061
Revises: 20260818_core_0060
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_core_0061"
down_revision: str | None = "20260818_core_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_evaluation_jobs",
        sa.Column("retry_of_job_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "research_evaluation_jobs",
        sa.Column("retry_of_job_sha256", sa.String(64)),
    )
    op.add_column(
        "research_evaluation_jobs",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        "fk_research_evaluation_jobs_retry_parent",
        "research_evaluation_jobs",
        "research_evaluation_jobs",
        ["retry_of_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_research_evaluation_job_retry_parent",
        "research_evaluation_jobs",
        ["retry_of_job_id"],
    )
    op.create_check_constraint(
        "ck_research_evaluation_jobs_retry_lineage",
        "research_evaluation_jobs",
        "(attempt_number=1 AND retry_of_job_id IS NULL "
        "AND retry_of_job_sha256 IS NULL) OR "
        "(attempt_number BETWEEN 2 AND 5 AND retry_of_job_id IS NOT NULL "
        "AND retry_of_job_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_index(
        "ix_research_evaluation_jobs_target_attempt",
        "research_evaluation_jobs",
        ["target_id", "attempt_number"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_research_evaluation_job_identity()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Harbor evaluation Job DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            IF (NEW.research_project_id, NEW.research_simulation_run_id,
                NEW.cohort_id, NEW.target_id, NEW.kind, NEW.job_sha256,
                NEW.retry_of_job_id, NEW.retry_of_job_sha256,
                NEW.attempt_number, NEW.created_at)
               IS DISTINCT FROM
               (OLD.research_project_id, OLD.research_simulation_run_id,
                OLD.cohort_id, OLD.target_id, OLD.kind, OLD.job_sha256,
                OLD.retry_of_job_id, OLD.retry_of_job_sha256,
                OLD.attempt_number, OLD.created_at) THEN
                RAISE EXCEPTION 'Harbor evaluation Job identity is immutable'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_evaluation_job_identity_guard
        BEFORE UPDATE OR DELETE ON research_evaluation_jobs
        FOR EACH ROW EXECUTE FUNCTION protect_research_evaluation_job_identity()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER research_evaluation_job_identity_guard ON research_evaluation_jobs")
    op.execute("DROP FUNCTION protect_research_evaluation_job_identity()")
    op.drop_index(
        "ix_research_evaluation_jobs_target_attempt",
        table_name="research_evaluation_jobs",
    )
    op.drop_constraint(
        "ck_research_evaluation_jobs_retry_lineage",
        "research_evaluation_jobs",
        type_="check",
    )
    op.drop_constraint(
        "uq_research_evaluation_job_retry_parent",
        "research_evaluation_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_research_evaluation_jobs_retry_parent",
        "research_evaluation_jobs",
        type_="foreignkey",
    )
    op.drop_column("research_evaluation_jobs", "attempt_number")
    op.drop_column("research_evaluation_jobs", "retry_of_job_sha256")
    op.drop_column("research_evaluation_jobs", "retry_of_job_id")
