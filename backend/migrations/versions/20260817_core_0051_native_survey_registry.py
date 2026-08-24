"""Allow native Research Survey parents in immutable batch registries.

Revision ID: 20260817_core_0051
Revises: 20260817_core_0050
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_core_0051"
down_revision: str | None = "20260817_core_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH_SCHEMA_VERSION = "matraix-batch-registry/v1"


def _survey_match(reference: str, include_native: bool) -> str:
    native = (
        f" OR EXISTS (SELECT 1 FROM research_surveys source WHERE source.id={reference}.parent_id "
        f"AND source.sealed_at IS NOT NULL AND source.survey_sha256={reference}.parent_sha256)"
        if include_native
        else ""
    )
    return (
        f"EXISTS (SELECT 1 FROM matraix_survey_experiments source "
        f"WHERE source.id={reference}.parent_id AND source.input_sealed_at IS NOT NULL "
        f"AND source.experiment_sha256={reference}.parent_sha256){native}"
    )


def _replace_guards(include_native: bool) -> None:
    new_match = _survey_match("NEW", include_native)
    selected_match = _survey_match("selected", include_native)
    op.execute(
        f"""
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
                SELECT ({new_match}) INTO source_matches;
            ELSIF NEW.kind='chat' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_chat_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            ELSIF NEW.kind='web' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_web_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            ELSIF NEW.kind='linux' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_linux_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            ELSE
                RAISE EXCEPTION 'unsupported MatrAIx batch registry source kind'
                    USING ERRCODE='55000';
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
                        SELECT ({selected_match}) INTO source_matches;
                    ELSIF selected.kind='chat' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_chat_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    ELSIF selected.kind='web' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_web_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    ELSIF selected.kind='linux' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_linux_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    ELSE
                        RAISE EXCEPTION 'unsupported MatrAIx batch registry source kind'
                            USING ERRCODE='55000';
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
                    '],"schema_version":"{BATCH_SCHEMA_VERSION}","title":' ||
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
    _replace_guards(True)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM matraix_batch_registry_items item
                JOIN research_surveys survey ON survey.id=item.parent_id
                WHERE item.kind='survey' AND item.parent_sha256=survey.survey_sha256
            ) THEN
                RAISE EXCEPTION
                    'cannot remove native Survey registry support while references exist';
            END IF;
        END $$
        """
    )
    _replace_guards(False)
