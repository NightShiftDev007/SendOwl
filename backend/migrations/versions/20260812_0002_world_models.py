"""Create persistent world models and append-only content-addressed snapshots.

Revision ID: 20260812_0002
Revises: 20260812_0001
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0002"
down_revision: str | None = "20260812_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable snapshot storage without changing imported media tables."""
    op.create_table(
        "world_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(btrim(title)) > 0", name="ck_world_models_title"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_world_models_created_at",
        "world_models",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_world_models_company",
        "world_models",
        ["company_id"],
        unique=False,
    )

    op.create_table(
        "world_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verification", sa.String(length=32), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_canonical_name", sa.String(length=300), nullable=False),
        sa.Column("company_aliases", postgresql.ARRAY(sa.String(length=300)), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_world_snapshots_version"),
        sa.CheckConstraint(
            "verification = 'human_confirmed'",
            name="ck_world_snapshots_verification",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_world_snapshots_sha256",
        ),
        sa.CheckConstraint(
            "length(btrim(company_canonical_name)) > 0",
            name="ck_world_snapshots_company_name",
        ),
        sa.ForeignKeyConstraint(["world_model_id"], ["world_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "world_model_id",
            "version",
            name="uq_world_snapshots_model_version",
        ),
    )
    op.create_index(
        "ix_world_snapshots_model_version",
        "world_snapshots",
        ["world_model_id", "version"],
        unique=False,
    )

    op.create_table(
        "world_snapshot_evidence",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("original_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("captured_text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("excerpt", sa.String(length=280), nullable=False),
        sa.Column("captured_text_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_world_snapshot_evidence_position"),
        sa.CheckConstraint(
            "length(btrim(source_name)) > 0",
            name="ck_world_snapshot_evidence_source_name",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_world_snapshot_evidence_title",
        ),
        sa.CheckConstraint(
            "length(btrim(excerpt)) BETWEEN 1 AND 280",
            name="ck_world_snapshot_evidence_excerpt",
        ),
        sa.CheckConstraint(
            "captured_text_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_world_snapshot_evidence_sha256",
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["world_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("snapshot_id", "position"),
        sa.UniqueConstraint(
            "snapshot_id",
            "article_id",
            name="uq_world_snapshot_evidence_article",
        ),
    )
    op.create_index(
        "ix_world_snapshot_evidence_article",
        "world_snapshot_evidence",
        ["article_id"],
        unique=False,
    )

    op.create_table(
        "world_snapshot_mentions",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_position", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=300), nullable=False),
        sa.Column("surface_form", sa.String(length=300), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "evidence_position >= 0",
            name="ck_world_snapshot_mentions_evidence",
        ),
        sa.CheckConstraint("position >= 0", name="ck_world_snapshot_mentions_position"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset",
            name="ck_world_snapshot_mentions_offsets",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "evidence_position"],
            ["world_snapshot_evidence.snapshot_id", "world_snapshot_evidence.position"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("snapshot_id", "evidence_position", "position"),
    )


def downgrade() -> None:
    """Remove world-model storage in reverse dependency order."""
    op.drop_table("world_snapshot_mentions")
    op.drop_index("ix_world_snapshot_evidence_article", table_name="world_snapshot_evidence")
    op.drop_table("world_snapshot_evidence")
    op.drop_index("ix_world_snapshots_model_version", table_name="world_snapshots")
    op.drop_table("world_snapshots")
    op.drop_index("ix_world_models_company", table_name="world_models")
    op.drop_index("ix_world_models_created_at", table_name="world_models")
    op.drop_table("world_models")
