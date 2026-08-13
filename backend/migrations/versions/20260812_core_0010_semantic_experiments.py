"""Create durable content-addressed OASIS semantic experiments.

Revision ID: 20260812_core_0010
Revises: 20260812_core_0009
Create Date: 2026-08-12
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0010"
down_revision: str | None = "20260812_core_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extend_worker_heartbeats() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column(
            "semantic_runtime_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("semantic_model_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("semantic_prompt_schema_version", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_simulation_worker_semantic_config",
        "simulation_worker_heartbeats",
        "(semantic_runtime_ready AND platform_runtime_ready AND "
        "length(btrim(semantic_model_name)) BETWEEN 1 AND 200 "
        "AND semantic_model_name !~ E'[\\r\\n]' "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND semantic_prompt_schema_version = 'matraix-semantic-profile/v1') OR "
        "(NOT semantic_runtime_ready AND semantic_model_name IS NULL "
        "AND semantic_config_sha256 IS NULL "
        "AND semantic_prompt_schema_version IS NULL)",
    )


def _create_experiment_tables() -> None:
    op.create_table(
        "semantic_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=False),
        sa.Column("scenario_title", sa.String(length=300), nullable=False),
        sa.Column("decision_question", sa.Text(), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_title", sa.String(length=200), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("rounds", sa.Integer(), nullable=False),
        sa.Column("minutes_per_round", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("experiment_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_scenario_sha256",
        ),
        sa.CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_cohort_sha256",
        ),
        sa.CheckConstraint(
            "dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_dataset_sha256",
        ),
        sa.CheckConstraint(
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_config_sha256",
        ),
        sa.CheckConstraint(
            "experiment_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_sha256",
        ),
        sa.CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_semantic_persona_count"),
        sa.CheckConstraint("rounds BETWEEN 1 AND 3", name="ck_semantic_rounds"),
        sa.CheckConstraint(
            "minutes_per_round BETWEEN 15 AND 240",
            name="ck_semantic_minutes_per_round",
        ),
        sa.CheckConstraint(
            "prompt_schema_version = 'matraix-semantic-profile/v1'",
            name="ck_semantic_prompt_schema",
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_semantic_model_name",
        ),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_semantic_experiments_sealed_time",
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_sha256", name="uq_semantic_experiments_sha256"),
    )
    op.create_index("ix_semantic_experiments_created_at", "semantic_experiments", ["created_at"])

    op.create_table(
        "semantic_experiment_variants",
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("scenario_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("intervention_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(position = 0 AND role = 'baseline' AND scenario_position = 0 "
            "AND intervention_count = 0) OR "
            "(position BETWEEN 1 AND 2 AND role = 'alternative' "
            "AND scenario_position BETWEEN 1 AND 5 AND intervention_count BETWEEN 1 AND 20)",
            name="ck_semantic_variants_role_position",
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["semantic_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scenario_variant_id"], ["scenario_variants.id"]),
        sa.PrimaryKeyConstraint("experiment_id", "position"),
        sa.UniqueConstraint(
            "experiment_id", "scenario_variant_id", name="uq_semantic_variants_selection"
        ),
    )
    op.create_index(
        "ix_semantic_variants_scenario_variant",
        "semantic_experiment_variants",
        ["scenario_variant_id"],
    )

    op.create_table(
        "semantic_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_position", sa.Integer(), nullable=False),
        sa.Column("variant_role", sa.String(length=16), nullable=False),
        sa.Column("scenario_variant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_position", sa.Integer(), nullable=False),
        sa.Column("variant_name", sa.String(length=200), nullable=False),
        sa.Column("variant_hypothesis", sa.Text(), nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("trial_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("engine_version", sa.String(length=32), nullable=True),
        sa.Column("camel_version", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("user_count", sa.Integer(), nullable=True),
        sa.Column("initial_post_count", sa.Integer(), nullable=True),
        sa.Column("generated_post_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("reaction_count", sa.Integer(), nullable=True),
        sa.Column("do_nothing_count", sa.Integer(), nullable=True),
        sa.Column("observed_action_count", sa.Integer(), nullable=True),
        sa.Column("rounds_completed", sa.Integer(), nullable=True),
        sa.Column("limitations", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_semantic_trials_seed"),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_semantic_trials_sha256"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_semantic_trials_status",
        ),
        sa.CheckConstraint("current_round BETWEEN 0 AND 3", name="ck_semantic_current_round"),
        sa.CheckConstraint(
            "(variant_position = 0 AND variant_role = 'baseline' "
            "AND scenario_position = 0) OR "
            "(variant_position BETWEEN 1 AND 2 AND variant_role = 'alternative' "
            "AND scenario_position BETWEEN 1 AND 5)",
            name="ck_semantic_trials_variant",
        ),
        sa.CheckConstraint(_trial_state_shape(), name="ck_semantic_trials_state_shape"),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_semantic_started_time"
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_semantic_completed_time",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id", "variant_position"],
            ["semantic_experiment_variants.experiment_id", "semantic_experiment_variants.position"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_sha256", name="uq_semantic_trials_sha256"),
        sa.UniqueConstraint(
            "experiment_id", "variant_position", "seed", name="uq_semantic_trials_cartesian"
        ),
    )
    op.create_index(
        "ix_semantic_trials_status_created", "semantic_trials", ["status", "created_at"]
    )

    op.create_table(
        "semantic_trial_events",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_position", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("post_id", sa.String(length=128), nullable=True),
        sa.Column("comment_id", sa.String(length=128), nullable=True),
        sa.Column("target_post_id", sa.String(length=128), nullable=True),
        sa.Column("observed_at_raw", sa.String(length=200), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_semantic_events_sequence"),
        sa.CheckConstraint("round BETWEEN 1 AND 3", name="ck_semantic_events_round"),
        sa.CheckConstraint(
            "phase IN ('intervention', 'audience')", name="ck_semantic_events_phase"
        ),
        sa.CheckConstraint(
            "(actor_kind = 'scenario' AND persona_id IS NULL AND agent_position = 0 "
            "AND phase = 'intervention' AND action_type = 'create_post') OR "
            "(actor_kind = 'persona' AND persona_id IS NOT NULL "
            "AND agent_position BETWEEN 1 AND 8 AND phase = 'audience')",
            name="ck_semantic_events_actor",
        ),
        sa.CheckConstraint(
            "action_type IN ('create_post', 'create_comment', 'like_post', "
            "'dislike_post', 'do_nothing')",
            name="ck_semantic_events_action",
        ),
        sa.CheckConstraint(
            "content IS NULL OR char_length(content) <= 4000",
            name="ck_semantic_events_content_length",
        ),
        sa.CheckConstraint(_event_action_shape(), name="ck_semantic_events_action_shape"),
        sa.CheckConstraint(
            "length(btrim(observed_at_raw)) BETWEEN 1 AND 200 AND observed_at_raw !~ E'[\\r\\n]'",
            name="ck_semantic_events_observed_at",
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["semantic_trials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("trial_id", "sequence"),
    )
    op.create_index(
        "ix_semantic_events_trial_sequence",
        "semantic_trial_events",
        ["trial_id", "sequence"],
    )


def _trial_state_shape() -> str:
    empty_result = (
        "engine_version IS NULL AND camel_version IS NULL AND model_name IS NULL "
        "AND semantic_config_sha256 IS NULL AND prompt_schema_version IS NULL "
        "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
        "AND user_count IS NULL AND initial_post_count IS NULL "
        "AND generated_post_count IS NULL AND comment_count IS NULL "
        "AND reaction_count IS NULL AND do_nothing_count IS NULL "
        "AND observed_action_count IS NULL AND rounds_completed IS NULL "
        "AND limitations IS NULL"
    )
    return (
        "(status = 'queued' AND current_round = 0 AND claimed_by_worker_id IS NULL "
        f"AND started_at IS NULL AND completed_at IS NULL AND {empty_result} "
        "AND error_code IS NULL AND error_message IS NULL) OR "
        "(status = 'running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
        f"AND started_at IS NOT NULL AND completed_at IS NULL AND {empty_result} "
        "AND error_code IS NULL AND error_message IS NULL) OR "
        "(status = 'succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
        "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
        "AND engine_version = '0.2.5' AND camel_version = '0.2.78' "
        "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND prompt_schema_version = 'matraix-semantic-profile/v1' "
        "AND artifact_sha256 ~ '^[a-f0-9]{64}$' AND artifact_size_bytes > 0 "
        "AND user_count BETWEEN 2 AND 9 AND initial_post_count >= 0 "
        "AND generated_post_count >= 0 AND comment_count >= 0 "
        "AND reaction_count >= 0 AND do_nothing_count >= 0 "
        "AND observed_action_count = initial_post_count + generated_post_count "
        "+ comment_count + reaction_count + do_nothing_count "
        "AND rounds_completed BETWEEN 1 AND 3 AND cardinality(limitations) >= 1 "
        "AND error_code IS NULL AND error_message IS NULL) OR "
        "(status = 'failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
        f"AND started_at IS NOT NULL AND completed_at IS NOT NULL AND {empty_result} "
        "AND length(error_code) BETWEEN 1 AND 128 "
        "AND length(error_message) BETWEEN 1 AND 4000)"
    )


def _event_action_shape() -> str:
    return (
        "(action_type = 'create_post' AND length(btrim(content)) >= 1 "
        "AND length(post_id) BETWEEN 1 AND 128 AND comment_id IS NULL "
        "AND target_post_id IS NULL) OR "
        "(action_type = 'create_comment' AND length(btrim(content)) >= 1 "
        "AND post_id IS NULL AND length(comment_id) BETWEEN 1 AND 128 "
        "AND length(target_post_id) BETWEEN 1 AND 128) OR "
        "(action_type IN ('like_post', 'dislike_post') AND content IS NULL "
        "AND post_id IS NULL AND comment_id IS NULL "
        "AND length(target_post_id) BETWEEN 1 AND 128) OR "
        "(action_type = 'do_nothing' AND content IS NULL AND post_id IS NULL "
        "AND comment_id IS NULL AND target_post_id IS NULL)"
    )


def _create_canonical_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION canonical_semantic_experiment_json(target_experiment_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected semantic_experiments%ROWTYPE;
            variants_json text;
            seeds_json text;
        BEGIN
            SELECT * INTO selected FROM semantic_experiments
            WHERE id = target_experiment_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cannot canonicalize missing semantic experiment %',
                    target_experiment_id USING ERRCODE = '55000';
            END IF;

            SELECT string_agg(
                '{"hypothesis":' || to_json(variant.hypothesis)::text ||
                ',"id":' || to_json(variant.scenario_variant_id::text)::text ||
                ',"name":' || to_json(variant.name)::text ||
                ',"position":' || variant.scenario_position::text ||
                ',"role":' || to_json(variant.role)::text || '}',
                ',' ORDER BY variant.position
            ) INTO variants_json
            FROM semantic_experiment_variants AS variant
            WHERE variant.experiment_id = target_experiment_id;

            SELECT string_agg(seed::text, ',' ORDER BY seed)
            INTO seeds_json
            FROM (
                SELECT DISTINCT trial.seed
                FROM semantic_trials AS trial
                WHERE trial.experiment_id = target_experiment_id
            ) AS selected_seed;

            RETURN '{"cohort":{"cohort_sha256":' || to_json(selected.cohort_sha256)::text ||
                ',"id":' || to_json(selected.cohort_id::text)::text || '}' ||
                ',"minutes_per_round":' || selected.minutes_per_round::text ||
                ',"model":{"config_sha256":' ||
                    to_json(selected.semantic_config_sha256)::text ||
                    ',"name":' || to_json(selected.model_name)::text ||
                    ',"prompt_schema_version":' ||
                    to_json(selected.prompt_schema_version)::text || '}' ||
                ',"rounds":' || selected.rounds::text ||
                ',"scenario":{"id":' || to_json(selected.scenario_id::text)::text ||
                    ',"scenario_sha256":' || to_json(selected.scenario_sha256)::text || '}' ||
                ',"schema":"oasis-semantic-experiment/v1"' ||
                ',"seeds":[' || coalesce(seeds_json, '') || ']' ||
                ',"variants":[' || coalesce(variants_json, '') || ']}';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION canonical_semantic_trial_json(target_trial_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            selected semantic_trials%ROWTYPE;
            experiment_hash text;
        BEGIN
            SELECT * INTO selected FROM semantic_trials WHERE id = target_trial_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'cannot canonicalize missing semantic trial %', target_trial_id
                    USING ERRCODE = '55000';
            END IF;
            SELECT experiment_sha256 INTO experiment_hash
            FROM semantic_experiments WHERE id = selected.experiment_id;
            RETURN '{"experiment_sha256":' || to_json(experiment_hash)::text ||
                ',"prompt_schema_version":"matraix-semantic-profile/v1"' ||
                ',"schema":"oasis-semantic-trial/v1"' ||
                ',"seed":' || selected.seed::text ||
                ',"variant":{"id":' || to_json(selected.scenario_variant_id::text)::text ||
                    ',"name":' || to_json(selected.variant_name)::text ||
                    ',"position":' || selected.scenario_position::text ||
                    ',"role":' || to_json(selected.variant_role)::text || '}}';
        END;
        $$
        """
    )


