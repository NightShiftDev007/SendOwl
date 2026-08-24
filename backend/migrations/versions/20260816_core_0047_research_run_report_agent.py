"""Bind ReportAgent scopes to one sealed SandOwl simulation run.

Revision ID: 20260816_core_0047
Revises: 20260816_core_0046
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0047"
down_revision: str | None = "20260816_core_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_SCHEMA = "bounded-report-agent-evidence/v1"
RESEARCH_RUN_SCHEMA = "sandowl-research-run-report-agent/v1"


def _install_run_validator() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION validate_report_agent_run_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE snapshot world_snapshots%ROWTYPE;
        DECLARE linked_report_sha text;
        DECLARE linked_world_model_id uuid;
        DECLARE linked_snapshot_id uuid;
        DECLARE linked_snapshot_sha text;
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
            IF NEW.schema_version='{LEGACY_SCHEMA}' THEN
                IF NEW.research_simulation_run_id IS NOT NULL
                   OR NEW.research_run_report_sha256 IS NOT NULL THEN
                    RAISE EXCEPTION 'legacy ReportAgent scope cannot bind a research run'
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
            ELSIF NEW.schema_version='{RESEARCH_RUN_SCHEMA}' THEN
                SELECT report.report_sha256, project.world_model_id,
                       project.world_snapshot_id, project.snapshot_sha256
                INTO linked_report_sha, linked_world_model_id,
                     linked_snapshot_id, linked_snapshot_sha
                FROM research_simulation_runs run
                JOIN research_projects project ON project.id=run.research_project_id
                JOIN research_run_reports report ON report.run_id=run.id
                WHERE run.id=NEW.research_simulation_run_id AND run.status='succeeded'
                FOR SHARE OF run, project, report;
                IF NOT FOUND
                   OR linked_report_sha IS DISTINCT FROM NEW.research_run_report_sha256
                   OR linked_world_model_id IS DISTINCT FROM NEW.world_model_id
                   OR linked_snapshot_id IS DISTINCT FROM NEW.world_snapshot_id
                   OR linked_snapshot_sha IS DISTINCT FROM NEW.snapshot_sha256
                   OR NEW.max_tool_calls <> 1 THEN
                    RAISE EXCEPTION 'ReportAgent research-run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected := report_agent_digest(ARRAY[
                    NEW.schema_version,
                    NEW.world_model_id::text,
                    NEW.world_snapshot_id::text,
                    NEW.snapshot_sha256,
                    NEW.research_simulation_run_id::text,
                    NEW.research_run_report_sha256,
                    NEW.objective,
                    NEW.outline_json,
                    NEW.max_tool_calls::text
                ]);
            ELSE
                RAISE EXCEPTION 'unsupported ReportAgent run schema'
                    USING ERRCODE='55000';
            END IF;
            IF NEW.run_sha256 IS DISTINCT FROM expected THEN
                RAISE EXCEPTION 'ReportAgent run hash mismatch' USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )


def _install_tool_validator() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_tool_call_insert()
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
            ELSIF NEW.tool_name='read_policy' THEN
                SELECT content_sha256 INTO expected_result
                FROM world_snapshot_policy_evidence
                WHERE snapshot_id=parent.world_snapshot_id AND policy_version_id=NEW.target_id;
            ELSIF NEW.tool_name='read_simulation_run'
               AND parent.schema_version='sandowl-research-run-report-agent/v1'
               AND NEW.target_id=parent.research_simulation_run_id
               AND NEW.result_text IS NOT NULL THEN
                expected_result := encode(digest(convert_to(NEW.result_text, 'UTF8'), 'sha256'), 'hex');
            ELSE
                RAISE EXCEPTION 'ReportAgent tool is outside its parent scope'
                    USING ERRCODE='55000';
            END IF;
            IF expected_result IS NULL OR NEW.result_sha256 IS DISTINCT FROM expected_result THEN
                RAISE EXCEPTION 'ReportAgent tool result is outside its sealed scope'
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


def _install_draft_functions() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION report_agent_evidence_calls_sha(target_run_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE call_hashes text[];
        BEGIN
            SELECT array_agg(call_sha256 ORDER BY position) INTO call_hashes
            FROM report_agent_evidence_tool_calls
            WHERE run_id=target_run_id
              AND tool_name IN ('read_media','read_policy','read_simulation_run');
            IF call_hashes IS NULL OR array_length(call_hashes, 1) < 1 THEN
                RAISE EXCEPTION 'ReportAgent cited draft requires at least one audited evidence read'
                    USING ERRCODE='55000';
            END IF;
            RETURN report_agent_digest(
                array_prepend('bounded-report-agent-evidence-calls/v1', call_hashes)
            );
        END; $$
        """
    )
    _install_draft_transition()


