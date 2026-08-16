"""Add bounded evidence-bound follow-up chains to report questions.

Revision ID: 20260813_core_0023
Revises: 20260813_core_0022
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0023"
down_revision: str | None = "20260813_core_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


THREADED_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_report_question_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_report decision_reports%ROWTYPE;
DECLARE selected_graph semantic_world_graphs%ROWTYPE;
DECLARE selected_scenario scenarios%ROWTYPE;
DECLARE selected_parent report_questions%ROWTYPE;
DECLARE expected_question_sha256 text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO STRICT selected_report FROM decision_reports WHERE id = NEW.report_id AND sealed_at IS NOT NULL FOR SHARE;
        SELECT * INTO STRICT selected_graph FROM semantic_world_graphs WHERE id = NEW.graph_id AND status = 'succeeded' FOR SHARE;
        SELECT * INTO STRICT selected_scenario FROM scenarios WHERE id = selected_report.scenario_id AND sealed_at IS NOT NULL FOR SHARE;
        IF NEW.parent_question_id IS NULL THEN
            expected_question_sha256 := encode(digest(
                convert_to('report-evidence-qa/v1', 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.report_sha256, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.graph_sha256, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.question, 'UTF8'), 'sha256'), 'hex');
        ELSE
            SELECT * INTO STRICT selected_parent FROM report_questions
            WHERE id = NEW.parent_question_id AND status = 'succeeded' FOR SHARE;
            IF selected_parent.report_id <> NEW.report_id
               OR selected_parent.graph_id <> NEW.graph_id
               OR selected_parent.model_name <> NEW.model_name
               OR selected_parent.semantic_config_sha256 <> NEW.semantic_config_sha256
               OR selected_parent.question_sha256 <> NEW.parent_question_sha256
               OR selected_parent.answer_sha256 <> NEW.parent_answer_sha256
               OR selected_parent.conversation_depth + 1 <> NEW.conversation_depth THEN
                RAISE EXCEPTION 'report question parent lineage mismatch' USING ERRCODE = '23514';
            END IF;
            expected_question_sha256 := encode(digest(
                convert_to('report-evidence-qa/v2', 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.report_sha256, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.graph_sha256, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.question, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.parent_question_sha256, 'UTF8') || decode('00', 'hex') ||
                convert_to(NEW.parent_answer_sha256, 'UTF8'), 'sha256'), 'hex');
        END IF;
        IF selected_report.report_sha256 <> NEW.report_sha256
           OR selected_graph.graph_sha256 <> NEW.graph_sha256
           OR selected_graph.world_model_id <> selected_scenario.world_model_id
           OR selected_graph.snapshot_id <> selected_scenario.world_snapshot_id
           OR selected_graph.snapshot_sha256 <> selected_scenario.snapshot_sha256
           OR selected_graph.model_name <> NEW.model_name
           OR selected_graph.semantic_config_sha256 <> NEW.semantic_config_sha256
           OR expected_question_sha256 <> NEW.question_sha256 THEN
            RAISE EXCEPTION 'report question immutable input mismatch' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'queued' AND NEW.status = 'running'
       AND (to_jsonb(NEW) - ARRAY['status','started_at','claimed_by_worker_id']) =
           (to_jsonb(OLD) - ARRAY['status','started_at','claimed_by_worker_id']) THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed')
       AND (to_jsonb(NEW) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) =
           (to_jsonb(OLD) - ARRAY['status','completed_at','answer_markdown','citations_json','answer_sha256','error_code','error_message']) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid report question state transition' USING ERRCODE = '55000';
END;
$$
"""


