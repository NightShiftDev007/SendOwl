"""Add immutable retry lineage to MatrAIx Survey experiments.

Revision ID: 20260813_core_0027
Revises: 20260813_core_0026
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0027"
down_revision: str | None = "20260813_core_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_insert_guard() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_matraix_survey_experiment_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent matraix_survey_experiments%ROWTYPE;
        DECLARE parent_total integer;
        DECLARE parent_failed integer;
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
                  AND scenario.scenario_sha256=NEW.scenario_sha256 AND scenario.title=NEW.scenario_title
                  AND scenario.decision_question=NEW.decision_question
                  AND cohort.cohort_sha256=NEW.cohort_sha256 AND cohort.title=NEW.cohort_title
                  AND cohort.persona_count=NEW.persona_count AND dataset.dataset_sha256=NEW.dataset_sha256
                  AND baseline.role='baseline' AND baseline.position=NEW.baseline_position
                  AND baseline.name=NEW.baseline_name AND baseline.hypothesis=NEW.baseline_hypothesis
                  AND alternative.role='alternative' AND alternative.position=NEW.alternative_position
                  AND alternative.name=NEW.alternative_name AND alternative.hypothesis=NEW.alternative_hypothesis
            ) THEN
                RAISE EXCEPTION 'Survey experiment does not match sealed inputs' USING ERRCODE='55000';
            END IF;
            IF NEW.attempt_number=1 THEN
                IF NEW.retry_of_experiment_id IS NOT NULL OR NEW.retry_of_experiment_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'root Survey experiment cannot have retry lineage' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            SELECT * INTO parent FROM matraix_survey_experiments
            WHERE id=NEW.retry_of_experiment_id FOR SHARE;
            IF NOT FOUND OR parent.input_sealed_at IS NULL
               OR NEW.retry_of_experiment_sha256 IS DISTINCT FROM parent.experiment_sha256
               OR NEW.attempt_number <> parent.attempt_number+1 OR NEW.attempt_number > 5 THEN
                RAISE EXCEPTION 'Survey retry lineage does not match a sealed parent attempt' USING ERRCODE='55000';
            END IF;
            IF (NEW.scenario_id,NEW.scenario_sha256,NEW.scenario_title,NEW.decision_question,
                NEW.cohort_id,NEW.cohort_sha256,NEW.cohort_title,NEW.dataset_sha256,NEW.persona_count,
                NEW.baseline_id,NEW.baseline_position,NEW.baseline_name,NEW.baseline_hypothesis,
                NEW.alternative_id,NEW.alternative_position,NEW.alternative_name,NEW.alternative_hypothesis,
                NEW.instrument_schema_version,NEW.instrument_sha256,NEW.prompt_schema_version)
               IS DISTINCT FROM
               (parent.scenario_id,parent.scenario_sha256,parent.scenario_title,parent.decision_question,
                parent.cohort_id,parent.cohort_sha256,parent.cohort_title,parent.dataset_sha256,parent.persona_count,
                parent.baseline_id,parent.baseline_position,parent.baseline_name,parent.baseline_hypothesis,
                parent.alternative_id,parent.alternative_position,parent.alternative_name,parent.alternative_hypothesis,
                parent.instrument_schema_version,parent.instrument_sha256,parent.prompt_schema_version) THEN
                RAISE EXCEPTION 'Survey retry changed frozen Scenario, Cohort, or instrument' USING ERRCODE='55000';
            END IF;
            SELECT count(*),count(*) FILTER (WHERE status='failed') INTO parent_total,parent_failed
            FROM matraix_survey_trials WHERE experiment_id=parent.id AND status IN ('succeeded','failed');
            IF parent_total<>parent.persona_count OR parent_failed<1 THEN
                RAISE EXCEPTION 'Survey retry requires a terminal parent with a failed trial' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )


def upgrade() -> None:
    op.add_column(
        "matraix_survey_experiments",
        sa.Column("retry_of_experiment_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "matraix_survey_experiments", sa.Column("retry_of_experiment_sha256", sa.String(length=64))
    )
    op.add_column(
        "matraix_survey_experiments",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        "fk_survey_retry_parent",
        "matraix_survey_experiments",
        "matraix_survey_experiments",
        ["retry_of_experiment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_survey_attempt_lineage",
        "matraix_survey_experiments",
        "(attempt_number=1 AND retry_of_experiment_id IS NULL AND retry_of_experiment_sha256 IS NULL) OR (attempt_number BETWEEN 2 AND 5 AND retry_of_experiment_id IS NOT NULL AND retry_of_experiment_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.create_unique_constraint(
        "uq_survey_retry_parent", "matraix_survey_experiments", ["retry_of_experiment_id"]
    )
    _replace_insert_guard()


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM matraix_survey_experiments WHERE attempt_number>1) THEN RAISE EXCEPTION 'cannot downgrade while Survey retry attempts exist'; END IF; END $$"
    )
    op.drop_constraint("uq_survey_retry_parent", "matraix_survey_experiments", type_="unique")
    op.drop_constraint("ck_survey_attempt_lineage", "matraix_survey_experiments", type_="check")
    op.drop_constraint("fk_survey_retry_parent", "matraix_survey_experiments", type_="foreignkey")
    op.drop_column("matraix_survey_experiments", "attempt_number")
    op.drop_column("matraix_survey_experiments", "retry_of_experiment_sha256")
    op.drop_column("matraix_survey_experiments", "retry_of_experiment_id")
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_matraix_survey_experiment_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.input_sealed_at IS NOT NULL THEN RAISE EXCEPTION 'Survey experiment must be inserted as draft' USING ERRCODE='55000'; END IF;
            IF NOT EXISTS (SELECT 1 FROM scenarios scenario JOIN scenario_variants baseline ON baseline.scenario_id=scenario.id AND baseline.id=NEW.baseline_id JOIN scenario_variants alternative ON alternative.scenario_id=scenario.id AND alternative.id=NEW.alternative_id JOIN cohorts cohort ON cohort.id=NEW.cohort_id JOIN persona_datasets dataset ON dataset.id=cohort.dataset_id WHERE scenario.id=NEW.scenario_id AND scenario.sealed_at IS NOT NULL AND cohort.sealed_at IS NOT NULL AND dataset.sealed_at IS NOT NULL AND scenario.scenario_sha256=NEW.scenario_sha256 AND scenario.title=NEW.scenario_title AND scenario.decision_question=NEW.decision_question AND cohort.cohort_sha256=NEW.cohort_sha256 AND cohort.title=NEW.cohort_title AND cohort.persona_count=NEW.persona_count AND dataset.dataset_sha256=NEW.dataset_sha256 AND baseline.role='baseline' AND baseline.position=NEW.baseline_position AND baseline.name=NEW.baseline_name AND baseline.hypothesis=NEW.baseline_hypothesis AND alternative.role='alternative' AND alternative.position=NEW.alternative_position AND alternative.name=NEW.alternative_name AND alternative.hypothesis=NEW.alternative_hypothesis) THEN RAISE EXCEPTION 'Survey experiment does not match sealed inputs' USING ERRCODE='55000'; END IF;
            RETURN NEW;
        END; $$
    """)
