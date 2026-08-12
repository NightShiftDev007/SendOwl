"""Long-running PostgreSQL-backed OASIS platform-smoke worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import queue
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Annotated
from urllib.parse import urlsplit

from psycopg import Error as PsycopgError
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from oasis_worker.contracts import ActorSpec, JobResult, JobSpec, PostSpec
from oasis_worker.engine import run_job, verify_runtime_dependencies
from oasis_worker.errors import OasisWorkerError
from oasis_worker.queue import (
    acquire_worker_lock,
    artifact_directory,
    claim_next_run,
    complete_run,
    connect,
    fail_orphaned_runs,
    fail_run,
    fail_runs_owned_by_worker,
    remove_heartbeat,
    update_heartbeat,
)
from oasis_worker.queue_contracts import ClaimedRun, NormalizedFailure, NormalizedSuccess

POLL_INTERVAL_SECONDS = 1
HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_STALE_SECONDS = 30
HASH_CHUNK_SIZE_BYTES = 1024 * 1024
LOGGER = logging.getLogger("oasis_worker.daemon")


class DaemonSettings(BaseModel):
    """Validated non-secret daemon process configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    database_url: Annotated[str, StringConstraints(min_length=1, strict=True)]
    artifact_root: Path
    worker_id: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            strict=True,
        ),
    ]


def _required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None:
        raise OasisWorkerError(f"{name} is required for daemon mode")
    if not value:
        raise OasisWorkerError(f"{name} is present but empty")
    return value


def _normalize_database_url(value: str) -> str:
    normalized = value.replace("postgresql+asyncpg://", "postgresql://", 1)
    normalized = normalized.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"postgresql", "postgres"} or parsed.hostname is None:
        raise OasisWorkerError("DATABASE_URL must be a PostgreSQL URL with an explicit host")
    if parsed.path in {"", "/"}:
        raise OasisWorkerError("DATABASE_URL must include a database name")
    return normalized


def load_daemon_settings(environment: Mapping[str, str]) -> DaemonSettings:
    """Load exactly the required daemon settings without exposing the database URL."""
    artifact_root_text = _required_environment(environment, "OASIS_ARTIFACT_ROOT")
    artifact_root = Path(artifact_root_text)
    if not artifact_root.is_absolute():
        raise OasisWorkerError("OASIS_ARTIFACT_ROOT must be an absolute path")
    if "\x00" in artifact_root_text:
        raise OasisWorkerError("OASIS_ARTIFACT_ROOT must not contain a NUL byte")
    try:
        return DaemonSettings(
            database_url=_normalize_database_url(
                _required_environment(environment, "DATABASE_URL")
            ),
            artifact_root=artifact_root,
            worker_id=_required_environment(environment, "OASIS_WORKER_ID"),
        )
    except ValidationError as error:
        raise OasisWorkerError(f"invalid OASIS daemon configuration: {error}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(HASH_CHUNK_SIZE_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise OasisWorkerError(f"cannot independently hash artifact {path}: {error}") from error
    return digest.hexdigest()


def _job_spec(run: ClaimedRun, artifact_root: Path) -> JobSpec:
    output_directory = artifact_directory(artifact_root, run.id)
    return JobSpec(
        schema_version="oasis-manual-smoke/v1",
        run_id=str(run.id),
        seed=run.seed,
        output_directory=str(output_directory),
        actor=ActorSpec(
            agent_id=0,
            user_name=run.actor_user_name,
            name=run.actor_name,
            bio=run.actor_bio,
        ),
        posts=tuple(PostSpec(content=post.content) for post in run.posts),
    )


def normalize_job_result(
    run: ClaimedRun,
    artifact_root: Path,
    result: JobResult,
) -> NormalizedSuccess:
    """Bind a strict worker result to the claimed job and independently verify its artifact."""
    expected_path = artifact_directory(artifact_root, run.id) / f"{run.id}.sqlite3"
    actual_path = Path(result.artifact.database_path)
    if actual_path != expected_path:
        raise OasisWorkerError(
            f"worker artifact path mismatch for run {run.id}: "
            f"expected {expected_path}, observed {actual_path}"
        )
    if result.run_id != str(run.id) or result.seed != run.seed:
        raise OasisWorkerError(f"worker result identity does not match claimed run {run.id}")
    if not actual_path.is_file():
        raise OasisWorkerError(f"worker artifact is missing for run {run.id}: {actual_path}")
    actual_size = actual_path.stat().st_size
    actual_sha256 = _sha256_file(actual_path)
    if result.artifact.size_bytes != actual_size:
        raise OasisWorkerError(
            f"worker artifact size mismatch for run {run.id}: "
            f"reported {result.artifact.size_bytes}, observed {actual_size}"
        )
    if result.artifact.sha256 != actual_sha256:
        raise OasisWorkerError(
            f"worker artifact digest mismatch for run {run.id}: "
            f"reported {result.artifact.sha256}, observed {actual_sha256}"
        )
    user_count = 1
    post_count = len(result.observed.posts)
    trace_count = len(result.observed.traces)
    if post_count != len(run.posts):
        raise OasisWorkerError(
            f"worker post count mismatch for run {run.id}: "
            f"expected {len(run.posts)}, observed {post_count}"
        )
    return NormalizedSuccess(
        engine_version=result.engine_version,
        camel_version=result.camel_version,
        artifact_sha256=actual_sha256,
        artifact_size_bytes=actual_size,
        user_count=user_count,
        post_count=post_count,
        trace_count=trace_count,
    )


def _failure(error: BaseException) -> NormalizedFailure:
    code = type(error).__name__.lower()
    return NormalizedFailure(
        code=code,
        message=f"OASIS platform-smoke execution failed with {type(error).__name__}.",
    )


def _heartbeat_loop(
    settings: DaemonSettings,
    started_at: datetime,
    stop_event: threading.Event,
    failures: queue.SimpleQueue[BaseException],
) -> None:
    try:
        connection = connect(settings.database_url)
        try:
            while not stop_event.is_set():
                update_heartbeat(connection, settings.worker_id, started_at, True)
                stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)
        finally:
            connection.close()
    except Exception as error:
        failures.put(error)


