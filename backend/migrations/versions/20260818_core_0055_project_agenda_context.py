"""Freeze AgendaScope topic context into native research projects.

Revision ID: 20260818_core_0055
Revises: 20260818_core_0054
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_core_0055"
down_revision: str | None = "20260818_core_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_project_agenda_contexts",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("project_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "source_sync_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_sync_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("source_observed_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "schema_version='sandowl-project-agenda-context/v1'",
            name="ck_research_project_agenda_context_schema",
        ),
        sa.CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' AND context_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_project_agenda_context_digests",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json)='object'",
            name="ck_research_project_agenda_context_payload",
        ),
    )
    op.create_index(
        "ix_research_project_agenda_context_captured",
        "research_project_agenda_contexts",
        ["captured_at"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_research_project_agenda_context_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Research Project Agenda contexts are immutable'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER research_project_agenda_context_immutable
        BEFORE UPDATE OR DELETE ON research_project_agenda_contexts
        FOR EACH ROW EXECUTE FUNCTION reject_research_project_agenda_context_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS research_project_agenda_context_immutable "
        "ON research_project_agenda_contexts"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_research_project_agenda_context_mutation()")
    op.drop_index(
        "ix_research_project_agenda_context_captured",
        table_name="research_project_agenda_contexts",
    )
    op.drop_table("research_project_agenda_contexts")