ROOT_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_report_question_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_report decision_reports%ROWTYPE;
DECLARE selected_graph semantic_world_graphs%ROWTYPE;
DECLARE selected_scenario scenarios%ROWTYPE;
DECLARE expected_question_sha256 text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO STRICT selected_report FROM decision_reports WHERE id = NEW.report_id AND sealed_at IS NOT NULL FOR SHARE;
        SELECT * INTO STRICT selected_graph FROM semantic_world_graphs WHERE id = NEW.graph_id AND status = 'succeeded' FOR SHARE;
        SELECT * INTO STRICT selected_scenario FROM scenarios WHERE id = selected_report.scenario_id AND sealed_at IS NOT NULL FOR SHARE;
        expected_question_sha256 := encode(digest(
            convert_to('report-evidence-qa/v1', 'UTF8') || decode('00', 'hex') ||
            convert_to(NEW.report_sha256, 'UTF8') || decode('00', 'hex') ||
            convert_to(NEW.graph_sha256, 'UTF8') || decode('00', 'hex') ||
            convert_to(NEW.question, 'UTF8'), 'sha256'), 'hex');
        IF selected_report.report_sha256 <> NEW.report_sha256
           OR selected_graph.graph_sha256 <> NEW.graph_sha256
           OR selected_graph.world_model_id <> selected_scenario.world_model_id
           OR selected_graph.snapshot_id <> selected_scenario.world_snapshot_id
           OR selected_graph.snapshot_sha256 <> selected_scenario.snapshot_sha256
           OR selected_graph.model_name <> NEW.model_name
           OR selected_graph.semantic_config_sha256 <> NEW.semantic_config_sha256
           OR expected_question_sha256 <> NEW.question_sha256 THEN
            RAISE EXCEPTION 'report question immutable input mismatch' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'queued' AND NEW.status = 'running'
       AND OLD.id = NEW.id AND OLD.report_id = NEW.report_id AND OLD.report_sha256 = NEW.report_sha256
       AND OLD.graph_id = NEW.graph_id AND OLD.graph_sha256 = NEW.graph_sha256
       AND OLD.question = NEW.question AND OLD.question_sha256 = NEW.question_sha256
       AND OLD.model_name = NEW.model_name AND OLD.semantic_config_sha256 = NEW.semantic_config_sha256
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at THEN RETURN NEW; END IF;
    IF OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed')
       AND OLD.id = NEW.id AND OLD.report_id = NEW.report_id AND OLD.report_sha256 = NEW.report_sha256
       AND OLD.graph_id = NEW.graph_id AND OLD.graph_sha256 = NEW.graph_sha256
       AND OLD.question = NEW.question AND OLD.question_sha256 = NEW.question_sha256
       AND OLD.model_name = NEW.model_name AND OLD.semantic_config_sha256 = NEW.semantic_config_sha256
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at
       AND OLD.started_at = NEW.started_at AND OLD.claimed_by_worker_id = NEW.claimed_by_worker_id THEN RETURN NEW; END IF;
    RAISE EXCEPTION 'invalid report question state transition' USING ERRCODE = '55000';
END;
$$
"""


def upgrade() -> None:
    op.add_column(
        "report_questions",
        sa.Column("parent_question_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("report_questions", sa.Column("parent_question_sha256", sa.String(64)))
    op.add_column("report_questions", sa.Column("parent_answer_sha256", sa.String(64)))
    op.add_column(
        "report_questions",
        sa.Column("conversation_depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("report_questions", "conversation_depth", server_default=None)
    op.create_foreign_key(
        "fk_report_questions_parent",
        "report_questions",
        "report_questions",
        ["parent_question_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_report_questions_prompt_schema", "report_questions", type_="check")
    op.create_check_constraint(
        "ck_report_questions_prompt_schema",
        "report_questions",
        "prompt_schema_version IN ('report-evidence-qa/v1', 'report-evidence-qa/v2')",
    )
    op.create_check_constraint(
        "ck_report_questions_lineage",
        "report_questions",
        "(conversation_depth = 0 AND parent_question_id IS NULL AND parent_question_sha256 IS NULL AND parent_answer_sha256 IS NULL AND prompt_schema_version = 'report-evidence-qa/v1') OR "
        "(conversation_depth BETWEEN 1 AND 4 AND parent_question_id IS NOT NULL AND parent_question_sha256 ~ '^[a-f0-9]{64}$' AND parent_answer_sha256 ~ '^[a-f0-9]{64}$' AND prompt_schema_version = 'report-evidence-qa/v2')",
    )
    op.execute(THREADED_FUNCTION)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM report_questions WHERE parent_question_id IS NOT NULL) THEN
                RAISE EXCEPTION 'cannot downgrade while follow-up report questions exist';
            END IF;
        END $$
        """
    )
    op.execute(ROOT_ONLY_FUNCTION)
    op.drop_constraint("ck_report_questions_lineage", "report_questions", type_="check")
    op.drop_constraint("ck_report_questions_prompt_schema", "report_questions", type_="check")
    op.create_check_constraint(
        "ck_report_questions_prompt_schema",
        "report_questions",
        "prompt_schema_version = 'report-evidence-qa/v1'",
    )
    op.drop_constraint("fk_report_questions_parent", "report_questions", type_="foreignkey")
    op.drop_column("report_questions", "conversation_depth")
    op.drop_column("report_questions", "parent_answer_sha256")
    op.drop_column("report_questions", "parent_question_sha256")
    op.drop_column("report_questions", "parent_question_id")
