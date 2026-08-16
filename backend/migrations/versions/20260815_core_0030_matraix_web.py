"""Create durable MatrAIx Playwright quote-choice evaluations.

Revision ID: 20260815_core_0030
Revises: 20260814_core_0029
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_core_0030"
down_revision: str | None = "20260814_core_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extend_heartbeats() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("web_runtime_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name, length in (
        ("web_model_name", 200),
        ("web_config_sha256", 64),
        ("web_prompt_schema_version", 64),
        ("web_executor_schema_version", 64),
        ("web_executor_spec_sha256", 64),
    ):
        op.add_column(
            "simulation_worker_heartbeats",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
    op.create_check_constraint(
        "ck_simulation_worker_web_config",
        "simulation_worker_heartbeats",
        "(web_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready "
        "AND length(btrim(web_model_name)) BETWEEN 1 AND 200 "
        "AND web_model_name !~ E'[\\r\\n]' "
        "AND web_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND web_prompt_schema_version='matraix-web-quotes-choice/v1' "
        "AND web_executor_schema_version='matraix-web-browser-executor/v1' "
        "AND web_executor_spec_sha256="
        "'36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7') OR "
        "(NOT web_runtime_ready AND web_model_name IS NULL "
        "AND web_config_sha256 IS NULL AND web_prompt_schema_version IS NULL "
        "AND web_executor_schema_version IS NULL AND web_executor_spec_sha256 IS NULL)",
    )


def _create_tables() -> None:
    op.create_table(
        "matraix_web_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_title", sa.String(length=200), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("task_version", sa.String(length=32), nullable=False),
        sa.Column("task_schema_version", sa.String(length=64), nullable=False),
        sa.Column("task_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("executor_schema_version", sa.String(length=64), nullable=False),
        sa.Column("executor_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("web_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("evaluation_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_cohort_sha"),
        sa.CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_dataset_sha"),
        sa.CheckConstraint("persona_count BETWEEN 1 AND 4", name="ck_web_eval_persona_count"),
        sa.CheckConstraint(
            "task_id='matraix/quotes-playwright-choice'", name="ck_web_eval_task_id"
        ),
        sa.CheckConstraint("task_version='1.0.0'", name="ck_web_eval_task_version"),
        sa.CheckConstraint(
            "task_schema_version='matraix-web-task/quote-choice-v1'",
            name="ck_web_eval_task_schema",
        ),
        sa.CheckConstraint(
            "task_spec_sha256='f5be8a4a377764ac77f80e3178720e914b4b069875dc5b8f3bbd6ff3508525ad'",
            name="ck_web_eval_task_sha",
        ),
        sa.CheckConstraint(
            "executor_schema_version='matraix-web-browser-executor/v1'",
            name="ck_web_eval_executor_schema",
        ),
        sa.CheckConstraint(
            "executor_spec_sha256="
            "'36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7'",
            name="ck_web_eval_executor_sha",
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_web_eval_model",
        ),
        sa.CheckConstraint("web_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_config_sha"),
        sa.CheckConstraint(
            "prompt_schema_version='matraix-web-quotes-choice/v1'",
            name="ck_web_eval_prompt_schema",
        ),
        sa.CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_eval_sha"),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_web_eval_sealed_time",
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_sha256", name="uq_web_eval_sha"),
    )
    op.create_index("ix_web_evaluations_created", "matraix_web_evaluations", ["created_at"])

    op.create_table(
        "matraix_web_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("web_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=True),
        sa.Column("trace_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("decision_subject_id", sa.String(length=64), nullable=True),
        sa.Column("decision_subject_label", sa.Text(), nullable=True),
        sa.Column("basis_primary", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("task_author", sa.String(length=200), nullable=True),
        sa.Column("need_constraint_satisfaction", sa.String(length=16), nullable=True),
        sa.Column("personal_preference_satisfaction", sa.String(length=16), nullable=True),
        sa.Column("overall_experience_rating", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("persona_position BETWEEN 0 AND 3", name="ck_web_trial_position"),
        sa.CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_web_trial_persona_external_id",
        ),
        sa.CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200 "
            "AND persona_display_name !~ E'[\\r\\n]'",
            name="ck_web_trial_persona_name",
        ),
        sa.CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_trial_profile_sha"
        ),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_trial_sha"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_web_trial_status"
        ),
        sa.CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version='1.0.0' AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND web_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version='matraix-web-quotes-choice/v1' "
            "AND trace_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' "
            "AND decision_subject_id ~ '^[a-f0-9]{64}$' "
            "AND decision_subject_label IS NOT NULL AND basis_primary IS NOT NULL "
            "AND reason IS NOT NULL AND task_author IS NOT NULL "
            "AND need_constraint_satisfaction IS NOT NULL "
            "AND personal_preference_satisfaction IS NOT NULL "
            "AND overall_experience_rating IS NOT NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND runner_version IS NULL AND model_name IS NULL "
            "AND web_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND trace_sha256 IS NULL AND result_sha256 IS NULL "
            "AND decision_subject_id IS NULL AND decision_subject_label IS NULL "
            "AND basis_primary IS NULL AND reason IS NULL AND task_author IS NULL "
            "AND need_constraint_satisfaction IS NULL "
            "AND personal_preference_satisfaction IS NULL "
            "AND overall_experience_rating IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_web_trial_state_shape",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_web_trial_started_time"
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_web_trial_completed_time",
        ),
        sa.CheckConstraint(
            "decision_subject_label IS NULL OR "
            "length(btrim(decision_subject_label)) BETWEEN 1 AND 2000",
            name="ck_web_trial_subject_label",
        ),
        sa.CheckConstraint(
            "basis_primary IS NULL OR basis_primary IN "
            "('price','quality','features','convenience','taste','trust','familiarity',"
            "'novelty','fit','other')",
            name="ck_web_trial_basis",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) BETWEEN 20 AND 2000",
            name="ck_web_trial_reason",
        ),
        sa.CheckConstraint(
            "task_author IS NULL OR length(btrim(task_author)) BETWEEN 1 AND 200",
            name="ck_web_trial_author",
        ),
        sa.CheckConstraint(
            "need_constraint_satisfaction IS NULL OR "
            "need_constraint_satisfaction IN ('yes','partially','no')",
            name="ck_web_trial_need",
        ),
        sa.CheckConstraint(
            "personal_preference_satisfaction IS NULL OR "
            "personal_preference_satisfaction IN ('yes','partially','no')",
            name="ck_web_trial_preference",
        ),
        sa.CheckConstraint(
            "overall_experience_rating IS NULL OR overall_experience_rating BETWEEN 1 AND 10",
            name="ck_web_trial_rating",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["matraix_web_evaluations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_sha256", name="uq_web_trial_sha"),
        sa.UniqueConstraint("evaluation_id", "persona_position", name="uq_web_trial_eval_position"),
        sa.UniqueConstraint("evaluation_id", "persona_id", name="uq_web_trial_eval_persona"),
    )
    op.create_index("ix_web_trials_status_created", "matraix_web_trials", ["status", "created_at"])

    op.create_table(
        "matraix_web_pages",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("screenshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 2", name="ck_web_page_position"),
        sa.CheckConstraint(
            "url ~ '^https://quotes\\.toscrape\\.com/(page/[1-9][0-9]*/)?$'",
            name="ck_web_page_url",
        ),
        sa.CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="ck_web_page_title"),
        sa.CheckConstraint(
            "screenshot_sha256 ~ '^[a-f0-9]{64}$'", name="ck_web_page_screenshot_sha"
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_web_trials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trial_id", "position"),
    )

    op.create_table(
        "matraix_web_quotes",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("page_position", sa.Integer(), nullable=False),
        sa.Column("quote_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=128)), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 59", name="ck_web_quote_position"),
        sa.CheckConstraint("page_position BETWEEN 0 AND 2", name="ck_web_quote_page_position"),
        sa.CheckConstraint("quote_id ~ '^[a-f0-9]{64}$'", name="ck_web_quote_id"),
        sa.CheckConstraint("length(btrim(text)) BETWEEN 1 AND 2000", name="ck_web_quote_text"),
        sa.CheckConstraint("length(btrim(author)) BETWEEN 1 AND 200", name="ck_web_quote_author"),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_web_trials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["trial_id", "page_position"],
            ["matraix_web_pages.trial_id", "matraix_web_pages.position"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("trial_id", "position"),
        sa.UniqueConstraint("trial_id", "quote_id", name="uq_web_quote_trial_id"),
    )


def _create_hash_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION matraix_web_digest(parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE payload bytea := ''::bytea;
        DECLARE part text;
        DECLARE first_part boolean := true;
        BEGIN
            FOREACH part IN ARRAY parts LOOP
                IF part IS NULL THEN
                    RAISE EXCEPTION 'MatrAIx Web hash part is null' USING ERRCODE='55000';
                END IF;
                IF NOT first_part THEN payload := payload || decode('00', 'hex'); END IF;
                payload := payload || convert_to(part, 'UTF8');
                first_part := false;
            END LOOP;
            RETURN encode(digest(payload, 'sha256'), 'hex');
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION canonical_matraix_web_trace_sha(target_trial_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE AS $$
        DECLARE parts text[];
        DECLARE page_record matraix_web_pages%ROWTYPE;
        DECLARE quote_record matraix_web_quotes%ROWTYPE;
        DECLARE tag text;
        DECLARE trial_sha text;
        BEGIN
            SELECT trial_sha256 INTO trial_sha FROM matraix_web_trials WHERE id=target_trial_id;
            IF trial_sha IS NULL THEN
                RAISE EXCEPTION 'missing MatrAIx Web trial %', target_trial_id
                    USING ERRCODE='55000';
            END IF;
            parts := ARRAY['matraix-web-trace/v1', trial_sha];
            FOR page_record IN SELECT * FROM matraix_web_pages
                WHERE trial_id=target_trial_id ORDER BY position
            LOOP
                parts := parts || ARRAY[
                    page_record.position::text, page_record.url, page_record.title,
                    page_record.screenshot_sha256
                ];
                FOR quote_record IN SELECT * FROM matraix_web_quotes
                    WHERE trial_id=target_trial_id AND page_position=page_record.position
                    ORDER BY position
                LOOP
                    parts := parts || ARRAY[
                        quote_record.position::text, quote_record.quote_id,
                        quote_record.text, quote_record.author
                    ];
                    FOREACH tag IN ARRAY quote_record.tags LOOP
                        parts := parts || tag;
                    END LOOP;
                END LOOP;
            END LOOP;
            RETURN matraix_web_digest(parts);
        END; $$
        """
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_matraix_web_evaluation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE trial_count integer;
        DECLARE actual_hash text;
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed MatrAIx Web evaluation DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                IF NEW.input_sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'MatrAIx Web evaluation must be inserted as draft'
                        USING ERRCODE='55000';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM cohorts cohort
                    JOIN persona_datasets dataset ON dataset.id=cohort.dataset_id
                    WHERE cohort.id=NEW.cohort_id AND cohort.sealed_at IS NOT NULL
                      AND dataset.sealed_at IS NOT NULL
                      AND cohort.cohort_sha256=NEW.cohort_sha256
                      AND cohort.title=NEW.cohort_title
                      AND cohort.persona_count=NEW.persona_count
                      AND dataset.dataset_sha256=NEW.dataset_sha256
                ) THEN
                    RAISE EXCEPTION 'MatrAIx Web evaluation does not match sealed Cohort'
                        USING ERRCODE='55000';
                END IF;
                actual_hash := matraix_web_digest(ARRAY[
                    'matraix-web-evaluation/v1', NEW.task_spec_sha256,
                    NEW.executor_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                    NEW.web_config_sha256, NEW.prompt_schema_version
                ]);
                IF NEW.evaluation_sha256 IS DISTINCT FROM actual_hash THEN
                    RAISE EXCEPTION 'MatrAIx Web evaluation hash mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.input_sealed_at IS NULL AND NEW.input_sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'input_sealed_at')=(to_jsonb(OLD)-'input_sealed_at')
            THEN
                SELECT count(*) INTO trial_count FROM matraix_web_trials
                WHERE evaluation_id=NEW.id;
                IF trial_count <> NEW.persona_count OR EXISTS (
                    SELECT 1 FROM matraix_web_trials trial
                    LEFT JOIN cohort_members member
                      ON member.cohort_id=NEW.cohort_id
                     AND member.position=trial.persona_position
                     AND member.persona_id=trial.persona_id
                    LEFT JOIN personas persona
                      ON persona.dataset_id=member.dataset_id AND persona.id=member.persona_id
                    WHERE trial.evaluation_id=NEW.id
                      AND (trial.status <> 'queued' OR member.persona_id IS NULL
                           OR trial.created_at IS DISTINCT FROM NEW.created_at
                           OR persona.persona_id IS DISTINCT FROM trial.persona_external_id
                           OR persona.display_name IS DISTINCT FROM trial.persona_display_name
                           OR persona.profile_sha256 IS DISTINCT FROM trial.persona_profile_sha256)
                ) THEN
                    RAISE EXCEPTION 'MatrAIx Web trials do not match the frozen Cohort'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'MatrAIx Web evaluation input is immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_web_evaluation_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_web_evaluations FOR EACH ROW EXECUTE FUNCTION protect_matraix_web_evaluation()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_web_trial()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_web_evaluations%ROWTYPE;
        DECLARE expected_sha text;
        DECLARE page_count integer;
        DECLARE quote_count integer;
        DECLARE first_page_position integer;
        DECLARE last_page_position integer;
        DECLARE actual_trace_sha text;
        DECLARE actual_result_sha text;
        BEGIN
            IF TG_OP='DELETE' THEN
                SELECT * INTO parent FROM matraix_web_evaluations
                WHERE id=OLD.evaluation_id FOR SHARE;
                IF parent.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed MatrAIx Web trial DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_web_evaluations
            WHERE id=COALESCE(NEW.evaluation_id, OLD.evaluation_id) FOR SHARE;
            IF TG_OP='INSERT' THEN
                IF NOT FOUND OR parent.input_sealed_at IS NOT NULL OR NEW.status <> 'queued'
                   OR NEW.created_at IS DISTINCT FROM parent.created_at
                THEN
                    RAISE EXCEPTION 'MatrAIx Web trial requires an unsealed draft parent'
                        USING ERRCODE='55000';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM cohort_members member
                    JOIN personas persona
                      ON persona.dataset_id=member.dataset_id AND persona.id=member.persona_id
                    WHERE member.cohort_id=parent.cohort_id
                      AND member.position=NEW.persona_position
                      AND persona.id=NEW.persona_id
                      AND persona.persona_id=NEW.persona_external_id
                      AND persona.display_name=NEW.persona_display_name
                      AND persona.profile_sha256=NEW.persona_profile_sha256
                ) THEN
                    RAISE EXCEPTION 'MatrAIx Web trial does not match frozen Persona'
                        USING ERRCODE='55000';
                END IF;
                expected_sha := matraix_web_digest(ARRAY[
                    'matraix-web-trial/v1', parent.evaluation_sha256,
                    NEW.persona_position::text, NEW.persona_id::text,
                    NEW.persona_external_id, NEW.persona_display_name,
                    NEW.persona_profile_sha256
                ]);
                IF NEW.trial_sha256 IS DISTINCT FROM expected_sha THEN
                    RAISE EXCEPTION 'MatrAIx Web trial hash mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NOT FOUND OR parent.input_sealed_at IS NULL THEN
                RAISE EXCEPTION 'MatrAIx Web transition requires sealed parent'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND NEW.started_at IS NOT NULL AND length(NEW.claimed_by_worker_id) BETWEEN 1 AND 128
               AND (to_jsonb(NEW)-ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD)-ARRAY['status','started_at','claimed_by_worker_id'])
            THEN RETURN NEW; END IF;
            IF OLD.status='running' AND NEW.status='failed'
               AND (to_jsonb(NEW)-ARRAY['status','completed_at','error_code','error_message']) =
                   (to_jsonb(OLD)-ARRAY['status','completed_at','error_code','error_message'])
            THEN RETURN NEW; END IF;
            IF OLD.status='running' AND NEW.status='succeeded'
               AND (to_jsonb(NEW)-ARRAY[
                    'status','completed_at','runner_version','model_name','web_config_sha256',
                    'prompt_schema_version','trace_sha256','result_sha256',
                    'decision_subject_id','decision_subject_label','basis_primary','reason',
                    'task_author','need_constraint_satisfaction',
                    'personal_preference_satisfaction','overall_experience_rating'
               ]) = (to_jsonb(OLD)-ARRAY[
                    'status','completed_at','runner_version','model_name','web_config_sha256',
                    'prompt_schema_version','trace_sha256','result_sha256',
                    'decision_subject_id','decision_subject_label','basis_primary','reason',
                    'task_author','need_constraint_satisfaction',
                    'personal_preference_satisfaction','overall_experience_rating'
               ])
            THEN
                SELECT count(*), min(position), max(position)
                INTO page_count, first_page_position, last_page_position
                FROM matraix_web_pages WHERE trial_id=NEW.id;
                SELECT count(*) INTO quote_count FROM matraix_web_quotes WHERE trial_id=NEW.id;
                IF page_count <> 3 OR first_page_position <> 0 OR last_page_position <> 2
                   OR quote_count < 3 OR quote_count > 60
                THEN
                    RAISE EXCEPTION 'successful MatrAIx Web trial requires bounded observations'
                        USING ERRCODE='55000';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM matraix_web_quotes quote
                    WHERE quote.trial_id=NEW.id AND quote.quote_id=NEW.decision_subject_id
                      AND quote.text=NEW.decision_subject_label AND quote.author=NEW.task_author
                ) THEN
                    RAISE EXCEPTION 'selected quote was not present in recorded observations'
                        USING ERRCODE='55000';
                END IF;
                actual_trace_sha := canonical_matraix_web_trace_sha(NEW.id);
                actual_result_sha := matraix_web_digest(ARRAY[
                    'matraix-web-result/v1', NEW.trial_sha256, actual_trace_sha,
                    NEW.decision_subject_id, NEW.decision_subject_label, 'selected',
                    NEW.basis_primary, 'compared_multiple', NEW.reason, NEW.task_author,
                    NEW.need_constraint_satisfaction, NEW.personal_preference_satisfaction,
                    NEW.overall_experience_rating::text
                ]);
                IF NEW.runner_version <> '1.0.0'
                   OR NEW.model_name IS DISTINCT FROM parent.model_name
                   OR NEW.web_config_sha256 IS DISTINCT FROM parent.web_config_sha256
                   OR NEW.prompt_schema_version IS DISTINCT FROM parent.prompt_schema_version
                   OR NEW.trace_sha256 IS DISTINCT FROM actual_trace_sha
                   OR NEW.result_sha256 IS DISTINCT FROM actual_result_sha
                THEN
                    RAISE EXCEPTION 'successful MatrAIx Web result is inconsistent'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'MatrAIx Web trial permits queued -> running -> terminal only'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_web_trial_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_web_trials FOR EACH ROW EXECUTE FUNCTION protect_matraix_web_trial()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_web_observation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_status text;
        DECLARE started timestamptz;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'MatrAIx Web observations are append-only' USING ERRCODE='55000';
            END IF;
            SELECT status, started_at INTO parent_status, started FROM matraix_web_trials
            WHERE id=NEW.trial_id FOR UPDATE;
            IF parent_status <> 'running' THEN
                RAISE EXCEPTION 'MatrAIx Web observation requires running trial'
                    USING ERRCODE='55000';
            END IF;
            IF TG_TABLE_NAME='matraix_web_pages' THEN
                IF NEW.observed_at < started THEN
                    RAISE EXCEPTION 'MatrAIx Web page observation predates trial start'
                        USING ERRCODE='55000';
                END IF;
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    for table in ("matraix_web_pages", "matraix_web_quotes"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_protect BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_matraix_web_observation()"
        )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_web_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'MatrAIx Web TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    for table in (
        "matraix_web_evaluations",
        "matraix_web_trials",
        "matraix_web_pages",
        "matraix_web_quotes",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_reject_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_matraix_web_truncate()"
        )


