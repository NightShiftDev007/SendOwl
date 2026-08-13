"""Add durable MatrAIx scenario-preference surveys.

Revision ID: 20260813_core_0016
Revises: 20260813_core_0015
Create Date: 2026-08-13
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0016"
down_revision: str | None = "20260813_core_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extend_worker_heartbeats() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("survey_runtime_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("survey_model_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("survey_config_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("survey_prompt_schema_version", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        "ck_simulation_worker_survey_config",
        "simulation_worker_heartbeats",
        "(survey_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready AND "
        "length(btrim(survey_model_name)) BETWEEN 1 AND 200 "
        "AND survey_model_name !~ E'[\\r\\n]' "
        "AND survey_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND survey_prompt_schema_version = 'matraix-survey-scenario-preference/v1') OR "
        "(NOT survey_runtime_ready AND survey_model_name IS NULL "
        "AND survey_config_sha256 IS NULL AND survey_prompt_schema_version IS NULL)",
    )


def _create_experiments() -> None:
    op.create_table(
        "matraix_survey_experiments",
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
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("baseline_position", sa.Integer(), nullable=False),
        sa.Column("baseline_name", sa.String(length=200), nullable=False),
        sa.Column("baseline_hypothesis", sa.Text(), nullable=False),
        sa.Column("alternative_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alternative_position", sa.Integer(), nullable=False),
        sa.Column("alternative_name", sa.String(length=200), nullable=False),
        sa.Column("alternative_hypothesis", sa.Text(), nullable=False),
        sa.Column("instrument_schema_version", sa.String(length=64), nullable=False),
        sa.Column("instrument_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("survey_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("experiment_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scenario_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_scenario_sha"),
        sa.CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_cohort_sha"),
        sa.CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_dataset_sha"),
        sa.CheckConstraint("instrument_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_instrument_sha"),
        sa.CheckConstraint("survey_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_config_sha"),
        sa.CheckConstraint("experiment_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_experiment_sha"),
        sa.CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_survey_persona_count"),
        sa.CheckConstraint("baseline_position = 0", name="ck_survey_baseline_position"),
        sa.CheckConstraint(
            "alternative_position BETWEEN 1 AND 5", name="ck_survey_alternative_position"
        ),
        sa.CheckConstraint(
            "instrument_schema_version = 'scenario-preference/v1'",
            name="ck_survey_instrument_schema",
        ),
        sa.CheckConstraint(
            "prompt_schema_version = 'matraix-survey-scenario-preference/v1'",
            name="ck_survey_prompt_schema",
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_survey_model_name",
        ),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_survey_experiment_sealed_time",
        ),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.ForeignKeyConstraint(
            ["scenario_id", "baseline_id"],
            ["scenario_variants.scenario_id", "scenario_variants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id", "alternative_id"],
            ["scenario_variants.scenario_id", "scenario_variants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_sha256", name="uq_survey_experiment_sha"),
    )
    op.create_index("ix_survey_experiments_created", "matraix_survey_experiments", ["created_at"])


def _create_trials_and_answers() -> None:
    op.create_table(
        "matraix_survey_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_position", sa.Integer(), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_external_id", sa.String(length=128), nullable=False),
        sa.Column("persona_display_name", sa.String(length=200), nullable=False),
        sa.Column("persona_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("trial_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runner_version", sa.String(length=32), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("survey_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=True),
        sa.Column("answers_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("persona_position BETWEEN 0 AND 7", name="ck_survey_trial_position"),
        sa.CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_survey_trial_persona_external_id",
        ),
        sa.CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_trial_profile_sha"
        ),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_survey_trial_sha"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_survey_trial_status"
        ),
        sa.CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL AND survey_config_sha256 IS NULL AND prompt_schema_version IS NULL AND answers_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 AND started_at IS NOT NULL AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL AND survey_config_sha256 IS NULL AND prompt_schema_version IS NULL AND answers_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 AND started_at IS NOT NULL AND completed_at IS NOT NULL AND runner_version='1.0.0' AND length(btrim(model_name)) BETWEEN 1 AND 200 AND survey_config_sha256 ~ '^[a-f0-9]{64}$' AND prompt_schema_version='matraix-survey-scenario-preference/v1' AND answers_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 AND started_at IS NOT NULL AND completed_at IS NOT NULL AND runner_version IS NULL AND model_name IS NULL AND survey_config_sha256 IS NULL AND prompt_schema_version IS NULL AND answers_sha256 IS NULL AND length(error_code) BETWEEN 1 AND 128 AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_survey_trial_state_shape",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_survey_trial_started_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_survey_trial_completed_time",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["matraix_survey_experiments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_sha256", name="uq_survey_trial_sha"),
        sa.UniqueConstraint(
            "experiment_id", "persona_position", name="uq_survey_trial_persona_position"
        ),
        sa.UniqueConstraint("experiment_id", "persona_id", name="uq_survey_trial_persona"),
    )
    op.create_index(
        "ix_survey_trials_status_created", "matraix_survey_trials", ["status", "created_at"]
    )
    op.create_table(
        "matraix_survey_answers",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_position", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("answer_type", sa.String(length=32), nullable=False),
        sa.Column("choice_value", sa.String(length=32), nullable=True),
        sa.Column("likert_value", sa.Integer(), nullable=True),
        sa.Column("free_text_value", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(question_position=0 AND question_id='preferred_variant' AND answer_type='single_choice' AND choice_value IN ('baseline','alternative') AND likert_value IS NULL AND free_text_value IS NULL) OR "
            "(question_position=1 AND question_id='alternative_support' AND answer_type='likert' AND choice_value IS NULL AND likert_value BETWEEN 1 AND 5 AND free_text_value IS NULL) OR "
            "(question_position=2 AND question_id='primary_reason' AND answer_type='free_text' AND choice_value IS NULL AND likert_value IS NULL AND length(btrim(free_text_value)) BETWEEN 1 AND 2000)",
            name="ck_survey_answer_typed_shape",
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_survey_trials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trial_id", "question_position"),
    )
    op.create_index(
        "ix_survey_answers_trial_position",
        "matraix_survey_answers",
        ["trial_id", "question_position"],
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION canonical_matraix_survey_answers_json(target_trial_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE AS $$
        DECLARE selected matraix_survey_trials%ROWTYPE;
        DECLARE answers_json text;
        BEGIN
            SELECT * INTO selected FROM matraix_survey_trials WHERE id=target_trial_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'missing Survey trial %', target_trial_id USING ERRCODE='55000';
            END IF;
            SELECT string_agg(
                '{"position":' || answer.question_position::text ||
                ',"question_id":' || to_json(answer.question_id)::text ||
                ',"type":' || to_json(answer.answer_type)::text ||
                ',"value":' || CASE answer.answer_type
                    WHEN 'single_choice' THEN to_json(answer.choice_value)::text
                    WHEN 'likert' THEN answer.likert_value::text
                    WHEN 'free_text' THEN to_json(answer.free_text_value)::text
                    ELSE 'null' END || '}',
                ',' ORDER BY answer.question_position
            ) INTO answers_json
            FROM matraix_survey_answers answer WHERE answer.trial_id=target_trial_id;
            RETURN '{"answers":[' || coalesce(answers_json, '') ||
                '],"schema":"matraix-survey-answers/v1","trial_sha256":' ||
                to_json(selected.trial_sha256)::text || '}';
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_matraix_survey_experiment_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.input_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'Survey experiment must be inserted as draft' USING ERRCODE='55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM scenarios scenario
                JOIN scenario_variants baseline ON baseline.scenario_id=scenario.id AND baseline.id=NEW.baseline_id
                JOIN scenario_variants alternative ON alternative.scenario_id=scenario.id AND alternative.id=NEW.alternative_id
                JOIN cohorts cohort ON cohort.id=NEW.cohort_id
                JOIN persona_datasets dataset ON dataset.id=cohort.dataset_id
                WHERE scenario.id=NEW.scenario_id AND scenario.sealed_at IS NOT NULL
                  AND cohort.sealed_at IS NOT NULL AND dataset.sealed_at IS NOT NULL
                  AND scenario.scenario_sha256=NEW.scenario_sha256
                  AND scenario.title=NEW.scenario_title AND scenario.decision_question=NEW.decision_question
                  AND cohort.cohort_sha256=NEW.cohort_sha256 AND cohort.title=NEW.cohort_title
                  AND cohort.persona_count=NEW.persona_count AND dataset.dataset_sha256=NEW.dataset_sha256
                  AND baseline.role='baseline' AND baseline.position=NEW.baseline_position
                  AND baseline.name=NEW.baseline_name AND baseline.hypothesis=NEW.baseline_hypothesis
                  AND alternative.role='alternative' AND alternative.position=NEW.alternative_position
                  AND alternative.name=NEW.alternative_name AND alternative.hypothesis=NEW.alternative_hypothesis
            ) THEN
                RAISE EXCEPTION 'Survey experiment does not match sealed inputs' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_survey_experiment_insert BEFORE INSERT ON matraix_survey_experiments FOR EACH ROW EXECUTE FUNCTION enforce_matraix_survey_experiment_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_matraix_survey_trial_insert_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_survey_experiments%ROWTYPE;
        BEGIN
            IF TG_OP='DELETE' THEN
                SELECT * INTO parent FROM matraix_survey_experiments WHERE id=OLD.experiment_id FOR SHARE;
                IF parent.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed Survey trial DELETE is forbidden' USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_survey_experiments WHERE id=NEW.experiment_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NOT NULL OR NEW.status <> 'queued'
               OR NEW.created_at IS DISTINCT FROM parent.created_at THEN
                RAISE EXCEPTION 'Survey trial requires an unsealed experiment draft' USING ERRCODE='55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM cohort_members member
                JOIN personas persona ON persona.dataset_id=member.dataset_id AND persona.id=member.persona_id
                WHERE member.cohort_id=parent.cohort_id AND member.position=NEW.persona_position
                  AND persona.id=NEW.persona_id AND persona.persona_id=NEW.persona_external_id
                  AND persona.display_name=NEW.persona_display_name
                  AND persona.profile_sha256=NEW.persona_profile_sha256
            ) THEN
                RAISE EXCEPTION 'Survey trial does not match frozen cohort persona' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_survey_trial_insert_delete BEFORE INSERT OR DELETE ON matraix_survey_trials FOR EACH ROW EXECUTE FUNCTION enforce_matraix_survey_trial_insert_delete()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_survey_experiment()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE stored_count integer;
        DECLARE first_position integer;
        DECLARE last_position integer;
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed Survey experiment DELETE is forbidden' USING ERRCODE='55000';
            END IF;
            IF OLD.input_sealed_at IS NULL AND NEW.input_sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'input_sealed_at')=(to_jsonb(OLD)-'input_sealed_at') THEN
                SELECT count(*), min(persona_position), max(persona_position)
                INTO stored_count, first_position, last_position
                FROM matraix_survey_trials WHERE experiment_id=NEW.id;
                IF stored_count <> NEW.persona_count OR first_position <> 0 OR last_position <> NEW.persona_count-1 THEN
                    RAISE EXCEPTION 'Survey experiment requires one contiguous trial per persona' USING ERRCODE='55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM matraix_survey_trials trial
                    LEFT JOIN cohort_members member ON member.cohort_id=NEW.cohort_id
                      AND member.position=trial.persona_position AND member.persona_id=trial.persona_id
                    LEFT JOIN personas persona ON persona.dataset_id=member.dataset_id AND persona.id=member.persona_id
                    WHERE trial.experiment_id=NEW.id AND (trial.status <> 'queued' OR member.persona_id IS NULL
                      OR trial.created_at IS DISTINCT FROM NEW.created_at
                      OR persona.persona_id IS DISTINCT FROM trial.persona_external_id
                      OR persona.display_name IS DISTINCT FROM trial.persona_display_name
                      OR persona.profile_sha256 IS DISTINCT FROM trial.persona_profile_sha256)
                ) THEN
                    RAISE EXCEPTION 'Survey trials do not exactly match sealed cohort personas' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Survey experiment input is immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_survey_experiment_protect BEFORE UPDATE OR DELETE ON matraix_survey_experiments FOR EACH ROW EXECUTE FUNCTION protect_matraix_survey_experiment()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_survey_trial_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_survey_experiments%ROWTYPE;
        DECLARE stored_count integer;
        DECLARE actual_answers_sha text;
        BEGIN
            SELECT * INTO parent FROM matraix_survey_experiments WHERE id=OLD.experiment_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NULL THEN
                RAISE EXCEPTION 'Survey transition requires sealed experiment' USING ERRCODE='55000';
            END IF;
            IF OLD.status='queued' AND NEW.status='running' AND NEW.started_at IS NOT NULL
               AND length(NEW.claimed_by_worker_id) BETWEEN 1 AND 128
               AND (to_jsonb(NEW)-ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD)-ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status='failed'
               AND (to_jsonb(NEW)-ARRAY['status','completed_at','error_code','error_message']) =
                   (to_jsonb(OLD)-ARRAY['status','completed_at','error_code','error_message']) THEN
                SELECT count(*) INTO stored_count FROM matraix_survey_answers WHERE trial_id=NEW.id;
                IF stored_count <> 0 THEN
                    RAISE EXCEPTION 'failed Survey trial must contain zero answers' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status='succeeded'
               AND (to_jsonb(NEW)-ARRAY['status','completed_at','runner_version','model_name','survey_config_sha256','prompt_schema_version','answers_sha256']) =
                   (to_jsonb(OLD)-ARRAY['status','completed_at','runner_version','model_name','survey_config_sha256','prompt_schema_version','answers_sha256']) THEN
                SELECT count(*) INTO stored_count FROM matraix_survey_answers WHERE trial_id=NEW.id;
                actual_answers_sha := encode(digest(convert_to(canonical_matraix_survey_answers_json(NEW.id), 'UTF8'), 'sha256'), 'hex');
                IF stored_count <> 3 OR NEW.runner_version <> '1.0.0'
                   OR NEW.model_name IS DISTINCT FROM parent.model_name
                   OR NEW.survey_config_sha256 IS DISTINCT FROM parent.survey_config_sha256
                   OR NEW.prompt_schema_version IS DISTINCT FROM parent.prompt_schema_version
                   OR NEW.answers_sha256 IS DISTINCT FROM actual_answers_sha THEN
                    RAISE EXCEPTION 'successful Survey result is incomplete or inconsistent' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Survey trial permits only queued -> running -> terminal' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_survey_trial_update BEFORE UPDATE ON matraix_survey_trials FOR EACH ROW EXECUTE FUNCTION protect_matraix_survey_trial_update()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_survey_answer()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_survey_trials%ROWTYPE;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Survey answers are append-only' USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_survey_trials WHERE id=NEW.trial_id FOR UPDATE;
            IF NOT FOUND OR parent.status <> 'running' OR NEW.recorded_at < parent.started_at THEN
                RAISE EXCEPTION 'Survey answer requires a running trial' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_survey_answer_protect BEFORE INSERT OR UPDATE OR DELETE ON matraix_survey_answers FOR EACH ROW EXECUTE FUNCTION protect_matraix_survey_answer()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_survey_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Survey TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    for table_name in (
        "matraix_survey_experiments",
        "matraix_survey_trials",
        "matraix_survey_answers",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_reject_truncate BEFORE TRUNCATE ON "
            f"{table_name} FOR EACH STATEMENT EXECUTE FUNCTION reject_matraix_survey_truncate()"
        )


def _drop_guards() -> None:
    for table_name in (
        "matraix_survey_answers",
        "matraix_survey_trials",
        "matraix_survey_experiments",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    op.execute("DROP TRIGGER trg_survey_answer_protect ON matraix_survey_answers")
    op.execute("DROP TRIGGER trg_survey_trial_update ON matraix_survey_trials")
    op.execute("DROP TRIGGER trg_survey_trial_insert_delete ON matraix_survey_trials")
    op.execute("DROP TRIGGER trg_survey_experiment_protect ON matraix_survey_experiments")
    op.execute("DROP TRIGGER trg_survey_experiment_insert ON matraix_survey_experiments")
    op.execute("DROP FUNCTION reject_matraix_survey_truncate()")
    op.execute("DROP FUNCTION protect_matraix_survey_answer()")
    op.execute("DROP FUNCTION protect_matraix_survey_trial_update()")
    op.execute("DROP FUNCTION protect_matraix_survey_experiment()")
    op.execute("DROP FUNCTION enforce_matraix_survey_trial_insert_delete()")
    op.execute("DROP FUNCTION enforce_matraix_survey_experiment_insert()")
    op.execute("DROP FUNCTION canonical_matraix_survey_answers_json(uuid)")


def upgrade() -> None:
    _extend_worker_heartbeats()
    _create_experiments()
    _create_trials_and_answers()
    _create_guards()


def downgrade() -> None:
    _drop_guards()
    op.drop_index("ix_survey_answers_trial_position", table_name="matraix_survey_answers")
    op.drop_table("matraix_survey_answers")
    op.drop_index("ix_survey_trials_status_created", table_name="matraix_survey_trials")
    op.drop_table("matraix_survey_trials")
    op.drop_index("ix_survey_experiments_created", table_name="matraix_survey_experiments")
    op.drop_table("matraix_survey_experiments")
    op.drop_constraint(
        "ck_simulation_worker_survey_config", "simulation_worker_heartbeats", type_="check"
    )
    for column in (
        "survey_prompt_schema_version",
        "survey_config_sha256",
        "survey_model_name",
        "survey_runtime_ready",
    ):
        op.drop_column("simulation_worker_heartbeats", column)