def _raise_heartbeat_failure(failures: queue.SimpleQueue[BaseException]) -> None:
    try:
        error = failures.get_nowait()
    except queue.Empty:
        return
    raise OasisWorkerError(f"worker heartbeat failed: {type(error).__name__}: {error}") from error


def _run_claimed_job(settings: DaemonSettings, run: ClaimedRun) -> NormalizedSuccess:
    spec = _job_spec(run, settings.artifact_root)
    result = asyncio.run(run_job(spec))
    return normalize_job_result(run, settings.artifact_root, result)


def run_daemon(settings: DaemonSettings) -> None:
    """Poll PostgreSQL, execute real OASIS jobs, and persist normalized terminal facts."""
    verify_runtime_dependencies()
    try:
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OasisWorkerError(
            f"cannot create OASIS_ARTIFACT_ROOT {settings.artifact_root}: {error}"
        ) from error
    if not settings.artifact_root.is_dir():
        raise OasisWorkerError(f"OASIS_ARTIFACT_ROOT is not a directory: {settings.artifact_root}")

    started_at = datetime.now(UTC)
    control = connect(settings.database_url)
    heartbeat_stop = threading.Event()
    heartbeat_failures: queue.SimpleQueue[BaseException] = queue.SimpleQueue()
    heartbeat_thread: threading.Thread | None = None
    owns_heartbeat = False
    try:
        acquire_worker_lock(control, settings.worker_id)
        fail_runs_owned_by_worker(control, settings.worker_id)
        fail_orphaned_runs(control, HEARTBEAT_STALE_SECONDS)
        update_heartbeat(control, settings.worker_id, started_at, True)
        owns_heartbeat = True
        heartbeat_thread = threading.Thread(
            target=_heartbeat_loop,
            args=(settings, started_at, heartbeat_stop, heartbeat_failures),
            name="oasis-worker-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        while True:
            _raise_heartbeat_failure(heartbeat_failures)
            fail_orphaned_runs(control, HEARTBEAT_STALE_SECONDS)
            run = claim_next_run(control, settings.worker_id)
            if run is None:
                sleep(POLL_INTERVAL_SECONDS)
                continue
            try:
                result = _run_claimed_job(settings, run)
            except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                LOGGER.exception(
                    "OASIS platform-smoke run failed",
                    extra={"run_id": str(run.id), "worker_id": settings.worker_id},
                )
                fail_run(control, run.id, settings.worker_id, _failure(error))
                continue
            try:
                _raise_heartbeat_failure(heartbeat_failures)
            except OasisWorkerError as error:
                fail_run(control, run.id, settings.worker_id, _failure(error))
                raise
            complete_run(control, run.id, settings.worker_id, result)
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 1)
        if owns_heartbeat:
            try:
                remove_heartbeat(control, settings.worker_id, started_at)
            except (PsycopgError, RuntimeError) as error:
                LOGGER.warning(
                    "cannot remove OASIS worker heartbeat",
                    extra={"worker_id": settings.worker_id, "error_type": type(error).__name__},
                )
        control.close()
