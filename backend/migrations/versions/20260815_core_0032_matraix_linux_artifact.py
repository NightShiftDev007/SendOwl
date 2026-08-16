"""Create fixed MatrAIx Linux artifact trials.

Revision ID: 20260815_core_0032
Revises: 20260815_core_0031
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_core_0032"
down_revision: str | None = "20260815_core_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _extend_heartbeats() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column("linux_runtime_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for name, length in (
        ("linux_model_name", 200),
        ("linux_config_sha256", 64),
        ("linux_prompt_schema_version", 64),
        ("linux_runner_schema_version", 64),
        ("linux_runner_spec_sha256", 64),
    ):
        op.add_column(
            "simulation_worker_heartbeats",
            sa.Column(name, sa.String(length=length), nullable=True),
        )
    op.create_check_constraint(
        "ck_simulation_worker_linux_config",
        "simulation_worker_heartbeats",
        "(linux_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready "
        "AND length(btrim(linux_model_name)) BETWEEN 1 AND 200 "
        "AND linux_model_name !~ E'[\\r\\n]' "
        "AND linux_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND linux_prompt_schema_version='matraix-linux-note-to-csv/v1' "
        "AND linux_runner_schema_version='matraix-linux-artifact-runner/v1' "
        "AND linux_runner_spec_sha256="
        "'ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354') OR "
        "(NOT linux_runtime_ready AND linux_model_name IS NULL "
        "AND linux_config_sha256 IS NULL AND linux_prompt_schema_version IS NULL "
        "AND linux_runner_schema_version IS NULL AND linux_runner_spec_sha256 IS NULL)",
    )


def _create_table() -> None:
    op.create_table(
        "matraix_linux_trials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_title", sa.String(length=200), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona_position", sa.Integer(), nullable=False),
        sa.Column("persona_external_id", sa.String(length=128), nullable=False),
        sa.Column("persona_display_name", sa.String(length=200), nullable=False),
        sa.Column("persona_profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("task_version", sa.String(length=32), nullable=False),
        sa.Column("task_schema_version", sa.String(length=64), nullable=False),
        sa.Column("task_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("runner_schema_version", sa.String(length=64), nullable=False),
        sa.Column("runner_spec_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("linux_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("trial_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_runner_version", sa.String(length=32), nullable=True),
        sa.Column("result_artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_cleaned_list_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_submission_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_feedback_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_verifier_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_sha256", sa.String(length=64), nullable=True),
        sa.Column("result_reason", sa.Text(), nullable=True),
        sa.Column("result_need_satisfaction", sa.String(length=16), nullable=True),
        sa.Column("result_preference_satisfaction", sa.String(length=16), nullable=True),
        sa.Column("result_rating", sa.Integer(), nullable=True),
        sa.Column("result_feedback_reason", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint("length(btrim(cohort_title)) BETWEEN 1 AND 200", name="ck_linux_cohort"),
        sa.CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_linux_cohort_hashes",
        ),
        sa.CheckConstraint("persona_position BETWEEN 0 AND 99", name="ck_linux_persona_position"),
        sa.CheckConstraint(
            "persona_external_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_linux_persona_external_id",
        ),
        sa.CheckConstraint(
            "length(btrim(persona_display_name)) BETWEEN 1 AND 200",
            name="ck_linux_persona_name",
        ),
        sa.CheckConstraint(
            "persona_profile_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_persona_sha"
        ),
        sa.CheckConstraint("task_id='matraix/linux-note-to-csv'", name="ck_linux_task_id"),
        sa.CheckConstraint("task_version='1.0.0'", name="ck_linux_task_version"),
        sa.CheckConstraint(
            "task_schema_version='matraix-linux-task/note-to-csv-v1'",
            name="ck_linux_task_schema",
        ),
        sa.CheckConstraint(
            "task_spec_sha256='0a4bf540dec44e3ea488a2884eb1b4d3233470616e87c9ff370847b0509155a9'",
            name="ck_linux_task_sha",
        ),
        sa.CheckConstraint(
            "runner_schema_version='matraix-linux-artifact-runner/v1'",
            name="ck_linux_runner_schema",
        ),
        sa.CheckConstraint(
            "runner_spec_sha256='ec2a5c1dd6ae8daa9163f3d5749654ef8fcb53f750bcf6614f9a9883f0e01354'",
            name="ck_linux_runner_sha",
        ),
        sa.CheckConstraint("length(btrim(model_name)) BETWEEN 1 AND 200", name="ck_linux_model"),
        sa.CheckConstraint("linux_config_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_config_sha"),
        sa.CheckConstraint(
            "prompt_schema_version='matraix-linux-note-to-csv/v1'",
            name="ck_linux_prompt_schema",
        ),
        sa.CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_linux_trial_sha"),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')", name="ck_linux_status"
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_linux_started_at"
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="ck_linux_completed_at"
        ),
        sa.CheckConstraint(
            "result_need_satisfaction IS NULL OR result_need_satisfaction IN "
            "('yes','partially','no')",
            name="ck_linux_need",
        ),
        sa.CheckConstraint(
            "result_preference_satisfaction IS NULL OR result_preference_satisfaction IN "
            "('yes','partially','no')",
            name="ck_linux_preference",
        ),
        sa.CheckConstraint(
            "result_rating IS NULL OR result_rating BETWEEN 1 AND 10", name="ck_linux_rating"
        ),
        sa.CheckConstraint(
            "status='succeeded' OR (result_runner_version IS NULL "
            "AND result_artifact_sha256 IS NULL AND result_cleaned_list_sha256 IS NULL "
            "AND result_submission_sha256 IS NULL AND result_feedback_sha256 IS NULL "
            "AND result_verifier_sha256 IS NULL AND result_sha256 IS NULL "
            "AND result_reason IS NULL AND result_need_satisfaction IS NULL "
            "AND result_preference_satisfaction IS NULL AND result_rating IS NULL "
            "AND result_feedback_reason IS NULL)",
            name="ck_linux_non_success_results_empty",
        ),
        sa.CheckConstraint(
            "(status='queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR "
            "(status='running' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND result_sha256 IS NULL AND error_code IS NULL) OR "
            "(status='succeeded' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result_runner_version='1.0.0' "
            "AND result_artifact_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_cleaned_list_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_submission_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_feedback_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_verifier_sha256 ~ '^[a-f0-9]{64}$' "
            "AND result_sha256 ~ '^[a-f0-9]{64}$' AND result_reason IS NOT NULL "
            "AND result_need_satisfaction IS NOT NULL "
            "AND result_preference_satisfaction IS NOT NULL AND result_rating IS NOT NULL "
            "AND result_feedback_reason IS NOT NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status='failed' AND claimed_by_worker_id IS NOT NULL AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND result_sha256 IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_linux_lifecycle",
        ),
        sa.ForeignKeyConstraint(["cohort_id"], ["cohorts.id"]),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trial_sha256", name="uq_linux_trial_sha"),
    )
    op.create_index("ix_linux_trials_created", "matraix_linux_trials", ["created_at"])
    op.create_index(
        "ix_linux_trials_status_created", "matraix_linux_trials", ["status", "created_at"]
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION protect_matraix_linux_trial()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='DELETE' THEN
                IF OLD.status IN ('queued','running') THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'terminal Linux trial DELETE is forbidden' USING ERRCODE='55000';
            END IF;
            IF OLD.status='queued' AND NEW.status='running'
               AND (to_jsonb(NEW)-ARRAY['status','claimed_by_worker_id','started_at'])=
                   (to_jsonb(OLD)-ARRAY['status','claimed_by_worker_id','started_at'])
            THEN RETURN NEW; END IF;
            IF OLD.status='running' AND NEW.status IN ('succeeded','failed')
               AND (to_jsonb(NEW)-ARRAY[
                    'status','completed_at','result_runner_version','result_artifact_sha256',
                    'result_cleaned_list_sha256','result_submission_sha256',
                    'result_feedback_sha256','result_verifier_sha256','result_sha256',
                    'result_reason','result_need_satisfaction','result_preference_satisfaction',
                    'result_rating','result_feedback_reason','error_code','error_message'
               ])=(to_jsonb(OLD)-ARRAY[
                    'status','completed_at','result_runner_version','result_artifact_sha256',
                    'result_cleaned_list_sha256','result_submission_sha256',
                    'result_feedback_sha256','result_verifier_sha256','result_sha256',
                    'result_reason','result_need_satisfaction','result_preference_satisfaction',
                    'result_rating','result_feedback_reason','error_code','error_message'
               ])
            THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'Linux trial permits only queued to running to terminal'
                USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_linux_trial_protect BEFORE UPDATE OR DELETE ON "
        "matraix_linux_trials FOR EACH ROW EXECUTE FUNCTION protect_matraix_linux_trial()"
    )
    op.execute(
        """
        CREATE FUNCTION reject_matraix_linux_truncate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Linux trial TRUNCATE is forbidden' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_linux_trials_reject_truncate BEFORE TRUNCATE ON "
        "matraix_linux_trials FOR EACH STATEMENT EXECUTE FUNCTION reject_matraix_linux_truncate()"
    )


def upgrade() -> None:
    _extend_heartbeats()
    _create_table()
    _create_guards()


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_linux_trials_reject_truncate ON matraix_linux_trials")
    op.execute("DROP TRIGGER trg_linux_trial_protect ON matraix_linux_trials")
    op.execute("DROP FUNCTION reject_matraix_linux_truncate()")
    op.execute("DROP FUNCTION protect_matraix_linux_trial()")
    op.drop_index("ix_linux_trials_status_created", table_name="matraix_linux_trials")
    op.drop_index("ix_linux_trials_created", table_name="matraix_linux_trials")
    op.drop_table("matraix_linux_trials")
    op.drop_constraint(
        "ck_simulation_worker_linux_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    for column in (
        "linux_runner_spec_sha256",
        "linux_runner_schema_version",
        "linux_prompt_schema_version",
        "linux_config_sha256",
        "linux_model_name",
        "linux_runtime_ready",
    ):
        op.drop_column("simulation_worker_heartbeats", column)
