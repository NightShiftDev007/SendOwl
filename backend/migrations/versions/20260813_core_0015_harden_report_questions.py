"""Harden report question content addressing without replacing existing data.

Revision ID: 20260813_core_0015
Revises: 20260813_core_0014
Create Date: 2026-08-13
"""

# ruff: noqa: E501

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_core_0015"
down_revision: str | None = "20260813_core_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LIFECYCLE_800 = (
    "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
    "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
    "(status = 'succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND length(answer_markdown) BETWEEN 1 AND 800 AND length(citations_json) >= 2 AND answer_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL AND error_message IS NULL) OR "
    "(status = 'failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND length(error_code) BETWEEN 1 AND 128 AND length(error_message) BETWEEN 1 AND 500)"
)

LIFECYCLE_12000 = LIFECYCLE_800.replace("BETWEEN 1 AND 800", "BETWEEN 1 AND 12000")

HARDENED_FUNCTION = """
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
            convert_to(NEW.question, 'UTF8'), 'sha256'
        ), 'hex');
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
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed')
       AND OLD.id = NEW.id AND OLD.report_id = NEW.report_id AND OLD.report_sha256 = NEW.report_sha256
       AND OLD.graph_id = NEW.graph_id AND OLD.graph_sha256 = NEW.graph_sha256
       AND OLD.question = NEW.question AND OLD.question_sha256 = NEW.question_sha256
       AND OLD.model_name = NEW.model_name AND OLD.semantic_config_sha256 = NEW.semantic_config_sha256
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at
       AND OLD.started_at = NEW.started_at AND OLD.claimed_by_worker_id = NEW.claimed_by_worker_id THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid report question state transition' USING ERRCODE = '55000';
END;
$$
"""

ORIGINAL_FUNCTION = """
CREATE OR REPLACE FUNCTION validate_report_question_transition()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE selected_report decision_reports%ROWTYPE;
DECLARE selected_graph semantic_world_graphs%ROWTYPE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT * INTO STRICT selected_report FROM decision_reports WHERE id = NEW.report_id AND sealed_at IS NOT NULL FOR SHARE;
        SELECT * INTO STRICT selected_graph FROM semantic_world_graphs WHERE id = NEW.graph_id AND status = 'succeeded' FOR SHARE;
        IF selected_report.report_sha256 <> NEW.report_sha256 OR selected_graph.graph_sha256 <> NEW.graph_sha256 THEN
            RAISE EXCEPTION 'report question immutable input mismatch' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'queued' AND NEW.status = 'running'
       AND OLD.id = NEW.id AND OLD.report_id = NEW.report_id AND OLD.report_sha256 = NEW.report_sha256
       AND OLD.graph_id = NEW.graph_id AND OLD.graph_sha256 = NEW.graph_sha256
       AND OLD.question = NEW.question AND OLD.question_sha256 = NEW.question_sha256
       AND OLD.model_name = NEW.model_name AND OLD.semantic_config_sha256 = NEW.semantic_config_sha256
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed')
       AND OLD.id = NEW.id AND OLD.report_id = NEW.report_id AND OLD.report_sha256 = NEW.report_sha256
       AND OLD.graph_id = NEW.graph_id AND OLD.graph_sha256 = NEW.graph_sha256
       AND OLD.question = NEW.question AND OLD.question_sha256 = NEW.question_sha256
       AND OLD.model_name = NEW.model_name AND OLD.semantic_config_sha256 = NEW.semantic_config_sha256
       AND OLD.prompt_schema_version = NEW.prompt_schema_version AND OLD.created_at = NEW.created_at
       AND OLD.started_at = NEW.started_at AND OLD.claimed_by_worker_id = NEW.claimed_by_worker_id THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'invalid report question state transition' USING ERRCODE = '55000';
END;
$$
"""


def upgrade() -> None:
    op.drop_constraint("ck_report_questions_lifecycle", "report_questions", type_="check")
    op.create_check_constraint(
        "ck_report_questions_lifecycle",
        "report_questions",
        LIFECYCLE_800,
    )
    op.execute(HARDENED_FUNCTION)


def downgrade() -> None:
    op.drop_constraint("ck_report_questions_lifecycle", "report_questions", type_="check")
    op.create_check_constraint(
        "ck_report_questions_lifecycle",
        "report_questions",
        LIFECYCLE_12000,
    )
    op.execute(ORIGINAL_FUNCTION)
