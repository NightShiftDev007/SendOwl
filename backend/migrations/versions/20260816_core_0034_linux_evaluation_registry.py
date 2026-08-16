"""Add sealed Linux evaluation parents and allow registry-only membership.

Revision ID: 20260816_core_0034
Revises: 20260816_core_0033
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0034"
down_revision: str | None = "20260816_core_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH_SCHEMA_VERSION = "matraix-batch-registry/v1"
LINUX_EVALUATION_SCHEMA_VERSION = "matraix-linux-evaluation/v1"


def _create_linux_evaluations() -> None:
    op.create_table(
        "matraix_linux_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trial_sha256", sa.String(length=64), nullable=False),
        sa.Column("evaluation_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_eval_trial_sha"),
        sa.CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_eval_sha"),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_linux_eval_sealed_time",
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_linux_trials.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_id", name="uq_linux_eval_trial"),
        sa.UniqueConstraint("evaluation_sha256", name="uq_linux_eval_sha"),
    )
    op.create_index("ix_linux_evaluations_created", "matraix_linux_evaluations", ["created_at"])


def _create_linux_evaluation_guards() -> None:
    op.execute(
        f"""
        CREATE FUNCTION protect_matraix_linux_evaluation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_matches boolean;
        DECLARE canonical_payload text;
        DECLARE actual_sha text;
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed MatrAIx Linux evaluation DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' OR (
                OLD.input_sealed_at IS NULL AND NEW.input_sealed_at IS NOT NULL
                AND (to_jsonb(NEW)-'input_sealed_at')=(to_jsonb(OLD)-'input_sealed_at')
            ) THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_linux_trials source
                    WHERE source.id=NEW.trial_id
                      AND source.trial_sha256=NEW.trial_sha256
                ) INTO source_matches;
                IF NOT source_matches THEN
                    RAISE EXCEPTION 'MatrAIx Linux evaluation trial identity mismatch'
                        USING ERRCODE='55000';
                END IF;
                canonical_payload := '{{"schema_version":"{LINUX_EVALUATION_SCHEMA_VERSION}",'
                    '"trial_id":' || to_json(NEW.trial_id::text)::text ||
                    ',"trial_sha256":' || to_json(NEW.trial_sha256)::text || '}}';
                actual_sha := encode(
                    digest(convert_to(canonical_payload, 'UTF8'), 'sha256'), 'hex'
                );
                IF actual_sha IS DISTINCT FROM NEW.evaluation_sha256 THEN
                    RAISE EXCEPTION 'MatrAIx Linux evaluation hash does not match frozen input'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'MatrAIx Linux evaluation input is immutable'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_linux_evaluation_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_linux_evaluations FOR EACH ROW "
        "EXECUTE FUNCTION protect_matraix_linux_evaluation()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_linux_evaluation_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'MatrAIx Linux evaluation TRUNCATE is forbidden'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_linux_evaluations_reject_truncate BEFORE TRUNCATE ON "
        "matraix_linux_evaluations FOR EACH STATEMENT "
        "EXECUTE FUNCTION reject_matraix_linux_evaluation_truncate()"
    )


def _linux_item_branch(enabled: bool, selected: bool) -> str:
    if not enabled:
        return ""
    reference = "selected" if selected else "NEW"
    return f"""
                    ELSIF {reference}.kind='linux' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_linux_evaluations source
                            WHERE source.id={reference}.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256={reference}.parent_sha256
                        ) INTO source_matches;
    """


def _replace_item_guard(include_linux: bool) -> None:
    linux_branch = _linux_item_branch(include_linux, False)
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
            ELSIF NEW.kind='web' THEN
                SELECT EXISTS (
                    SELECT 1 FROM matraix_web_evaluations source
                    WHERE source.id=NEW.parent_id AND source.input_sealed_at IS NOT NULL
                      AND source.evaluation_sha256=NEW.parent_sha256
                ) INTO source_matches;
            {linux_branch}
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


def _replace_registry_guard(include_linux: bool) -> None:
    linux_branch = _linux_item_branch(include_linux, True)
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
                    ELSIF selected.kind='web' THEN
                        SELECT EXISTS (
                            SELECT 1 FROM matraix_web_evaluations source
                            WHERE source.id=selected.parent_id
                              AND source.input_sealed_at IS NOT NULL
                              AND source.evaluation_sha256=selected.parent_sha256
                        ) INTO source_matches;
                    {linux_branch}
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
    _create_linux_evaluations()
    _create_linux_evaluation_guards()
    op.drop_constraint("ck_batch_registry_item_kind", "matraix_batch_registry_items", type_="check")
    op.create_check_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        "kind IN ('survey','chat','web','linux')",
    )
    _replace_item_guard(True)
    _replace_registry_guard(True)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM matraix_batch_registry_items WHERE kind='linux') THEN
                RAISE EXCEPTION 'cannot downgrade while Linux batch registry items exist';
            END IF;
        END $$
        """
    )
    _replace_item_guard(False)
    _replace_registry_guard(False)
    op.drop_constraint("ck_batch_registry_item_kind", "matraix_batch_registry_items", type_="check")
    op.create_check_constraint(
        "ck_batch_registry_item_kind",
        "matraix_batch_registry_items",
        "kind IN ('survey','chat','web')",
    )
    op.execute("DROP TRIGGER trg_linux_evaluations_reject_truncate ON matraix_linux_evaluations")
    op.execute("DROP TRIGGER trg_linux_evaluation_protect ON matraix_linux_evaluations")
    op.execute("DROP FUNCTION reject_matraix_linux_evaluation_truncate()")
    op.execute("DROP FUNCTION protect_matraix_linux_evaluation()")
    op.drop_index("ix_linux_evaluations_created", table_name="matraix_linux_evaluations")
    op.drop_table("matraix_linux_evaluations")
