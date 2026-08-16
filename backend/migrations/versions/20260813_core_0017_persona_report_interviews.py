"""Add report-grounded synthetic Persona interviews.

Revision ID: 20260813_core_0017
Revises: 20260813_core_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0017"
down_revision: str | None = "20260813_core_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persona_report_interviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_position", sa.Integer(), nullable=False),
        sa.Column("persona_external_id", sa.String(length=128), nullable=False),
        sa.Column("persona_display_name", sa.String(length=200), nullable=False),
        sa.Column("persona_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("interview_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("cited_section_positions_json", sa.Text(), nullable=True),
        sa.Column("answer_sha256", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "persona_position BETWEEN 0 AND 99", name="ck_persona_interviews_position"
        ),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_persona_interviews_question",
        ),
        sa.CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND persona_profile_sha256 ~ '^[a-f0-9]{64}$' "
            "AND interview_sha256 ~ '^[a-f0-9]{64}$' "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_interviews_digests",
        ),
        sa.CheckConstraint(
            "prompt_schema_version='persona-report-interview/v1'",
            name="ck_persona_interviews_prompt_schema",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name="ck_persona_interviews_status",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_persona_interviews_started_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_persona_interviews_completed_time",
        ),
        sa.CheckConstraint(
            "(status='queued' AND started_at IS NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='running' AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status='succeeded' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND length(answer_markdown) BETWEEN 1 AND 2000 "
            "AND length(cited_section_positions_json) >= 3 "
            "AND answer_sha256 ~ '^[a-f0-9]{64}$' AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='failed' AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND claimed_by_worker_id IS NOT NULL AND answer_markdown IS NULL "
            "AND cited_section_positions_json IS NULL AND answer_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_persona_interviews_lifecycle",
        ),
        sa.ForeignKeyConstraint(["report_id"], ["decision_reports.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("interview_sha256", name="uq_persona_interviews_sha256"),
    )
    op.create_index(
        "ix_persona_interviews_report_created",
        "persona_report_interviews",
        ["report_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION protect_persona_report_interview()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE expected_interview_sha text;
        DECLARE expected_answer_sha text;
        BEGIN
            IF TG_OP='INSERT' THEN
                expected_interview_sha := encode(sha256(convert_to(concat_ws(
                    chr(0), 'persona-report-interview/v1', NEW.report_sha256,
                    NEW.cohort_sha256, NEW.persona_id::text,
                    NEW.persona_profile_sha256, NEW.question,
                    NEW.semantic_config_sha256
                ), 'UTF8')), 'hex');
                IF NEW.status <> 'queued' OR NOT EXISTS (
                    SELECT 1 FROM decision_reports report
                    JOIN cohorts cohort ON cohort.id=NEW.cohort_id AND cohort.sealed_at IS NOT NULL
                    JOIN cohort_members member
                      ON member.cohort_id=cohort.id AND member.persona_id=NEW.persona_id
                    JOIN personas persona ON persona.id=member.persona_id
                    WHERE report.id=NEW.report_id AND report.sealed_at IS NOT NULL
                      AND report.report_sha256=NEW.report_sha256
                      AND report.cohort_id=NEW.cohort_id
                      AND report.cohort_sha256=NEW.cohort_sha256
                      AND cohort.cohort_sha256=NEW.cohort_sha256
                      AND member.position=NEW.persona_position
                      AND persona.persona_id=NEW.persona_external_id
                      AND persona.display_name=NEW.persona_display_name
                      AND persona.profile_sha256=NEW.persona_profile_sha256
                ) OR NEW.interview_sha256 IS DISTINCT FROM expected_interview_sha THEN
                    RAISE EXCEPTION 'Persona interview does not match sealed report Cohort input'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' THEN
                RAISE EXCEPTION 'Persona interviews are append-only' USING ERRCODE='55000';
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW)-ARRAY['status','started_at','claimed_by_worker_id']) =
                   (to_jsonb(OLD)-ARRAY['status','started_at','claimed_by_worker_id'])
            THEN RETURN NEW; END IF;
            IF OLD.status='running' AND NEW.status='succeeded'
               AND (to_jsonb(NEW)-ARRAY[
                    'status','completed_at','answer_markdown',
                    'cited_section_positions_json','answer_sha256'
               ]) = (to_jsonb(OLD)-ARRAY[
                    'status','completed_at','answer_markdown',
                    'cited_section_positions_json','answer_sha256'
               ])
            THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        NEW.cited_section_positions_json::jsonb
                    ) WITH ORDINALITY AS item(value, position)
                    HAVING count(*) BETWEEN 1 AND 4
                       AND bool_and(item.value ~ '^[0-3]$')
                       AND array_agg(
                            CASE WHEN item.value ~ '^[0-3]$' THEN item.value::integer ELSE -1 END
                            ORDER BY item.position
                       ) = array_agg(
                            DISTINCT CASE
                                WHEN item.value ~ '^[0-3]$' THEN item.value::integer ELSE -1
                            END ORDER BY CASE
                                WHEN item.value ~ '^[0-3]$' THEN item.value::integer ELSE -1
                            END
                       )
                ) THEN
                    RAISE EXCEPTION 'Persona interview section citations are invalid'
                        USING ERRCODE='55000';
                END IF;
                expected_answer_sha := encode(sha256(convert_to(concat_ws(
                    chr(0), 'persona-report-interview-answer/v1',
                    NEW.interview_sha256, NEW.answer_markdown,
                    NEW.cited_section_positions_json
                ), 'UTF8')), 'hex');
                IF NEW.answer_sha256 IS DISTINCT FROM expected_answer_sha THEN
                    RAISE EXCEPTION 'Persona interview answer digest mismatch'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status='running' AND NEW.status='failed'
               AND (to_jsonb(NEW)-ARRAY['status','completed_at','error_code','error_message']) =
                   (to_jsonb(OLD)-ARRAY['status','completed_at','error_code','error_message'])
            THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'Persona interview permits only queued -> running -> terminal'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_persona_report_interview_protect BEFORE INSERT OR UPDATE OR DELETE "
        "ON persona_report_interviews FOR EACH ROW "
        "EXECUTE FUNCTION protect_persona_report_interview()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_persona_report_interview_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Persona interview TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_persona_report_interview_reject_truncate BEFORE TRUNCATE "
        "ON persona_report_interviews FOR EACH STATEMENT "
        "EXECUTE FUNCTION reject_persona_report_interview_truncate()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_persona_report_interview_reject_truncate ON persona_report_interviews"
    )
    op.execute("DROP TRIGGER trg_persona_report_interview_protect ON persona_report_interviews")
    op.execute("DROP FUNCTION reject_persona_report_interview_truncate()")
    op.execute("DROP FUNCTION protect_persona_report_interview()")
    op.drop_index(
        "ix_persona_interviews_report_created",
        table_name="persona_report_interviews",
    )
    op.drop_table("persona_report_interviews")