def _create_experiment_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_semantic_experiment_draft_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            selected_scenario scenarios%ROWTYPE;
            selected_cohort cohorts%ROWTYPE;
            selected_dataset persona_datasets%ROWTYPE;
        BEGIN
            IF NEW.input_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'semantic experiment % must be inserted as an unsealed draft',
                    NEW.id USING ERRCODE = '55000';
            END IF;
            SELECT * INTO selected_scenario FROM scenarios
            WHERE id = NEW.scenario_id FOR SHARE;
            IF NOT FOUND OR selected_scenario.sealed_at IS NULL THEN
                RAISE EXCEPTION 'semantic experiment % requires sealed scenario %',
                    NEW.id, NEW.scenario_id USING ERRCODE = '55000';
            END IF;
            SELECT * INTO selected_cohort FROM cohorts
            WHERE id = NEW.cohort_id FOR SHARE;
            IF NOT FOUND OR selected_cohort.sealed_at IS NULL OR selected_cohort.persona_count > 8 THEN
                RAISE EXCEPTION 'semantic experiment % requires a sealed cohort of at most 8 personas',
                    NEW.id USING ERRCODE = '55000';
            END IF;
            SELECT * INTO selected_dataset FROM persona_datasets
            WHERE id = selected_cohort.dataset_id FOR SHARE;
            IF NOT FOUND OR selected_dataset.sealed_at IS NULL THEN
                RAISE EXCEPTION 'semantic experiment % requires a sealed persona dataset',
                    NEW.id USING ERRCODE = '55000';
            END IF;
            IF NEW.scenario_sha256 IS DISTINCT FROM selected_scenario.scenario_sha256
               OR NEW.scenario_title IS DISTINCT FROM selected_scenario.title
               OR NEW.decision_question IS DISTINCT FROM selected_scenario.decision_question
               OR NEW.cohort_sha256 IS DISTINCT FROM selected_cohort.cohort_sha256
               OR NEW.cohort_title IS DISTINCT FROM selected_cohort.title
               OR NEW.persona_count IS DISTINCT FROM selected_cohort.persona_count
               OR NEW.dataset_sha256 IS DISTINCT FROM selected_dataset.dataset_sha256
            THEN
                RAISE EXCEPTION 'semantic experiment % frozen references do not match sources',
                    NEW.id USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_experiments_draft_insert
        BEFORE INSERT ON semantic_experiments
        FOR EACH ROW EXECUTE FUNCTION enforce_semantic_experiment_draft_insert()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_semantic_experiment_update_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            variant_count integer;
            seed_count integer;
            trial_count integer;
            actual_hash text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'semantic experiment % is sealed; DELETE is forbidden', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.input_sealed_at IS NULL AND NEW.input_sealed_at IS NOT NULL
               AND (to_jsonb(NEW) - 'input_sealed_at') = (to_jsonb(OLD) - 'input_sealed_at')
            THEN
                SELECT count(*) INTO variant_count FROM semantic_experiment_variants
                WHERE experiment_id = NEW.id;
                IF variant_count NOT BETWEEN 2 AND 3 OR EXISTS (
                    SELECT expected.position FROM generate_series(0, variant_count - 1) expected(position)
                    EXCEPT SELECT position FROM semantic_experiment_variants
                    WHERE experiment_id = NEW.id
                ) THEN
                    RAISE EXCEPTION 'semantic experiment % requires baseline plus 1..2 contiguous alternatives',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM semantic_experiment_variants frozen
                    LEFT JOIN scenario_variants source
                      ON source.scenario_id = NEW.scenario_id
                     AND source.id = frozen.scenario_variant_id
                    WHERE frozen.experiment_id = NEW.id AND (
                        source.id IS NULL OR source.position IS DISTINCT FROM frozen.scenario_position
                        OR source.role IS DISTINCT FROM frozen.role
                        OR source.name IS DISTINCT FROM frozen.name
                        OR source.hypothesis IS DISTINCT FROM frozen.hypothesis
                        OR frozen.intervention_count IS DISTINCT FROM (
                            SELECT count(*) FROM scenario_interventions intervention
                            WHERE intervention.scenario_id = NEW.scenario_id
                              AND intervention.variant_id = frozen.scenario_variant_id
                        )
                    )
                ) THEN
                    RAISE EXCEPTION 'semantic experiment % variants do not match sealed scenario %',
                        NEW.id, NEW.scenario_id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM semantic_experiment_variants frozen
                    JOIN scenario_interventions intervention
                      ON intervention.scenario_id = NEW.scenario_id
                     AND intervention.variant_id = frozen.scenario_variant_id
                    WHERE frozen.experiment_id = NEW.id
                      AND intervention.offset_minutes > NEW.rounds * NEW.minutes_per_round
                ) THEN
                    RAISE EXCEPTION 'semantic experiment % has an intervention outside its time horizon',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                SELECT count(DISTINCT seed), count(*) INTO seed_count, trial_count
                FROM semantic_trials WHERE experiment_id = NEW.id;
                IF seed_count NOT BETWEEN 1 AND 2 OR trial_count <> variant_count * seed_count
                   OR EXISTS (
                        SELECT variant.position, seed.seed
                        FROM semantic_experiment_variants variant
                        CROSS JOIN (
                            SELECT DISTINCT seed FROM semantic_trials WHERE experiment_id = NEW.id
                        ) seed
                        WHERE variant.experiment_id = NEW.id
                        EXCEPT
                        SELECT variant_position, seed FROM semantic_trials
                        WHERE experiment_id = NEW.id
                   )
                THEN
                    RAISE EXCEPTION 'semantic experiment % trials are not a complete Cartesian product',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF variant_count * seed_count * NEW.rounds * NEW.persona_count > 96 THEN
                    RAISE EXCEPTION 'semantic experiment % exceeds the 96 persona-round budget',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                actual_hash := encode(
                    sha256(convert_to(canonical_semantic_experiment_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF actual_hash IS DISTINCT FROM NEW.experiment_sha256 THEN
                    RAISE EXCEPTION 'semantic experiment % cannot be sealed; experiment_sha256 mismatch',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM semantic_trials trial
                    WHERE trial.experiment_id = NEW.id AND trial.trial_sha256 IS DISTINCT FROM
                        encode(sha256(convert_to(canonical_semantic_trial_json(trial.id), 'UTF8')), 'hex')
                ) THEN
                    RAISE EXCEPTION 'semantic experiment % cannot be sealed; trial_sha256 mismatch',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'semantic experiment % permits only its draft-to-sealed transition',
                OLD.id USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_experiments_protect
        BEFORE UPDATE OR DELETE ON semantic_experiments
        FOR EACH ROW EXECUTE FUNCTION protect_semantic_experiment_update_delete()
        """
    )


def _create_child_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_semantic_variant_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent semantic_experiments%ROWTYPE;
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION 'semantic experiment variants are immutable; UPDATE is forbidden'
                    USING ERRCODE = '55000';
            END IF;
            SELECT * INTO parent FROM semantic_experiments
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.experiment_id ELSE NEW.experiment_id END
            FOR UPDATE;
            IF TG_OP = 'DELETE' THEN
                IF FOUND AND parent.input_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'semantic experiment % is sealed; variant DELETE is forbidden',
                        OLD.experiment_id USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF NOT FOUND OR parent.input_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'semantic experiment % is missing or sealed; variant INSERT is forbidden',
                    NEW.experiment_id USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_variants_protect
        BEFORE INSERT OR UPDATE OR DELETE ON semantic_experiment_variants
        FOR EACH ROW EXECUTE FUNCTION protect_semantic_variant_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_semantic_trial_insert_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parent semantic_experiments%ROWTYPE;
            selected_variant semantic_experiment_variants%ROWTYPE;
        BEGIN
            SELECT * INTO parent FROM semantic_experiments
            WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.experiment_id ELSE NEW.experiment_id END
            FOR UPDATE;
            IF TG_OP = 'DELETE' THEN
                IF FOUND AND parent.input_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'semantic experiment % is sealed; trial DELETE is forbidden',
                        OLD.experiment_id USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF NOT FOUND OR parent.input_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'semantic experiment % is missing or sealed; trial INSERT is forbidden',
                    NEW.experiment_id USING ERRCODE = '55000';
            END IF;
            SELECT * INTO selected_variant FROM semantic_experiment_variants
            WHERE experiment_id = NEW.experiment_id AND position = NEW.variant_position;
            IF NOT FOUND OR selected_variant.role IS DISTINCT FROM NEW.variant_role
               OR selected_variant.scenario_variant_id IS DISTINCT FROM NEW.scenario_variant_id
               OR selected_variant.scenario_position IS DISTINCT FROM NEW.scenario_position
               OR selected_variant.name IS DISTINCT FROM NEW.variant_name
               OR selected_variant.hypothesis IS DISTINCT FROM NEW.variant_hypothesis
            THEN
                RAISE EXCEPTION 'semantic trial % does not match experiment variant', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.created_at IS DISTINCT FROM parent.created_at THEN
                RAISE EXCEPTION 'semantic trial % created_at must equal experiment created_at', NEW.id
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_trials_insert_delete
        BEFORE INSERT OR DELETE ON semantic_trials
        FOR EACH ROW EXECUTE FUNCTION enforce_semantic_trial_insert_delete()
        """
    )


def _create_trial_transition_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_semantic_trial_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parent semantic_experiments%ROWTYPE;
            selected_variant semantic_experiment_variants%ROWTYPE;
            stored_initial integer;
            stored_generated integer;
            stored_comments integer;
            stored_reactions integer;
            stored_idle integer;
            stored_total integer;
        BEGIN
            SELECT * INTO parent FROM semantic_experiments
            WHERE id = OLD.experiment_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NULL THEN
                RAISE EXCEPTION 'semantic trial % requires a sealed experiment', OLD.id
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'queued' AND NEW.status = 'running'
               AND NEW.current_round = 0 AND NEW.started_at IS NOT NULL
               AND length(NEW.claimed_by_worker_id) BETWEEN 1 AND 128
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id'])
            THEN RETURN NEW; END IF;
            IF OLD.status = 'running' AND NEW.status = 'running'
               AND NEW.current_round = OLD.current_round + 1
               AND NEW.current_round <= parent.rounds
               AND (to_jsonb(NEW) - 'current_round') = (to_jsonb(OLD) - 'current_round')
            THEN
                IF EXISTS (
                    SELECT 1 FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.round > NEW.current_round
                ) OR (
                    SELECT count(*) FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                      AND event.round = NEW.current_round
                ) <> parent.persona_count OR (
                    SELECT count(DISTINCT event.persona_id)
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                      AND event.round = NEW.current_round
                ) <> parent.persona_count OR (
                    SELECT count(DISTINCT event.agent_position)
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                      AND event.round = NEW.current_round
                ) <> parent.persona_count
                THEN
                    RAISE EXCEPTION 'semantic trial % round % audience events are incomplete',
                        NEW.id, NEW.current_round USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT event.round, event.content
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'intervention'
                      AND event.round <= NEW.current_round
                    EXCEPT ALL
                    SELECT greatest(1, ceiling(
                               intervention.offset_minutes::numeric / parent.minutes_per_round
                           )::integer), intervention.content
                    FROM scenario_interventions intervention
                    WHERE intervention.scenario_id = parent.scenario_id
                      AND intervention.variant_id = NEW.scenario_variant_id
                      AND greatest(1, ceiling(
                              intervention.offset_minutes::numeric / parent.minutes_per_round
                          )::integer) <= NEW.current_round
                ) OR EXISTS (
                    SELECT greatest(1, ceiling(
                               intervention.offset_minutes::numeric / parent.minutes_per_round
                           )::integer), intervention.content
                    FROM scenario_interventions intervention
                    WHERE intervention.scenario_id = parent.scenario_id
                      AND intervention.variant_id = NEW.scenario_variant_id
                      AND greatest(1, ceiling(
                              intervention.offset_minutes::numeric / parent.minutes_per_round
                          )::integer) <= NEW.current_round
                    EXCEPT ALL
                    SELECT event.round, event.content
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'intervention'
                      AND event.round <= NEW.current_round
                ) THEN
                    RAISE EXCEPTION 'semantic trial % interventions through round % are incomplete',
                        NEW.id, NEW.current_round USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'running' AND NEW.status = 'failed'
               AND NEW.current_round = OLD.current_round
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','error_code','error_message'])
            THEN RETURN NEW; END IF;
            IF OLD.status = 'running' AND NEW.status = 'succeeded'
               AND (to_jsonb(NEW) - ARRAY[
                    'status','current_round','completed_at','engine_version','camel_version',
                    'model_name','semantic_config_sha256','prompt_schema_version',
                    'artifact_sha256','artifact_size_bytes','user_count','initial_post_count',
                    'generated_post_count','comment_count','reaction_count','do_nothing_count',
                    'observed_action_count','rounds_completed','limitations'
               ]) = (to_jsonb(OLD) - ARRAY[
                    'status','current_round','completed_at','engine_version','camel_version',
                    'model_name','semantic_config_sha256','prompt_schema_version',
                    'artifact_sha256','artifact_size_bytes','user_count','initial_post_count',
                    'generated_post_count','comment_count','reaction_count','do_nothing_count',
                    'observed_action_count','rounds_completed','limitations'
               ])
            THEN
                IF NEW.current_round <> parent.rounds OR NEW.rounds_completed <> parent.rounds
                   OR NEW.user_count <> parent.persona_count + 1
                   OR NEW.model_name IS DISTINCT FROM parent.model_name
                   OR NEW.semantic_config_sha256 IS DISTINCT FROM parent.semantic_config_sha256
                   OR NEW.prompt_schema_version IS DISTINCT FROM parent.prompt_schema_version
                   OR EXISTS (
                       SELECT 1 FROM unnest(NEW.limitations) limitation
                       WHERE length(btrim(limitation)) = 0
                   )
                THEN
                    RAISE EXCEPTION 'semantic trial % result provenance is inconsistent', NEW.id
                        USING ERRCODE = '55000';
                END IF;
                SELECT * INTO selected_variant FROM semantic_experiment_variants
                WHERE experiment_id = NEW.experiment_id AND position = NEW.variant_position;
                SELECT
                    count(*) FILTER (WHERE phase = 'intervention' AND action_type = 'create_post'),
                    count(*) FILTER (WHERE phase = 'audience' AND action_type = 'create_post'),
                    count(*) FILTER (WHERE action_type = 'create_comment'),
                    count(*) FILTER (WHERE action_type IN ('like_post','dislike_post')),
                    count(*) FILTER (WHERE action_type = 'do_nothing'), count(*)
                INTO stored_initial, stored_generated, stored_comments,
                     stored_reactions, stored_idle, stored_total
                FROM semantic_trial_events WHERE trial_id = NEW.id;
                IF NEW.initial_post_count <> stored_initial
                   OR NEW.generated_post_count <> stored_generated
                   OR NEW.comment_count <> stored_comments
                   OR NEW.reaction_count <> stored_reactions
                   OR NEW.do_nothing_count <> stored_idle
                   OR NEW.observed_action_count <> stored_total
                   OR stored_initial <> selected_variant.intervention_count
                THEN
                    RAISE EXCEPTION 'semantic trial % result counts do not match normalized events',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT round_number FROM generate_series(1, parent.rounds) round_number
                    WHERE (
                        SELECT count(*) FROM semantic_trial_events event
                        WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                          AND event.round = round_number
                    ) <> parent.persona_count
                    OR (
                        SELECT count(DISTINCT event.persona_id)
                        FROM semantic_trial_events event
                        WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                          AND event.round = round_number
                    ) <> parent.persona_count
                    OR (
                        SELECT count(DISTINCT event.agent_position)
                        FROM semantic_trial_events event
                        WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                          AND event.round = round_number
                    ) <> parent.persona_count
                ) THEN
                    RAISE EXCEPTION 'semantic trial % requires each cohort persona once per round',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM semantic_trial_events event
                    LEFT JOIN semantic_experiments experiment ON experiment.id = NEW.experiment_id
                    LEFT JOIN cohorts cohort ON cohort.id = experiment.cohort_id
                    LEFT JOIN cohort_members member
                      ON member.cohort_id = cohort.id AND member.persona_id = event.persona_id
                     AND member.position + 1 = event.agent_position
                    WHERE event.trial_id = NEW.id AND event.phase = 'audience'
                      AND member.persona_id IS NULL
                ) THEN
                    RAISE EXCEPTION 'semantic trial % contains an audience actor outside its cohort',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT event.round, event.content
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'intervention'
                    EXCEPT ALL
                    SELECT greatest(1, ceiling(
                               intervention.offset_minutes::numeric / parent.minutes_per_round
                           )::integer), intervention.content
                    FROM scenario_interventions intervention
                    WHERE intervention.scenario_id = parent.scenario_id
                      AND intervention.variant_id = NEW.scenario_variant_id
                ) OR EXISTS (
                    SELECT greatest(1, ceiling(
                               intervention.offset_minutes::numeric / parent.minutes_per_round
                           )::integer), intervention.content
                    FROM scenario_interventions intervention
                    WHERE intervention.scenario_id = parent.scenario_id
                      AND intervention.variant_id = NEW.scenario_variant_id
                    EXCEPT ALL
                    SELECT event.round, event.content
                    FROM semantic_trial_events event
                    WHERE event.trial_id = NEW.id AND event.phase = 'intervention'
                ) THEN
                    RAISE EXCEPTION 'semantic trial % intervention events do not match frozen variant',
                        NEW.id USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'semantic trial % permits only queued -> running -> terminal transitions',
                OLD.id USING ERRCODE = '55000';
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_trials_protect_update
        BEFORE UPDATE ON semantic_trials
        FOR EACH ROW EXECUTE FUNCTION protect_semantic_trial_update()
        """
    )


def _create_event_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_semantic_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parent semantic_trials%ROWTYPE;
            experiment semantic_experiments%ROWTYPE;
            expected_sequence integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'semantic trial events are append-only; % is forbidden', TG_OP
                    USING ERRCODE = '55000';
            END IF;
            SELECT * INTO parent FROM semantic_trials WHERE id = NEW.trial_id FOR UPDATE;
            IF NOT FOUND OR parent.status <> 'running' THEN
                RAISE EXCEPTION 'semantic event requires running trial %', NEW.trial_id
                    USING ERRCODE = '55000';
            END IF;
            SELECT * INTO experiment FROM semantic_experiments
            WHERE id = parent.experiment_id;
            IF NEW.round <> parent.current_round + 1 OR NEW.round > experiment.rounds THEN
                RAISE EXCEPTION
                    'semantic event round must equal the running trial next round; expected %, got %',
                    parent.current_round + 1, NEW.round
                    USING ERRCODE = '55000';
            END IF;
            SELECT coalesce(max(sequence), 0) + 1 INTO expected_sequence
            FROM semantic_trial_events WHERE trial_id = NEW.trial_id;
            IF NEW.sequence <> expected_sequence THEN
                RAISE EXCEPTION 'semantic trial % event sequence must be contiguous; expected %, got %',
                    NEW.trial_id, expected_sequence, NEW.sequence USING ERRCODE = '55000';
            END IF;
            IF NEW.phase = 'audience' AND NOT EXISTS (
                SELECT 1 FROM cohort_members member
                WHERE member.cohort_id = experiment.cohort_id
                  AND member.persona_id = NEW.persona_id
                  AND member.position + 1 = NEW.agent_position
            ) THEN
                RAISE EXCEPTION 'semantic event persona/agent does not match frozen cohort'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_events_append_only
        BEFORE INSERT OR UPDATE OR DELETE ON semantic_trial_events
        FOR EACH ROW EXECUTE FUNCTION protect_semantic_event_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_semantic_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'TRUNCATE is forbidden for semantic table %', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END; $$
        """
    )
    for table_name in (
        "semantic_experiments",
        "semantic_experiment_variants",
        "semantic_trials",
        "semantic_trial_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON {table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION reject_semantic_truncate()
            """
        )


def upgrade() -> None:
    _extend_worker_heartbeats()
    _create_experiment_tables()
    _create_canonical_functions()
    _create_experiment_guards()
    _create_child_guards()
    _create_trial_transition_guard()
    _create_event_guards()


def downgrade() -> None:
    for table_name in (
        "semantic_trial_events",
        "semantic_trials",
        "semantic_experiment_variants",
        "semantic_experiments",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    op.execute("DROP TRIGGER trg_semantic_events_append_only ON semantic_trial_events")
    op.execute("DROP TRIGGER trg_semantic_trials_protect_update ON semantic_trials")
    op.execute("DROP TRIGGER trg_semantic_trials_insert_delete ON semantic_trials")
    op.execute("DROP TRIGGER trg_semantic_variants_protect ON semantic_experiment_variants")
    op.execute("DROP TRIGGER trg_semantic_experiments_protect ON semantic_experiments")
    op.execute("DROP TRIGGER trg_semantic_experiments_draft_insert ON semantic_experiments")
    op.execute("DROP FUNCTION reject_semantic_truncate()")
    op.execute("DROP FUNCTION protect_semantic_event_mutation()")
    op.execute("DROP FUNCTION protect_semantic_trial_update()")
    op.execute("DROP FUNCTION enforce_semantic_trial_insert_delete()")
    op.execute("DROP FUNCTION protect_semantic_variant_mutation()")
    op.execute("DROP FUNCTION protect_semantic_experiment_update_delete()")
    op.execute("DROP FUNCTION enforce_semantic_experiment_draft_insert()")
    op.execute("DROP FUNCTION canonical_semantic_trial_json(uuid)")
    op.execute("DROP FUNCTION canonical_semantic_experiment_json(uuid)")
    op.drop_index("ix_semantic_events_trial_sequence", table_name="semantic_trial_events")
    op.drop_table("semantic_trial_events")
    op.drop_index("ix_semantic_trials_status_created", table_name="semantic_trials")
    op.drop_table("semantic_trials")
    op.drop_index(
        "ix_semantic_variants_scenario_variant", table_name="semantic_experiment_variants"
    )
    op.drop_table("semantic_experiment_variants")
    op.drop_index("ix_semantic_experiments_created_at", table_name="semantic_experiments")
    op.drop_table("semantic_experiments")
    op.drop_constraint(
        "ck_simulation_worker_semantic_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    op.drop_column("simulation_worker_heartbeats", "semantic_prompt_schema_version")
    op.drop_column("simulation_worker_heartbeats", "semantic_config_sha256")
    op.drop_column("simulation_worker_heartbeats", "semantic_model_name")
    op.drop_column("simulation_worker_heartbeats", "semantic_runtime_ready")
