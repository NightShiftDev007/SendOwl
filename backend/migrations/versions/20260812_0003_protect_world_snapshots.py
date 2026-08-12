"""Reject mutation of frozen world-snapshot content at the database boundary.

Revision ID: 20260812_0003
Revises: 20260812_0002
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260812_0003"
down_revision: str | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FROZEN_TABLES: tuple[str, ...] = (
    "world_snapshots",
    "world_snapshot_evidence",
    "world_snapshot_mentions",
)


def upgrade() -> None:
    """Install one explicit append-only guard on every frozen snapshot table."""
    op.execute(
        """
        CREATE FUNCTION reject_world_snapshot_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'world snapshot table % is append-only; UPDATE and DELETE are forbidden',
                TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in FROZEN_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_world_snapshot_mutation()
            """
        )


def downgrade() -> None:
    """Remove guards before the preceding revision drops snapshot tables."""
    for table_name in reversed(FROZEN_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION reject_world_snapshot_mutation()")
