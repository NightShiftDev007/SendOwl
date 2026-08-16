"""Add the fixed MatrAIx Acme Support MCP Chat task.

Revision ID: 20260813_core_0024
Revises: 20260813_core_0023
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260813_core_0024"
down_revision: str | None = "20260813_core_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REST_TASK_ID = "matraix/acme-support-order-4521"
MCP_TASK_ID = "matraix/acme-support-mcp-order-4521"
REST_TASK_SHA = "4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1"
MCP_TASK_SHA = "cd92b749ac08d0a229c3ea6191c52f03c096b03aff1689f5da04e7ec2daabd98"
REST_SUT_SHA = "b3609ac5ab58a4994c497f276d4689b8272150a9251676ddef84ebe9e8bdc980"
MCP_SUT_SHA = "5fbc2623be9df873de0c025edd1f2dcbf9d0b24672d627f1e063002c9e9587e1"
SUITE_ID = "sendowl/matraix-acme-rest-mcp-suite"
SUITE_SHA = "0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"


def _drop_chat_checks() -> None:
    for name in (
        "ck_chat_eval_task_id",
        "ck_chat_eval_task_spec_sha",
        "ck_chat_eval_sut_spec_sha",
    ):
        op.drop_constraint(name, "matraix_chat_evaluations", type_="check")


def _reset_chat_heartbeats() -> None:
    op.execute(
        """
        UPDATE simulation_worker_heartbeats SET
            chat_runtime_ready=false,
            chat_model_name=NULL,
            chat_config_sha256=NULL,
            chat_prompt_schema_version=NULL,
            chat_sut_task_id=NULL,
            chat_sut_task_version=NULL,
            chat_sut_spec_sha256=NULL
        """
    )


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM matraix_chat_trials WHERE status IN ('queued','running')
            ) THEN
                RAISE EXCEPTION
                    'cannot add MCP Chat while REST Chat trials are queued or running';
            END IF;
        END $$
        """
    )
    _drop_chat_checks()
    op.create_check_constraint(
        "ck_chat_eval_task_id",
        "matraix_chat_evaluations",
        f"task_id IN ('{REST_TASK_ID}','{MCP_TASK_ID}')",
    )
    op.create_check_constraint(
        "ck_chat_eval_task_spec_sha",
        "matraix_chat_evaluations",
        f"(task_id='{REST_TASK_ID}' AND task_spec_sha256='{REST_TASK_SHA}') OR "
        f"(task_id='{MCP_TASK_ID}' AND task_spec_sha256='{MCP_TASK_SHA}')",
    )
    op.create_check_constraint(
        "ck_chat_eval_sut_spec_sha",
        "matraix_chat_evaluations",
        f"(task_id='{REST_TASK_ID}' AND sut_spec_sha256='{REST_SUT_SHA}') OR "
        f"(task_id='{MCP_TASK_ID}' AND sut_spec_sha256='{MCP_SUT_SHA}')",
    )
    _reset_chat_heartbeats()
    op.drop_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready "
        "AND length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND chat_prompt_schema_version='matraix-chat-acme-support/v1' "
        f"AND chat_sut_task_id='{SUITE_ID}' "
        "AND chat_sut_task_version='1.0.0' "
        f"AND chat_sut_spec_sha256='{SUITE_SHA}') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM matraix_chat_evaluations WHERE task_id='{MCP_TASK_ID}'
            ) THEN
                RAISE EXCEPTION 'cannot downgrade while MCP Chat evaluations exist';
            END IF;
        END $$
        """
    )
    _drop_chat_checks()
    op.create_check_constraint(
        "ck_chat_eval_task_id",
        "matraix_chat_evaluations",
        f"task_id='{REST_TASK_ID}'",
    )
    op.create_check_constraint(
        "ck_chat_eval_task_spec_sha",
        "matraix_chat_evaluations",
        f"task_spec_sha256='{REST_TASK_SHA}'",
    )
    op.create_check_constraint(
        "ck_chat_eval_sut_spec_sha",
        "matraix_chat_evaluations",
        f"sut_spec_sha256='{REST_SUT_SHA}'",
    )
    _reset_chat_heartbeats()
    op.drop_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready "
        "AND length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND chat_prompt_schema_version='matraix-chat-acme-support/v1' "
        f"AND chat_sut_task_id='{REST_TASK_ID}' "
        "AND chat_sut_task_version='1.0.0' "
        f"AND chat_sut_spec_sha256='{REST_SUT_SHA}') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )
