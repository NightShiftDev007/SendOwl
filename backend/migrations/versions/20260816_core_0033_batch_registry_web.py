"""Allow sealed MatrAIx Web evaluations in registry-only batches.

Revision ID: 20260816_core_0033
Revises: 20260815_core_0032
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_core_0033"
down_revision: str | None = "20260815_core_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_VERSION = "matraix-batch-registry/v1"


def _replace_item_guard_with_web() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_matraix_batch_registry_item()
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
            ELSIF NEW.kind='chat' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_chat_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            ELSE
                SELECT EXISTS (
                    SELECT 1 FROM matraix_web_evaluations source
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


def _replace_registry_guard_with_web() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_matraix_batch_registry()
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
                    ELSIF selected.kind='chat' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_chat_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    ELSE
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_web_evaluations source
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


def _replace_item_guard_without_web() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_matraix_batch_registry_item()
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


def _replace_registry_guard_without_web() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_matraix_batch_registry()
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


def upgrade() -> None:
    op.drop_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        "kind IN ('survey','chat','web')",
    )
    _replace_item_guard_with_web()
    _replace_registry_guard_with_web()


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM matraix_batch_registry_items WHERE kind='web') THEN
                RAISE EXCEPTION 'cannot downgrade while Web batch registry items exist';
            END IF;
        END $$
        """
    )
    _replace_item_guard_without_web()
    _replace_registry_guard_without_web()
    op.drop_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        "kind IN ('survey','chat')",
    )
