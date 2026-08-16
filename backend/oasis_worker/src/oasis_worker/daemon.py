"""Long-running PostgreSQL-backed OASIS platform-smoke worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import queue
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit
from uuid import UUID

from psycopg import Connection
from psycopg import Error as PsycopgError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from oasis_worker.chat_contracts import (
    CHAT_MCP_TASK_ID,
    CHAT_PROMPT_SCHEMA_VERSION,
    CHAT_REST_TASK_ID,
    CHAT_SUITE_ID,
    CHAT_SUITE_SHA256,
    CHAT_SUITE_VERSION,
    ChatRuntimeConfig,
    ClaimedChatTrial,
)
from oasis_worker.chat_hashing import chat_config_sha256
from oasis_worker.chat_queue import (
    append_chat_message,
    chat_queue_head,
    claim_chat_trial,
    complete_chat_trial,
    fail_chat_trial,
    fail_chat_trials_owned_by_worker,
    fail_orphaned_chat_trials,
)
from oasis_worker.contracts import ActorSpec, JobResult, JobSpec, PostSpec
from oasis_worker.engine import run_job, verify_runtime_dependencies
from oasis_worker.errors import (
    ArtifactConflictError,
    ArtifactVerificationError,
    OasisExecutionError,
    OasisWorkerError,
)
from oasis_worker.linux_contracts import (
    LINUX_PROMPT_SCHEMA_VERSION,
    LINUX_RUNNER_SCHEMA_VERSION,
    LINUX_RUNNER_SPEC_SHA256,
    LinuxFrozenTrial,
    LinuxRuntimeConfig,
)
from oasis_worker.linux_hashing import linux_config_sha256
from oasis_worker.linux_queue import (
    claim_linux_trial,
    complete_linux_trial,
    fail_linux_trial,
    fail_linux_trials_owned_by_worker,
    fail_orphaned_linux_trials,
    linux_queue_head,
)
from oasis_worker.persona_interview_contracts import ClaimedPersonaInterview
from oasis_worker.persona_interview_queue import (
    claim_persona_interview,
    complete_persona_interview,
    fail_orphaned_persona_interviews,
    fail_persona_interview,
    fail_persona_interviews_owned_by_worker,
    persona_interview_queue_head,
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
from oasis_worker.web_contracts import (
    WEB_EXECUTOR_SCHEMA_VERSION,
    WEB_EXECUTOR_SPEC_SHA256,
    WEB_PROMPT_SCHEMA_VERSION,
    ClaimedWebTrial,
    WebRuntimeConfig,
)
from oasis_worker.web_hashing import web_config_sha256
from oasis_worker.web_queue import (
    claim_web_trial,
    complete_web_trial,
    fail_orphaned_web_trials,
    fail_web_trial,
    fail_web_trials_owned_by_worker,
    web_queue_head,
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
    chat_config: ChatRuntimeConfig | None = Field(repr=False)
    web_config: WebRuntimeConfig | None = Field(repr=False)
    linux_config: LinuxRuntimeConfig | None = Field(repr=False)


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


def _chat_config(
    environment: Mapping[str, str],
    semantic_config: SemanticRuntimeConfig | None,
) -> ChatRuntimeConfig | None:
    if semantic_config is None:
        return None
    rest_sut_base_url = environment.get("CHATBOT_SUT_BASE_URL")
    mcp_sut_url = environment.get("CHATBOT_MCP_SUT_URL")
    if rest_sut_base_url is None and mcp_sut_url is None:
        return None
    if not rest_sut_base_url or not mcp_sut_url:
        raise OasisWorkerError(
            "CHATBOT_SUT_BASE_URL and CHATBOT_MCP_SUT_URL must both be configured or both omitted"
        )
    for name, url in (
        ("CHATBOT_SUT_BASE_URL", rest_sut_base_url),
        ("CHATBOT_MCP_SUT_URL", mcp_sut_url),
    ):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise OasisWorkerError(f"{name} must be an HTTP(S) URL with an explicit host")
        if parsed.username is not None or parsed.password is not None:
            raise OasisWorkerError(f"{name} must not contain credentials")
    return ChatRuntimeConfig(
        api_key=semantic_config.api_key,
        provider_base_url=semantic_config.base_url,
        rest_sut_base_url=rest_sut_base_url,
        mcp_sut_url=mcp_sut_url,
        model_name=semantic_config.model_name,
        config_sha256=chat_config_sha256(
            semantic_config.base_url,
            semantic_config.model_name,
        ),
        prompt_schema_version=CHAT_PROMPT_SCHEMA_VERSION,
        sut_task_id=CHAT_SUITE_ID,
        sut_task_version=CHAT_SUITE_VERSION,
        sut_spec_sha256=CHAT_SUITE_SHA256,
    )


def _web_config(
    environment: Mapping[str, str],
    semantic_config: SemanticRuntimeConfig | None,
) -> WebRuntimeConfig | None:
    if semantic_config is None:
        return None
    browser_base_url = environment.get("MATRAIX_WEB_BROWSER_URL")
    if browser_base_url is None:
        return None
    if not browser_base_url:
        raise OasisWorkerError("MATRAIX_WEB_BROWSER_URL is present but empty")
    parsed = urlsplit(browser_base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise OasisWorkerError(
            "MATRAIX_WEB_BROWSER_URL must be an HTTP(S) URL with an explicit host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise OasisWorkerError("MATRAIX_WEB_BROWSER_URL must not contain credentials")
    return WebRuntimeConfig(
        api_key=semantic_config.api_key,
        provider_base_url=semantic_config.base_url,
        browser_base_url=browser_base_url,
        model_name=semantic_config.model_name,
        config_sha256=web_config_sha256(
            semantic_config.base_url,
            semantic_config.model_name,
        ),
        prompt_schema_version=WEB_PROMPT_SCHEMA_VERSION,
        executor_schema_version=WEB_EXECUTOR_SCHEMA_VERSION,
        executor_spec_sha256=WEB_EXECUTOR_SPEC_SHA256,
    )


def _linux_config(
    environment: Mapping[str, str],
    semantic_config: SemanticRuntimeConfig | None,
) -> LinuxRuntimeConfig | None:
    if semantic_config is None:
        return None
    runner_base_url = environment.get("MATRAIX_LINUX_RUNNER_URL")
    if runner_base_url is None:
        return None
    if not runner_base_url:
        raise OasisWorkerError("MATRAIX_LINUX_RUNNER_URL is present but empty")
    parsed = urlsplit(runner_base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise OasisWorkerError(
            "MATRAIX_LINUX_RUNNER_URL must be an HTTP(S) URL with an explicit host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise OasisWorkerError("MATRAIX_LINUX_RUNNER_URL must not contain credentials")
    return LinuxRuntimeConfig(
        api_key=semantic_config.api_key,
        provider_base_url=semantic_config.base_url,
        runner_base_url=runner_base_url,
        model_name=semantic_config.model_name,
        config_sha256=linux_config_sha256(
            semantic_config.base_url,
            semantic_config.model_name,
        ),
        prompt_schema_version=LINUX_PROMPT_SCHEMA_VERSION,
        runner_schema_version=LINUX_RUNNER_SCHEMA_VERSION,
        runner_spec_sha256=LINUX_RUNNER_SPEC_SHA256,
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
            chat_config=_chat_config(environment, semantic_config),
            web_config=_web_config(environment, semantic_config),
            linux_config=_linux_config(environment, semantic_config),
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
                    settings.chat_config,
                    settings.web_config,
                    settings.linux_config,
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
    runtime_config: (
        SemanticRuntimeConfig
        | SurveyRuntimeConfig
        | ChatRuntimeConfig
        | WebRuntimeConfig
        | LinuxRuntimeConfig
    ),
) -> NormalizedFailure:
    is_survey = isinstance(runtime_config, SurveyRuntimeConfig)
    is_chat = isinstance(runtime_config, ChatRuntimeConfig)
    is_web = isinstance(runtime_config, WebRuntimeConfig)
    is_linux = isinstance(runtime_config, LinuxRuntimeConfig)
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
        for marker in (
            "tool",
            "trace",
            "audience agent",
            "intervention",
            "survey provider",
            "chat provider",
            "web provider",
            "linux provider",
        )
    ):
        code = "tool_contract"
    else:
        if is_chat:
            code = "chat_execution"
        elif is_survey:
            code = "survey_execution"
        elif is_web:
            code = "web_execution"
        elif is_linux:
            code = "linux_execution"
        else:
            code = "semantic_execution"
    if isinstance(error, (OasisExecutionError, ArtifactConflictError, ArtifactVerificationError)):
        if is_chat:
            label = "Chat"
        elif is_survey:
            label = "Survey"
        elif is_web:
            label = "Web"
        elif is_linux:
            label = "Linux"
        else:
            label = "Semantic"
        if isinstance(runtime_config, ChatRuntimeConfig):
            forbidden_values = (
                runtime_config.api_key,
                runtime_config.provider_base_url,
                runtime_config.rest_sut_base_url,
                runtime_config.mcp_sut_url,
            )
        elif isinstance(runtime_config, WebRuntimeConfig):
            forbidden_values = (
                runtime_config.api_key,
                runtime_config.provider_base_url,
                runtime_config.browser_base_url,
            )
        elif isinstance(runtime_config, LinuxRuntimeConfig):
            forbidden_values = (
                runtime_config.api_key,
                runtime_config.provider_base_url,
                runtime_config.runner_base_url,
            )
        else:
            forbidden_values = (runtime_config.api_key, runtime_config.base_url)
        message = _bounded_safe_message(
            f"{label} trial failed: {error}",
            forbidden_values,
        )
    else:
        label = (
            "Chat"
            if is_chat
            else (
                "Survey"
                if is_survey
                else ("Web" if is_web else ("Linux" if is_linux else "Semantic"))
            )
        )
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
    | ClaimedPersonaInterview
    | ClaimedSurveyTrial
    | ClaimedChatTrial
    | ClaimedWebTrial
    | LinuxFrozenTrial
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
    persona_interview_head = (
        persona_interview_queue_head(connection, settings.semantic_config)
        if settings.semantic_config is not None
        else None
    )
    survey_head = (
        survey_queue_head(connection, settings.survey_config)
        if settings.survey_config is not None
        else None
    )
    chat_head = (
        chat_queue_head(connection, settings.chat_config)
        if settings.chat_config is not None
        else None
    )
    web_head = (
        web_queue_head(connection, settings.web_config) if settings.web_config is not None else None
    )
    linux_head = (
        linux_queue_head(connection, settings.linux_config)
        if settings.linux_config is not None
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
    if persona_interview_head is not None:
        candidates.append(
            (persona_interview_head[1], "persona_interview", persona_interview_head[0])
        )
    if survey_head is not None:
        candidates.append((survey_head[1], "survey", survey_head[0]))
    if chat_head is not None:
        candidates.append((chat_head[1], "chat", chat_head[0]))
    if web_head is not None:
        candidates.append((web_head[1], "web", web_head[0]))
    if linux_head is not None:
        candidates.append((linux_head[1], "linux", linux_head[0]))
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
    if kind == "persona_interview":
        return claim_persona_interview(
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
    if kind == "chat":
        if settings.chat_config is None:
            raise RuntimeError("chat queue selected without a ready runtime configuration")
        return claim_chat_trial(
            connection,
            job_id,
            settings.worker_id,
            settings.chat_config,
        )
    if kind == "web":
        if settings.web_config is None:
            raise RuntimeError("Web queue selected without a ready runtime configuration")
        return claim_web_trial(
            connection,
            job_id,
            settings.worker_id,
            settings.web_config,
        )
    if kind == "linux":
        if settings.linux_config is None:
            raise RuntimeError("Linux queue selected without a ready runtime configuration")
        return claim_linux_trial(
            connection,
            job_id,
            settings.worker_id,
            settings.linux_config,
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
    from oasis_worker.chat_engine import (
        AcmeSupportClient,
        AcmeSupportMcpClient,
        ChatSupportClient,
        create_chat_model,
        probe_chat_runtime,
        run_chat_trial,
    )
    from oasis_worker.linux_engine import (
        FixedLinuxRunnerClient,
        create_linux_model,
        probe_linux_runtime,
        run_linux_trial,
    )
    from oasis_worker.persona_interview_engine import answer_persona_interview
    from oasis_worker.report_qa_engine import answer_report_question
    from oasis_worker.semantic_engine import create_provider_model, probe_semantic_runtime
    from oasis_worker.survey_engine import (
        create_survey_model,
        probe_survey_runtime,
        run_survey_trial,
    )
    from oasis_worker.web_engine import (
        FixedWebBrowserClient,
        create_web_model,
        probe_web_runtime,
        run_web_trial,
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
    chat_model: BaseModelBackend | None = None
    chat_suts: dict[str, ChatSupportClient] = {}
    web_model: BaseModelBackend | None = None
    web_browser: FixedWebBrowserClient | None = None
    linux_model: BaseModelBackend | None = None
    linux_runner: FixedLinuxRunnerClient | None = None

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
        fail_persona_interviews_owned_by_worker(control, settings.worker_id)
        fail_survey_trials_owned_by_worker(control, settings.worker_id)
        fail_chat_trials_owned_by_worker(control, settings.worker_id)
        fail_web_trials_owned_by_worker(control, settings.worker_id)
        fail_linux_trials_owned_by_worker(control, settings.worker_id)
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
        fail_orphaned_persona_interviews(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_survey_trials(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_chat_trials(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_web_trials(
            control,
            datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
        )
        fail_orphaned_linux_trials(
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
            None,
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
                if settings.chat_config is not None:
                    chat_model = create_chat_model(settings.chat_config)
                    chat_suts = {
                        CHAT_REST_TASK_ID: AcmeSupportClient(
                            settings.chat_config.rest_sut_base_url
                        ),
                        CHAT_MCP_TASK_ID: AcmeSupportMcpClient(settings.chat_config.mcp_sut_url),
                    }
                    asyncio.run(probe_chat_runtime(chat_model, tuple(chat_suts.values())))
                if settings.web_config is not None:
                    web_model = create_web_model(settings.web_config)
                    web_browser = FixedWebBrowserClient(settings.web_config.browser_base_url)
                    asyncio.run(probe_web_runtime(web_model, web_browser))
                if settings.linux_config is not None:
                    linux_model = create_linux_model(settings.linux_config)
                    linux_runner = FixedLinuxRunnerClient(settings.linux_config.runner_base_url)
                    asyncio.run(probe_linux_runtime(linux_model, linux_runner))
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
                settings.chat_config,
                settings.web_config,
                settings.linux_config,
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
            fail_orphaned_persona_interviews(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_survey_trials(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_chat_trials(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_web_trials(
                control,
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS),
            )
            fail_orphaned_linux_trials(
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
            if isinstance(job, ClaimedPersonaInterview):
                if semantic_model is None or settings.semantic_config is None:
                    raise RuntimeError("Persona interview claimed without a provider model")
                try:
                    interview_answer = asyncio.run(answer_persona_interview(job, semantic_model))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.semantic_config)
                    LOGGER.error(
                        "report-grounded Persona interview failed",
                        extra={
                            "interview_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_persona_interview(
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
                    fail_persona_interview(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.semantic_config),
                        False,
                    )
                    raise
                complete_persona_interview(
                    control,
                    job.id,
                    settings.worker_id,
                    interview_answer,
                )
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
            if isinstance(job, ClaimedChatTrial):
                if chat_model is None or not chat_suts or settings.chat_config is None:
                    raise RuntimeError("chat trial claimed without a ready chat runtime")
                chat_sut = chat_suts.get(job.evaluation.task_id)
                if chat_sut is None:
                    raise RuntimeError("chat trial references an unsupported fixed task")

                append_message = partial(
                    append_chat_message,
                    control,
                    job.id,
                    settings.worker_id,
                )

                try:
                    chat_result = asyncio.run(
                        run_chat_trial(job, chat_model, chat_sut, append_message)
                    )
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.chat_config)
                    LOGGER.error(
                        "MatrAIx chatbot evaluation failed",
                        extra={
                            "trial_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_chat_trial(control, job.id, settings.worker_id, failure, False)
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_chat_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.chat_config),
                        False,
                    )
                    raise
                complete_chat_trial(control, job.id, settings.worker_id, chat_result)
                continue
            if isinstance(job, ClaimedWebTrial):
                if web_model is None or web_browser is None or settings.web_config is None:
                    raise RuntimeError("Web trial claimed without a ready Web runtime")
                try:
                    web_result = asyncio.run(run_web_trial(job, web_model, web_browser))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.web_config)
                    LOGGER.error(
                        "MatrAIx Web evaluation failed",
                        extra={
                            "trial_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_web_trial(control, job.id, settings.worker_id, failure, False)
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_web_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.web_config),
                        False,
                    )
                    raise
                complete_web_trial(control, job, settings.worker_id, web_result)
                continue
            if isinstance(job, LinuxFrozenTrial):
                if linux_model is None or linux_runner is None or settings.linux_config is None:
                    raise RuntimeError("Linux trial claimed without a ready Linux runtime")
                try:
                    linux_result = asyncio.run(run_linux_trial(job, linux_model, linux_runner))
                except (OasisWorkerError, ValidationError, OSError, RuntimeError) as error:
                    failure = _semantic_failure(error, settings.linux_config)
                    LOGGER.error(
                        "MatrAIx Linux artifact trial failed",
                        extra={
                            "trial_id": str(job.id),
                            "worker_id": settings.worker_id,
                            "error_code": failure.code,
                        },
                    )
                    fail_linux_trial(control, job.id, settings.worker_id, failure, False)
                    continue
                try:
                    _raise_heartbeat_failure(heartbeat_failures)
                except OasisWorkerError as error:
                    fail_linux_trial(
                        control,
                        job.id,
                        settings.worker_id,
                        _semantic_failure(error, settings.linux_config),
                        False,
                    )
                    raise
                complete_linux_trial(control, job, settings.worker_id, linux_result)
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
