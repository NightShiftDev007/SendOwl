"""Rename the transient Chat worker suite identity to SandOwl.

Revision ID: 20260816_core_0043
Revises: 20260816_core_0042
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_core_0043"
down_revision: str | None = "20260816_core_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_SUITE_ID = "sendowl/matraix-acme-rest-mcp-suite"
SANDOWL_SUITE_ID = "sandowl/matraix-acme-rest-mcp-suite"
SUITE_SHA256 = "0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a"


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


def _replace_chat_constraint(suite_id: str) -> None:
    op.drop_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        type_="check",
    )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND worker_domain = 'evaluation' "
        "AND length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND chat_prompt_schema_version = 'matraix-chat-acme-support/v1' "
        f"AND chat_sut_task_id = '{suite_id}' "
        "AND chat_sut_task_version = '1.0.0' "
        f"AND chat_sut_spec_sha256 = '{SUITE_SHA256}') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )


def upgrade() -> None:
    # Heartbeats describe live processes and can be safely republished after deployment.
    _reset_chat_heartbeats()
    op.execute("DELETE FROM simulation_worker_heartbeats WHERE worker_id LIKE 'sendowl-%'")
    _replace_chat_constraint(SANDOWL_SUITE_ID)


def downgrade() -> None:
    _reset_chat_heartbeats()
    _replace_chat_constraint(LEGACY_SUITE_ID)
