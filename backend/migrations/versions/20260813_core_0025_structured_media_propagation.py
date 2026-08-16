"""Bind media propagation edges to AgendaScope structured followers.

Revision ID: 20260813_core_0025
Revises: 20260813_core_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0025"
down_revision: str | None = "20260813_core_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_propagation_edges",
        sa.Column("source_follower_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "media_propagation_edges",
        sa.Column("follower_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "media_propagation_edges",
        sa.Column(
            "observation_source",
            sa.String(length=24),
            nullable=False,
            server_default="legacy_projection",
        ),
    )
    op.create_foreign_key(
        "fk_media_propagation_edge_follower_source",
        "media_propagation_edges",
        "media_sources",
        ["follower_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "uq_media_propagation_event_country",
        "media_propagation_edges",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_media_propagation_source_follower",
        "media_propagation_edges",
        ["event_id", "source_follower_id"],
    )
    op.create_check_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        "(observation_source='legacy_projection' AND source_follower_id IS NULL) OR "
        "(observation_source='structured_followers' AND source_follower_id IS NOT NULL "
        "AND follower_source_id IS NOT NULL)",
    )
    op.create_index(
        "ix_media_propagation_edges_follower_source",
        "media_propagation_edges",
        ["follower_source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_propagation_edges_follower_source",
        table_name="media_propagation_edges",
    )
    op.drop_constraint(
        "ck_media_propagation_edge_observation_source",
        "media_propagation_edges",
        type_="check",
    )
    op.drop_constraint(
        "uq_media_propagation_source_follower",
        "media_propagation_edges",
        type_="unique",
    )
    op.execute(
        """
        DELETE FROM media_propagation_edges AS later
        USING media_propagation_edges AS earlier
        WHERE later.event_id=earlier.event_id
          AND later.to_country_code=earlier.to_country_code
          AND (later.position, later.source_follower_id)
              > (earlier.position, earlier.source_follower_id)
        """
    )
    op.create_unique_constraint(
        "uq_media_propagation_event_country",
        "media_propagation_edges",
        ["event_id", "to_country_code"],
    )
    op.drop_constraint(
        "fk_media_propagation_edge_follower_source",
        "media_propagation_edges",
        type_="foreignkey",
    )
    op.drop_column("media_propagation_edges", "observation_source")
    op.drop_column("media_propagation_edges", "follower_source_id")
    op.drop_column("media_propagation_edges", "source_follower_id")
