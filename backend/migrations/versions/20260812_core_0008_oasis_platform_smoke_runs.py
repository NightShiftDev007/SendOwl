"""Create durable generic OASIS platform-smoke orchestration.

Revision ID: 20260812_core_0008
Revises: 20260812_core_0007
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0008"
down_revision: str | None = "20260812_core_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tables() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_name", sa.String(length=200), nullable=False),
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_name", sa.String(length=32), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=False),
        sa.Column("actor_bio", sa.String(length=500), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("engine_version", sa.String(length=32), nullable=True),
        sa.Column("camel_version", sa.String(length=32), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("user_count", sa.Integer(), nullable=True),
        sa.Column("post_count", sa.Integer(), nullable=True),
        sa.Column("trace_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("mode = 'reddit_manual_smoke'", name="ck_simulation_runs_mode"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_simulation_runs_status",
        ),
        sa.CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_scenario_sha256",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_snapshot_sha256",
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_input_sha256",
        ),
        sa.CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_simulation_runs_seed"),
        sa.CheckConstraint(
            "length(btrim(variant_name)) BETWEEN 1 AND 200 AND variant_name !~ E'[\\r\\n]'",
            name="ck_simulation_runs_variant_name",
        ),
        sa.CheckConstraint(
            "actor_user_name ~ '^[A-Za-z0-9_-]{1,32}$'",
            name="ck_simulation_runs_actor_user_name",
        ),
        sa.CheckConstraint(
            "length(actor_name) BETWEEN 1 AND 200",
            name="ck_simulation_runs_actor_name",
        ),
        sa.CheckConstraint(
            "length(actor_bio) BETWEEN 1 AND 500",
            name="ck_simulation_runs_actor_bio",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND claimed_by_worker_id IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version = '0.2.5' AND camel_version = '0.2.78' "
            "AND artifact_sha256 ~ '^[a-f0-9]{64}$' AND artifact_size_bytes > 0 "
            "AND user_count = 1 AND post_count BETWEEN 1 AND 20 "
            "AND trace_count = post_count + 1 "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 AND length(error_message) >= 1)",
            name="ck_simulation_runs_state_shape",
        ),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_simulation_runs_sealed_time",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR (input_sealed_at IS NOT NULL AND started_at >= created_at)",
            name="ck_simulation_runs_started_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_simulation_runs_completed_time",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "variant_id"],
            ["scenario_variants.scenario_id", "scenario_variants.id"],
        ),
        sa.ForeignKeyConstraint(["world_snapshot_id"], ["world_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("input_sha256", name="uq_simulation_runs_input_sha256"),
    )
    op.create_index("ix_simulation_runs_created_at", "simulation_runs", ["created_at"])
    op.create_index(
        "ix_simulation_runs_status_created_at",
        "simulation_runs",
        ["status", "created_at"],
    )

    op.create_table(
        "simulation_run_posts",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("offset_minutes", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 19",
            name="ck_simulation_run_posts_position",
        ),
        sa.CheckConstraint(
            "length(btrim(content)) BETWEEN 1 AND 4000",
            name="ck_simulation_run_posts_content",
        ),
        sa.CheckConstraint(
            "offset_minutes BETWEEN 0 AND 1440",
            name="ck_simulation_run_posts_offset",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["simulation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "position"),
    )
    op.create_index(
        "ix_simulation_run_posts_run_position",
        "simulation_run_posts",
        ["run_id", "position"],
    )

    op.create_table(
        "simulation_worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("camel_version", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("platform_runtime_ready", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(worker_id) BETWEEN 1 AND 128",
            name="ck_simulation_worker_heartbeats_worker_id",
        ),
        sa.CheckConstraint("engine = 'camel-oasis'", name="ck_simulation_worker_engine"),
        sa.CheckConstraint(
            "engine_version = '0.2.5'",
            name="ck_simulation_worker_engine_version",
        ),
        sa.CheckConstraint(
            "camel_version = '0.2.78'",
            name="ck_simulation_worker_camel_version",
        ),
        sa.CheckConstraint("mode = 'reddit_manual_smoke'", name="ck_simulation_worker_mode"),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_simulation_worker_heartbeats_last_seen",
        "simulation_worker_heartbeats",
        ["last_seen_at"],
    )


def _create_canonical_input_functions() -> None:
    """Install exact oasis-platform-smoke/v2 addressing and actor derivation."""
    op.execute(
        """
        CREATE FUNCTION derive_simulation_run_actor_digest(
            target_scenario_id uuid,
            target_variant_id uuid
        )
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        STRICT
        AS $$
            SELECT substr(
                encode(
                    sha256(
                        convert_to(target_scenario_id::text, 'UTF8') ||
                        decode('00', 'hex') ||
                        convert_to(target_variant_id::text, 'UTF8')
                    ),
                    'hex'
                ),
                1,
                16
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION canonical_simulation_run_input_json(target_run_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected_run simulation_runs%ROWTYPE;
            posts_json text;
        BEGIN
            SELECT * INTO selected_run
            FROM simulation_runs
            WHERE id = target_run_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'cannot canonicalize missing simulation run %', target_run_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT string_agg(
                '{"content":' || to_json(run_post.content)::text ||
                ',"offset_minutes":' || run_post.offset_minutes::text ||
                ',"position":' || run_post.position::text || '}',
                ',' ORDER BY run_post.position
            )
            INTO posts_json
            FROM simulation_run_posts AS run_post
            WHERE run_post.run_id = target_run_id;

            RETURN '{"actor":{"agent_id":' || 0::text ||
                ',"bio":' || to_json(selected_run.actor_bio)::text ||
                ',"name":' || to_json(selected_run.actor_name)::text ||
                ',"user_name":' || to_json(selected_run.actor_user_name)::text || '}' ||
                ',"mode":' || to_json(selected_run.mode)::text ||
                ',"posts":[' || coalesce(posts_json, '') || ']' ||
                ',"scenario":{"id":' || to_json(selected_run.scenario_id::text)::text ||
                    ',"scenario_sha256":' ||
                    to_json(selected_run.scenario_sha256)::text ||
                    ',"snapshot_sha256":' ||
                    to_json(selected_run.snapshot_sha256)::text ||
                    ',"variant_id":' || to_json(selected_run.variant_id::text)::text ||
                    ',"variant_name":' || to_json(selected_run.variant_name)::text ||
                    ',"world_snapshot_id":' ||
                    to_json(selected_run.world_snapshot_id::text)::text || '}' ||
                ',"schema_version":"oasis-platform-smoke/v2"' ||
                ',"seed":' || selected_run.seed::text || '}';
        END;
        $$
        """
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_simulation_run_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            selected_scenario scenarios%ROWTYPE;
            selected_variant scenario_variants%ROWTYPE;
        BEGIN
            IF NEW.input_sealed_at IS NOT NULL OR NEW.status <> 'queued' THEN
                RAISE EXCEPTION
                    'simulation run % must be inserted as an unsealed queued draft',
                    NEW.id
                    USING ERRCODE = '55000';
            END IF;

            SELECT * INTO selected_scenario
            FROM scenarios
            WHERE id = NEW.scenario_id
            FOR SHARE;
            IF NOT FOUND OR selected_scenario.sealed_at IS NULL THEN
                RAISE EXCEPTION
                    'simulation run % requires sealed scenario %', NEW.id, NEW.scenario_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT * INTO selected_variant
            FROM scenario_variants
            WHERE scenario_id = NEW.scenario_id AND id = NEW.variant_id
            FOR SHARE;
            IF NOT FOUND OR selected_variant.role <> 'alternative' THEN
                RAISE EXCEPTION
                    'simulation run % requires an alternative variant %', NEW.id, NEW.variant_id
                    USING ERRCODE = '55000';
            END IF;

            IF selected_scenario.scenario_sha256 IS DISTINCT FROM NEW.scenario_sha256
               OR selected_variant.name IS DISTINCT FROM NEW.variant_name
               OR selected_scenario.world_snapshot_id IS DISTINCT FROM NEW.world_snapshot_id
               OR selected_scenario.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256
            THEN
                RAISE EXCEPTION
                    'simulation run % does not match its frozen scenario input', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_simulation_runs_draft_insert_only
        BEFORE INSERT ON simulation_runs
        FOR EACH ROW
        EXECUTE FUNCTION enforce_simulation_run_draft_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_simulation_run_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            post_count bigint;
            stored_post_count bigint;
            first_position integer;
            last_position integer;
            actor_digest text;
            actual_input_sha256 text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION
                    'simulation run % input is sealed; DELETE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.input_sealed_at IS NULL
               AND NEW.input_sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'input_sealed_at') =
                   (to_jsonb(OLD) - 'input_sealed_at')
            THEN
                SELECT count(*), min(position), max(position)
                INTO post_count, first_position, last_position
                FROM simulation_run_posts
                WHERE run_id = NEW.id;
                IF post_count < 1 OR post_count > 20
                   OR first_position <> 0 OR last_position <> post_count - 1
                THEN
                    RAISE EXCEPTION
                        'simulation run % requires 1..20 contiguous posts starting at zero', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT run_post.position, run_post.content, run_post.offset_minutes
                    FROM simulation_run_posts AS run_post
                    WHERE run_post.run_id = NEW.id
                    EXCEPT
                    SELECT intervention.position, intervention.content,
                           intervention.offset_minutes
                    FROM scenario_interventions AS intervention
                    WHERE intervention.scenario_id = NEW.scenario_id
                      AND intervention.variant_id = NEW.variant_id
                ) OR EXISTS (
                    SELECT intervention.position, intervention.content,
                           intervention.offset_minutes
                    FROM scenario_interventions AS intervention
                    WHERE intervention.scenario_id = NEW.scenario_id
                      AND intervention.variant_id = NEW.variant_id
                    EXCEPT
                    SELECT run_post.position, run_post.content, run_post.offset_minutes
                    FROM simulation_run_posts AS run_post
                    WHERE run_post.run_id = NEW.id
                ) THEN
                    RAISE EXCEPTION
                        'simulation run % posts do not exactly match scenario alternative %',
                        NEW.id, NEW.variant_id
                        USING ERRCODE = '55000';
                END IF;

                actor_digest := derive_simulation_run_actor_digest(
                    NEW.scenario_id,
                    NEW.variant_id
                );
                IF NEW.actor_user_name IS DISTINCT FROM 'scenario_' || actor_digest
                   OR NEW.actor_name IS DISTINCT FROM 'Scenario actor ' || actor_digest
                   OR NEW.actor_bio IS DISTINCT FROM
                        'Synthetic actor compiled from Scenario ' || NEW.scenario_id::text ||
                        ' variant ' || NEW.variant_id::text ||
                        '. Manual OASIS platform smoke only.'
                THEN
                    RAISE EXCEPTION
                        'simulation run % actor does not match its deterministic scenario actor',
                        NEW.id
                        USING ERRCODE = '55000';
                END IF;

                actual_input_sha256 := encode(
                    sha256(
                        convert_to(canonical_simulation_run_input_json(NEW.id), 'UTF8')
                    ),
                    'hex'
                );
                IF actual_input_sha256 IS DISTINCT FROM NEW.input_sha256 THEN
                    RAISE EXCEPTION
                        'simulation run % cannot be sealed; input_sha256 mismatch', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.input_sealed_at IS NOT NULL
               AND OLD.status = 'queued' AND NEW.status = 'running'
               AND NEW.started_at IS NOT NULL
               AND length(NEW.claimed_by_worker_id) BETWEEN 1 AND 128
               AND (to_jsonb(NEW) - ARRAY['status', 'started_at', 'claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status', 'started_at', 'claimed_by_worker_id'])
            THEN
                RETURN NEW;
            END IF;

            IF OLD.input_sealed_at IS NOT NULL
               AND OLD.status = 'running' AND NEW.status = 'succeeded'
               AND (to_jsonb(NEW) - ARRAY[
                       'status', 'completed_at', 'engine_version', 'camel_version',
                       'artifact_sha256', 'artifact_size_bytes', 'user_count',
                       'post_count', 'trace_count'
                   ]) =
                   (to_jsonb(OLD) - ARRAY[
                       'status', 'completed_at', 'engine_version', 'camel_version',
                       'artifact_sha256', 'artifact_size_bytes', 'user_count',
                       'post_count', 'trace_count'
                   ])
            THEN
                SELECT count(*) INTO stored_post_count
                FROM simulation_run_posts
                WHERE run_id = NEW.id;
                IF NEW.user_count <> 1
                   OR NEW.post_count IS DISTINCT FROM stored_post_count
                   OR NEW.trace_count IS DISTINCT FROM NEW.post_count + 1
                THEN
                    RAISE EXCEPTION
                        'simulation run % result counts do not match frozen input', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF OLD.input_sealed_at IS NOT NULL
               AND OLD.status = 'running' AND NEW.status = 'failed'
               AND (to_jsonb(NEW) - ARRAY[
                       'status', 'completed_at', 'error_code', 'error_message'
                   ]) =
                   (to_jsonb(OLD) - ARRAY[
                       'status', 'completed_at', 'error_code', 'error_message'
                   ])
            THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'simulation run % permits only input sealing and '
                'queued -> running -> terminal transitions',
                OLD.id
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_simulation_runs_protect_update_delete
        BEFORE UPDATE OR DELETE ON simulation_runs
        FOR EACH ROW
        EXECUTE FUNCTION protect_simulation_run_update_delete()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_simulation_run_post_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent simulation_runs%ROWTYPE;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION
                    'simulation run posts are immutable; UPDATE is forbidden'
                    USING ERRCODE = '55000';
            END IF;

            IF TG_OP = 'DELETE' THEN
                SELECT * INTO parent
                FROM simulation_runs
                WHERE id = OLD.run_id
                FOR UPDATE;
                IF FOUND AND parent.input_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION
                        'simulation run % input is sealed; post DELETE is forbidden', OLD.run_id
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;

            SELECT * INTO parent
            FROM simulation_runs
            WHERE id = NEW.run_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'simulation run post references missing run %', NEW.run_id
                    USING ERRCODE = '55000';
            END IF;
            IF parent.input_sealed_at IS NOT NULL OR parent.status <> 'queued' THEN
                RAISE EXCEPTION
                    'simulation run % input is sealed; post INSERT is forbidden', NEW.run_id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_simulation_run_posts_protect_mutation
        BEFORE INSERT OR UPDATE OR DELETE ON simulation_run_posts
        FOR EACH ROW
        EXECUTE FUNCTION protect_simulation_run_post_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_simulation_run_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'TRUNCATE is forbidden for immutable simulation run table %', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table_name in ("simulation_runs", "simulation_run_posts"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION reject_simulation_run_truncate()
            """
        )


def upgrade() -> None:
    """Create normalized run state, heartbeats, and database-enforced transitions."""
    _create_tables()
    _create_canonical_input_functions()
    _create_guards()


def downgrade() -> None:
    """Remove OASIS platform-smoke orchestration without touching Scenarios."""
    for table_name in ("simulation_run_posts", "simulation_runs"):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    op.execute("DROP TRIGGER trg_simulation_run_posts_protect_mutation ON simulation_run_posts")
    op.execute("DROP TRIGGER trg_simulation_runs_protect_update_delete ON simulation_runs")
    op.execute("DROP TRIGGER trg_simulation_runs_draft_insert_only ON simulation_runs")
    op.execute("DROP FUNCTION reject_simulation_run_truncate()")
    op.execute("DROP FUNCTION protect_simulation_run_post_mutation()")
    op.execute("DROP FUNCTION protect_simulation_run_update_delete()")
    op.execute("DROP FUNCTION enforce_simulation_run_draft_insert()")
    op.execute("DROP FUNCTION IF EXISTS canonical_simulation_run_input_json(uuid)")
    op.execute("DROP FUNCTION IF EXISTS derive_simulation_run_actor_digest(uuid, uuid)")
    op.drop_index(
        "ix_simulation_worker_heartbeats_last_seen",
        table_name="simulation_worker_heartbeats",
    )
    op.drop_table("simulation_worker_heartbeats")
    op.drop_index("ix_simulation_run_posts_run_position", table_name="simulation_run_posts")
    op.drop_table("simulation_run_posts")
    op.drop_index("ix_simulation_runs_status_created_at", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_created_at", table_name="simulation_runs")
    op.drop_table("simulation_runs")