def upgrade() -> None:
    _extend_heartbeats()
    _create_tables()
    _create_hash_functions()
    _create_guards()


def downgrade() -> None:
    for table in (
        "matraix_web_quotes",
        "matraix_web_pages",
        "matraix_web_trials",
        "matraix_web_evaluations",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_reject_truncate ON {table}")
    op.execute("DROP TRIGGER trg_matraix_web_quotes_protect ON matraix_web_quotes")
    op.execute("DROP TRIGGER trg_matraix_web_pages_protect ON matraix_web_pages")
    op.execute("DROP TRIGGER trg_web_trial_protect ON matraix_web_trials")
    op.execute("DROP TRIGGER trg_web_evaluation_protect ON matraix_web_evaluations")
    op.execute("DROP FUNCTION reject_matraix_web_truncate()")
    op.execute("DROP FUNCTION protect_matraix_web_observation()")
    op.execute("DROP FUNCTION protect_matraix_web_trial()")
    op.execute("DROP FUNCTION protect_matraix_web_evaluation()")
    op.execute("DROP FUNCTION canonical_matraix_web_trace_sha(uuid)")
    op.execute("DROP FUNCTION matraix_web_digest(text[])")
    op.drop_table("matraix_web_quotes")
    op.drop_table("matraix_web_pages")
    op.drop_index("ix_web_trials_status_created", table_name="matraix_web_trials")
    op.drop_table("matraix_web_trials")
    op.drop_index("ix_web_evaluations_created", table_name="matraix_web_evaluations")
    op.drop_table("matraix_web_evaluations")
    op.drop_constraint(
        "ck_simulation_worker_web_config", "simulation_worker_heartbeats", type_="check"
    )
    for name in (
        "web_executor_spec_sha256",
        "web_executor_schema_version",
        "web_prompt_schema_version",
        "web_config_sha256",
        "web_model_name",
        "web_runtime_ready",
    ):
        op.drop_column("simulation_worker_heartbeats", name)
