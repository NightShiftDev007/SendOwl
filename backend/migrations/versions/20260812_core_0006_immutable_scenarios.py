"""Create generic immutable scenarios with database-enforced sealing.

Revision ID: 20260812_core_0006
Revises: 20260812_core_0005
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0006"
down_revision: str | None = "20260812_core_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCENARIO_TABLES: tuple[str, ...] = (
    "scenarios",
    "scenario_variants",
    "scenario_interventions",
)
SCENARIO_CHILD_TABLES: tuple[str, ...] = (
    "scenario_variants",
    "scenario_interventions",
)


def _create_tables() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("decision_question", sa.Text(), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_evidence_count", sa.Integer(), nullable=False),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300 AND title !~ E'[\\r\\n]'",
            name="ck_scenarios_title",
        ),
        sa.CheckConstraint(
            "length(btrim(decision_question)) BETWEEN 1 AND 2000",
            name="ck_scenarios_decision_question",
        ),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_scenarios_snapshot_version"),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_scenarios_snapshot_sha256",
        ),
        sa.CheckConstraint(
            "snapshot_evidence_count BETWEEN 1 AND 50",
            name="ck_scenarios_snapshot_evidence_count",
        ),
        sa.CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_scenarios_sha256",
        ),
        sa.ForeignKeyConstraint(["world_model_id"], ["world_models.id"]),
        sa.ForeignKeyConstraint(["world_snapshot_id"], ["world_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scenarios_created_at", "scenarios", ["created_at"], unique=False)
    op.create_index(
        "ix_scenarios_world_snapshot",
        "scenarios",
        ["world_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "scenario_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(role = 'baseline' AND position = 0) OR "
            "(role = 'alternative' AND position BETWEEN 1 AND 5)",
            name="ck_scenario_variants_role_position",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200 AND name !~ E'[\\r\\n]'",
            name="ck_scenario_variants_name",
        ),
        sa.CheckConstraint(
            "length(btrim(hypothesis)) BETWEEN 1 AND 2000",
            name="ck_scenario_variants_hypothesis",
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_id", "position", name="uq_scenario_variants_position"),
        sa.UniqueConstraint("scenario_id", "id", name="uq_scenario_variants_scenario_id"),
    )
    op.create_index(
        "ix_scenario_variants_scenario_position",
        "scenario_variants",
        ["scenario_id", "position"],
        unique=False,
    )

    op.create_table(
        "scenario_interventions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 19",
            name="ck_scenario_interventions_position",
        ),
        sa.CheckConstraint("kind = 'initial_post'", name="ck_scenario_interventions_kind"),
        sa.CheckConstraint(
            "actor = 'scenario_actor'",
            name="ck_scenario_interventions_actor",
        ),
        sa.CheckConstraint("channel = 'reddit'", name="ck_scenario_interventions_channel"),
        sa.CheckConstraint(
            "length(btrim(content)) BETWEEN 1 AND 4000",
            name="ck_scenario_interventions_content",
        ),
        sa.CheckConstraint(
            "offset_minutes BETWEEN 0 AND 1440",
            name="ck_scenario_interventions_offset",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "variant_id"],
            ["scenario_variants.scenario_id", "scenario_variants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id",
            "variant_id",
            "position",
            name="uq_scenario_interventions_position",
        ),
    )
    op.create_index(
        "ix_scenario_interventions_variant_position",
        "scenario_interventions",
        ["scenario_id", "variant_id", "position"],
        unique=False,
    )


def _create_canonical_scenario_function() -> None:
    """Install the SQL equivalent of the application's scenario/v2 encoder."""
    op.execute(
        """
        CREATE FUNCTION canonical_scenario_json(target_scenario_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_scenario scenarios%ROWTYPE;
            selected_variant scenario_variants%ROWTYPE;
            baseline_json text;
            intervention_json text;
            alternatives_json text := '';
            alternative_separator text := '';
        BEGIN
            SELECT * INTO selected_scenario
            FROM scenarios
            WHERE id = target_scenario_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing scenario %', target_scenario_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT
                '{"hypothesis":' || to_json(variant.hypothesis)::text ||
                ',"interventions":[]' ||
                ',"name":' || to_json(variant.name)::text ||
                ',"position":' || variant.position::text || '}'
            INTO baseline_json
            FROM scenario_variants AS variant
            WHERE variant.scenario_id = target_scenario_id
              AND variant.role = 'baseline'
            ORDER BY variant.position
            LIMIT 1;

            FOR selected_variant IN
                SELECT *
                FROM scenario_variants
                WHERE scenario_id = target_scenario_id
                  AND role = 'alternative'
                ORDER BY position
            LOOP
                SELECT string_agg(
                    '{"actor":' || to_json(intervention.actor)::text ||
                    ',"channel":' || to_json(intervention.channel)::text ||
                    ',"content":' || to_json(intervention.content)::text ||
                    ',"kind":' || to_json(intervention.kind)::text ||
                    ',"offset_minutes":' || intervention.offset_minutes::text ||
                    ',"position":' || intervention.position::text || '}',
                    ',' ORDER BY intervention.position
                )
                INTO intervention_json
                FROM scenario_interventions AS intervention
                WHERE intervention.scenario_id = target_scenario_id
                  AND intervention.variant_id = selected_variant.id;

                alternatives_json := alternatives_json || alternative_separator ||
                    '{"hypothesis":' || to_json(selected_variant.hypothesis)::text ||
                    ',"interventions":[' || coalesce(intervention_json, '') || ']' ||
                    ',"name":' || to_json(selected_variant.name)::text ||
                    ',"position":' || selected_variant.position::text || '}';
                alternative_separator := ',';
            END LOOP;

            RETURN '{"alternatives":[' || alternatives_json || ']' ||
                ',"baseline":' || coalesce(baseline_json, 'null') ||
                ',"decision_question":' ||
                    to_json(selected_scenario.decision_question)::text ||
                ',"schema_version":"scenario/v2"' ||
                ',"snapshot":{"evidence_count":' ||
                    selected_scenario.snapshot_evidence_count::text ||
                    ',"snapshot_sha256":' ||
                    to_json(selected_scenario.snapshot_sha256)::text ||
                    ',"version":' || selected_scenario.snapshot_version::text ||
                    ',"world_model_id":' ||
                    to_json(selected_scenario.world_model_id::text)::text ||
                    ',"world_snapshot_id":' ||
                    to_json(selected_scenario.world_snapshot_id::text)::text || '}' ||
                ',"title":' || to_json(selected_scenario.title)::text || '}';
        END;
        $$
        """
    )


