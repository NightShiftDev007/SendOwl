"""Add stable decision identities and append-only context revisions.

Revision ID: 20260812_core_0012
Revises: 20260812_core_0011
Create Date: 2026-08-12
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0012"
down_revision: str | None = "20260812_core_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("decision_question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300", name="ck_decision_threads_title"
        ),
        sa.CheckConstraint(
            "length(btrim(decision_question)) BETWEEN 1 AND 2000",
            name="ck_decision_threads_question",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decision_threads_created_at", "decision_threads", ["created_at"])
    op.create_table(
        "decision_thread_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=True),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=True),
        sa.Column("semantic_experiment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("experiment_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_decision_thread_revisions_version"),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
            "((scenario_id IS NULL AND scenario_sha256 IS NULL) OR (scenario_id IS NOT NULL AND scenario_sha256 ~ '^[a-f0-9]{64}$')) AND "
            "((cohort_id IS NULL AND cohort_sha256 IS NULL) OR (cohort_id IS NOT NULL AND cohort_sha256 ~ '^[a-f0-9]{64}$')) AND "
            "((semantic_experiment_id IS NULL AND experiment_sha256 IS NULL) OR (semantic_experiment_id IS NOT NULL AND experiment_sha256 ~ '^[a-f0-9]{64}$'))",
            name="ck_decision_thread_revisions_digests",
        ),
        sa.CheckConstraint(
            "semantic_experiment_id IS NULL OR (scenario_id IS NOT NULL AND cohort_id IS NOT NULL)",
            name="ck_decision_thread_revisions_dependencies",
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["decision_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["world_model_id"], ["world_models.id"]),
        sa.ForeignKeyConstraint(["world_snapshot_id"], ["world_snapshots.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.ForeignKeyConstraint(["semantic_experiment_id"], ["semantic_experiments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "version", name="uq_decision_thread_revisions_version"),
    )
    op.create_index(
        "ix_decision_thread_revisions_thread_version",
        "decision_thread_revisions",
        ["thread_id", "version"],
    )
    op.execute(
        """
        CREATE FUNCTION validate_decision_thread_revision()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE selected_snapshot world_snapshots%ROWTYPE;
        DECLARE selected_scenario scenarios%ROWTYPE;
        DECLARE selected_cohort cohorts%ROWTYPE;
        DECLARE selected_experiment semantic_experiments%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT selected_snapshot FROM world_snapshots
            WHERE id = NEW.world_snapshot_id AND sealed_at IS NOT NULL FOR SHARE;
            IF selected_snapshot.world_model_id <> NEW.world_model_id
               OR selected_snapshot.snapshot_sha256 <> NEW.snapshot_sha256 THEN
                RAISE EXCEPTION 'decision revision world snapshot identity mismatch' USING ERRCODE = '23514';
            END IF;
            IF NEW.scenario_id IS NOT NULL THEN
                SELECT * INTO STRICT selected_scenario FROM scenarios
                WHERE id = NEW.scenario_id AND sealed_at IS NOT NULL FOR SHARE;
                IF selected_scenario.world_model_id <> NEW.world_model_id
                   OR selected_scenario.world_snapshot_id <> NEW.world_snapshot_id
                   OR selected_scenario.snapshot_sha256 <> NEW.snapshot_sha256
                   OR selected_scenario.scenario_sha256 <> NEW.scenario_sha256 THEN
                    RAISE EXCEPTION 'decision revision scenario identity mismatch' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.cohort_id IS NOT NULL THEN
                SELECT * INTO STRICT selected_cohort FROM cohorts
                WHERE id = NEW.cohort_id AND sealed_at IS NOT NULL FOR SHARE;
                IF selected_cohort.cohort_sha256 <> NEW.cohort_sha256 THEN
                    RAISE EXCEPTION 'decision revision cohort identity mismatch' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF NEW.semantic_experiment_id IS NOT NULL THEN
                SELECT * INTO STRICT selected_experiment FROM semantic_experiments
                WHERE id = NEW.semantic_experiment_id AND input_sealed_at IS NOT NULL FOR SHARE;
                IF selected_experiment.scenario_id <> NEW.scenario_id
                   OR selected_experiment.scenario_sha256 <> NEW.scenario_sha256
                   OR selected_experiment.cohort_id <> NEW.cohort_id
                   OR selected_experiment.cohort_sha256 <> NEW.cohort_sha256
                   OR selected_experiment.experiment_sha256 <> NEW.experiment_sha256 THEN
                    RAISE EXCEPTION 'decision revision experiment identity mismatch' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_thread_revision_validate
        BEFORE INSERT ON decision_thread_revisions
        FOR EACH ROW EXECUTE FUNCTION validate_decision_thread_revision()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_decision_thread_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'decision thread records are append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_threads_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON decision_threads
        FOR EACH STATEMENT EXECUTE FUNCTION reject_decision_thread_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_thread_revisions_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON decision_thread_revisions
        FOR EACH STATEMENT EXECUTE FUNCTION reject_decision_thread_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_decision_thread_revisions_immutable ON decision_thread_revisions")
    op.execute("DROP TRIGGER trg_decision_threads_immutable ON decision_threads")
    op.execute("DROP TRIGGER trg_decision_thread_revision_validate ON decision_thread_revisions")
    op.execute("DROP FUNCTION reject_decision_thread_mutation()")
    op.execute("DROP FUNCTION validate_decision_thread_revision()")
    op.drop_index(
        "ix_decision_thread_revisions_thread_version", table_name="decision_thread_revisions"
    )
    op.drop_table("decision_thread_revisions")
    op.drop_index("ix_decision_threads_created_at", table_name="decision_threads")
    op.drop_table("decision_threads")
