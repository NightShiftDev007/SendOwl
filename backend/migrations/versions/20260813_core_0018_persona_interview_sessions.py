"""Add immutable multi-Persona report interview sessions.

Revision ID: 20260813_core_0018
Revises: 20260813_core_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_core_0018"
down_revision: str | None = "20260813_core_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persona_interview_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("persona_count", sa.Integer(), nullable=False),
        sa.Column("session_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(btrim(question)) BETWEEN 2 AND 1000",
            name="ck_persona_interview_sessions_question",
        ),
        sa.CheckConstraint(
            "persona_count BETWEEN 2 AND 8", name="ck_persona_interview_sessions_count"
        ),
        sa.CheckConstraint(
            "report_sha256 ~ '^[a-f0-9]{64}$' AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND session_sha256 ~ '^[a-f0-9]{64}$' "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_interview_sessions_digests",
        ),
        sa.CheckConstraint(
            "prompt_schema_version='persona-report-interview-session/v1'",
            name="ck_persona_interview_sessions_schema",
        ),
        sa.CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_persona_interview_sessions_sealed_time",
        ),
        sa.ForeignKeyConstraint(["report_id"], ["decision_reports.id"]),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_sha256", name="uq_persona_interview_sessions_sha256"),
    )
    op.create_index(
        "ix_persona_interview_sessions_report_created",
        "persona_interview_sessions",
        ["report_id", "created_at"],
    )
    op.create_table(
        "persona_interview_session_members",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "position BETWEEN 0 AND 7", name="ck_persona_interview_session_members_position"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["persona_interview_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.ForeignKeyConstraint(["interview_id"], ["persona_report_interviews.id"]),
        sa.PrimaryKeyConstraint("session_id", "position"),
        sa.UniqueConstraint("session_id", "persona_id", name="uq_session_member_persona"),
        sa.UniqueConstraint("session_id", "interview_id", name="uq_session_member_interview"),
    )
    op.execute(
        """
        CREATE FUNCTION protect_persona_interview_session()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE member_count integer;
        DECLARE first_position integer;
        DECLARE last_position integer;
        DECLARE personas_json text;
        DECLARE expected_sha text;
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.sealed_at IS NOT NULL OR NOT EXISTS (
                    SELECT 1 FROM decision_reports report
                    JOIN cohorts cohort ON cohort.id=NEW.cohort_id AND cohort.sealed_at IS NOT NULL
                    WHERE report.id=NEW.report_id AND report.sealed_at IS NOT NULL
                      AND report.report_sha256=NEW.report_sha256
                      AND report.cohort_id=NEW.cohort_id
                      AND report.cohort_sha256=NEW.cohort_sha256
                      AND cohort.cohort_sha256=NEW.cohort_sha256
                ) THEN
                    RAISE EXCEPTION 'Persona interview session requires sealed report inputs'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP='DELETE' THEN
                IF OLD.sealed_at IS NULL THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'sealed Persona interview sessions are append-only'
                    USING ERRCODE='55000';
            END IF;
            IF OLD.sealed_at IS NULL AND NEW.sealed_at IS NOT NULL
               AND (to_jsonb(NEW)-'sealed_at')=(to_jsonb(OLD)-'sealed_at')
            THEN
                SELECT count(*), min(position), max(position), string_agg(
                    '[' || to_json(member.persona_id::text)::text || ',' ||
                    to_json(interview.persona_profile_sha256)::text || ']',
                    ',' ORDER BY member.position
                ) INTO member_count, first_position, last_position, personas_json
                FROM persona_interview_session_members member
                JOIN persona_report_interviews interview ON interview.id=member.interview_id
                WHERE member.session_id=NEW.id;
                expected_sha := encode(sha256(convert_to(concat_ws(
                    chr(0), 'persona-report-interview-session/v1', NEW.report_sha256,
                    NEW.cohort_sha256, '[' || coalesce(personas_json, '') || ']',
                    NEW.question, NEW.semantic_config_sha256
                ), 'UTF8')), 'hex');
                IF member_count <> NEW.persona_count OR first_position <> 0
                   OR last_position <> NEW.persona_count-1
                   OR NEW.session_sha256 IS DISTINCT FROM expected_sha
                THEN
                    RAISE EXCEPTION 'Persona interview session members or digest are incomplete'
                        USING ERRCODE='55000';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Persona interview session input is immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_persona_interview_session_protect BEFORE INSERT OR UPDATE OR DELETE "
        "ON persona_interview_sessions FOR EACH ROW "
        "EXECUTE FUNCTION protect_persona_interview_session()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_persona_interview_session_member()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent persona_interview_sessions%ROWTYPE;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Persona interview session members are append-only'
                    USING ERRCODE='55000';
            END IF;
            SELECT * INTO parent FROM persona_interview_sessions
            WHERE id=NEW.session_id FOR UPDATE;
            IF NOT FOUND OR parent.sealed_at IS NOT NULL OR NOT EXISTS (
                SELECT 1 FROM persona_report_interviews interview
                WHERE interview.id=NEW.interview_id
                  AND interview.persona_id=NEW.persona_id
                  AND interview.report_id=parent.report_id
                  AND interview.report_sha256=parent.report_sha256
                  AND interview.cohort_id=parent.cohort_id
                  AND interview.cohort_sha256=parent.cohort_sha256
                  AND interview.question=parent.question
                  AND interview.model_name=parent.model_name
                  AND interview.semantic_config_sha256=parent.semantic_config_sha256
            ) THEN
                RAISE EXCEPTION 'Persona interview session member does not match its draft'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_persona_interview_session_member_protect "
        "BEFORE INSERT OR UPDATE OR DELETE ON persona_interview_session_members FOR EACH ROW "
        "EXECUTE FUNCTION protect_persona_interview_session_member()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_persona_interview_session_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Persona interview session TRUNCATE is forbidden'
                USING ERRCODE='55000';
        END; $$
        """
    )
    for table_name in (
        "persona_interview_sessions",
        "persona_interview_session_members",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_reject_truncate BEFORE TRUNCATE ON "
            f"{table_name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION reject_persona_interview_session_truncate()"
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_persona_interview_session_members_reject_truncate "
        "ON persona_interview_session_members"
    )
    op.execute(
        "DROP TRIGGER trg_persona_interview_sessions_reject_truncate ON persona_interview_sessions"
    )
    op.execute(
        "DROP TRIGGER trg_persona_interview_session_member_protect "
        "ON persona_interview_session_members"
    )
    op.execute("DROP TRIGGER trg_persona_interview_session_protect ON persona_interview_sessions")
    op.execute("DROP FUNCTION reject_persona_interview_session_truncate()")
    op.execute("DROP FUNCTION protect_persona_interview_session_member()")
    op.execute("DROP FUNCTION protect_persona_interview_session()")
    op.drop_table("persona_interview_session_members")
    op.drop_index(
        "ix_persona_interview_sessions_report_created",
        table_name="persona_interview_sessions",
    )
    op.drop_table("persona_interview_sessions")
