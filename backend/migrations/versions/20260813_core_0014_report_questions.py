"""Add evidence-bound report question queue.

Revision ID: 20260813_core_0014
Revises: 20260812_core_0013
Create Date: 2026-08-13
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0014"
down_revision: str | None = "20260812_core_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column("answer_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000", name="ck_report_questions_text"
        ),
        sa.CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND graph_sha256 ~ '^[a-f0-9]{64}$' AND question_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_report_questions_input_digests",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_report_questions_status",
        ),
        sa.CheckConstraint(
            "prompt_schema_version = 'report-evidence-qa/v1'",
            name="ck_report_questions_prompt_schema",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND started_at IS NOT NULL AND completed_at IS NULL AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND length(answer_markdown) BETWEEN 1 AND 12000 AND length(citations_json) >= 2 AND answer_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL AND citations_json IS NULL AND answer_sha256 IS NULL AND length(error_code) BETWEEN 1 AND 128 AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_report_questions_lifecycle",
        ),
        sa.ForeignKeyConstraint(["report_id"], ["decision_reports.id"]),
        sa.ForeignKeyConstraint(["graph_id"], ["semantic_world_graphs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_sha256", name="uq_report_questions_sha256"),
    )
    op.create_index(
        "ix_report_questions_report_created", "report_questions", ["report_id", "created_at"]
    )
    op.execute(
        """
        CREATE FUNCTION validate_report_question_transition()
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
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_questions_transition
        BEFORE INSERT OR UPDATE OR DELETE ON report_questions
        FOR EACH ROW EXECUTE FUNCTION validate_report_question_transition()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_report_questions_truncate
        BEFORE TRUNCATE ON report_questions
        FOR EACH STATEMENT EXECUTE FUNCTION validate_report_question_transition()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_report_questions_truncate ON report_questions")
    op.execute("DROP TRIGGER trg_report_questions_transition ON report_questions")
    op.execute("DROP FUNCTION validate_report_question_transition()")
    op.drop_index("ix_report_questions_report_created", table_name="report_questions")
    op.drop_table("report_questions")
