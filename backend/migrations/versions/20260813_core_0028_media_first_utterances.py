"""Import evidence-bound AgendaScope first-utterance observations.

Revision ID: 20260813_core_0028
Revises: 20260813_core_0027
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0028"
down_revision: str | None = "20260813_core_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_first_utterances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_name", sa.String(length=200), nullable=False),
        sa.Column("entity_type", sa.String(length=15), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=12), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["media_topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["media_articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "entity_type IN ('person','thinktank','intl_org','gov_body')",
            name="ck_media_first_utterance_entity_type",
        ),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_media_first_utterance_country"),
        sa.CheckConstraint("confidence='high'", name="ck_media_first_utterance_confidence"),
        sa.CheckConstraint(
            "length(btrim(entity_name)) BETWEEN 1 AND 200",
            name="ck_media_first_utterance_entity_name",
        ),
        sa.CheckConstraint(
            "length(btrim(evidence_quote)) BETWEEN 1 AND 2000",
            name="ck_media_first_utterance_quote",
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND "
            "length(btrim(prompt_version)) BETWEEN 1 AND 100",
            name="ck_media_first_utterance_provenance",
        ),
    )
    op.create_index(
        "ix_media_first_utterances_topic_time",
        "media_first_utterances",
        ["topic_id", sa.text("occurred_at DESC"), "id"],
    )
    op.create_index(
        "ix_media_first_utterances_article",
        "media_first_utterances",
        ["article_id"],
    )
    op.drop_constraint("ck_media_sync_run_tables_name", "media_sync_run_tables", type_="check")
    op.create_check_constraint(
        "ck_media_sync_run_tables_name",
        "media_sync_run_tables",
        "table_name IN ('sources','articles','topics','topic_articles','topic_snapshots',"
        "'propagation_events','propagation_edges','first_utterances')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM media_sync_run_tables WHERE table_name='first_utterances'")
    op.drop_constraint("ck_media_sync_run_tables_name", "media_sync_run_tables", type_="check")
    op.create_check_constraint(
        "ck_media_sync_run_tables_name",
        "media_sync_run_tables",
        "table_name IN ('sources','articles','topics','topic_articles','topic_snapshots',"
        "'propagation_events','propagation_edges')",
    )
    op.drop_index("ix_media_first_utterances_article", table_name="media_first_utterances")
    op.drop_index("ix_media_first_utterances_topic_time", table_name="media_first_utterances")
    op.drop_table("media_first_utterances")
