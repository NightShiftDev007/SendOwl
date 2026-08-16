"""Add durable MatrAIx source-sample chatbot evaluations.

Revision ID: 20260813_core_0021
Revises: 20260813_core_0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0021"
down_revision: str | None = "20260813_core_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_ID = "matraix/acme-support-order-4521"
TASK_VERSION = "1.0.0"
TASK_SCHEMA_VERSION = "matraix-chat-task/acme-support-v1"
TASK_SPEC_SHA256 = "4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1"
SUT_SPEC_SHA256 = "b3609ac5ab58a4994c497f276d4689b8272150a9251676ddef84ebe9e8bdc980"
PROMPT_SCHEMA_VERSION = "matraix-chat-acme-support/v1"
FEEDBACK_SCHEMA_VERSION = "matraix-chat-feedback/acme-support-v1"


def _extend_worker_heartbeats() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("chat_runtime_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name, length in (
        ("chat_model_name", 200),
        ("chat_config_sha256", 64),
        ("chat_prompt_schema_version", 64),
        ("chat_sut_task_id", 128),
        ("chat_sut_task_version", 32),
        ("chat_sut_spec_sha256", 64),
    ):
        op.add_column(
            "simulation_worker_heartbeats",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready AND "
        "length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        f"AND chat_prompt_schema_version = '{PROMPT_SCHEMA_VERSION}' "
        f"AND chat_sut_task_id = '{TASK_ID}' "
        f"AND chat_sut_task_version = '{TASK_VERSION}' "
        f"AND chat_sut_spec_sha256 = '{SUT_SPEC_SHA256}') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )


def _create_evaluations() -> None:
    op.create_table(
        "matraix_chat_evaluations",
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
        sa.Column("sut_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("chat_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("evaluation_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("cohort_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_cohort_sha"),
        sa.CheckConstraint("dataset_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_dataset_sha"),
        sa.CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_chat_eval_persona_count"),
        sa.CheckConstraint(f"task_id = '{TASK_ID}'", name="ck_chat_eval_task_id"),
        sa.CheckConstraint(f"task_version = '{TASK_VERSION}'", name="ck_chat_eval_task_version"),
        sa.CheckConstraint(
            f"task_schema_version = '{TASK_SCHEMA_VERSION}'",
            name="ck_chat_eval_task_schema",
        ),
        sa.CheckConstraint(
            f"task_spec_sha256 = '{TASK_SPEC_SHA256}'", name="ck_chat_eval_task_spec_sha"
        ),
        sa.CheckConstraint(
            f"sut_spec_sha256 = '{SUT_SPEC_SHA256}'", name="ck_chat_eval_sut_spec_sha"
        ),
        sa.CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_chat_eval_model_name",
        ),
        sa.CheckConstraint("chat_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_config_sha"),
        sa.CheckConstraint(
            f"prompt_schema_version = '{PROMPT_SCHEMA_VERSION}'",
            name="ck_chat_eval_prompt_schema",
        ),
        sa.CheckConstraint("evaluation_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_eval_sha"),
        sa.CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_chat_eval_sealed_time",
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_sha256", name="uq_chat_eval_sha"),
    )
    op.create_index(
        "ix_chat_evaluations_created",
        "matraix_chat_evaluations",
        ["created_at"],
    )


def _create_trials() -> None:
    op.create_table(
        "matraix_chat_trials",
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
        sa.Column("chat_config_sha256", sa.String(length=64), nullable=True),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=True),
        sa.Column("transcript_sha256", sa.String(length=64), nullable=True),
        sa.Column("feedback_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("outcome_status", sa.String(length=32), nullable=True),
        sa.Column("next_step_owner", sa.String(length=16), nullable=True),
        sa.Column("conversation_path", sa.String(length=32), nullable=True),
        sa.Column("resolution_progression", sa.String(length=32), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=True),
        sa.Column("customer_turn_count", sa.Integer(), nullable=True),
        sa.Column("support_turn_count", sa.Integer(), nullable=True),
        sa.Column("clarification_question_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("persona_position BETWEEN 0 AND 7", name="ck_chat_trial_position"),
        sa.CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_chat_trial_persona_external_id",
        ),
        sa.CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200 "
            "AND persona_display_name !~ E'[\\r\\n]'",
            name="ck_chat_trial_persona_display_name",
        ),
        sa.CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_chat_trial_profile_sha",
        ),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_chat_trial_sha"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_chat_trial_status",
        ),
        sa.CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND chat_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND transcript_sha256 IS NULL AND feedback_sha256 IS NULL "
            "AND result_sha256 IS NULL AND outcome_status IS NULL "
            "AND next_step_owner IS NULL AND conversation_path IS NULL "
            "AND resolution_progression IS NULL AND message_count IS NULL "
            "AND customer_turn_count IS NULL AND support_turn_count IS NULL "
            "AND clarification_question_count IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='running' AND claimed_by_worker_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9_.:-]*$' AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND chat_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND transcript_sha256 IS NULL AND feedback_sha256 IS NULL "
            "AND result_sha256 IS NULL AND outcome_status IS NULL "
            "AND next_step_owner IS NULL AND conversation_path IS NULL "
            "AND resolution_progression IS NULL AND message_count IS NULL "
            "AND customer_turn_count IS NULL AND support_turn_count IS NULL "
            "AND clarification_question_count IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='succeeded' AND claimed_by_worker_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9_.:-]*$' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND runner_version='1.0.0' "
            "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
            f"AND prompt_schema_version='{PROMPT_SCHEMA_VERSION}' "
            "AND transcript_sha256 ~ '^[a-f0-9]{64}$' "
            "AND feedback_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' "
            "AND outcome_status IN ('resolved','partially_resolved','unresolved') "
            "AND next_step_owner IN ('user','support','none') "
            "AND conversation_path IN "
            "('clarify_then_resolve','clarify_then_partial','stalled') "
            "AND resolution_progression IN ('single_response','looped','advanced') "
            "AND message_count BETWEEN 4 AND 40 AND message_count % 2 = 0 "
            "AND customer_turn_count BETWEEN 2 AND 20 "
            "AND support_turn_count = customer_turn_count "
            "AND message_count = customer_turn_count + support_turn_count "
            "AND clarification_question_count BETWEEN 0 AND support_turn_count "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND claimed_by_worker_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9_.:-]*$' AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND runner_version IS NULL AND model_name IS NULL "
            "AND chat_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND transcript_sha256 IS NULL AND feedback_sha256 IS NULL "
            "AND result_sha256 IS NULL AND outcome_status IS NULL "
            "AND next_step_owner IS NULL AND conversation_path IS NULL "
            "AND resolution_progression IS NULL AND message_count IS NULL "
            "AND customer_turn_count IS NULL AND support_turn_count IS NULL "
            "AND clarification_question_count IS NULL "
            "AND error_code ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$' "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_chat_trial_state_shape",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_chat_trial_started_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_chat_trial_completed_time",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["matraix_chat_evaluations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_sha256", name="uq_chat_trial_sha"),
        sa.UniqueConstraint(
            "evaluation_id", "persona_position", name="uq_chat_trial_eval_position"
        ),
        sa.UniqueConstraint("evaluation_id", "persona_id", name="uq_chat_trial_eval_persona"),
    )
    op.create_index(
        "ix_chat_trials_status_created",
        "matraix_chat_trials",
        ["status", "created_at"],
    )


def _create_artifacts() -> None:
    op.create_table(
        "matraix_chat_messages",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 39", name="ck_chat_message_position"),
        sa.CheckConstraint("role IN ('customer','support')", name="ck_chat_message_role"),
        sa.CheckConstraint(
            "content = btrim(content) AND length(btrim(content)) BETWEEN 1 AND 8000 "
            "AND content ~ '[^[:space:]]'",
            name="ck_chat_message_content",
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_chat_trials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trial_id", "position"),
    )
    op.create_index(
        "ix_chat_messages_trial_position",
        "matraix_chat_messages",
        ["trial_id", "position"],
    )
    op.create_table(
        "matraix_chat_feedback",
        sa.Column("trial_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("need_constraint_satisfaction", sa.String(length=16), nullable=False),
        sa.Column("personal_preference_satisfaction", sa.String(length=16), nullable=False),
        sa.Column("overall_experience_rating", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("asked_useful_clarification_questions", sa.Boolean(), nullable=False),
        sa.Column("clarifying_notes", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"schema_version = '{FEEDBACK_SCHEMA_VERSION}'",
            name="ck_chat_feedback_schema",
        ),
        sa.CheckConstraint(
            "need_constraint_satisfaction IN ('yes','partially','no')",
            name="ck_chat_feedback_need",
        ),
        sa.CheckConstraint(
            "personal_preference_satisfaction IN ('yes','partially','no')",
            name="ck_chat_feedback_preference",
        ),
        sa.CheckConstraint(
            "overall_experience_rating BETWEEN 1 AND 10",
            name="ck_chat_feedback_rating",
        ),
        sa.CheckConstraint(
            "reason = btrim(reason) AND length(btrim(reason)) BETWEEN 1 AND 2000 "
            "AND reason ~ '[^[:space:]]'",
            name="ck_chat_feedback_reason",
        ),
        sa.CheckConstraint(
            "clarifying_notes = btrim(clarifying_notes) "
            "AND length(btrim(clarifying_notes)) BETWEEN 1 AND 2000 "
            "AND clarifying_notes ~ '[^[:space:]]'",
            name="ck_chat_feedback_notes",
        ),
        sa.ForeignKeyConstraint(["trial_id"], ["matraix_chat_trials.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trial_id"),
    )


def _create_hash_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION matraix_chat_sha256_nul(parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
        DECLARE payload bytea := ''::bytea;
        DECLARE position integer;
        BEGIN
            IF array_length(parts, 1) IS NULL THEN
                RAISE EXCEPTION 'chat hash requires at least one part' USING ERRCODE='22023';
            END IF;
            FOR position IN 1..array_length(parts, 1) LOOP
                IF parts[position] IS NULL THEN
                    RAISE EXCEPTION 'chat hash part % is null', position USING ERRCODE='22004';
                END IF;
                IF position > 1 THEN payload := payload || decode('00', 'hex'); END IF;
                payload := payload || convert_to(parts[position], 'UTF8');
            END LOOP;
            RETURN encode(digest(payload, 'sha256'), 'hex');
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION matraix_chat_transcript_sha(target_trial_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE selected matraix_chat_trials%ROWTYPE;
        DECLARE message matraix_chat_messages%ROWTYPE;
        DECLARE parts text[];
        BEGIN
            SELECT * INTO selected FROM matraix_chat_trials WHERE id=target_trial_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'missing Chat trial %', target_trial_id USING ERRCODE='55000';
            END IF;
            parts := ARRAY['matraix-chat-transcript/v1', selected.trial_sha256];
            FOR message IN
                SELECT * FROM matraix_chat_messages
                WHERE trial_id=target_trial_id ORDER BY position
            LOOP
                parts := parts || ARRAY[message.position::text, message.role, message.content];
            END LOOP;
            RETURN matraix_chat_sha256_nul(parts);
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION matraix_chat_feedback_sha(target_trial_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE selected matraix_chat_trials%ROWTYPE;
        DECLARE feedback matraix_chat_feedback%ROWTYPE;
        BEGIN
            SELECT * INTO selected FROM matraix_chat_trials WHERE id=target_trial_id;
            SELECT * INTO feedback FROM matraix_chat_feedback WHERE trial_id=target_trial_id;
            IF selected.id IS NULL OR feedback.trial_id IS NULL THEN
                RAISE EXCEPTION 'missing Chat trial or feedback %', target_trial_id
                    USING ERRCODE='55000';
            END IF;
            RETURN matraix_chat_sha256_nul(ARRAY[
                'matraix-chat-feedback/v1', selected.trial_sha256, feedback.schema_version,
                feedback.need_constraint_satisfaction,
                feedback.personal_preference_satisfaction,
                feedback.overall_experience_rating::text, feedback.reason,
                feedback.asked_useful_clarification_questions::text,
                feedback.clarifying_notes
            ]);
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION matraix_chat_result_sha(target_trial_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE selected matraix_chat_trials%ROWTYPE;
        BEGIN
            SELECT * INTO selected FROM matraix_chat_trials WHERE id=target_trial_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'missing Chat trial %', target_trial_id USING ERRCODE='55000';
            END IF;
            RETURN matraix_chat_sha256_nul(ARRAY[
                'matraix-chat-result/v1', selected.trial_sha256,
                selected.transcript_sha256, selected.feedback_sha256,
                selected.outcome_status, selected.next_step_owner,
                selected.conversation_path, selected.resolution_progression,
                selected.message_count::text, selected.customer_turn_count::text,
                selected.support_turn_count::text,
                selected.clarification_question_count::text
            ]);
        END; $$
        """
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION enforce_matraix_chat_evaluation_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actual_sha text;
        BEGIN
            IF NEW.input_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'Chat evaluation must be inserted as draft'
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
                RAISE EXCEPTION 'Chat evaluation does not match a sealed Cohort'
                    USING ERRCODE='55000';
            END IF;
            actual_sha := matraix_chat_sha256_nul(ARRAY[
                'matraix-chat-evaluation/v1', NEW.task_spec_sha256, NEW.sut_spec_sha256,
                NEW.cohort_id::text, NEW.cohort_sha256, NEW.dataset_sha256,
                NEW.persona_count::text, NEW.model_name, NEW.chat_config_sha256,
                NEW.prompt_schema_version
            ]);
            IF actual_sha IS DISTINCT FROM NEW.evaluation_sha256 THEN
                RAISE EXCEPTION 'Chat evaluation hash does not match frozen inputs'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_evaluation_insert BEFORE INSERT ON "
        "matraix_chat_evaluations FOR EACH ROW EXECUTE FUNCTION "
        "enforce_matraix_chat_evaluation_insert()"
    )
    op.execute(
        """
        CREATE FUNCTION enforce_matraix_chat_trial_insert_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_chat_evaluations%ROWTYPE;
        DECLARE actual_sha text;
        BEGIN
            IF TG_OP='DELETE' THEN
                SELECT * INTO parent FROM matraix_chat_evaluations
                WHERE id=OLD.evaluation_id FOR SHARE;
                IF parent.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed Chat trial DELETE is forbidden' USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_chat_evaluations
            WHERE id=NEW.evaluation_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NOT NULL OR NEW.status <> 'queued'
               OR NEW.created_at IS DISTINCT FROM parent.created_at THEN
                RAISE EXCEPTION 'Chat trial requires an unsealed evaluation draft'
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
                RAISE EXCEPTION 'Chat trial does not match frozen Cohort Persona'
                    USING ERRCODE='55000';
            END IF;
            actual_sha := matraix_chat_sha256_nul(ARRAY[
                'matraix-chat-trial/v1', parent.evaluation_sha256,
                NEW.persona_position::text, NEW.persona_id::text,
                NEW.persona_external_id, NEW.persona_display_name,
                NEW.persona_profile_sha256
            ]);
            IF actual_sha IS DISTINCT FROM NEW.trial_sha256 THEN
                RAISE EXCEPTION 'Chat trial hash does not match frozen Persona'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_trial_insert_delete BEFORE INSERT OR DELETE ON "
        "matraix_chat_trials FOR EACH ROW EXECUTE FUNCTION "
        "enforce_matraix_chat_trial_insert_delete()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_chat_evaluation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE stored_count integer;
        DECLARE first_position integer;
        DECLARE last_position integer;
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.input_sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed Chat evaluation DELETE is forbidden'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.input_sealed_at IS NULL AND NEW.input_sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'input_sealed_at')=(to_jsonb(OLD)-'input_sealed_at') THEN
                SELECT count(*), min(persona_position), max(persona_position)
                INTO stored_count, first_position, last_position
                FROM matraix_chat_trials WHERE evaluation_id=NEW.id;
                IF stored_count <> NEW.persona_count OR first_position <> 0
                   OR last_position <> NEW.persona_count-1 THEN
                    RAISE EXCEPTION 'Chat evaluation requires one contiguous trial per Persona'
                        USING ERRCODE='55000';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM matraix_chat_trials trial
                    LEFT JOIN cohort_members member ON member.cohort_id=NEW.cohort_id
                      AND member.position=trial.persona_position
                      AND member.persona_id=trial.persona_id
                    LEFT JOIN personas persona ON persona.dataset_id=member.dataset_id
                      AND persona.id=member.persona_id
                    WHERE trial.evaluation_id=NEW.id
                      AND (trial.status <> 'queued' OR member.persona_id IS NULL
                        OR trial.created_at IS DISTINCT FROM NEW.created_at
                        OR persona.persona_id IS DISTINCT FROM trial.persona_external_id
                        OR persona.display_name IS DISTINCT FROM trial.persona_display_name
                        OR persona.profile_sha256 IS DISTINCT FROM trial.persona_profile_sha256)
                ) THEN
                    RAISE EXCEPTION 'Chat trials do not exactly match sealed Cohort Personas'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Chat evaluation input is immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_evaluation_protect BEFORE UPDATE OR DELETE ON "
        "matraix_chat_evaluations FOR EACH ROW EXECUTE FUNCTION "
        "protect_matraix_chat_evaluation()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_chat_message()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_chat_trials%ROWTYPE;
        DECLARE stored_count integer;
        DECLARE expected_role text;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Chat messages are append-only' USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_chat_trials WHERE id=NEW.trial_id FOR UPDATE;
            IF NOT FOUND OR parent.status <> 'running' OR NEW.recorded_at < parent.started_at THEN
                RAISE EXCEPTION 'Chat message requires a running trial' USING ERRCODE='55000';
            END IF;
            SELECT count(*) INTO stored_count FROM matraix_chat_messages
            WHERE trial_id=NEW.trial_id;
            expected_role := CASE WHEN stored_count % 2 = 0 THEN 'customer' ELSE 'support' END;
            IF NEW.position <> stored_count OR NEW.role <> expected_role THEN
                RAISE EXCEPTION 'Chat messages must be contiguous and alternate customer/support'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_message_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_chat_messages FOR EACH ROW EXECUTE FUNCTION protect_matraix_chat_message()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_chat_feedback()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_chat_trials%ROWTYPE;
        DECLARE stored_count integer;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Chat feedback is append-only' USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM matraix_chat_trials WHERE id=NEW.trial_id FOR UPDATE;
            IF NOT FOUND OR parent.status <> 'running' OR NEW.recorded_at < parent.started_at THEN
                RAISE EXCEPTION 'Chat feedback requires a running trial' USING ERRCODE='55000';
            END IF;
            SELECT count(*) INTO stored_count FROM matraix_chat_messages
            WHERE trial_id=NEW.trial_id;
            IF stored_count < 4 OR stored_count % 2 <> 0 THEN
                RAISE EXCEPTION 'Chat feedback requires at least two complete exchanges'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_feedback_protect BEFORE INSERT OR UPDATE OR DELETE ON "
        "matraix_chat_feedback FOR EACH ROW EXECUTE FUNCTION protect_matraix_chat_feedback()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_matraix_chat_trial_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_chat_evaluations%ROWTYPE;
        DECLARE stored_count integer;
        DECLARE customer_count integer;
        DECLARE support_count integer;
        DECLARE latest_artifact_at timestamptz;
        DECLARE actual_transcript_sha text;
        DECLARE actual_feedback_sha text;
        DECLARE actual_result_sha text;
        BEGIN
            SELECT * INTO parent FROM matraix_chat_evaluations
            WHERE id=OLD.evaluation_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NULL THEN
                RAISE EXCEPTION 'Chat transition requires a sealed evaluation'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW)-ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD)-ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status='failed'
               AND (to_jsonb(NEW)-ARRAY['status','completed_at','error_code','error_message']) =
                   (to_jsonb(OLD)-ARRAY['status','completed_at','error_code','error_message']) THEN
                IF EXISTS (SELECT 1 FROM matraix_chat_feedback WHERE trial_id=NEW.id) THEN
                    RAISE EXCEPTION 'failed Chat trial must not retain feedback'
                        USING ERRCODE='55000';
                END IF;
                SELECT max(recorded_at) INTO latest_artifact_at FROM matraix_chat_messages
                WHERE trial_id=NEW.id;
                IF latest_artifact_at IS NOT NULL AND NEW.completed_at < latest_artifact_at THEN
                    RAISE EXCEPTION 'Chat failure predates its partial transcript'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status='succeeded'
               AND (to_jsonb(NEW)-ARRAY[
                    'status','completed_at','runner_version','model_name',
                    'chat_config_sha256','prompt_schema_version','transcript_sha256',
                    'feedback_sha256','result_sha256','outcome_status','next_step_owner',
                    'conversation_path','resolution_progression','message_count',
                    'customer_turn_count','support_turn_count',
                    'clarification_question_count']) =
                   (to_jsonb(OLD)-ARRAY[
                    'status','completed_at','runner_version','model_name',
                    'chat_config_sha256','prompt_schema_version','transcript_sha256',
                    'feedback_sha256','result_sha256','outcome_status','next_step_owner',
                    'conversation_path','resolution_progression','message_count',
                    'customer_turn_count','support_turn_count',
                    'clarification_question_count']) THEN
                SELECT count(*), count(*) FILTER (WHERE role='customer'),
                       count(*) FILTER (WHERE role='support'), max(recorded_at)
                INTO stored_count, customer_count, support_count, latest_artifact_at
                FROM matraix_chat_messages WHERE trial_id=NEW.id;
                SELECT greatest(latest_artifact_at, recorded_at) INTO latest_artifact_at
                FROM matraix_chat_feedback WHERE trial_id=NEW.id;
                IF NOT FOUND OR stored_count < 4 OR stored_count % 2 <> 0
                   OR customer_count <> support_count
                   OR NEW.message_count <> stored_count
                   OR NEW.customer_turn_count <> customer_count
                   OR NEW.support_turn_count <> support_count
                   OR NEW.completed_at < latest_artifact_at
                   OR NEW.runner_version <> '1.0.0'
                   OR NEW.model_name IS DISTINCT FROM parent.model_name
                   OR NEW.chat_config_sha256 IS DISTINCT FROM parent.chat_config_sha256
                   OR NEW.prompt_schema_version IS DISTINCT FROM parent.prompt_schema_version THEN
                    RAISE EXCEPTION 'successful Chat result is incomplete or inconsistent'
                        USING ERRCODE='55000';
                END IF;
                actual_transcript_sha := matraix_chat_transcript_sha(NEW.id);
                actual_feedback_sha := matraix_chat_feedback_sha(NEW.id);
                IF NEW.transcript_sha256 IS DISTINCT FROM actual_transcript_sha
                   OR NEW.feedback_sha256 IS DISTINCT FROM actual_feedback_sha THEN
                    RAISE EXCEPTION 'successful Chat artifact hash mismatch'
                        USING ERRCODE='55000';
                END IF;
                actual_result_sha := matraix_chat_sha256_nul(ARRAY[
                    'matraix-chat-result/v1', NEW.trial_sha256,
                    NEW.transcript_sha256, NEW.feedback_sha256,
                    NEW.outcome_status, NEW.next_step_owner,
                    NEW.conversation_path, NEW.resolution_progression,
                    NEW.message_count::text, NEW.customer_turn_count::text,
                    NEW.support_turn_count::text,
                    NEW.clarification_question_count::text
                ]);
                IF NEW.result_sha256 IS DISTINCT FROM actual_result_sha THEN
                    RAISE EXCEPTION 'successful Chat result hash mismatch'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Chat trial permits only queued -> running -> terminal'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_chat_trial_update BEFORE UPDATE ON matraix_chat_trials "
        "FOR EACH ROW EXECUTE FUNCTION protect_matraix_chat_trial_update()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_chat_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Chat TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    for table_name in (
        "matraix_chat_evaluations",
        "matraix_chat_trials",
        "matraix_chat_messages",
        "matraix_chat_feedback",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_reject_truncate BEFORE TRUNCATE ON "
            f"{table_name} FOR EACH STATEMENT EXECUTE FUNCTION reject_matraix_chat_truncate()"
        )


def _drop_guards() -> None:
    for table_name in (
        "matraix_chat_feedback",
        "matraix_chat_messages",
        "matraix_chat_trials",
        "matraix_chat_evaluations",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_reject_truncate ON {table_name}")
    op.execute("DROP TRIGGER trg_chat_trial_update ON matraix_chat_trials")
    op.execute("DROP TRIGGER trg_chat_feedback_protect ON matraix_chat_feedback")
    op.execute("DROP TRIGGER trg_chat_message_protect ON matraix_chat_messages")
    op.execute("DROP TRIGGER trg_chat_evaluation_protect ON matraix_chat_evaluations")
    op.execute("DROP TRIGGER trg_chat_trial_insert_delete ON matraix_chat_trials")
    op.execute("DROP TRIGGER trg_chat_evaluation_insert ON matraix_chat_evaluations")
    op.execute("DROP FUNCTION reject_matraix_chat_truncate()")
    op.execute("DROP FUNCTION protect_matraix_chat_trial_update()")
    op.execute("DROP FUNCTION protect_matraix_chat_feedback()")
    op.execute("DROP FUNCTION protect_matraix_chat_message()")
    op.execute("DROP FUNCTION protect_matraix_chat_evaluation()")
    op.execute("DROP FUNCTION enforce_matraix_chat_trial_insert_delete()")
    op.execute("DROP FUNCTION enforce_matraix_chat_evaluation_insert()")
    op.execute("DROP FUNCTION matraix_chat_result_sha(uuid)")
    op.execute("DROP FUNCTION matraix_chat_feedback_sha(uuid)")
    op.execute("DROP FUNCTION matraix_chat_transcript_sha(uuid)")
    op.execute("DROP FUNCTION matraix_chat_sha256_nul(text[])")


def upgrade() -> None:
    _extend_worker_heartbeats()
    _create_evaluations()
    _create_trials()
    _create_artifacts()
    _create_hash_functions()
    _create_guards()


def downgrade() -> None:
    _drop_guards()
    op.drop_table("matraix_chat_feedback")
    op.drop_index("ix_chat_messages_trial_position", table_name="matraix_chat_messages")
    op.drop_table("matraix_chat_messages")
    op.drop_index("ix_chat_trials_status_created", table_name="matraix_chat_trials")
    op.drop_table("matraix_chat_trials")
    op.drop_index("ix_chat_evaluations_created", table_name="matraix_chat_evaluations")
    op.drop_table("matraix_chat_evaluations")
    op.drop_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    for column in (
        "chat_sut_spec_sha256",
        "chat_sut_task_version",
        "chat_sut_task_id",
        "chat_prompt_schema_version",
        "chat_config_sha256",
        "chat_model_name",
        "chat_runtime_ready",
    ):
        op.drop_column("simulation_worker_heartbeats", column)
