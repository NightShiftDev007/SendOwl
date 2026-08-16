"""Synchronous PostgreSQL queue operations with database-enforced transitions."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import ValidationError

from oasis_worker.chat_contracts import ChatRuntimeConfig
from oasis_worker.linux_contracts import LinuxRuntimeConfig
from oasis_worker.queue_contracts import (
    ClaimedRun,
    NormalizedFailure,
    NormalizedSuccess,
    QueuePost,
)
from oasis_worker.semantic_contracts import SemanticRuntimeConfig
from oasis_worker.survey_contracts import SurveyRuntimeConfig
from oasis_worker.web_contracts import WebRuntimeConfig

ENGINE = "camel-oasis"
ENGINE_VERSION = "0.2.5"
CAMEL_VERSION = "0.2.78"
MODE = "reddit_manual_smoke"


def connect(database_url: str) -> Connection[dict[str, object]]:
    """Open one explicit libpq connection without logging its DSN."""
    try:
        return psycopg.connect(database_url, row_factory=dict_row, autocommit=False)
    except psycopg.Error as error:
        raise RuntimeError(f"cannot connect to PostgreSQL: {type(error).__name__}") from error


def _worker_lock_key(worker_id: str) -> int:
    value = 1469598103934665603
    for byte in worker_id.encode():
        value ^= byte
        value = (value * 1099511628211) & ((1 << 64) - 1)
    return value - (1 << 64) if value >= (1 << 63) else value


def acquire_worker_lock(connection: Connection[dict[str, object]], worker_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired",
            (_worker_lock_key(worker_id),),
        )
        row = cursor.fetchone()
    if row is None or row["acquired"] is not True:
        raise RuntimeError(f"another daemon already owns worker_id {worker_id!r}")
    connection.commit()


def update_heartbeat(
    connection: Connection[dict[str, object]],
    worker_id: str,
    started_at: datetime,
    ready: bool,
    semantic_config: SemanticRuntimeConfig | None,
    survey_config: SurveyRuntimeConfig | None,
    chat_config: ChatRuntimeConfig | None,
    web_config: WebRuntimeConfig | None,
    linux_config: LinuxRuntimeConfig | None,
) -> None:
    now = datetime.now(UTC)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO simulation_worker_heartbeats (
                worker_id, engine, engine_version, camel_version, mode,
                platform_runtime_ready, semantic_runtime_ready, semantic_model_name,
                semantic_config_sha256, semantic_prompt_schema_version,
                survey_runtime_ready, survey_model_name, survey_config_sha256,
                survey_prompt_schema_version,
                chat_runtime_ready, chat_model_name, chat_config_sha256,
                chat_prompt_schema_version, chat_sut_task_id, chat_sut_task_version,
                chat_sut_spec_sha256,
                web_runtime_ready, web_model_name, web_config_sha256,
                web_prompt_schema_version, web_executor_schema_version,
                web_executor_spec_sha256,
                linux_runtime_ready, linux_model_name, linux_config_sha256,
                linux_prompt_schema_version, linux_runner_schema_version,
                linux_runner_spec_sha256,
                started_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (worker_id) DO UPDATE SET
                engine = EXCLUDED.engine,
                engine_version = EXCLUDED.engine_version,
                camel_version = EXCLUDED.camel_version,
                mode = EXCLUDED.mode,
                platform_runtime_ready = EXCLUDED.platform_runtime_ready,
                semantic_runtime_ready = EXCLUDED.semantic_runtime_ready,
                semantic_model_name = EXCLUDED.semantic_model_name,
                semantic_config_sha256 = EXCLUDED.semantic_config_sha256,
                semantic_prompt_schema_version = EXCLUDED.semantic_prompt_schema_version,
                survey_runtime_ready = EXCLUDED.survey_runtime_ready,
                survey_model_name = EXCLUDED.survey_model_name,
                survey_config_sha256 = EXCLUDED.survey_config_sha256,
                survey_prompt_schema_version = EXCLUDED.survey_prompt_schema_version,
                chat_runtime_ready = EXCLUDED.chat_runtime_ready,
                chat_model_name = EXCLUDED.chat_model_name,
                chat_config_sha256 = EXCLUDED.chat_config_sha256,
                chat_prompt_schema_version = EXCLUDED.chat_prompt_schema_version,
                chat_sut_task_id = EXCLUDED.chat_sut_task_id,
                chat_sut_task_version = EXCLUDED.chat_sut_task_version,
                chat_sut_spec_sha256 = EXCLUDED.chat_sut_spec_sha256,
                web_runtime_ready = EXCLUDED.web_runtime_ready,
                web_model_name = EXCLUDED.web_model_name,
                web_config_sha256 = EXCLUDED.web_config_sha256,
                web_prompt_schema_version = EXCLUDED.web_prompt_schema_version,
                web_executor_schema_version = EXCLUDED.web_executor_schema_version,
                web_executor_spec_sha256 = EXCLUDED.web_executor_spec_sha256,
                linux_runtime_ready = EXCLUDED.linux_runtime_ready,
                linux_model_name = EXCLUDED.linux_model_name,
                linux_config_sha256 = EXCLUDED.linux_config_sha256,
                linux_prompt_schema_version = EXCLUDED.linux_prompt_schema_version,
                linux_runner_schema_version = EXCLUDED.linux_runner_schema_version,
                linux_runner_spec_sha256 = EXCLUDED.linux_runner_spec_sha256,
                started_at = EXCLUDED.started_at,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                worker_id,
                ENGINE,
                ENGINE_VERSION,
                CAMEL_VERSION,
                MODE,
                ready,
                semantic_config is not None,
                semantic_config.model_name if semantic_config is not None else None,
                semantic_config.config_sha256 if semantic_config is not None else None,
                (semantic_config.prompt_schema_version if semantic_config is not None else None),
                survey_config is not None,
                survey_config.model_name if survey_config is not None else None,
                survey_config.config_sha256 if survey_config is not None else None,
                survey_config.prompt_schema_version if survey_config is not None else None,
                chat_config is not None,
                chat_config.model_name if chat_config is not None else None,
                chat_config.config_sha256 if chat_config is not None else None,
                chat_config.prompt_schema_version if chat_config is not None else None,
                chat_config.sut_task_id if chat_config is not None else None,
                chat_config.sut_task_version if chat_config is not None else None,
                chat_config.sut_spec_sha256 if chat_config is not None else None,
                web_config is not None,
                web_config.model_name if web_config is not None else None,
                web_config.config_sha256 if web_config is not None else None,
                web_config.prompt_schema_version if web_config is not None else None,
                web_config.executor_schema_version if web_config is not None else None,
                web_config.executor_spec_sha256 if web_config is not None else None,
                linux_config is not None,
                linux_config.model_name if linux_config is not None else None,
                linux_config.config_sha256 if linux_config is not None else None,
                linux_config.prompt_schema_version if linux_config is not None else None,
                linux_config.runner_schema_version if linux_config is not None else None,
                linux_config.runner_spec_sha256 if linux_config is not None else None,
                started_at,
                now,
            ),
        )
    connection.commit()


def remove_heartbeat(
    connection: Connection[dict[str, object]],
    worker_id: str,
    started_at: datetime,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM simulation_worker_heartbeats
            WHERE worker_id = %s AND started_at = %s
            """,
            (worker_id, started_at),
        )
    connection.commit()


