"""Add queued, immutable cited drafts for bounded ReportAgent evidence runs.

Revision ID: 20260816_core_0040
Revises: 20260816_core_0039
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0040"
down_revision: str | None = "20260816_core_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_agent_cited_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_call_count", sa.Integer(), nullable=False),
        sa.Column("evidence_calls_sha256", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("sections_json", sa.Text(), nullable=True),
        sa.Column("draft_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "evidence_call_count BETWEEN 1 AND 20",
            name="ck_report_agent_draft_evidence_count",
        ),
        sa.CheckConstraint(
            "run_sha256 ~ '^[a-f0-9]{64}$' AND evidence_calls_sha256 ~ '^[a-f0-9]{64}$' AND input_sha256 ~ '^[a-f0-9]{64}$' AND semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_report_agent_draft_input_hashes",
        ),
        sa.CheckConstraint(
            "prompt_schema_version='bounded-report-agent-cited-draft/v1'",
            name="ck_report_agent_draft_prompt_schema",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_report_agent_draft_status",
        ),
        sa.CheckConstraint(
            "(status='queued' AND started_at IS NULL AND completed_at IS NULL AND claimed_by_worker_id IS NULL AND title IS NULL AND sections_json IS NULL AND draft_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND started_at IS NOT NULL AND completed_at IS NULL AND claimed_by_worker_id IS NOT NULL AND title IS NULL AND sections_json IS NULL AND draft_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND length(btrim(title)) BETWEEN 1 AND 300 AND length(sections_json) BETWEEN 2 AND 100000 AND draft_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND title IS NULL AND sections_json IS NULL AND draft_sha256 IS NULL AND length(error_code) BETWEEN 1 AND 128 AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_report_agent_draft_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["report_agent_evidence_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("input_sha256", name="uq_report_agent_draft_input_sha256"),
    )
    op.create_index(
        "ix_report_agent_drafts_run_created",
        "report_agent_cited_drafts",
        ["run_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION report_agent_evidence_calls_sha(target_run_id uuid)
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
        CREATE FUNCTION validate_report_agent_draft_transition()
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
                    'bounded-report-agent-cited-draft-input/v1',
                    NEW.run_sha256,
                    expected_calls,
                    NEW.model_name,
                    NEW.semantic_config_sha256,
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
                        'bounded-report-agent-cited-draft/v1',
                        NEW.input_sha256,
                        NEW.title,
                        NEW.sections_json
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
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_draft_transition
        BEFORE INSERT OR UPDATE OR DELETE ON report_agent_cited_drafts
        FOR EACH ROW EXECUTE FUNCTION validate_report_agent_draft_transition()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_agent_draft_truncate
        BEFORE TRUNCATE ON report_agent_cited_drafts
        FOR EACH STATEMENT EXECUTE FUNCTION reject_report_agent_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_report_agent_draft_truncate ON report_agent_cited_drafts")
    op.execute("DROP TRIGGER trg_report_agent_draft_transition ON report_agent_cited_drafts")
    op.execute("DROP FUNCTION validate_report_agent_draft_transition()")
    op.execute("DROP FUNCTION report_agent_evidence_calls_sha(uuid)")
    op.drop_index(
        "ix_report_agent_drafts_run_created",
        table_name="report_agent_cited_drafts",
    )
    op.drop_table("report_agent_cited_drafts")
