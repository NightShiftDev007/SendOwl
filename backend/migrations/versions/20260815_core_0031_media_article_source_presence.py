"""Track AgendaScope article presence without deleting frozen SendOwl evidence.

Revision ID: 20260815_core_0031
Revises: 20260815_core_0030
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260815_core_0031"
down_revision: str | None = "20260815_core_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_articles",
        sa.Column("source_present", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "media_articles",
        sa.Column("source_last_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_articles",
        sa.Column("source_absent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_media_articles_source_presence",
        "media_articles",
        "(source_present AND source_absent_at IS NULL) OR "
        "(NOT source_present AND source_absent_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_media_articles_source_observation_time",
        "media_articles",
        "source_absent_at IS NULL OR source_last_observed_at IS NULL "
        "OR source_absent_at >= source_last_observed_at",
    )
    op.create_index(
        "ix_media_articles_source_presence_published",
        "media_articles",
        ["source_present", "published_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_articles_source_presence_published",
        table_name="media_articles",
    )
    op.drop_constraint(
        "ck_media_articles_source_observation_time",
        "media_articles",
        type_="check",
    )
    op.drop_constraint(
        "ck_media_articles_source_presence",
        "media_articles",
        type_="check",
    )
    op.drop_column("media_articles", "source_absent_at")
    op.drop_column("media_articles", "source_last_observed_at")
    op.drop_column("media_articles", "source_present")