def _install_draft_transition() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_draft_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent report_agent_evidence_runs%ROWTYPE;
        DECLARE expected_calls text;
        DECLARE expected_call_count integer;
        DECLARE expected_input text;
        DECLARE expected_draft text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'ReportAgent cited drafts are immutable'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                SELECT * INTO parent FROM report_agent_evidence_runs
                WHERE id=NEW.run_id FOR SHARE;
                IF NOT FOUND OR parent.run_sha256 IS DISTINCT FROM NEW.run_sha256 THEN
                    RAISE EXCEPTION 'ReportAgent cited draft run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected_calls := report_agent_evidence_calls_sha(NEW.run_id);
                SELECT count(*) INTO expected_call_count
                FROM report_agent_evidence_tool_calls
                WHERE run_id=NEW.run_id
                  AND tool_name IN ('read_media','read_policy','read_simulation_run');
                expected_input := report_agent_digest(ARRAY[
                    'bounded-report-agent-cited-draft-input/v1', NEW.run_sha256,
                    expected_calls, NEW.model_name, NEW.semantic_config_sha256,
                    NEW.prompt_schema_version
                ]);
                IF NEW.evidence_call_count IS DISTINCT FROM expected_call_count
                   OR NEW.evidence_calls_sha256 IS DISTINCT FROM expected_calls
                   OR NEW.input_sha256 IS DISTINCT FROM expected_input THEN
                    RAISE EXCEPTION 'ReportAgent cited draft input hash mismatch'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) THEN
                IF NEW.status='succeeded' THEN
                    expected_draft := report_agent_digest(ARRAY[
                        'bounded-report-agent-cited-draft/v1', NEW.input_sha256,
                        NEW.title, NEW.sections_json
                    ]);
                    IF NEW.draft_sha256 IS DISTINCT FROM expected_draft THEN
                        RAISE EXCEPTION 'ReportAgent cited draft output hash mismatch'
                            USING ERRCODE='55000';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid ReportAgent cited draft state transition'
                USING ERRCODE='55000';
        END; $$
        """
    )


def _install_legacy_validators() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_run_insert()
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
                NEW.schema_version, NEW.world_model_id::text, NEW.world_snapshot_id::text,
                NEW.snapshot_sha256, NEW.objective, NEW.outline_json,
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
        CREATE OR REPLACE FUNCTION validate_report_agent_tool_call_insert()
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
                'bounded-report-agent-tool-input/v1', parent.run_sha256,
                NEW.position::text, NEW.tool_name, coalesce(NEW.target_id::text, '')
            ]);
            expected_call := report_agent_digest(ARRAY[
                'bounded-report-agent-tool-call/v1', expected_input, NEW.result_sha256
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
        CREATE OR REPLACE FUNCTION report_agent_evidence_calls_sha(target_run_id uuid)
        RETURNS text LANGUAGE plpgsql STABLE STRICT AS $$
        DECLARE call_hashes text[];
        BEGIN
            SELECT array_agg(call_sha256 ORDER BY position) INTO call_hashes
            FROM report_agent_evidence_tool_calls
            WHERE run_id=target_run_id AND tool_name IN ('read_media','read_policy');
            IF call_hashes IS NULL OR array_length(call_hashes, 1) < 1 THEN
                RAISE EXCEPTION 'ReportAgent cited draft requires at least one audited evidence read'
                    USING ERRCODE='55000';
            END IF;
            RETURN report_agent_digest(
                array_prepend('bounded-report-agent-evidence-calls/v1', call_hashes)
            );
        END; $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_draft_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent report_agent_evidence_runs%ROWTYPE;
        DECLARE expected_calls text;
        DECLARE expected_call_count integer;
        DECLARE expected_input text;
        DECLARE expected_draft text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'ReportAgent cited drafts are immutable'
                    USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                SELECT * INTO parent FROM report_agent_evidence_runs
                WHERE id=NEW.run_id FOR SHARE;
                IF NOT FOUND OR parent.run_sha256 IS DISTINCT FROM NEW.run_sha256 THEN
                    RAISE EXCEPTION 'ReportAgent cited draft run scope mismatch'
                        USING ERRCODE='55000';
                END IF;
                expected_calls := report_agent_evidence_calls_sha(NEW.run_id);
                SELECT count(*) INTO expected_call_count
                FROM report_agent_evidence_tool_calls
                WHERE run_id=NEW.run_id AND tool_name IN ('read_media','read_policy');
                expected_input := report_agent_digest(ARRAY[
                    'bounded-report-agent-cited-draft-input/v1', NEW.run_sha256,
                    expected_calls, NEW.model_name, NEW.semantic_config_sha256,
                    NEW.prompt_schema_version
                ]);
                IF NEW.evidence_call_count IS DISTINCT FROM expected_call_count
                   OR NEW.evidence_calls_sha256 IS DISTINCT FROM expected_calls
                   OR NEW.input_sha256 IS DISTINCT FROM expected_input THEN
                    RAISE EXCEPTION 'ReportAgent cited draft input hash mismatch'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','title','sections_json','draft_sha256','error_code','error_message']) THEN
                IF NEW.status='succeeded' THEN
                    expected_draft := report_agent_digest(ARRAY[
                        'bounded-report-agent-cited-draft/v1', NEW.input_sha256,
                        NEW.title, NEW.sections_json
                    ]);
                    IF NEW.draft_sha256 IS DISTINCT FROM expected_draft THEN
                        RAISE EXCEPTION 'ReportAgent cited draft output hash mismatch'
                            USING ERRCODE='55000';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid ReportAgent cited draft state transition'
                USING ERRCODE='55000';
        END; $$
        """
    )