def _create_sealing_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_scenario_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            selected_snapshot world_snapshots%ROWTYPE;
            selected_evidence_count bigint;
        BEGIN
            IF NEW.sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'scenario % must be inserted as an unsealed draft',
                    NEW.id
                    USING ERRCODE = '55000';
            END IF;

            SELECT *
            INTO selected_snapshot
            FROM world_snapshots
            WHERE id = NEW.world_snapshot_id
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'scenario % references missing world snapshot %',
                    NEW.id,
                    NEW.world_snapshot_id
                    USING ERRCODE = '55000';
            END IF;
            IF selected_snapshot.sealed_at IS NULL THEN
                RAISE EXCEPTION
                    'scenario % references unsealed world snapshot %',
                    NEW.id,
                    NEW.world_snapshot_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT count(*)
            INTO selected_evidence_count
            FROM world_snapshot_evidence
            WHERE snapshot_id = NEW.world_snapshot_id;

            IF selected_snapshot.world_model_id IS DISTINCT FROM NEW.world_model_id
               OR selected_snapshot.version IS DISTINCT FROM NEW.snapshot_version
               OR selected_snapshot.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256
               OR selected_evidence_count IS DISTINCT FROM NEW.snapshot_evidence_count
            THEN
                RAISE EXCEPTION
                    'scenario % world snapshot reference does not match frozen snapshot %',
                    NEW.id,
                    NEW.world_snapshot_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_scenarios_draft_insert_only
        BEFORE INSERT ON scenarios
        FOR EACH ROW
        EXECUTE FUNCTION enforce_scenario_draft_insert()
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_scenario_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            variant_count bigint;
            baseline_count bigint;
            alternative_count bigint;
            first_alternative_position integer;
            last_alternative_position integer;
            invalid_variant_id uuid;
            actual_scenario_sha256 text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.sealed_at IS NULL THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'scenario % is sealed; DELETE is forbidden',
                    OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.sealed_at IS NULL
               AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'sealed_at') =
                   (to_jsonb(OLD) - 'sealed_at')
            THEN
                SELECT count(*)
                INTO variant_count
                FROM scenario_variants
                WHERE scenario_id = NEW.id;

                SELECT count(*)
                INTO baseline_count
                FROM scenario_variants
                WHERE scenario_id = NEW.id
                  AND role = 'baseline'
                  AND position = 0;

                SELECT count(*), min(position), max(position)
                INTO alternative_count, first_alternative_position,
                     last_alternative_position
                FROM scenario_variants
                WHERE scenario_id = NEW.id
                  AND role = 'alternative';

                IF variant_count <> baseline_count + alternative_count
                   OR baseline_count <> 1
                   OR alternative_count < 1
                   OR alternative_count > 5
                   OR first_alternative_position <> 1
                   OR last_alternative_position <> alternative_count
                THEN
                    RAISE EXCEPTION
                        'scenario % cannot be sealed; require exactly one baseline at '
                        'position zero and 1..5 contiguous alternatives starting at one',
                        NEW.id
                        USING ERRCODE = '55000';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM scenario_interventions AS intervention
                    JOIN scenario_variants AS variant
                      ON variant.scenario_id = intervention.scenario_id
                     AND variant.id = intervention.variant_id
                    WHERE intervention.scenario_id = NEW.id
                      AND variant.role = 'baseline'
                ) THEN
                    RAISE EXCEPTION
                        'scenario % cannot be sealed; baseline interventions are forbidden',
                        NEW.id
                        USING ERRCODE = '55000';
                END IF;

                SELECT variant.id
                INTO invalid_variant_id
                FROM scenario_variants AS variant
                LEFT JOIN scenario_interventions AS intervention
                  ON intervention.scenario_id = variant.scenario_id
                 AND intervention.variant_id = variant.id
                WHERE variant.scenario_id = NEW.id
                  AND variant.role = 'alternative'
                GROUP BY variant.id, variant.position
                HAVING count(intervention.id) < 1
                    OR count(intervention.id) > 20
                    OR min(intervention.position) <> 0
                    OR max(intervention.position) <> count(intervention.id) - 1
                ORDER BY variant.position
                LIMIT 1;

                IF FOUND THEN
                    RAISE EXCEPTION
                        'scenario % cannot be sealed; alternative variant % must have '
                        '1..20 contiguous interventions starting at zero',
                        NEW.id,
                        invalid_variant_id
                        USING ERRCODE = '55000';
                END IF;

                actual_scenario_sha256 := encode(
                    sha256(convert_to(canonical_scenario_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF actual_scenario_sha256 IS DISTINCT FROM NEW.scenario_sha256 THEN
                    RAISE EXCEPTION
                        'scenario % cannot be sealed; scenario_sha256 mismatch', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'scenario % is immutable; only sealing a complete draft is allowed',
                OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_scenarios_seal_only
        BEFORE UPDATE OR DELETE ON scenarios
        FOR EACH ROW
        EXECUTE FUNCTION protect_scenario_update_delete()
        """
    )

    op.execute(
        """
        CREATE FUNCTION protect_scenario_child_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            target_scenario_id uuid;
            old_scenario_id uuid;
            parent_sealed_at timestamp with time zone;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                target_scenario_id := OLD.scenario_id;
            ELSE
                target_scenario_id := NEW.scenario_id;
            END IF;

            SELECT sealed_at
            INTO parent_sealed_at
            FROM scenarios
            WHERE id = target_scenario_id
            FOR UPDATE;

            IF FOUND AND parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'scenario % is sealed; % on % is forbidden',
                    target_scenario_id,
                    TG_OP,
                    TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                old_scenario_id := OLD.scenario_id;
                IF old_scenario_id IS DISTINCT FROM target_scenario_id THEN
                    SELECT sealed_at
                    INTO parent_sealed_at
                    FROM scenarios
                    WHERE id = old_scenario_id
                    FOR UPDATE;
                    IF FOUND AND parent_sealed_at IS NOT NULL THEN
                        RAISE EXCEPTION
                            'scenario % is sealed; moving a child from % is forbidden',
                            old_scenario_id,
                            TG_TABLE_NAME
                            USING ERRCODE = '55000';
                    END IF;
                END IF;
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in SCENARIO_CHILD_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_draft_mutation_only
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION protect_scenario_child_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION reject_scenario_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'scenario table % is immutable; TRUNCATE is forbidden',
                TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in SCENARIO_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_scenario_truncate()
            """
        )


def upgrade() -> None:
    """Create normalized scenario storage and its database integrity boundary."""
    _create_tables()
    _create_canonical_scenario_function()
    _create_sealing_guards()


def downgrade() -> None:
    """Remove scenario guards and tables in reverse dependency order."""
    for table_name in reversed(SCENARIO_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    for table_name in reversed(SCENARIO_CHILD_TABLES):
        op.execute(f"DROP TRIGGER trg_{table_name}_draft_mutation_only ON {table_name}")
    op.execute("DROP TRIGGER trg_scenarios_seal_only ON scenarios")
    op.execute("DROP TRIGGER trg_scenarios_draft_insert_only ON scenarios")
    op.execute("DROP FUNCTION reject_scenario_truncate()")
    op.execute("DROP FUNCTION protect_scenario_child_mutation()")
    op.execute("DROP FUNCTION protect_scenario_update_delete()")
    op.execute("DROP FUNCTION enforce_scenario_draft_insert()")
    op.execute("DROP FUNCTION IF EXISTS canonical_scenario_json(uuid)")

    op.drop_index(
        "ix_scenario_interventions_variant_position",
        table_name="scenario_interventions",
    )
    op.drop_table("scenario_interventions")
    op.drop_index("ix_scenario_variants_scenario_position", table_name="scenario_variants")
    op.drop_table("scenario_variants")
    op.drop_index("ix_scenarios_world_snapshot", table_name="scenarios")
    op.drop_index("ix_scenarios_created_at", table_name="scenarios")
    op.drop_table("scenarios")
