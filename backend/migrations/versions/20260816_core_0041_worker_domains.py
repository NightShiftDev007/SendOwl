"""Add strict worker domains to the existing OASIS heartbeat projection.

Revision ID: 20260816_core_0041
Revises: 20260816_core_0040
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_core_0041"
down_revision: str | None = "20260816_core_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_runtime_constraints() -> None:
    for name in (
        "ck_simulation_worker_semantic_config",
        "ck_simulation_worker_survey_config",
        "ck_simulation_worker_chat_config",
        "ck_simulation_worker_web_config",
        "ck_simulation_worker_linux_config",
    ):
        op.drop_constraint(name, "simulation_worker_heartbeats", type_="check")


def _create_runtime_constraints() -> None:
    op.create_check_constraint(
        "ck_simulation_worker_semantic_config",
        "simulation_worker_heartbeats",
        "(semantic_runtime_ready AND worker_domain IN ('semantic', 'report') "
        "AND length(btrim(semantic_model_name)) BETWEEN 1 AND 200 "
        "AND semantic_model_name !~ E'[\\r\\n]' "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND semantic_prompt_schema_version = 'matraix-semantic-profile/v1') OR "
        "(NOT semantic_runtime_ready AND semantic_model_name IS NULL "
        "AND semantic_config_sha256 IS NULL "
        "AND semantic_prompt_schema_version IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_survey_config",
        "simulation_worker_heartbeats",
        "(survey_runtime_ready AND worker_domain = 'evaluation' "
        "AND length(btrim(survey_model_name)) BETWEEN 1 AND 200 "
        "AND survey_model_name !~ E'[\\r\\n]' "
        "AND survey_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND survey_prompt_schema_version = 'matraix-survey-scenario-preference/v1') OR "
        "(NOT survey_runtime_ready AND survey_model_name IS NULL "
        "AND survey_config_sha256 IS NULL "
        "AND survey_prompt_schema_version IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND worker_domain = 'evaluation' "
        "AND length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND chat_prompt_schema_version = 'matraix-chat-acme-support/v1' "
        "AND chat_sut_task_id = 'sendowl/matraix-acme-rest-mcp-suite' "
        "AND chat_sut_task_version = '1.0.0' "
        "AND chat_sut_spec_sha256 = "
        "'0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_web_config",
        "simulation_worker_heartbeats",
        "(web_runtime_ready AND worker_domain = 'evaluation' "
        "AND length(btrim(web_model_name)) BETWEEN 1 AND 200 "
        "AND web_model_name !~ E'[\\r\\n]' "
        "AND web_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND web_prompt_schema_version='matraix-web-quotes-choice/v1' "
        "AND web_executor_schema_version='matraix-web-browser-executor/v1' "
        "AND web_executor_spec_sha256="
        "'36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7') OR "
        "(NOT web_runtime_ready AND web_model_name IS NULL "
        "AND web_config_sha256 IS NULL AND web_prompt_schema_version IS NULL "
        "AND web_executor_schema_version IS NULL AND web_executor_spec_sha256 IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_linux_config",
        "simulation_worker_heartbeats",
        "(linux_runtime_ready AND worker_domain = 'evaluation' "
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


def upgrade() -> None:
    op.add_column(
        "simulation_worker_heartbeats",
        sa.Column(
            "worker_domain",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'semantic'"),
        ),
    )
    op.alter_column("simulation_worker_heartbeats", "worker_domain", server_default=None)
    # Heartbeats are transient presence records; discard pre-domain combined rows before
    # enforcing capability ownership on the replacement projection.
    op.execute("TRUNCATE TABLE simulation_worker_heartbeats")
    _drop_runtime_constraints()
    op.create_check_constraint(
        "ck_simulation_worker_heartbeats_domain",
        "simulation_worker_heartbeats",
        "worker_domain IN ('semantic', 'evaluation', 'report')",
    )
    _create_runtime_constraints()
    op.create_index(
        "ix_simulation_worker_heartbeats_domain_last_seen",
        "simulation_worker_heartbeats",
        ["worker_domain", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_simulation_worker_heartbeats_domain_last_seen",
        table_name="simulation_worker_heartbeats",
    )
    _drop_runtime_constraints()
    op.drop_constraint(
        "ck_simulation_worker_heartbeats_domain",
        "simulation_worker_heartbeats",
        type_="check",
    )
    op.drop_column("simulation_worker_heartbeats", "worker_domain")
    op.create_check_constraint(
        "ck_simulation_worker_semantic_config",
        "simulation_worker_heartbeats",
        "(semantic_runtime_ready AND platform_runtime_ready AND "
        "length(btrim(semantic_model_name)) BETWEEN 1 AND 200 "
        "AND semantic_model_name !~ E'[\\r\\n]' "
        "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND semantic_prompt_schema_version = 'matraix-semantic-profile/v1') OR "
        "(NOT semantic_runtime_ready AND semantic_model_name IS NULL "
        "AND semantic_config_sha256 IS NULL "
        "AND semantic_prompt_schema_version IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_survey_config",
        "simulation_worker_heartbeats",
        "(survey_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready AND "
        "length(btrim(survey_model_name)) BETWEEN 1 AND 200 "
        "AND survey_model_name !~ E'[\\r\\n]' "
        "AND survey_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND survey_prompt_schema_version = 'matraix-survey-scenario-preference/v1') OR "
        "(NOT survey_runtime_ready AND survey_model_name IS NULL "
        "AND survey_config_sha256 IS NULL "
        "AND survey_prompt_schema_version IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_chat_config",
        "simulation_worker_heartbeats",
        "(chat_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready AND "
        "length(btrim(chat_model_name)) BETWEEN 1 AND 200 "
        "AND chat_model_name !~ E'[\\r\\n]' "
        "AND chat_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND chat_prompt_schema_version = 'matraix-chat-acme-support/v1' "
        "AND chat_sut_task_id = 'sendowl/matraix-acme-rest-mcp-suite' "
        "AND chat_sut_task_version = '1.0.0' "
        "AND chat_sut_spec_sha256 = "
        "'0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a') OR "
        "(NOT chat_runtime_ready AND chat_model_name IS NULL "
        "AND chat_config_sha256 IS NULL AND chat_prompt_schema_version IS NULL "
        "AND chat_sut_task_id IS NULL AND chat_sut_task_version IS NULL "
        "AND chat_sut_spec_sha256 IS NULL)",
    )
    op.create_check_constraint(
        "ck_simulation_worker_web_config",
        "simulation_worker_heartbeats",
        "(web_runtime_ready AND platform_runtime_ready AND semantic_runtime_ready "
        "AND length(btrim(web_model_name)) BETWEEN 1 AND 200 "
        "AND web_model_name !~ E'[\\r\\n]' "
        "AND web_config_sha256 ~ '^[a-f0-9]{64}$' "
        "AND web_prompt_schema_version='matraix-web-quotes-choice/v1' "
        "AND web_executor_schema_version='matraix-web-browser-executor/v1' "
        "AND web_executor_spec_sha256="
        "'36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7') OR "
        "(NOT web_runtime_ready AND web_model_name IS NULL "
        "AND web_config_sha256 IS NULL AND web_prompt_schema_version IS NULL "
        "AND web_executor_schema_version IS NULL AND web_executor_spec_sha256 IS NULL)",
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