def fail_orphaned_runs(
    connection: Connection[dict[str, object]],
    stale_after_seconds: int,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE simulation_runs AS run
            SET status = 'failed',
                completed_at = now(),
                error_code = 'worker_heartbeat_lost',
                error_message = 'The OASIS worker stopped before completing this run.'
            WHERE run.status = 'running'
              AND NOT EXISTS (
                  SELECT 1
                  FROM simulation_worker_heartbeats AS heartbeat
                  WHERE heartbeat.worker_id = run.claimed_by_worker_id
                    AND heartbeat.last_seen_at >= %s
              )
            """,
            (cutoff,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated


def fail_runs_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    """Terminalize jobs left running by an earlier process with this locked identity."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE simulation_runs
            SET status = 'failed',
                completed_at = now(),
                error_code = 'worker_process_restarted',
                error_message = 'The owning OASIS worker restarted before completing this run.'
            WHERE status = 'running' AND claimed_by_worker_id = %s
            """,
            (worker_id,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated


def claim_next_run(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> ClaimedRun | None:
    head = platform_smoke_queue_head(connection)
    if head is None:
        connection.commit()
        return None
    return claim_platform_smoke_run(connection, worker_id, head[0])


def platform_smoke_queue_head(
    connection: Connection[dict[str, object]],
) -> tuple[UUID, datetime] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at
            FROM simulation_runs
            WHERE status = 'queued' AND input_sealed_at IS NOT NULL
            ORDER BY created_at, id
            LIMIT 1
            """
        )
        row = cursor.fetchone()
    if row is None:
        return None
    run_id = row["id"]
    if not isinstance(run_id, UUID):
        raise RuntimeError("queued simulation run id is not a PostgreSQL UUID")
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("queued simulation run created_at is not a PostgreSQL timestamp")
    return run_id, created_at


