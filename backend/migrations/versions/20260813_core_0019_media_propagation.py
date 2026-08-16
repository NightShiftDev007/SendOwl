"""Create the imported AgendaScope propagation read model.

Revision ID: 20260813_core_0019
Revises: 20260813_core_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0019"
down_revision: str | None = "20260813_core_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_propagation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("confidence", sa.String(length=12), nullable=False),
        sa.Column("origin_country_code", sa.String(length=2), nullable=False),
        sa.Column("origin_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin_confidence", sa.String(length=10), nullable=False),
        sa.Column("detection_method", sa.String(length=20), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('watching','suspected','confirmed','dismissed','revised','archived')",
            name="ck_media_propagation_event_status",
        ),
        sa.CheckConstraint(
            "confidence IN ('watching','suspected','confirmed')",
            name="ck_media_propagation_event_confidence",
        ),
        sa.CheckConstraint(
            "origin_country_code ~ '^[A-Z]{2}$'",
            name="ck_media_propagation_origin_country",
        ),
        sa.CheckConstraint(
            "origin_confidence IN ('high','medium','low')",
            name="ck_media_propagation_origin_confidence",
        ),
        sa.ForeignKeyConstraint(["topic_id"], ["media_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["origin_source_id"], ["media_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_propagation_events_origin_at",
        "media_propagation_events",
        [sa.text("origin_at DESC")],
    )
    op.create_index(
        "ix_media_propagation_events_status",
        "media_propagation_events",
        ["status"],
    )

    op.create_table(
        "media_propagation_edges",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("from_country_code", sa.String(length=2), nullable=False),
        sa.Column("to_country_code", sa.String(length=2), nullable=False),
        sa.Column("lag_hours", sa.Numeric(12, 3), nullable=False),
        sa.Column("first_media_name", sa.String(length=200), nullable=True),
        sa.Column("first_article_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("position >= 0", name="ck_media_propagation_edge_position"),
        sa.CheckConstraint(
            "from_country_code ~ '^[A-Z]{2}$' AND to_country_code ~ '^[A-Z]{2}$'",
            name="ck_media_propagation_edge_countries",
        ),
        sa.CheckConstraint("lag_hours >= 0", name="ck_media_propagation_edge_lag"),
        sa.ForeignKeyConstraint(["event_id"], ["media_propagation_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_article_id"], ["media_articles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("event_id", "position"),
        sa.UniqueConstraint(
            "event_id", "to_country_code", name="uq_media_propagation_event_country"
        ),
    )
    op.create_index(
        "ix_media_propagation_edges_destination",
        "media_propagation_edges",
        ["to_country_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_propagation_edges_destination", table_name="media_propagation_edges")
    op.drop_table("media_propagation_edges")
    op.drop_index("ix_media_propagation_events_status", table_name="media_propagation_events")
    op.drop_index("ix_media_propagation_events_origin_at", table_name="media_propagation_events")
    op.drop_table("media_propagation_events")