def upgrade() -> None:
    op.add_column(
        "report_agent_evidence_runs",
        sa.Column("research_simulation_run_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "report_agent_evidence_runs",
        sa.Column("research_run_report_sha256", sa.String(length=64)),
    )
    op.create_foreign_key(
        "fk_report_agent_runs_research_run",
        "report_agent_evidence_runs",
        "research_simulation_runs",
        ["research_simulation_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_report_agent_runs_research_run",
        "report_agent_evidence_runs",
        ["research_simulation_run_id"],
    )
    op.add_column(
        "report_agent_evidence_tool_calls",
        sa.Column("result_text", sa.Text()),
    )
    op.drop_constraint("ck_report_agent_run_schema", "report_agent_evidence_runs", type_="check")
    op.create_check_constraint(
        "ck_report_agent_run_schema",
        "report_agent_evidence_runs",
        f"(schema_version='{LEGACY_SCHEMA}' AND research_simulation_run_id IS NULL AND research_run_report_sha256 IS NULL) OR "
        f"(schema_version='{RESEARCH_RUN_SCHEMA}' AND research_simulation_run_id IS NOT NULL AND research_run_report_sha256 ~ '^[a-f0-9]{{64}}$' AND max_tool_calls=1)",
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_name", "report_agent_evidence_tool_calls", type_="check"
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_target", "report_agent_evidence_tool_calls", type_="check"
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_name",
        "report_agent_evidence_tool_calls",
        "tool_name IN ('list_evidence','read_media','read_policy','read_simulation_run')",
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_target",
        "report_agent_evidence_tool_calls",
        "(tool_name='list_evidence' AND target_id IS NULL AND result_text IS NULL) OR "
        "(tool_name IN ('read_media','read_policy') AND target_id IS NOT NULL AND result_text IS NULL) OR "
        "(tool_name='read_simulation_run' AND target_id IS NOT NULL AND length(result_text) BETWEEN 1 AND 500000)",
    )
    _install_run_validator()
    _install_tool_validator()
    _install_draft_functions()


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM report_agent_evidence_runs
                WHERE schema_version='{RESEARCH_RUN_SCHEMA}'
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while research-run ReportAgent scopes exist';
            END IF;
        END; $$
        """
    )
    _install_legacy_validators()
    op.drop_constraint(
        "ck_report_agent_tool_call_target", "report_agent_evidence_tool_calls", type_="check"
    )
    op.drop_constraint(
        "ck_report_agent_tool_call_name", "report_agent_evidence_tool_calls", type_="check"
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_name",
        "report_agent_evidence_tool_calls",
        "tool_name IN ('list_evidence','read_media','read_policy')",
    )
    op.create_check_constraint(
        "ck_report_agent_tool_call_target",
        "report_agent_evidence_tool_calls",
        "(tool_name='list_evidence' AND target_id IS NULL) OR "
        "(tool_name IN ('read_media','read_policy') AND target_id IS NOT NULL)",
    )
    op.drop_constraint("ck_report_agent_run_schema", "report_agent_evidence_runs", type_="check")
    op.create_check_constraint(
        "ck_report_agent_run_schema",
        "report_agent_evidence_runs",
        f"schema_version='{LEGACY_SCHEMA}'",
    )
    op.drop_constraint(
        "uq_report_agent_runs_research_run", "report_agent_evidence_runs", type_="unique"
    )
    op.drop_constraint(
        "fk_report_agent_runs_research_run", "report_agent_evidence_runs", type_="foreignkey"
    )
    op.drop_column("report_agent_evidence_tool_calls", "result_text")
    op.drop_column("report_agent_evidence_runs", "research_run_report_sha256")
    op.drop_column("report_agent_evidence_runs", "research_simulation_run_id")
