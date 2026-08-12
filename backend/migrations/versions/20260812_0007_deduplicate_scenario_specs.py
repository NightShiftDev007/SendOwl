"""Make immutable scenario creation idempotent by canonical content address.

Revision ID: 20260812_0007
Revises: 20260812_0006
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260812_0007"
down_revision: str | None = "20260812_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reject ambiguous adoption and enforce one resource per canonical spec."""
    op.execute("LOCK TABLE scenarios IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_digests text;
        BEGIN
            SELECT string_agg(scenario_sha256, ', ' ORDER BY scenario_sha256)
            INTO duplicate_digests
            FROM (
                SELECT scenario_sha256
                FROM scenarios
                GROUP BY scenario_sha256
                HAVING count(*) > 1
            ) AS duplicates;

            IF duplicate_digests IS NOT NULL THEN
                RAISE EXCEPTION
                    'cannot make scenario specs idempotent; duplicate scenario_sha256 values: %',
                    duplicate_digests
                    USING ERRCODE = '23505';
            END IF;
        END;
        $$
        """
    )
    op.create_unique_constraint(
        "uq_scenarios_sha256",
        "scenarios",
        ["scenario_sha256"],
    )


def downgrade() -> None:
    """Remove canonical-spec deduplication without changing scenario content."""
    op.drop_constraint("uq_scenarios_sha256", "scenarios", type_="unique")
