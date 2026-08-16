"""Add immutable registry-only grouping of sealed MatrAIx parent runs.

Revision ID: 20260813_core_0022
Revises: 20260813_core_0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0022"
down_revision: str | None = "20260813_core_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_VERSION = "matraix-batch-registry/v1"


def _create_tables() -> None:
    op.create_table(
        "matraix_batch_registries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("registry_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "title=btrim(title) AND length(title) BETWEEN 1 AND 200 AND title !~ E'[\\r\\n]'",
            name="ck_batch_registry_title",
        ),
        sa.CheckConstraint("registry_sha256 ~ '^[a-f0-9]{64}$'", name="ck_batch_registry_sha"),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_batch_registry_sealed_time",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registry_sha256", name="uq_batch_registry_sha"),
    )
    op.create_index(
        "ix_batch_registries_created",
        "matraix_batch_registries",
        ["created_at"],
    )
    op.create_table(
        "matraix_batch_registry_items",
        sa.Column("registry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 19", name="ck_batch_registry_item_position"),
        sa.CheckConstraint("kind IN ('survey','chat')", name="ck_batch_registry_item_kind"),
        sa.CheckConstraint(
            "parent_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_batch_registry_item_parent_sha",
        ),
        sa.ForeignKeyConstraint(
            ["registry_id"], ["matraix_batch_registries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("registry_id", "position"),
        sa.UniqueConstraint(
            "registry_id", "kind", "parent_id", name="uq_batch_registry_item_source"
        ),
    )
    op.create_index(
        "ix_batch_registry_items_parent",
        "matraix_batch_registry_items",
        ["kind", "parent_id"],
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_matraix_batch_registry_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'MatrAIx batch registry must be inserted as draft'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_batch_registry_insert BEFORE INSERT ON "
        "matraix_batch_registries FOR EACH ROW EXECUTE FUNCTION "
        "enforce_matraix_batch_registry_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_batch_registry_item()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_sealed_at timestamptz;
        DECLARE source_matches boolean;
        BEGIN
            IF TG_OP='DELETE' THEN
                SELECT sealed_at INTO parent_sealed_at FROM matraix_batch_registries
                WHERE id=OLD.registry_id FOR SHARE;
                IF NOT FOUND OR parent_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed MatrAIx batch registry items are immutable'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='UPDATE' AND NEW.registry_id IS DISTINCT FROM OLD.registry_id THEN
                RAISE EXCEPTION 'MatrAIx batch registry items cannot move between registries'
                    USING ERRCODE='55000';
            END IF;
            SELECT sealed_at INTO parent_sealed_at FROM matraix_batch_registries
            WHERE id=NEW.registry_id FOR SHARE;
            IF NOT FOUND OR parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'MatrAIx batch registry item requires an unsealed draft'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.kind='survey' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_survey_experiments source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.experiment_sha256=NEW.parent_sha256
                ) INTO source_matches;
            ELSE
                SELECT EXISTS (
                    SELECT 1 FROM matraix_chat_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            END IF;
            IF NOT source_matches THEN
                RAISE EXCEPTION 'MatrAIx batch registry item does not match a sealed source parent'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_batch_registry_item_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_batch_registry_items FOR EACH ROW EXECUTE FUNCTION "
        "protect_matraix_batch_registry_item()"
    )
    op.execute(
        f"""
        CREATE FUNCTION protect_matraix_batch_registry()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE stored_count integer;
        DECLARE first_position integer;
        DECLARE last_position integer;
        DECLARE selected matraix_batch_registry_items%ROWTYPE;
        DECLARE source_matches boolean;
        DECLARE item_payload text;
        DECLARE canonical_payload text;
        DECLARE actual_sha text;
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed MatrAIx batch registry DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'sealed_at')=(to_jsonb(OLD)-'sealed_at') THEN
                SELECT count(*), min(position), max(position)
                INTO stored_count, first_position, last_position
                FROM matraix_batch_registry_items WHERE registry_id=NEW.id;
                IF stored_count NOT BETWEEN 1 AND 20 OR first_position <> 0
                   OR last_position <> stored_count-1 THEN
                    RAISE EXCEPTION 'MatrAIx batch registry requires 1..20 contiguous items'
                        USING ERRCODE='55000';
                END IF;
                FOR selected IN
                    SELECT * FROM matraix_batch_registry_items
                    WHERE registry_id=NEW.id ORDER BY position
                LOOP
                    IF selected.kind='survey' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_survey_experiments source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.experiment_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    ELSE
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_chat_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    END IF;
                    IF NOT source_matches THEN
                        RAISE EXCEPTION 'MatrAIx batch registry source changed before sealing'
                            USING ERRCODE='55000';
                    END IF;
                END LOOP;
                SELECT string_agg(
                    '{{"kind":' || to_json(kind)::text ||
                    ',"parent_id":' || to_json(parent_id::text)::text ||
                    ',"parent_sha256":' || to_json(parent_sha256)::text ||
                    ',"position":' || position::text || '}}',
                    ',' ORDER BY position
                ) INTO item_payload
                FROM matraix_batch_registry_items WHERE registry_id=NEW.id;
                canonical_payload := '{{"items":[' || item_payload ||
                    '],"schema_version":"{SCHEMA_VERSION}","title":' ||
                    to_json(NEW.title)::text || '}}';
                actual_sha := encode(
                    digest(convert_to(canonical_payload, 'UTF8'), 'sha256'), 'hex'
                );
                IF actual_sha IS DISTINCT FROM NEW.registry_sha256 THEN
                    RAISE EXCEPTION 'MatrAIx batch registry hash does not match frozen inputs'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'MatrAIx batch registry input is immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_batch_registry_protect BEFORE UPDATE OR DELETE ON "
        "matraix_batch_registries FOR EACH ROW EXECUTE FUNCTION "
        "protect_matraix_batch_registry()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_batch_registry_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'MatrAIx batch registry TRUNCATE is forbidden'
                USING ERRCODE='55000';
        END; $$
        """
    )
    for table_name in ("matraix_batch_registries", "matraix_batch_registry_items"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_reject_truncate BEFORE TRUNCATE ON "
            f"{table_name} FOR EACH STATEMENT EXECUTE FUNCTION "
            "reject_matraix_batch_registry_truncate()"
        )


def upgrade() -> None:
    _create_tables()
    _create_guards()


def downgrade() -> None:
    for table_name in ("matraix_batch_registry_items", "matraix_batch_registries"):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    op.execute("DROP TRIGGER trg_batch_registry_protect ON matraix_batch_registries")
    op.execute("DROP TRIGGER trg_batch_registry_item_protect ON matraix_batch_registry_items")
    op.execute("DROP TRIGGER trg_batch_registry_insert ON matraix_batch_registries")
    op.execute("DROP FUNCTION reject_matraix_batch_registry_truncate()")
    op.execute("DROP FUNCTION protect_matraix_batch_registry()")
    op.execute("DROP FUNCTION protect_matraix_batch_registry_item()")
    op.execute("DROP FUNCTION enforce_matraix_batch_registry_insert()")
    op.drop_index("ix_batch_registry_items_parent", table_name="matraix_batch_registry_items")
    op.drop_table("matraix_batch_registry_items")
    op.drop_index("ix_batch_registries_created", table_name="matraix_batch_registries")
    op.drop_table("matraix_batch_registries")
