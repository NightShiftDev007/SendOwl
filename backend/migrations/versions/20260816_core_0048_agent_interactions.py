"""Bind Agent Interaction to one native ReportAgent single-run report.

Revision ID: 20260816_core_0048
Revises: 20260816_core_0047
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_core_0048"
down_revision: str | None = "20260816_core_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_simulation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "report_agent_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_agent_evidence_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("report_agent_run_sha256", sa.String(64), nullable=False),
        sa.Column(
            "report_agent_draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("report_agent_cited_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("report_agent_draft_sha256", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("interaction_sha256", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(64), nullable=False),
        sa.Column(
            "parent_interaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_interactions.id", ondelete="RESTRICT"),
        ),
        sa.Column("parent_interaction_sha256", sa.String(64)),
        sa.Column("parent_answer_sha256", sa.String(64)),
        sa.Column("conversation_depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_worker_id", sa.String(128)),
        sa.Column("answer_markdown", sa.Text()),
        sa.Column("citations_json", sa.Text()),
        sa.Column("answer_sha256", sa.String(64)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("error_message", sa.String(500)),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000", name="ck_agent_interactions_question"
        ),
        sa.CheckConstraint(
            "conversation_depth BETWEEN 0 AND 4", name="ck_agent_interactions_depth"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_agent_interactions_status",
        ),
        sa.CheckConstraint(
            "prompt_schema_version IN ('sandowl-agent-interaction/v1','sandowl-agent-interaction/v2')",
            name="ck_agent_interactions_prompt_schema",
        ),
        sa.UniqueConstraint("interaction_sha256", name="uq_agent_interactions_sha256"),
    )
    op.create_index(
        "ix_agent_interactions_draft_created",
        "agent_interactions",
        ["report_agent_draft_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION validate_agent_interaction_transition()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE native_run report_agent_evidence_runs%ROWTYPE;
        DECLARE draft report_agent_cited_drafts%ROWTYPE;
        DECLARE simulation_project_id uuid;
        DECLARE frozen_source_sha text;
        DECLARE parent agent_interactions%ROWTYPE;
        DECLARE expected_schema text;
        DECLARE expected_input text;
        DECLARE expected_answer text;
        BEGIN
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Agent Interactions are immutable' USING ERRCODE='55000';
            END IF;
            IF TG_OP='INSERT' THEN
                SELECT * INTO native_run FROM report_agent_evidence_runs
                WHERE id=NEW.report_agent_run_id
                  AND schema_version='sandowl-research-run-report-agent/v1'
                  AND research_simulation_run_id=NEW.research_simulation_run_id
                FOR SHARE;
                SELECT * INTO draft FROM report_agent_cited_drafts
                WHERE id=NEW.report_agent_draft_id AND run_id=NEW.report_agent_run_id
                  AND status='succeeded' FOR SHARE;
                SELECT research_project_id INTO simulation_project_id
                FROM research_simulation_runs WHERE id=NEW.research_simulation_run_id FOR SHARE;
                SELECT result_sha256 INTO frozen_source_sha
                FROM report_agent_evidence_tool_calls
                WHERE run_id=NEW.report_agent_run_id AND tool_name='read_simulation_run'
                  AND target_id=NEW.research_simulation_run_id FOR SHARE;
                IF native_run.id IS NULL OR draft.id IS NULL
                   OR draft.draft_sha256 IS NULL
                   OR simulation_project_id IS DISTINCT FROM NEW.research_project_id
                   OR native_run.run_sha256 IS DISTINCT FROM NEW.report_agent_run_sha256
                   OR draft.draft_sha256 IS DISTINCT FROM NEW.report_agent_draft_sha256
                   OR frozen_source_sha IS DISTINCT FROM NEW.source_sha256
                   OR draft.model_name IS DISTINCT FROM NEW.model_name
                   OR draft.semantic_config_sha256 IS DISTINCT FROM NEW.semantic_config_sha256 THEN
                    RAISE EXCEPTION 'Agent Interaction single-run scope mismatch' USING ERRCODE='55000';
                END IF;
                IF NEW.parent_interaction_id IS NULL THEN
                    IF NEW.parent_interaction_sha256 IS NOT NULL
                       OR NEW.parent_answer_sha256 IS NOT NULL
                       OR NEW.conversation_depth <> 0 THEN
                        RAISE EXCEPTION 'Agent Interaction root lineage mismatch' USING ERRCODE='55000';
                    END IF;
                    expected_schema := 'sandowl-agent-interaction/v1';
                ELSE
                    SELECT * INTO parent FROM agent_interactions
                    WHERE id=NEW.parent_interaction_id AND status='succeeded' FOR SHARE;
                    IF parent.id IS NULL
                       OR parent.report_agent_draft_id IS DISTINCT FROM NEW.report_agent_draft_id
                       OR parent.interaction_sha256 IS DISTINCT FROM NEW.parent_interaction_sha256
                       OR parent.answer_sha256 IS DISTINCT FROM NEW.parent_answer_sha256
                       OR NEW.conversation_depth <> parent.conversation_depth + 1 THEN
                        RAISE EXCEPTION 'Agent Interaction follow-up lineage mismatch' USING ERRCODE='55000';
                    END IF;
                    expected_schema := 'sandowl-agent-interaction/v2';
                END IF;
                expected_input := report_agent_digest(ARRAY[
                    expected_schema, NEW.research_project_id::text,
                    NEW.research_simulation_run_id::text, NEW.report_agent_run_sha256,
                    NEW.report_agent_draft_sha256, NEW.source_sha256, NEW.question,
                    coalesce(NEW.parent_interaction_sha256, ''),
                    coalesce(NEW.parent_answer_sha256, '')
                ]);
                IF NEW.prompt_schema_version IS DISTINCT FROM expected_schema
                   OR NEW.interaction_sha256 IS DISTINCT FROM expected_input
                   OR NEW.status <> 'queued' OR NEW.started_at IS NOT NULL
                   OR NEW.completed_at IS NOT NULL OR NEW.claimed_by_worker_id IS NOT NULL
                   OR NEW.answer_markdown IS NOT NULL OR NEW.citations_json IS NOT NULL
                   OR NEW.answer_sha256 IS NOT NULL OR NEW.error_code IS NOT NULL
                   OR NEW.error_message IS NOT NULL THEN
                    RAISE EXCEPTION 'Agent Interaction queued input mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND NEW.started_at IS NOT NULL AND NEW.claimed_by_worker_id IS NOT NULL
               AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND NEW.completed_at IS NOT NULL
               AND (to_jsonb(NEW) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) =
                   (to_jsonb(OLD) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) THEN
                IF NEW.status='succeeded' THEN
                    expected_answer := report_agent_digest(ARRAY[
                        'sandowl-agent-interaction-answer/v1', NEW.interaction_sha256,
                        NEW.answer_markdown, NEW.citations_json
                    ]);
                    IF NEW.answer_markdown IS NULL OR NEW.citations_json IS NULL
                       OR NEW.answer_sha256 IS DISTINCT FROM expected_answer
                       OR NEW.error_code IS NOT NULL OR NEW.error_message IS NOT NULL THEN
                        RAISE EXCEPTION 'Agent Interaction answer mismatch' USING ERRCODE='55000';
                    END IF;
                ELSIF NEW.answer_markdown IS NOT NULL OR NEW.citations_json IS NOT NULL
                   OR NEW.answer_sha256 IS NOT NULL OR NEW.error_code IS NULL
                   OR NEW.error_message IS NULL THEN
                    RAISE EXCEPTION 'Agent Interaction failure mismatch' USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'invalid Agent Interaction state transition' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_interaction_transition
        BEFORE INSERT OR UPDATE OR DELETE ON agent_interactions
        FOR EACH ROW EXECUTE FUNCTION validate_agent_interaction_transition()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS agent_interaction_transition ON agent_interactions")
    op.execute("DROP FUNCTION IF EXISTS validate_agent_interaction_transition()")
    op.drop_index("ix_agent_interactions_draft_created", table_name="agent_interactions")
    op.drop_table("agent_interactions")
