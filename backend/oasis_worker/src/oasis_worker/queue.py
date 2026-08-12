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

from oasis_worker.queue_contracts import (
    ClaimedRun,
    NormalizedFailure,
    NormalizedSuccess,
    QueuePost,
)

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
) -> None:
    now = datetime.now(UTC)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO simulation_worker_heartbeats (
                worker_id, engine, engine_version, camel_version, mode,
                platform_runtime_ready, started_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (worker_id) DO UPDATE SET
                engine = EXCLUDED.engine,
                engine_version = EXCLUDED.engine_version,
                camel_version = EXCLUDED.camel_version,
                mode = EXCLUDED.mode,
                platform_runtime_ready = EXCLUDED.platform_runtime_ready,
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
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, mode, scenario_id, scenario_sha256, variant_id, variant_name,
                   world_snapshot_id, snapshot_sha256, company_name, seed,
                   actor_user_name, actor_name, actor_bio, input_sha256
            FROM simulation_runs
            WHERE status = 'queued' AND input_sealed_at IS NOT NULL
            ORDER BY created_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
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


def _derive_actor_user_name(world_snapshot_id: UUID, company_name: str) -> str:
    material = f"{world_snapshot_id}\0{company_name}".encode()
    return f"company_{hashlib.sha256(material).hexdigest()[:16]}"


def _canonical_input_json(run: ClaimedRun) -> str:
    payload = {
        "schema_version": "oasis-platform-smoke/v1",
        "mode": run.mode,
        "scenario": {
            "id": str(run.scenario_id),
            "scenario_sha256": run.scenario_sha256,
            "variant_id": str(run.variant_id),
            "variant_name": run.variant_name,
            "world_snapshot_id": str(run.world_snapshot_id),
            "snapshot_sha256": run.snapshot_sha256,
            "company_name": run.company_name,
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
    expected_user_name = _derive_actor_user_name(run.world_snapshot_id, run.company_name)
    expected_actor_name = run.company_name[:200]
    expected_actor_bio = (
        f"Frozen company actor from WorldSnapshot {run.world_snapshot_id}. "
        "Manual OASIS platform smoke only."
    )
    if run.actor_user_name != expected_user_name:
        raise RuntimeError(f"simulation run {run.id} has an invalid derived actor user_name")
    if run.actor_name != expected_actor_name or run.actor_bio != expected_actor_bio:
        raise RuntimeError(f"simulation run {run.id} has invalid frozen actor metadata")
    actual_digest = hashlib.sha256(_canonical_input_json(run).encode()).hexdigest()
    if actual_digest != run.input_sha256:
        raise RuntimeError(f"simulation run {run.id} content does not match input_sha256")
