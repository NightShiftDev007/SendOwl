"""Long-running PostgreSQL-backed OASIS platform-smoke worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import queue
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import Connection
from psycopg import Error as PsycopgError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from oasis_worker.contracts import ActorSpec, JobResult, JobSpec, PostSpec
from oasis_worker.engine import run_job, verify_runtime_dependencies
from oasis_worker.errors import (
    ArtifactConflictError,
    ArtifactVerificationError,
    OasisExecutionError,
    OasisWorkerError,
)
from oasis_worker.queue import (
    acquire_worker_lock,
    artifact_directory,
    claim_platform_smoke_run,
    complete_run,
    connect,
    fail_orphaned_runs,
    fail_run,
    fail_runs_owned_by_worker,
    platform_smoke_queue_head,
    remove_heartbeat,
    update_heartbeat,
)
from oasis_worker.queue_contracts import ClaimedRun, NormalizedFailure, NormalizedSuccess
from oasis_worker.report_qa_contracts import ClaimedReportQuestion
from oasis_worker.report_qa_queue import (
    claim_report_question,
    complete_report_question,
    fail_orphaned_report_questions,
    fail_report_question,
    fail_report_questions_owned_by_worker,
    report_question_queue_head,
)
from oasis_worker.semantic_contracts import (
    PROMPT_SCHEMA_VERSION,
    ClaimedSemanticTrial,
    SemanticEvent,
    SemanticRuntimeConfig,
    SemanticSuccess,
)
from oasis_worker.semantic_hashing import semantic_config_sha256
from oasis_worker.semantic_queue import (
    append_round_events,
    claim_semantic_trial,
    complete_semantic_trial,
    fail_orphaned_semantic_trials,
    fail_semantic_trial,
    fail_semantic_trials_owned_by_worker,
    semantic_queue_head,
)
from oasis_worker.survey_contracts import (
    SURVEY_PROMPT_SCHEMA_VERSION,
    ClaimedSurveyTrial,
    SurveyRuntimeConfig,
)
from oasis_worker.survey_hashing import survey_config_sha256
from oasis_worker.survey_queue import (
    claim_survey_trial,
    complete_survey_trial,
    fail_orphaned_survey_trials,
    fail_survey_trial,
    fail_survey_trials_owned_by_worker,
    survey_queue_head,
)
from oasis_worker.world_graph_contracts import ClaimedWorldGraph
from oasis_worker.world_graph_queue import (
    claim_world_graph,
    complete_world_graph,
    fail_orphaned_world_graphs,
    fail_world_graph,
    fail_world_graphs_owned_by_worker,
    world_graph_queue_head,
)

if TYPE_CHECKING:
    from camel.models import BaseModelBackend

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
    semantic_config: SemanticRuntimeConfig | None = Field(repr=False)
    survey_config: SurveyRuntimeConfig | None = Field(repr=False)


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


def _semantic_config(environment: Mapping[str, str]) -> SemanticRuntimeConfig | None:
    names = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_NAME")
    configured = tuple(name for name in names if environment.get(name))
    if not configured:
        return None
    invalid = tuple(name for name in names if not environment.get(name))
    if invalid:
        raise OasisWorkerError(
            "semantic LLM configuration requires non-empty values for: " + ", ".join(invalid)
        )
    api_key = environment["LLM_API_KEY"]
    base_url = environment["LLM_BASE_URL"]
    model_name = environment["LLM_MODEL_NAME"]
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise OasisWorkerError("LLM_BASE_URL must be an HTTP(S) URL with an explicit host")
    if parsed.username is not None or parsed.password is not None:
        raise OasisWorkerError("LLM_BASE_URL must not contain credentials")
    try:
        return SemanticRuntimeConfig(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            config_sha256=semantic_config_sha256(base_url, model_name),
            prompt_schema_version=PROMPT_SCHEMA_VERSION,
        )
    except ValidationError as error:
        raise OasisWorkerError("invalid semantic LLM configuration") from error


def _survey_config(
    semantic_config: SemanticRuntimeConfig | None,
) -> SurveyRuntimeConfig | None:
    if semantic_config is None:
        return None
    return SurveyRuntimeConfig(
        api_key=semantic_config.api_key,
        base_url=semantic_config.base_url,
        model_name=semantic_config.model_name,
        config_sha256=survey_config_sha256(
            semantic_config.base_url,
            semantic_config.model_name,
        ),
        prompt_schema_version=SURVEY_PROMPT_SCHEMA_VERSION,
    )


def load_daemon_settings(environment: Mapping[str, str]) -> DaemonSettings:
    """Load exactly the required daemon settings without exposing the database URL."""
    artifact_root_text = _required_environment(environment, "OASIS_ARTIFACT_ROOT")
    artifact_root = Path(artifact_root_text)
    if not artifact_root.is_absolute():
        raise OasisWorkerError("OASIS_ARTIFACT_ROOT must be an absolute path")
    if "\x00" in artifact_root_text:
        raise OasisWorkerError("OASIS_ARTIFACT_ROOT must not contain a NUL byte")
    try:
        semantic_config = _semantic_config(environment)
        return DaemonSettings(
            database_url=_normalize_database_url(
                _required_environment(environment, "DATABASE_URL")
            ),
            artifact_root=artifact_root,
            worker_id=_required_environment(environment, "OASIS_WORKER_ID"),
            semantic_config=semantic_config,
            survey_config=_survey_config(semantic_config),
        )
    except ValidationError as error:
        raise OasisWorkerError("invalid OASIS daemon configuration") from error


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
        schema_version="oasis-manual-smoke/v2",
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
                update_heartbeat(
                    connection,
                    settings.worker_id,
                    started_at,
                    True,
                    settings.semantic_config,
                    settings.survey_config,
                )
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


def _bounded_safe_message(message: str, forbidden_values: Sequence[str]) -> str:
    sanitized = " ".join(message.split())
    for value in forbidden_values:
        if value:
            sanitized = sanitized.replace(value, "[redacted]")
    return sanitized[:500]


def _exception_type_names(error: BaseException) -> set[str]:
    names: set[str] = set()
    current: BaseException | None = error
    while current is not None and type(current).__name__ not in names:
        names.add(type(current).__name__)
        current = current.__cause__
    return names


def _semantic_failure(
    error: BaseException,
    runtime_config: SemanticRuntimeConfig | SurveyRuntimeConfig,
) -> NormalizedFailure:
    is_survey = isinstance(runtime_config, SurveyRuntimeConfig)
    type_names = _exception_type_names(error)
    if type_names & {"AuthenticationError", "PermissionDeniedError"}:
        code = "provider_auth"
    elif type_names & {"BadRequestError", "UnprocessableEntityError"}:
        code = "provider_bad_request"
    elif type_names & {"APITimeoutError", "TimeoutError"}:
        code = "provider_timeout"
    elif type_names & {"APIConnectionError", "RateLimitError", "InternalServerError"}:
        code = "provider_unavailable"
    elif isinstance(error, (ArtifactConflictError, ArtifactVerificationError, OSError)):
        code = "artifact"
    elif isinstance(error, OasisExecutionError) and any(
        marker in str(error).casefold()
        for marker in ("tool", "trace", "audience agent", "intervention", "survey provider")
    ):
        code = "tool_contract"
    else:
        code = "survey_execution" if is_survey else "semantic_execution"
    if isinstance(error, (OasisExecutionError, ArtifactConflictError, ArtifactVerificationError)):
        message = _bounded_safe_message(
            f"{'Survey' if is_survey else 'Semantic'} trial failed: {error}",
            (runtime_config.api_key, runtime_config.base_url),
        )
    else:
        label = "Survey" if is_survey else "Semantic"
        message = f"{label} trial failed with {type(error).__name__}."
    return NormalizedFailure(code=code, message=message)


def _claim_next_job(
    settings: DaemonSettings,
    connection: Connection[dict[str, object]],
) -> (
    ClaimedRun
    | ClaimedSemanticTrial
    | ClaimedWorldGraph
    | ClaimedReportQuestion
    | ClaimedSurveyTrial
    | None
):
    smoke_head = platform_smoke_queue_head(connection)
    semantic_head = (
        semantic_queue_head(connection, settings.semantic_config)
        if settings.semantic_config is not None
        else None
    )
    graph_head = (
        world_graph_queue_head(connection, settings.semantic_config)
        if settings.semantic_config is not None
        else None
    )
    report_question_head = (
        report_question_queue_head(connection, settings.semantic_config)
        if settings.semantic_config is not None
        else None
    )
    survey_head = (
        survey_queue_head(connection, settings.survey_config)
        if settings.survey_config is not None
        else None
    )
    candidates: list[tuple[datetime, str, UUID]] = []
    if smoke_head is not None:
        candidates.append((smoke_head[1], "smoke", smoke_head[0]))
    if semantic_head is not None:
        candidates.append((semantic_head[1], "semantic", semantic_head[0]))
    if graph_head is not None:
        candidates.append((graph_head[1], "world_graph", graph_head[0]))
    if report_question_head is not None:
        candidates.append((report_question_head[1], "report_qa", report_question_head[0]))
    if survey_head is not None:
        candidates.append((survey_head[1], "survey", survey_head[0]))
    if not candidates:
        connection.commit()
        return None
    _created_at, kind, job_id = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    if kind == "smoke":
        return claim_platform_smoke_run(connection, settings.worker_id, job_id)
    if settings.semantic_config is None:
        raise RuntimeError("semantic queue selected without a ready runtime configuration")
    if kind == "world_graph":
        return claim_world_graph(
            connection,
            job_id,
            settings.worker_id,
            settings.semantic_config,
        )
    if kind == "report_qa":
        return claim_report_question(
            connection,
            job_id,
            settings.worker_id,
            settings.semantic_config,
        )
    if kind == "survey":
        if settings.survey_config is None:
            raise RuntimeError("survey queue selected without a ready runtime configuration")
        return claim_survey_trial(
            connection,
            job_id,
            settings.worker_id,
            settings.survey_config,
        )
    return claim_semantic_trial(
        connection,
        job_id,
        settings.worker_id,
        settings.semantic_config,
    )


def _run_claimed_semantic_trial(
    settings: DaemonSettings,
    control: Connection[dict[str, object]],
    trial: ClaimedSemanticTrial,
    model_backend: BaseModelBackend,
) -> SemanticSuccess:
    from oasis_worker.semantic_engine import run_semantic_trial

    def append_round(round_number: int, events: Sequence[SemanticEvent]) -> None:
        append_round_events(
            control,
            trial.id,
            settings.worker_id,
            round_number,
            events,
        )

    return asyncio.run(
        run_semantic_trial(
            trial,
            settings.artifact_root,
            model_backend,
            append_round,
        )
    )


def run_daemon(settings: DaemonSettings) -> None:
    """Poll PostgreSQL, execute real OASIS jobs, and persist normalized terminal facts."""
    from oasis_worker.report_qa_engine import answer_report_question
    from oasis_worker.semantic_engine import create_provider_model, probe_semantic_runtime
    from oasis_worker.survey_engine import (
        create_survey_model,
        probe_survey_runtime,
        run_survey_trial,
    )
    from oasis_worker.world_graph_engine import create_world_graph_model, extract_world_graph

    verify_runtime_dependencies()
    try:
        settings.artifact_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OasisWorkerError(
            f"cannot create OASIS_ARTIFACT_ROOT {settings.artifact_root}: {error}"
        ) from error
    if not settings.artifact_root.is_dir():
        raise OasisWorkerError(f"OASIS_ARTIFACT_ROOT is not a directory: {settings.artifact_root}")

    semantic_model: BaseModelBackend | None = None
    world_graph_model: BaseModelBackend | None = None
    survey_model: BaseModelBackend | None = None

    started_at = datetime.now(UTC)
    control = connect(settings.database_url)
    heartbeat_stop = threading.Event()
    heartbeat_failures: queue.SimpleQueue[BaseException] = queue.SimpleQueue()
    heartbeat_thread: threading.Thread | None = None
    owns_heartbeat = False
    preserve_unready_heartbeat = False
    try:
        acquire_worker_lock(control, settings.worker_id)
        fail_runs_owned_by_worker(control, settings.worker_id)
        fail_semantic_trials_owned_by_worker(control, settings.worker_id)
        fail_world_graphs_owned_by_worker(control, settings.worker_id)
        fail_report_questions_owned_by_worker(control, settings.worker_id)
        fail_survey_trials_owned_by_worker(control, settings.worker_id)
        fail_orphaned_runs(control, HEARTBEAT_STALE_SECONDS)
        fail_orphaned_semantic_trials(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_world_graphs(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_report_questions(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_survey_trials(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        update_heartbeat(
            control,
            settings.worker_id,
            started_at,
            True,
            None,
            None,
        )
        owns_heartbeat = True
        if settings.semantic_config is not None:
            try:
                semantic_model = create_provider_model(settings.semantic_config)
                asyncio.run(probe_semantic_runtime(semantic_model))
                world_graph_model = create_world_graph_model(settings.semantic_config)
                if settings.survey_config is None:
                    raise RuntimeError("semantic runtime is configured without survey runtime")
                survey_model = create_survey_model(settings.survey_config)
                asyncio.run(probe_survey_runtime(survey_model))
            except Exception as error:
                preserve_unready_heartbeat = True
                LOGGER.error(
                    "model runtime readiness probe failed",
                    extra={
                        "worker_id": settings.worker_id,
                        "error_type": type(error).__name__,
                    },
                )
                raise OasisWorkerError(
                    "model runtime readiness probe failed after bounded provider retries"
                ) from error
            update_heartbeat(
                control,
                settings.worker_id,
                started_at,
                True,
                settings.semantic_config,
                settings.survey_config,
            )
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
            fail_orphaned_semantic_trials(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_world_graphs(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_report_questions(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_survey_trials(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            job = _claim_next_job(settings, control)
            if job is None:
                sleep(POLL_INTERVAL_SECONDS)
                continue
            if isinstance(job, ClaimedSemanticTrial):
                if semantic_model is None or settings.semantic_config is None:
                    raise RuntimeError("semantic trial claimed without a provider model")
                try:
                    semantic_result = _run_claimed_semantic_trial(
                        settings, control, job, semantic_model
                    )
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.semantic_config)
                    LOGGER.error(
                        "OASIS semantic trial failed",
                        extra={
                            "trial_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_semantic_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        failure,
                    )
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_semantic_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.semantic_config),
                    )
                    raise
                complete_semantic_trial(control, job.id, settings.worker_id, semantic_result)
                continue
            if isinstance(job, ClaimedWorldGraph):
                if world_graph_model is None or settings.semantic_config is None:
                    raise RuntimeError("world graph claimed without a provider model")
                try:
                    graph_result = asyncio.run(extract_world_graph(job, world_graph_model))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.semantic_config)
                    LOGGER.error(
                        "semantic world graph extraction failed",
                        extra={
                            "graph_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_world_graph(control, job.id, settings.worker_id, failure)
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_world_graph(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.semantic_config),
                    )
                    raise
                complete_world_graph(control, job.id, settings.worker_id, graph_result)
                continue
            if isinstance(job, ClaimedReportQuestion):
                if semantic_model is None or settings.semantic_config is None:
                    raise RuntimeError("report question claimed without a provider model")
                try:
                    answer = asyncio.run(answer_report_question(job, semantic_model))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.semantic_config)
                    LOGGER.error(
                        "evidence-bound report answer failed",
                        extra={
                            "question_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_report_question(
                        control,
                        job.id,
                        settings.worker_id,
                        failure,
                        False,
                    )
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_report_question(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.semantic_config),
                        False,
                    )
                    raise
                complete_report_question(control, job.id, settings.worker_id, answer)
                continue
            if isinstance(job, ClaimedSurveyTrial):
                if survey_model is None or settings.survey_config is None:
                    raise RuntimeError("survey trial claimed without a provider model")
                try:
                    survey_result = asyncio.run(run_survey_trial(job, survey_model))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.survey_config)
                    LOGGER.error(
                        "MatrAIx survey trial failed",
                        extra={
                            "trial_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_survey_trial(control, job.id, settings.worker_id, failure)
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_survey_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.survey_config),
                    )
                    raise
                complete_survey_trial(control, job, settings.worker_id, survey_result)
                continue
            run = job
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
        if owns_heartbeat and not preserve_unready_heartbeat:
            try:
                remove_heartbeat(control, settings.worker_id, started_at)
            except (PsycopgError, RuntimeError) as error:
                LOGGER.warning(
                    "cannot remove OASIS worker heartbeat",
                    extra={"worker_id": settings.worker_id, "error_type": type(error).__name__},
                )
        control.close()
