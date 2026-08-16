"""Add immutable retry lineage to MatrAIx Chat evaluations.

Revision ID: 20260813_core_0026
Revises: 20260813_core_0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0026"
down_revision: str | None = "20260813_core_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_insert_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_matraix_chat_evaluation_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actual_sha text;
        DECLARE parent matraix_chat_evaluations%ROWTYPE;
        DECLARE parent_total integer;
        DECLARE parent_failed integer;
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
            IF NEW.attempt_number=1 THEN
                IF NEW.retry_of_evaluation_id IS NOT NULL
                   OR NEW.retry_of_evaluation_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'root Chat evaluation cannot have retry lineage'
                        USING ERRCODE='55000';
                END IF;
                actual_sha := matraix_chat_sha256_nul(ARRAY[
                    'matraix-chat-evaluation/v1', NEW.task_spec_sha256,
                    NEW.sut_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                    NEW.chat_config_sha256, NEW.prompt_schema_version
                ]);
            ELSE
                SELECT * INTO parent FROM matraix_chat_evaluations
                WHERE id=NEW.retry_of_evaluation_id FOR SHARE;
                IF NOT FOUND OR parent.input_sealed_at IS NULL
                   OR NEW.retry_of_evaluation_sha256 IS DISTINCT FROM parent.evaluation_sha256
                   OR NEW.attempt_number <> parent.attempt_number+1
                   OR NEW.attempt_number > 5 THEN
                    RAISE EXCEPTION 'Chat retry lineage does not match a sealed parent attempt'
                        USING ERRCODE='55000';
                END IF;
                IF (NEW.cohort_id, NEW.cohort_sha256, NEW.cohort_title,
                    NEW.dataset_sha256, NEW.persona_count, NEW.task_id,
                    NEW.task_version, NEW.task_schema_version, NEW.task_spec_sha256,
                    NEW.sut_spec_sha256, NEW.prompt_schema_version)
                   IS DISTINCT FROM
                   (parent.cohort_id, parent.cohort_sha256, parent.cohort_title,
                    parent.dataset_sha256, parent.persona_count, parent.task_id,
                    parent.task_version, parent.task_schema_version,
                    parent.task_spec_sha256, parent.sut_spec_sha256,
                    parent.prompt_schema_version) THEN
                    RAISE EXCEPTION 'Chat retry changed frozen task or Cohort inputs'
                        USING ERRCODE='55000';
                END IF;
                SELECT count(*), count(*) FILTER (WHERE status='failed')
                INTO parent_total, parent_failed FROM matraix_chat_trials
                WHERE evaluation_id=parent.id AND status IN ('succeeded','failed');
                IF parent_total <> parent.persona_count OR parent_failed < 1 THEN
                    RAISE EXCEPTION 'Chat retry requires a terminal parent with a failed trial'
                        USING ERRCODE='55000';
                END IF;
                actual_sha := matraix_chat_sha256_nul(ARRAY[
                    'matraix-chat-evaluation-retry/v1', parent.evaluation_sha256,
                    NEW.attempt_number::text, NEW.task_spec_sha256,
                    NEW.sut_spec_sha256, NEW.cohort_id::text, NEW.cohort_sha256,
                    NEW.dataset_sha256, NEW.persona_count::text, NEW.model_name,
                    NEW.chat_config_sha256, NEW.prompt_schema_version
                ]);
            END IF;
            IF actual_sha IS DISTINCT FROM NEW.evaluation_sha256 THEN
                RAISE EXCEPTION 'Chat evaluation hash does not match frozen inputs'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )


def upgrade() -> None:
    op.add_column(
        "matraix_chat_evaluations",
        sa.Column("retry_of_evaluation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "matraix_chat_evaluations",
        sa.Column("retry_of_evaluation_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "matraix_chat_evaluations",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        "fk_chat_eval_retry_parent",
        "matraix_chat_evaluations",
        "matraix_chat_evaluations",
        ["retry_of_evaluation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_chat_eval_attempt_lineage",
        "matraix_chat_evaluations",
        "(attempt_number=1 AND retry_of_evaluation_id IS NULL "
        "AND retry_of_evaluation_sha256 IS NULL) OR "
        "(attempt_number BETWEEN 2 AND 5 AND retry_of_evaluation_id IS NOT NULL "
        "AND retry_of_evaluation_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_unique_constraint(
        "uq_chat_eval_retry_parent",
        "matraix_chat_evaluations",
        ["retry_of_evaluation_id"],
    )
    _replace_insert_guard()


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM matraix_chat_evaluations WHERE attempt_number > 1) THEN
                RAISE EXCEPTION 'cannot downgrade while Chat retry attempts exist';
            END IF;
        END $$
        """
    )
    op.drop_constraint("uq_chat_eval_retry_parent", "matraix_chat_evaluations", type_="unique")
    op.drop_constraint("ck_chat_eval_attempt_lineage", "matraix_chat_evaluations", type_="check")
    op.drop_constraint("fk_chat_eval_retry_parent", "matraix_chat_evaluations", type_="foreignkey")
    op.drop_column("matraix_chat_evaluations", "attempt_number")
    op.drop_column("matraix_chat_evaluations", "retry_of_evaluation_sha256")
    op.drop_column("matraix_chat_evaluations", "retry_of_evaluation_id")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_matraix_chat_evaluation_insert()
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
