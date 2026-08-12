"""Seal world snapshots only after their immutable children are captured.

Revision ID: 20260812_0004
Revises: 20260812_0003
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0004"
down_revision: str | None = "20260812_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FROZEN_TABLES: tuple[str, ...] = (
    "world_snapshots",
    "world_snapshot_evidence",
    "world_snapshot_mentions",
)
CHILD_TABLES: tuple[str, ...] = (
    "world_snapshot_evidence",
    "world_snapshot_mentions",
)


def upgrade() -> None:
    """Allow transactional assembly, then permanently seal every snapshot."""
    op.add_column(
        "world_snapshots",
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Revision 0003 rejects every snapshot UPDATE, so replace its parent-row
    # trigger before sealing pre-existing immutable snapshots in place.
    op.execute("DROP TRIGGER trg_world_snapshots_append_only ON world_snapshots")
    op.execute(
        """
        UPDATE world_snapshots
        SET sealed_at = created_at
        WHERE sealed_at IS NULL
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_world_snapshot_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'world snapshot % is immutable; DELETE is forbidden',
                    OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'sealed_at') =
                   (to_jsonb(OLD) - 'sealed_at')
            THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'world snapshot % is immutable; only sealing a draft is allowed',
                OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_world_snapshots_seal_only
        BEFORE UPDATE OR DELETE ON world_snapshots
        FOR EACH ROW
        EXECUTE FUNCTION protect_world_snapshot_update_delete()
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_world_snapshot_child_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_sealed_at timestamp with time zone;
        BEGIN
            SELECT sealed_at
            INTO parent_sealed_at
            FROM world_snapshots
            WHERE id = NEW.snapshot_id
            FOR UPDATE;

            IF FOUND AND parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'world snapshot % is sealed; INSERT into % is forbidden',
                    NEW.snapshot_id,
                    TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;

            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in CHILD_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_draft_insert_only
            BEFORE INSERT ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION protect_world_snapshot_child_insert()
            """
        )

    op.execute(
        """
        CREATE FUNCTION reject_world_snapshot_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'world snapshot table % is immutable; TRUNCATE is forbidden',
                TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in FROZEN_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_world_snapshot_truncate()
            """
        )


def downgrade() -> None:
    """Remove sealing and restore revision 0003's complete append-only guards."""
    for table_name in reversed(FROZEN_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    for table_name in reversed(CHILD_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_draft_insert_only ON {table_name}")
    op.execute("DROP TRIGGER trg_world_snapshots_seal_only ON world_snapshots")
    op.execute("DROP FUNCTION reject_world_snapshot_truncate()")
    op.execute("DROP FUNCTION protect_world_snapshot_child_insert()")
    op.execute("DROP FUNCTION protect_world_snapshot_update_delete()")

    # The two child triggers and their function survived upgrade from 0003.
    # Drop them before recreating the exact three-table 0003 protection set.
    for table_name in reversed(CHILD_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
    op.execute("DROP FUNCTION reject_world_snapshot_mutation()")
    op.drop_column("world_snapshots", "sealed_at")

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
