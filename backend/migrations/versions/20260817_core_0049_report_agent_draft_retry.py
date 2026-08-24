"""Add immutable retry lineage to failed ReportAgent drafts.

Revision ID: 20260817_core_0049
Revises: 20260816_core_0048
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_core_0049"
down_revision: str | None = "20260816_core_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_transition_with_retry_lineage() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_draft_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE scope_parent report_agent_evidence_runs%ROWTYPE;
        DECLARE retry_parent report_agent_cited_drafts%ROWTYPE;
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
                SELECT * INTO scope_parent FROM report_agent_evidence_runs
                WHERE id=NEW.run_id FOR SHARE;
                IF NOT FOUND OR scope_parent.run_sha256 IS DISTINCT FROM NEW.run_sha256 THEN
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
                IF NEW.attempt_number=1 THEN
                    IF NEW.retry_of_draft_id IS NOT NULL
                       OR NEW.retry_of_input_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION 'ReportAgent root draft cannot have retry lineage'
                            USING ERRCODE='55000';
                    END IF;
                ELSE
                    SELECT * INTO retry_parent FROM report_agent_cited_drafts
                    WHERE id=NEW.retry_of_draft_id FOR SHARE;
                    IF NOT FOUND OR retry_parent.status <> 'failed'
                       OR retry_parent.input_sha256 IS DISTINCT FROM NEW.retry_of_input_sha256
                       OR retry_parent.input_sha256 IS DISTINCT FROM NEW.input_sha256
                       OR retry_parent.attempt_number + 1 <> NEW.attempt_number
                       OR retry_parent.run_id IS DISTINCT FROM NEW.run_id
                       OR retry_parent.run_sha256 IS DISTINCT FROM NEW.run_sha256
                       OR retry_parent.evidence_call_count IS DISTINCT FROM NEW.evidence_call_count
                       OR retry_parent.evidence_calls_sha256 IS DISTINCT FROM NEW.evidence_calls_sha256
                       OR retry_parent.model_name IS DISTINCT FROM NEW.model_name
                       OR retry_parent.semantic_config_sha256 IS DISTINCT FROM NEW.semantic_config_sha256
                       OR retry_parent.prompt_schema_version IS DISTINCT FROM NEW.prompt_schema_version THEN
                        RAISE EXCEPTION 'ReportAgent retry lineage is invalid'
                            USING ERRCODE='55000';
                    END IF;
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


def _install_transition_without_retry_lineage() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION validate_report_agent_draft_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE scope_parent report_agent_evidence_runs%ROWTYPE;
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
                SELECT * INTO scope_parent FROM report_agent_evidence_runs
                WHERE id=NEW.run_id FOR SHARE;
                IF NOT FOUND OR scope_parent.run_sha256 IS DISTINCT FROM NEW.run_sha256 THEN
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


def upgrade() -> None:
    op.add_column(
        "report_agent_cited_drafts",
        sa.Column("retry_of_draft_id", postgresql.UUID(as_uuid=True)),
    )
    op.add_column(
        "report_agent_cited_drafts",
        sa.Column("retry_of_input_sha256", sa.String(length=64)),
    )
    op.add_column(
        "report_agent_cited_drafts",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        "fk_report_agent_draft_retry_parent",
        "report_agent_cited_drafts",
        "report_agent_cited_drafts",
        ["retry_of_draft_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_report_agent_draft_input_sha256",
        "report_agent_cited_drafts",
        type_="unique",
    )
    op.create_index(
        "uq_report_agent_draft_root_input",
        "report_agent_cited_drafts",
        ["input_sha256"],
        unique=True,
        postgresql_where=sa.text("attempt_number=1"),
    )
    op.create_unique_constraint(
        "uq_report_agent_draft_input_attempt",
        "report_agent_cited_drafts",
        ["input_sha256", "attempt_number"],
    )
    op.create_unique_constraint(
        "uq_report_agent_draft_retry_parent",
        "report_agent_cited_drafts",
        ["retry_of_draft_id"],
    )
    op.create_check_constraint(
        "ck_report_agent_draft_retry_lineage",
        "report_agent_cited_drafts",
        "(attempt_number=1 AND retry_of_draft_id IS NULL "
        "AND retry_of_input_sha256 IS NULL) OR "
        "(attempt_number BETWEEN 2 AND 5 AND retry_of_draft_id IS NOT NULL "
        "AND retry_of_input_sha256 ~ '^[a-f0-9]{64}$')",
    )
    _install_transition_with_retry_lineage()


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM report_agent_cited_drafts WHERE attempt_number > 1
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while ReportAgent retry drafts exist';
            END IF;
        END; $$
        """
    )
    op.drop_constraint(
        "ck_report_agent_draft_retry_lineage",
        "report_agent_cited_drafts",
        type_="check",
    )
    op.drop_constraint(
        "uq_report_agent_draft_retry_parent",
        "report_agent_cited_drafts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_report_agent_draft_input_attempt",
        "report_agent_cited_drafts",
        type_="unique",
    )
    op.drop_index(
        "uq_report_agent_draft_root_input",
        table_name="report_agent_cited_drafts",
    )
    op.create_unique_constraint(
        "uq_report_agent_draft_input_sha256",
        "report_agent_cited_drafts",
        ["input_sha256"],
    )
    op.drop_constraint(
        "fk_report_agent_draft_retry_parent",
        "report_agent_cited_drafts",
        type_="foreignkey",
    )
    _install_transition_without_retry_lineage()
    op.drop_column("report_agent_cited_drafts", "attempt_number")
    op.drop_column("report_agent_cited_drafts", "retry_of_input_sha256")
    op.drop_column("report_agent_cited_drafts", "retry_of_draft_id")
