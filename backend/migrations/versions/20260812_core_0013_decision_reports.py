"""Add deterministic, sealed decision reports.

Revision ID: 20260812_core_0013
Revises: 20260812_core_0012
Create Date: 2026-08-12
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0013"
down_revision: str | None = "20260812_core_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("experiment_sha256", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300", name="ck_decision_reports_title"
        ),
        sa.CheckConstraint(
            "experiment_sha256 ~ '^[a-f0-9]{64}$' AND scenario_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' AND report_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_decision_reports_digests",
        ),
        sa.CheckConstraint(
            "generator_version = 'deterministic-findings/v1'",
            name="ck_decision_reports_generator",
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["semantic_experiments.id"]),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", name="uq_decision_reports_experiment"),
        sa.UniqueConstraint("report_sha256", name="uq_decision_reports_sha256"),
    )
    op.create_index("ix_decision_reports_created_at", "decision_reports", ["created_at"])
    op.create_table(
        "decision_report_sections",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 3", name="ck_decision_report_sections_position"),
        sa.CheckConstraint(
            "kind IN ('scope', 'comparison', 'limitations', 'provenance')",
            name="ck_decision_report_sections_kind",
        ),
        sa.CheckConstraint(
            "length(body_markdown) BETWEEN 1 AND 40000",
            name="ck_decision_report_sections_body",
        ),
        sa.ForeignKeyConstraint(["report_id"], ["decision_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id", "position"),
    )
    op.execute(
        """
        CREATE FUNCTION decision_report_frame(value text)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT octet_length(value)::text || ':' || value
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_decision_report_parent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE selected_experiment semantic_experiments%ROWTYPE;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.sealed_at IS NOT NULL THEN
                    RAISE EXCEPTION 'decision report must be inserted as a draft' USING ERRCODE = '55000';
                END IF;
                SELECT * INTO STRICT selected_experiment FROM semantic_experiments
                WHERE id = NEW.experiment_id AND input_sealed_at IS NOT NULL FOR SHARE;
                IF selected_experiment.experiment_sha256 <> NEW.experiment_sha256
                   OR selected_experiment.scenario_id <> NEW.scenario_id
                   OR selected_experiment.scenario_sha256 <> NEW.scenario_sha256
                   OR selected_experiment.cohort_id <> NEW.cohort_id
                   OR selected_experiment.cohort_sha256 <> NEW.cohort_sha256 THEN
                    RAISE EXCEPTION 'decision report experiment identity mismatch' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
               AND OLD.id = NEW.id AND OLD.experiment_id = NEW.experiment_id
               AND OLD.experiment_sha256 = NEW.experiment_sha256
               AND OLD.scenario_id = NEW.scenario_id AND OLD.scenario_sha256 = NEW.scenario_sha256
               AND OLD.cohort_id = NEW.cohort_id AND OLD.cohort_sha256 = NEW.cohort_sha256
               AND OLD.title = NEW.title AND OLD.report_sha256 = NEW.report_sha256
               AND OLD.generator_version = NEW.generator_version AND OLD.created_at = NEW.created_at THEN
                IF (SELECT count(*) FROM decision_report_sections WHERE report_id = NEW.id) <> 4
                   OR EXISTS (
                       SELECT 1 FROM (
                           VALUES (0, 'scope'), (1, 'comparison'), (2, 'limitations'), (3, 'provenance')
                       ) AS expected(position, kind)
                       LEFT JOIN decision_report_sections actual
                         ON actual.report_id = NEW.id AND actual.position = expected.position
                        AND actual.kind = expected.kind
                       WHERE actual.report_id IS NULL
                ) THEN
                    RAISE EXCEPTION 'decision report requires the complete fixed outline before sealing' USING ERRCODE = '23514';
                END IF;
                IF encode(
                    digest(
                        convert_to(
                            decision_report_frame(NEW.generator_version)
                            || decision_report_frame(NEW.experiment_sha256)
                            || decision_report_frame(NEW.scenario_sha256)
                            || decision_report_frame(NEW.cohort_sha256)
                            || decision_report_frame(NEW.title)
                            ||
                                (
                                    SELECT string_agg(
                                        decision_report_frame(position::text)
                                        || decision_report_frame(kind)
                                        || decision_report_frame(title)
                                        || decision_report_frame(body_markdown)
                                        || decision_report_frame(metrics_json),
                                        '' ORDER BY position
                                    )
                                    FROM decision_report_sections WHERE report_id = NEW.id
                                ),
                            'UTF8'
                        ),
                        'sha256'
                    ),
                    'hex'
                ) <> NEW.report_sha256 THEN
                    RAISE EXCEPTION 'decision report content hash mismatch' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'decision reports are immutable after sealing' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_reports_guard
        BEFORE INSERT OR UPDATE OR DELETE ON decision_reports
        FOR EACH ROW EXECUTE FUNCTION guard_decision_report_parent()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_reports_truncate
        BEFORE TRUNCATE ON decision_reports
        FOR EACH STATEMENT EXECUTE FUNCTION guard_decision_report_parent()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_decision_report_section()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_sealed_at timestamptz;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'decision report sections cannot be truncated' USING ERRCODE = '55000';
            END IF;
            SELECT sealed_at INTO STRICT parent_sealed_at FROM decision_reports
            WHERE id = COALESCE(NEW.report_id, OLD.report_id) FOR UPDATE;
            IF parent_sealed_at IS NOT NULL THEN
                RAISE EXCEPTION 'sealed decision report sections are immutable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_report_sections_guard
        BEFORE INSERT OR UPDATE OR DELETE ON decision_report_sections
        FOR EACH ROW EXECUTE FUNCTION guard_decision_report_section()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_decision_report_sections_truncate
        BEFORE TRUNCATE ON decision_report_sections
        FOR EACH STATEMENT EXECUTE FUNCTION guard_decision_report_section()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_decision_report_sections_truncate ON decision_report_sections")
    op.execute("DROP TRIGGER trg_decision_report_sections_guard ON decision_report_sections")
    op.execute("DROP TRIGGER trg_decision_reports_guard ON decision_reports")
    op.execute("DROP TRIGGER trg_decision_reports_truncate ON decision_reports")
    op.execute("DROP FUNCTION guard_decision_report_section()")
    op.execute("DROP FUNCTION guard_decision_report_parent()")
    op.execute("DROP FUNCTION decision_report_frame(text)")
    op.drop_table("decision_report_sections")
    op.drop_index("ix_decision_reports_created_at", table_name="decision_reports")
    op.drop_table("decision_reports")
