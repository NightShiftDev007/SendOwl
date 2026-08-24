"""Add a versioned, structured seven-section DecisionReport V2."""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0042"
down_revision: str | None = "20260816_core_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_report_triggers() -> None:
    op.execute("DROP TRIGGER trg_decision_report_sections_truncate ON decision_report_sections")
    op.execute("DROP TRIGGER trg_decision_report_sections_guard ON decision_report_sections")
    op.execute("DROP TRIGGER trg_decision_reports_guard ON decision_reports")
    op.execute("DROP TRIGGER trg_decision_reports_truncate ON decision_reports")
    op.execute("DROP FUNCTION guard_decision_report_section()")
    op.execute("DROP FUNCTION guard_decision_report_parent()")


def _create_report_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_decision_report_parent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE selected_experiment semantic_experiments%ROWTYPE;
        DECLARE selected_scenario scenarios%ROWTYPE;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'decision reports cannot be truncated' USING ERRCODE = '55000';
            END IF;
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
                IF NEW.generator_version = 'deterministic-findings/v1' THEN
                    IF NEW.world_snapshot_id IS NOT NULL OR NEW.world_snapshot_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION 'V1 decision report cannot carry a WorldSnapshot identity' USING ERRCODE = '23514';
                    END IF;
                ELSE
                    SELECT * INTO STRICT selected_scenario FROM scenarios
                    WHERE id = NEW.scenario_id FOR SHARE;
                    IF selected_scenario.world_snapshot_id <> NEW.world_snapshot_id
                       OR selected_scenario.snapshot_sha256 <> NEW.world_snapshot_sha256 THEN
                        RAISE EXCEPTION 'V2 decision report WorldSnapshot identity mismatch' USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
               AND OLD.id = NEW.id AND OLD.experiment_id = NEW.experiment_id
               AND OLD.experiment_sha256 = NEW.experiment_sha256
               AND OLD.scenario_id = NEW.scenario_id AND OLD.scenario_sha256 = NEW.scenario_sha256
               AND OLD.cohort_id = NEW.cohort_id AND OLD.cohort_sha256 = NEW.cohort_sha256
               AND OLD.world_snapshot_id IS NOT DISTINCT FROM NEW.world_snapshot_id
               AND OLD.world_snapshot_sha256 IS NOT DISTINCT FROM NEW.world_snapshot_sha256
               AND OLD.title = NEW.title AND OLD.report_sha256 = NEW.report_sha256
               AND OLD.generator_version = NEW.generator_version AND OLD.created_at = NEW.created_at THEN
                IF NEW.generator_version = 'deterministic-findings/v1' THEN
                    IF (SELECT count(*) FROM decision_report_sections WHERE report_id = NEW.id) <> 4
                       OR EXISTS (
                           SELECT 1 FROM (
                               VALUES (0, 'scope'), (1, 'comparison'),
                                      (2, 'limitations'), (3, 'provenance')
                           ) AS expected(position, kind)
                           LEFT JOIN decision_report_sections actual
                             ON actual.report_id = NEW.id AND actual.position = expected.position
                            AND actual.kind = expected.kind
                           WHERE actual.report_id IS NULL
                       ) THEN
                        RAISE EXCEPTION 'V1 decision report requires its complete fixed outline' USING ERRCODE = '23514';
                    END IF;
                    IF encode(
                        digest(
                            convert_to(
                                decision_report_frame(NEW.generator_version)
                                || decision_report_frame(NEW.experiment_sha256)
                                || decision_report_frame(NEW.scenario_sha256)
                                || decision_report_frame(NEW.cohort_sha256)
                                || decision_report_frame(NEW.title)
                                || (
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
                        RAISE EXCEPTION 'V1 decision report content hash mismatch' USING ERRCODE = '23514';
                    END IF;
                ELSE
                    IF (SELECT count(*) FROM decision_report_sections WHERE report_id = NEW.id) <> 7
                       OR EXISTS (
                           SELECT 1 FROM (
                               VALUES (0, 'evidence'), (1, 'assumptions'), (2, 'experiment'),
                                      (3, 'observation'), (4, 'comparison'), (5, 'analysis'),
                                      (6, 'limitations')
                           ) AS expected(position, kind)
                           LEFT JOIN decision_report_sections actual
                             ON actual.report_id = NEW.id AND actual.position = expected.position
                            AND actual.kind = expected.kind
                           WHERE actual.report_id IS NULL
                       )
                       OR EXISTS (
                           SELECT 1 FROM (
                               VALUES (0, 'evidence'), (1, 'assumptions'), (2, 'experiment'),
                                      (3, 'observation'), (4, 'comparison'), (5, 'analysis'),
                                      (6, 'limitations')
                           ) AS expected(position, payload_kind)
                           LEFT JOIN decision_report_sections actual
                             ON actual.report_id = NEW.id AND actual.position = expected.position
                            AND (actual.data_json::jsonb ->> 'payload_kind') = expected.payload_kind
                           WHERE actual.report_id IS NULL
                       ) THEN
                        RAISE EXCEPTION 'V2 decision report requires its complete seven-part outline' USING ERRCODE = '23514';
                    END IF;
                    IF encode(
                        digest(
                            convert_to(
                                decision_report_frame(NEW.generator_version)
                                || decision_report_frame(NEW.experiment_sha256)
                                || decision_report_frame(NEW.scenario_sha256)
                                || decision_report_frame(NEW.cohort_sha256)
                                || decision_report_frame(NEW.world_snapshot_id::text)
                                || decision_report_frame(NEW.world_snapshot_sha256)
                                || decision_report_frame(NEW.title)
                                || (
                                    SELECT string_agg(
                                        decision_report_frame(position::text)
                                        || decision_report_frame(kind)
                                        || decision_report_frame(title)
                                        || decision_report_frame(body_markdown)
                                        || decision_report_frame(data_json),
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
                        RAISE EXCEPTION 'V2 decision report content hash mismatch' USING ERRCODE = '23514';
                    END IF;
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


def _create_v1_report_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_decision_report_parent()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE selected_experiment semantic_experiments%ROWTYPE;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'decision reports cannot be truncated' USING ERRCODE = '55000';
            END IF;
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
                           VALUES (0, 'scope'), (1, 'comparison'),
                                  (2, 'limitations'), (3, 'provenance')
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
                            || (
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


def upgrade() -> None:
    op.add_column(
        "decision_reports",
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "decision_reports",
        sa.Column("world_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_decision_reports_world_snapshot",
        "decision_reports",
        "world_snapshots",
        ["world_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "decision_report_sections",
        sa.Column("data_json", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.drop_constraint("uq_decision_reports_experiment", "decision_reports", type_="unique")
    op.create_unique_constraint(
        "uq_decision_reports_experiment_version",
        "decision_reports",
        ["experiment_id", "generator_version"],
    )
    op.drop_constraint("ck_decision_reports_generator", "decision_reports", type_="check")
    op.create_check_constraint(
        "ck_decision_reports_generator",
        "decision_reports",
        "generator_version IN ('deterministic-findings/v1', 'decision-report/v2')",
    )
    op.create_check_constraint(
        "ck_decision_reports_snapshot_identity",
        "decision_reports",
        "(generator_version = 'deterministic-findings/v1' AND world_snapshot_id IS NULL "
        "AND world_snapshot_sha256 IS NULL) OR "
        "(generator_version = 'decision-report/v2' AND world_snapshot_id IS NOT NULL "
        "AND world_snapshot_sha256 ~ '^[a-f0-9]{64}$')",
    )
    op.drop_constraint(
        "ck_decision_report_sections_position", "decision_report_sections", type_="check"
    )
    op.create_check_constraint(
        "ck_decision_report_sections_position",
        "decision_report_sections",
        "position BETWEEN 0 AND 6",
    )
    op.drop_constraint(
        "ck_decision_report_sections_kind", "decision_report_sections", type_="check"
    )
    op.create_check_constraint(
        "ck_decision_report_sections_kind",
        "decision_report_sections",
        "kind IN ('scope', 'comparison', 'limitations', 'provenance', 'evidence', "
        "'assumptions', 'experiment', 'observation', 'analysis')",
    )
    op.create_check_constraint(
        "ck_decision_report_sections_data",
        "decision_report_sections",
        "jsonb_typeof(data_json::jsonb) = 'object'",
    )
    _drop_report_triggers()
    _create_report_triggers()


def downgrade() -> None:
    _drop_report_triggers()
    op.drop_constraint(
        "ck_decision_report_sections_data", "decision_report_sections", type_="check"
    )
    op.drop_constraint(
        "ck_decision_report_sections_kind", "decision_report_sections", type_="check"
    )
    op.create_check_constraint(
        "ck_decision_report_sections_kind",
        "decision_report_sections",
        "kind IN ('scope', 'comparison', 'limitations', 'provenance')",
    )
    op.drop_constraint(
        "ck_decision_report_sections_position", "decision_report_sections", type_="check"
    )
    op.create_check_constraint(
        "ck_decision_report_sections_position",
        "decision_report_sections",
        "position BETWEEN 0 AND 3",
    )
    op.drop_constraint("ck_decision_reports_snapshot_identity", "decision_reports", type_="check")
    op.drop_constraint("ck_decision_reports_generator", "decision_reports", type_="check")
    op.create_check_constraint(
        "ck_decision_reports_generator",
        "decision_reports",
        "generator_version = 'deterministic-findings/v1'",
    )
    op.drop_constraint("uq_decision_reports_experiment_version", "decision_reports", type_="unique")
    op.create_unique_constraint(
        "uq_decision_reports_experiment", "decision_reports", ["experiment_id"]
    )
    op.drop_constraint("fk_decision_reports_world_snapshot", "decision_reports", type_="foreignkey")
    op.drop_column("decision_report_sections", "data_json")
    op.drop_column("decision_reports", "world_snapshot_sha256")
    op.drop_column("decision_reports", "world_snapshot_id")
    _create_v1_report_triggers()