def claim_platform_smoke_run(
    connection: Connection[dict[str, object]],
    worker_id: str,
    selected_run_id: UUID,
) -> ClaimedRun | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, mode, scenario_id, scenario_sha256, variant_id, variant_name,
                   world_snapshot_id, snapshot_sha256, seed,
                   actor_user_name, actor_name, actor_bio, input_sha256
            FROM simulation_runs
            WHERE id = %s AND status = 'queued' AND input_sealed_at IS NOT NULL
            FOR UPDATE SKIP LOCKED
            """,
            (selected_run_id,),
        )
        selected = cursor.fetchone()
        if selected is None:
            connection.commit()
            return None
        run_id = selected["id"]
        cursor.execute(
            """
            SELECT position, content, offset_minutes
            FROM simulation_run_posts
            WHERE run_id = %s
            ORDER BY position
            """,
            (run_id,),
        )
        posts = tuple(cursor.fetchall())
        try:
            run = ClaimedRun.model_validate(
                {
                    **selected,
                    "status": "running",
                    "posts": tuple(QueuePost.model_validate(post) for post in posts),
                }
            )
            _validate_claim_integrity(run)
        except (ValidationError, RuntimeError) as error:
            cursor.execute(
                """
                UPDATE simulation_runs
                SET status = 'running', started_at = now(), claimed_by_worker_id = %s
                WHERE id = %s AND status = 'queued'
                """,
                (worker_id, run_id),
            )
            cursor.execute(
                """
                UPDATE simulation_runs
                SET status = 'failed', completed_at = now(),
                    error_code = 'queue_input_integrity_error', error_message = %s
                WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
                """,
                (
                    f"The queued input failed integrity validation with {type(error).__name__}.",
                    run_id,
                    worker_id,
                ),
            )
            connection.commit()
            return None
        cursor.execute(
            """
            UPDATE simulation_runs
            SET status = 'running', started_at = now(), claimed_by_worker_id = %s
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, run_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(f"queued simulation run {run_id} could not be claimed")
    connection.commit()
    return run


def complete_run(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    result: NormalizedSuccess,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE simulation_runs
            SET status = 'succeeded', completed_at = now(),
                engine_version = %s, camel_version = %s,
                artifact_sha256 = %s, artifact_size_bytes = %s,
                user_count = %s, post_count = %s, trace_count = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (
                result.engine_version,
                result.camel_version,
                result.artifact_sha256,
                result.artifact_size_bytes,
                result.user_count,
                result.post_count,
                result.trace_count,
                run_id,
                worker_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"simulation run {run_id} is no longer running")
    connection.commit()


def fail_run(
    connection: Connection[dict[str, object]],
    run_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE simulation_runs
            SET status = 'failed', completed_at = now(),
                error_code = %s, error_message = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (failure.code, failure.message, run_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"simulation run {run_id} is no longer running")
    connection.commit()


def artifact_directory(artifact_root: Path, run_id: UUID) -> Path:
    return artifact_root / str(run_id)


def _actor_digest(scenario_id: UUID, variant_id: UUID) -> str:
    return hashlib.sha256(f"{scenario_id}\0{variant_id}".encode()).hexdigest()[:16]


def _derive_actor_user_name(scenario_id: UUID, variant_id: UUID) -> str:
    return f"scenario_{_actor_digest(scenario_id, variant_id)}"


def _derive_actor_name(scenario_id: UUID, variant_id: UUID) -> str:
    return f"Scenario actor {_actor_digest(scenario_id, variant_id)}"


def _derive_actor_bio(scenario_id: UUID, variant_id: UUID) -> str:
    return (
        f"Synthetic actor compiled from Scenario {scenario_id} variant {variant_id}. "
        "Manual OASIS platform smoke only."
    )


def _canonical_input_json(run: ClaimedRun) -> str:
    payload = {
        "schema_version": "oasis-platform-smoke/v2",
        "mode": run.mode,
        "scenario": {
            "id": str(run.scenario_id),
            "scenario_sha256": run.scenario_sha256,
            "variant_id": str(run.variant_id),
            "variant_name": run.variant_name,
            "world_snapshot_id": str(run.world_snapshot_id),
            "snapshot_sha256": run.snapshot_sha256,
        },
        "seed": run.seed,
        "actor": {
            "agent_id": 0,
            "user_name": run.actor_user_name,
            "name": run.actor_name,
            "bio": run.actor_bio,
        },
        "posts": [
            {
                "position": post.position,
                "content": post.content,
                "offset_minutes": post.offset_minutes,
            }
            for post in run.posts
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_claim_integrity(run: ClaimedRun) -> None:
    expected_user_name = _derive_actor_user_name(run.scenario_id, run.variant_id)
    expected_actor_name = _derive_actor_name(run.scenario_id, run.variant_id)
    expected_actor_bio = _derive_actor_bio(run.scenario_id, run.variant_id)
    if run.actor_user_name != expected_user_name:
        raise RuntimeError(f"simulation run {run.id} has an invalid derived actor user_name")
    if run.actor_name != expected_actor_name or run.actor_bio != expected_actor_bio:
        raise RuntimeError(f"simulation run {run.id} has invalid frozen actor metadata")
    actual_digest = hashlib.sha256(_canonical_input_json(run).encode()).hexdigest()
    if actual_digest != run.input_sha256:
        raise RuntimeError(f"simulation run {run.id} content does not match input_sha256")
