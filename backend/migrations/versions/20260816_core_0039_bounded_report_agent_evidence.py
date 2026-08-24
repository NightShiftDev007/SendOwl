"""Add immutable bounded ReportAgent evidence runs and audited read tools.

Revision ID: 20260816_core_0039
Revises: 20260816_core_0038
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0039"
down_revision: str | None = "20260816_core_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_agent_evidence_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("outline_json", sa.Text(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("run_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(objective)) BETWEEN 2 AND 1000",
            name="ck_report_agent_run_objective",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(outline_json::jsonb)='array' AND jsonb_array_length(outline_json::jsonb) BETWEEN 2 AND 6",
            name="ck_report_agent_run_outline",
        ),
        sa.CheckConstraint(
            "max_tool_calls BETWEEN 1 AND 20",
            name="ck_report_agent_run_tool_budget",
        ),
        sa.CheckConstraint(
            "schema_version='bounded-report-agent-evidence/v1'",
            name="ck_report_agent_run_schema",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND run_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_report_agent_run_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["world_model_id"],
            ["world_models.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["world_snapshot_id"],
            ["world_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_sha256", name="uq_report_agent_run_sha256"),
    )
    op.create_index(
        "ix_report_agent_runs_snapshot_created",
        "report_agent_evidence_runs",
        ["world_snapshot_id", "created_at"],
    )
    op.create_table(
        "report_agent_evidence_tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("call_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 19",
            name="ck_report_agent_tool_call_position",
        ),
        sa.CheckConstraint(
            "tool_name IN ('list_evidence','read_media','read_policy')",
            name="ck_report_agent_tool_call_name",
        ),
        sa.CheckConstraint(
            "(tool_name='list_evidence' AND target_id IS NULL) OR (tool_name IN ('read_media','read_policy') AND target_id IS NOT NULL)",
            name="ck_report_agent_tool_call_target",
        ),
        sa.CheckConstraint(
            "input_sha256 ~ '^[a-f0-9]{64}$' AND result_sha256 ~ '^[a-f0-9]{64}$' AND call_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_report_agent_tool_call_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["report_agent_evidence_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "position", name="uq_report_agent_tool_call_position"),
        sa.UniqueConstraint("call_sha256", name="uq_report_agent_tool_call_sha256"),
    )
    op.execute(
        """
        CREATE FUNCTION report_agent_digest(parts text[])
        RETURNS text LANGUAGE plpgsql IMMUTABLE STRICT AS $$
        DECLARE payload bytea := ''::bytea;
        DECLARE item text;
        DECLARE first_item boolean := true;
        BEGIN
            FOREACH item IN ARRAY parts LOOP
                IF item IS NULL THEN
                    RAISE EXCEPTION 'ReportAgent digest parts cannot be null'
                        USING ERRCODE='22023';
                END IF;
                IF NOT first_item THEN payload := payload || decode('00', 'hex'); END IF;
                payload := payload || convert_to(item, 'UTF8');
                first_item := false;
            END LOOP;
            RETURN encode(digest(payload, 'sha256'), 'hex');
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_report_agent_run_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot world_snapshots%ROWTYPE;
        DECLARE expected text;
        BEGIN
            SELECT * INTO snapshot FROM world_snapshots
            WHERE id=NEW.world_snapshot_id AND sealed_at IS NOT NULL FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ReportAgent run requires a sealed WorldSnapshot'
                    USING ERRCODE='55000';
            END IF;
            IF snapshot.world_model_id IS DISTINCT FROM NEW.world_model_id
               OR snapshot.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256 THEN
                RAISE EXCEPTION 'ReportAgent run snapshot scope mismatch'
                    USING ERRCODE='55000';
            END IF;
            expected := report_agent_digest(ARRAY[
                NEW.schema_version,
                NEW.world_model_id::text,
                NEW.world_snapshot_id::text,
                NEW.snapshot_sha256,
                NEW.objective,
                NEW.outline_json,
                NEW.max_tool_calls::text
            ]);
            IF NEW.run_sha256 IS DISTINCT FROM expected THEN
                RAISE EXCEPTION 'ReportAgent run hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_report_agent_tool_call_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent report_agent_evidence_runs%ROWTYPE;
        DECLARE stored_count integer;
        DECLARE expected_result text;
        DECLARE expected_input text;
        DECLARE expected_call text;
        BEGIN
            SELECT * INTO parent FROM report_agent_evidence_runs
            WHERE id=NEW.run_id FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'ReportAgent tool call parent run is missing'
                    USING ERRCODE='55000';
            END IF;
            SELECT count(*) INTO stored_count FROM report_agent_evidence_tool_calls
            WHERE run_id=NEW.run_id;
            IF NEW.position <> stored_count OR stored_count >= parent.max_tool_calls THEN
                RAISE EXCEPTION 'ReportAgent tool calls must be contiguous and within budget'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.tool_name='list_evidence' THEN
                expected_result := parent.snapshot_sha256;
            ELSIF NEW.tool_name='read_media' THEN
                SELECT captured_text_sha256 INTO expected_result
                FROM world_snapshot_evidence
                WHERE snapshot_id=parent.world_snapshot_id AND article_id=NEW.target_id;
            ELSE
                SELECT content_sha256 INTO expected_result
                FROM world_snapshot_policy_evidence
                WHERE snapshot_id=parent.world_snapshot_id AND policy_version_id=NEW.target_id;
            END IF;
            IF expected_result IS NULL OR NEW.result_sha256 IS DISTINCT FROM expected_result THEN
                RAISE EXCEPTION 'ReportAgent tool result is outside its sealed snapshot scope'
                    USING ERRCODE='55000';
            END IF;
            expected_input := report_agent_digest(ARRAY[
                'bounded-report-agent-tool-input/v1',
                parent.run_sha256,
                NEW.position::text,
                NEW.tool_name,
                coalesce(NEW.target_id::text, '')
            ]);
            expected_call := report_agent_digest(ARRAY[
                'bounded-report-agent-tool-call/v1',
                expected_input,
                NEW.result_sha256
            ]);
            IF NEW.input_sha256 IS DISTINCT FROM expected_input
               OR NEW.call_sha256 IS DISTINCT FROM expected_call THEN
                RAISE EXCEPTION 'ReportAgent tool call hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_report_agent_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'ReportAgent evidence records are append-only'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_run_validate
        BEFORE INSERT ON report_agent_evidence_runs
        FOR EACH ROW EXECUTE FUNCTION validate_report_agent_run_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_run_immutable
        BEFORE UPDATE OR DELETE ON report_agent_evidence_runs
        FOR EACH ROW EXECUTE FUNCTION reject_report_agent_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_run_truncate
        BEFORE TRUNCATE ON report_agent_evidence_runs
        FOR EACH STATEMENT EXECUTE FUNCTION reject_report_agent_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_tool_validate
        BEFORE INSERT ON report_agent_evidence_tool_calls
        FOR EACH ROW EXECUTE FUNCTION validate_report_agent_tool_call_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_tool_immutable
        BEFORE UPDATE OR DELETE ON report_agent_evidence_tool_calls
        FOR EACH ROW EXECUTE FUNCTION reject_report_agent_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_tool_truncate
        BEFORE TRUNCATE ON report_agent_evidence_tool_calls
        FOR EACH STATEMENT EXECUTE FUNCTION reject_report_agent_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_report_agent_tool_truncate ON report_agent_evidence_tool_calls")
    op.execute("DROP TRIGGER trg_report_agent_tool_immutable ON report_agent_evidence_tool_calls")
    op.execute("DROP TRIGGER trg_report_agent_tool_validate ON report_agent_evidence_tool_calls")
    op.execute("DROP TRIGGER trg_report_agent_run_truncate ON report_agent_evidence_runs")
    op.execute("DROP TRIGGER trg_report_agent_run_immutable ON report_agent_evidence_runs")
    op.execute("DROP TRIGGER trg_report_agent_run_validate ON report_agent_evidence_runs")
    op.execute("DROP FUNCTION reject_report_agent_mutation()")
    op.execute("DROP FUNCTION validate_report_agent_tool_call_insert()")
    op.execute("DROP FUNCTION validate_report_agent_run_insert()")
    op.execute("DROP FUNCTION report_agent_digest(text[])")
    op.drop_table("report_agent_evidence_tool_calls")
    op.drop_index(
        "ix_report_agent_runs_snapshot_created",
        table_name="report_agent_evidence_runs",
    )
    op.drop_table("report_agent_evidence_runs")
