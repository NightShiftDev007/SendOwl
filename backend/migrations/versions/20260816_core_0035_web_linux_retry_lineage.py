"""Add immutable retry lineage to MatrAIx Web and Linux attempts.

Revision ID: 20260816_core_0035
Revises: 20260816_core_0034
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0035"
down_revision: str | None = "20260816_core_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_web_guard(include_retry: bool) -> None:
    if include_retry:
        hash_logic = """
            IF NEW.attempt_number=1 THEN
                IF NEW.retry_of_evaluation_id IS NOT NULL
                   OR NEW.retry_of_evaluation_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'root Web evaluation cannot have retry lineage'
                        USING ERRCODE='55000';
                END IF;
                actual_hash := matraix_web_digest(ARRAY[
                    'matraix-web-evaluation/v1', NEW.task_spec_sha256,
                    NEW.executor_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                    NEW.web_config_sha256, NEW.prompt_schema_version
                ]);
            ELSE
                SELECT * INTO parent FROM matraix_web_evaluations
                WHERE id=NEW.retry_of_evaluation_id FOR SHARE;
                IF NOT FOUND OR parent.input_sealed_at IS NULL
                   OR NEW.retry_of_evaluation_sha256 IS DISTINCT FROM parent.evaluation_sha256
                   OR NEW.attempt_number <> parent.attempt_number+1
                   OR NEW.attempt_number > 5 THEN
                    RAISE EXCEPTION 'Web retry lineage does not match a sealed parent attempt'
                        USING ERRCODE='55000';
                END IF;
                IF (NEW.cohort_id, NEW.cohort_sha256, NEW.cohort_title,
                    NEW.dataset_sha256, NEW.persona_count, NEW.task_id,
                    NEW.task_version, NEW.task_schema_version, NEW.task_spec_sha256,
                    NEW.executor_schema_version, NEW.executor_spec_sha256,
                    NEW.prompt_schema_version)
                   IS DISTINCT FROM
                   (parent.cohort_id, parent.cohort_sha256, parent.cohort_title,
                    parent.dataset_sha256, parent.persona_count, parent.task_id,
                    parent.task_version, parent.task_schema_version, parent.task_spec_sha256,
                    parent.executor_schema_version, parent.executor_spec_sha256,
                    parent.prompt_schema_version) THEN
                    RAISE EXCEPTION 'Web retry changed frozen task or Cohort inputs'
                        USING ERRCODE='55000';
                END IF;
                SELECT count(*), count(*) FILTER (WHERE status='failed')
                INTO parent_total, parent_failed FROM matraix_web_trials
                WHERE evaluation_id=parent.id AND status IN ('succeeded','failed');
                IF parent_total <> parent.persona_count OR parent_failed < 1 THEN
                    RAISE EXCEPTION 'Web retry requires a terminal parent with a failed trial'
                        USING ERRCODE='55000';
                END IF;
                actual_hash := matraix_web_digest(ARRAY[
                    'matraix-web-evaluation-retry/v1', parent.evaluation_sha256,
                    NEW.attempt_number::text, NEW.task_spec_sha256,
                    NEW.executor_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                    NEW.web_config_sha256, NEW.prompt_schema_version
                ]);
            END IF;
        """
    else:
        hash_logic = """
            actual_hash := matraix_web_digest(ARRAY[
                'matraix-web-evaluation/v1', NEW.task_spec_sha256,
                NEW.executor_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                NEW.web_config_sha256, NEW.prompt_schema_version
            ]);
        """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_matraix_web_evaluation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE trial_count integer;
        DECLARE actual_hash text;
        DECLARE parent matraix_web_evaluations%ROWTYPE;
        DECLARE parent_total integer;
        DECLARE parent_failed integer;
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
                {hash_logic}
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


def _create_linux_insert_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION matraix_linux_digest(parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE payload bytea := ''::bytea;
        DECLARE part text;
        DECLARE first_part boolean := true;
        BEGIN
            FOREACH part IN ARRAY parts LOOP
                IF part IS NULL THEN
                    RAISE EXCEPTION 'MatrAIx Linux hash part is null' USING ERRCODE='55000';
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
        CREATE FUNCTION enforce_matraix_linux_trial_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_linux_trials%ROWTYPE;
        DECLARE actual_hash text;
        BEGIN
            IF NEW.status <> 'queued' THEN
                RAISE EXCEPTION 'Linux trial must be inserted as queued' USING ERRCODE='55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM cohorts cohort
                JOIN persona_datasets dataset ON dataset.id=cohort.dataset_id
                JOIN cohort_members member ON member.cohort_id=cohort.id
                JOIN personas persona
                  ON persona.dataset_id=member.dataset_id AND persona.id=member.persona_id
                WHERE cohort.id=NEW.cohort_id AND cohort.sealed_at IS NOT NULL
                  AND dataset.sealed_at IS NOT NULL
                  AND cohort.title=NEW.cohort_title
                  AND cohort.cohort_sha256=NEW.cohort_sha256
                  AND dataset.dataset_sha256=NEW.dataset_sha256
                  AND member.position=NEW.persona_position
                  AND persona.id=NEW.persona_id
                  AND persona.persona_id=NEW.persona_external_id
                  AND persona.display_name=NEW.persona_display_name
                  AND persona.profile_sha256=NEW.persona_profile_sha256
            ) THEN
                RAISE EXCEPTION 'Linux trial does not match sealed Cohort and Persona'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.attempt_number=1 THEN
                IF NEW.retry_of_trial_id IS NOT NULL OR NEW.retry_of_trial_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'root Linux trial cannot have retry lineage'
                        USING ERRCODE='55000';
                END IF;
                actual_hash := matraix_linux_digest(ARRAY[
                    'matraix-linux-trial/v1', NEW.task_spec_sha256,
                    NEW.runner_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_id::text, NEW.persona_position::text,
                    NEW.persona_external_id, NEW.persona_profile_sha256, NEW.model_name,
                    NEW.linux_config_sha256, NEW.prompt_schema_version
                ]);
            ELSE
                SELECT * INTO parent FROM matraix_linux_trials
                WHERE id=NEW.retry_of_trial_id FOR SHARE;
                IF NOT FOUND OR parent.status <> 'failed'
                   OR NEW.retry_of_trial_sha256 IS DISTINCT FROM parent.trial_sha256
                   OR NEW.attempt_number <> parent.attempt_number+1
                   OR NEW.attempt_number > 5 THEN
                    RAISE EXCEPTION 'Linux retry lineage does not match a failed parent attempt'
                        USING ERRCODE='55000';
                END IF;
                IF (NEW.cohort_id, NEW.cohort_title, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_id, NEW.persona_position,
                    NEW.persona_external_id, NEW.persona_display_name,
                    NEW.persona_profile_sha256, NEW.task_id, NEW.task_version,
                    NEW.task_schema_version, NEW.task_spec_sha256,
                    NEW.runner_schema_version, NEW.runner_spec_sha256,
                    NEW.prompt_schema_version)
                   IS DISTINCT FROM
                   (parent.cohort_id, parent.cohort_title, parent.cohort_sha256,
                    parent.dataset_sha256, parent.persona_id, parent.persona_position,
                    parent.persona_external_id, parent.persona_display_name,
                    parent.persona_profile_sha256, parent.task_id, parent.task_version,
                    parent.task_schema_version, parent.task_spec_sha256,
                    parent.runner_schema_version, parent.runner_spec_sha256,
                    parent.prompt_schema_version) THEN
                    RAISE EXCEPTION 'Linux retry changed frozen task, Cohort, or Persona inputs'
                        USING ERRCODE='55000';
                END IF;
                actual_hash := matraix_linux_digest(ARRAY[
                    'matraix-linux-trial-retry/v1', parent.trial_sha256,
                    NEW.attempt_number::text, NEW.task_spec_sha256,
                    NEW.runner_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_id::text, NEW.persona_position::text,
                    NEW.persona_external_id, NEW.persona_profile_sha256, NEW.model_name,
                    NEW.linux_config_sha256, NEW.prompt_schema_version
                ]);
            END IF;
            IF NEW.trial_sha256 IS DISTINCT FROM actual_hash THEN
                RAISE EXCEPTION 'Linux trial hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_linux_trial_insert BEFORE INSERT ON matraix_linux_trials "
        "FOR EACH ROW EXECUTE FUNCTION enforce_matraix_linux_trial_insert()"
    )


def upgrade() -> None:
    for column in (
        sa.Column("retry_of_evaluation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retry_of_evaluation_sha256", sa.String(length=64), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    ):
        op.add_column("matraix_web_evaluations", column)
    op.create_foreign_key(
        "fk_web_eval_retry_parent",
        "matraix_web_evaluations",
        "matraix_web_evaluations",
        ["retry_of_evaluation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_web_eval_attempt_lineage",
        "matraix_web_evaluations",
        "(attempt_number=1 AND retry_of_evaluation_id IS NULL "
        "AND retry_of_evaluation_sha256 IS NULL) OR "
        "(attempt_number BETWEEN 2 AND 5 AND retry_of_evaluation_id IS NOT NULL "
        "AND retry_of_evaluation_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_unique_constraint(
        "uq_web_eval_retry_parent",
        "matraix_web_evaluations",
        ["retry_of_evaluation_id"],
    )
    _replace_web_guard(True)

    for column in (
        sa.Column("retry_of_trial_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retry_of_trial_sha256", sa.String(length=64), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    ):
        op.add_column("matraix_linux_trials", column)
    op.create_foreign_key(
        "fk_linux_trial_retry_parent",
        "matraix_linux_trials",
        "matraix_linux_trials",
        ["retry_of_trial_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_linux_trial_attempt_lineage",
        "matraix_linux_trials",
        "(attempt_number=1 AND retry_of_trial_id IS NULL "
        "AND retry_of_trial_sha256 IS NULL) OR "
        "(attempt_number BETWEEN 2 AND 5 AND retry_of_trial_id IS NOT NULL "
        "AND retry_of_trial_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_unique_constraint(
        "uq_linux_trial_retry_parent",
        "matraix_linux_trials",
        ["retry_of_trial_id"],
    )
    _create_linux_insert_guard()


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM matraix_web_evaluations WHERE attempt_number > 1)
               OR EXISTS (SELECT 1 FROM matraix_linux_trials WHERE attempt_number > 1) THEN
                RAISE EXCEPTION 'cannot downgrade while Web or Linux retry attempts exist';
            END IF;
        END $$
        """
    )
    op.execute("DROP TRIGGER trg_linux_trial_insert ON matraix_linux_trials")
    op.execute("DROP FUNCTION enforce_matraix_linux_trial_insert()")
    op.execute("DROP FUNCTION matraix_linux_digest(text[])")
    op.drop_constraint("uq_linux_trial_retry_parent", "matraix_linux_trials", type_="unique")
    op.drop_constraint("ck_linux_trial_attempt_lineage", "matraix_linux_trials", type_="check")
    op.drop_constraint("fk_linux_trial_retry_parent", "matraix_linux_trials", type_="foreignkey")
    op.drop_column("matraix_linux_trials", "attempt_number")
    op.drop_column("matraix_linux_trials", "retry_of_trial_sha256")
    op.drop_column("matraix_linux_trials", "retry_of_trial_id")

    _replace_web_guard(False)
    op.drop_constraint("uq_web_eval_retry_parent", "matraix_web_evaluations", type_="unique")
    op.drop_constraint("ck_web_eval_attempt_lineage", "matraix_web_evaluations", type_="check")
    op.drop_constraint("fk_web_eval_retry_parent", "matraix_web_evaluations", type_="foreignkey")
    op.drop_column("matraix_web_evaluations", "attempt_number")
    op.drop_column("matraix_web_evaluations", "retry_of_evaluation_sha256")
    op.drop_column("matraix_web_evaluations", "retry_of_evaluation_id")
