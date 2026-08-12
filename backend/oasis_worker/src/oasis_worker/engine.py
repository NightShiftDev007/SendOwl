from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from oasis_worker.contracts import (
    ArtifactResult,
    CreatePostTrace,
    CreatePostTraceInfo,
    JobResult,
    JobSpec,
    ObservedPost,
    ObservedState,
    ObservedTrace,
    ObservedUser,
    SignupTrace,
    SignupTraceInfo,
)
from oasis_worker.errors import (
    ArtifactConflictError,
    ArtifactVerificationError,
    DependencyContractError,
    OasisExecutionError,
    OasisWorkerError,
)

EXPECTED_OASIS_VERSION = "0.2.5"
EXPECTED_CAMEL_VERSION = "0.2.78"
LIMITATIONS = (
    "This run verifies OASIS 0.2.5 Reddit platform wiring, SQLite persistence, "
    "and ordered manual CREATE_POST actions only.",
    "CAMEL StubModel is used: no LLM inference, audience behavior, social evolution, "
    "scenario comparison, or decision conclusion is produced.",
    "The seed is fixed and recorded, but OASIS writes runtime timestamps, so separate runs "
    "are not expected to produce byte-identical SQLite files.",
)


@contextmanager
def _working_directory(directory: Path) -> Iterator[None]:
    previous_directory = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


def _installed_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError as error:
        raise DependencyContractError(
            f"required distribution {distribution!r} is not installed"
        ) from error


def verify_runtime_dependencies() -> None:
    """Verify exact installed and importable OASIS/CAMEL runtime versions."""
    oasis_version = _installed_version("camel-oasis")
    camel_version = _installed_version("camel-ai")
    if oasis_version != EXPECTED_OASIS_VERSION:
        raise DependencyContractError(
            "camel-oasis version mismatch: "
            f"expected {EXPECTED_OASIS_VERSION}, installed {oasis_version}"
        )
    if camel_version != EXPECTED_CAMEL_VERSION:
        raise DependencyContractError(
            "camel-ai version mismatch: "
            f"expected {EXPECTED_CAMEL_VERSION}, installed {camel_version}"
        )
    try:
        import oasis
        from camel.models import StubModel
        from camel.types import ModelType
    except ImportError as error:
        raise DependencyContractError(
            f"cannot import pinned OASIS runtime dependencies: {error}"
        ) from error
    if oasis.__version__ != EXPECTED_OASIS_VERSION:
        raise DependencyContractError(
            "oasis module version mismatch: "
            f"expected {EXPECTED_OASIS_VERSION}, imported {oasis.__version__}"
        )
    del StubModel, ModelType


def _prepare_artifact_path(spec: JobSpec) -> Path:
    output_directory = Path(spec.output_directory)
    try:
        output_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise OasisExecutionError(
            f"cannot create output_directory {output_directory}: {error}"
        ) from error
    if not output_directory.is_dir():
        raise OasisExecutionError(f"output_directory is not a directory: {output_directory}")
    database_path = output_directory / f"{spec.run_id}.sqlite3"
    if database_path.exists():
        raise ArtifactConflictError(
            f"refusing to overwrite existing OASIS artifact: {database_path}"
        )
    return database_path


def _configure_oasis_logging() -> None:
    for logger_name in ("oasis.env", "social.agent", "social.rec", "social.twitter", "table"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


async def _execute_oasis(spec: JobSpec, database_path: Path) -> None:
    try:
        import oasis
        from camel.models import StubModel
        from camel.types import ModelType
        from oasis import (
            ActionType,
            AgentGraph,
            DefaultPlatformType,
            ManualAction,
            SocialAgent,
            UserInfo,
        )
    except ImportError as error:
        raise DependencyContractError(
            f"cannot import pinned OASIS runtime dependencies: {error}"
        ) from error

    _configure_oasis_logging()
    if oasis.__version__ != EXPECTED_OASIS_VERSION:
        raise DependencyContractError(
            "oasis module version mismatch: "
            f"expected {EXPECTED_OASIS_VERSION}, imported {oasis.__version__}"
        )

    graph = None
    environment = None
    primary_error: Exception | None = None
    try:
        graph = AgentGraph()
        user_info = UserInfo(
            user_name=spec.actor.user_name,
            name=spec.actor.name,
            description=spec.actor.bio,
            profile=None,
            recsys_type="reddit",
            is_controllable=True,
        )
        model = StubModel(model_type=ModelType.STUB)
        agent = SocialAgent(
            agent_id=spec.actor.agent_id,
            user_info=user_info,
            model=model,
            agent_graph=graph,
            available_actions=[ActionType.CREATE_POST],
        )
        graph.add_agent(agent)
        environment = oasis.make(
            agent_graph=graph,
            platform=DefaultPlatformType.REDDIT,
            database_path=str(database_path),
            semaphore=1,
        )
        await environment.reset()
        for post in spec.posts:
            await environment.step(
                {
                    agent: ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": post.content},
                    )
                }
            )
    except Exception as error:
        primary_error = error
        raise OasisExecutionError(
            "OASIS manual smoke execution failed for "
            f"run_id={spec.run_id}, database_path={database_path}: "
            f"{type(error).__name__}: {error}"
        ) from error
    finally:
        cleanup_error: Exception | None = None
        if environment is not None:
            try:
                await environment.close()
            except Exception as error:
                cleanup_error = error
        if graph is not None:
            try:
                graph.close()
            except Exception as error:
                if cleanup_error is None:
                    cleanup_error = error
        if primary_error is None and cleanup_error is not None:
            raise OasisExecutionError(
                "OASIS manual smoke cleanup failed for "
                f"run_id={spec.run_id}, database_path={database_path}: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            ) from cleanup_error


def _require_int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactVerificationError(
            f"expected integer at {location}, observed {type(value).__name__}"
        )
    return value


def _require_zero(value: object, location: str) -> Literal[0]:
    integer = _require_int(value, location)
    if integer != 0:
        raise ArtifactVerificationError(f"expected 0 at {location}, observed {integer}")
    return 0


def _require_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactVerificationError(
            f"expected non-empty text at {location}, observed {value!r}"
        )
    return value


def _require_none(value: object, location: str) -> None:
    if value is not None:
        raise ArtifactVerificationError(f"expected NULL at {location}, observed {value!r}")


def _parse_json_object(raw_value: object, location: str) -> dict[str, object]:
    raw_text = _require_text(raw_value, location)
    try:
        value: object = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ArtifactVerificationError(
            f"invalid JSON at {location}: {error.msg} at character {error.pos}"
        ) from error
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ArtifactVerificationError(f"expected a JSON object with string keys at {location}")
    return {str(key): item for key, item in value.items()}


def _verify_keys(payload: dict[str, object], expected_keys: set[str], location: str) -> None:
    observed_keys = set(payload)
    if observed_keys != expected_keys:
        raise ArtifactVerificationError(
            f"unexpected keys at {location}: expected {sorted(expected_keys)}, "
            f"observed {sorted(observed_keys)}"
        )


def _read_user(connection: sqlite3.Connection, spec: JobSpec) -> ObservedUser:
    rows = connection.execute(
        "SELECT user_id, agent_id, user_name, name, bio, created_at FROM user ORDER BY user_id"
    ).fetchall()
    if len(rows) != 1:
        raise ArtifactVerificationError(f"expected exactly 1 user row, observed {len(rows)}")
    row = rows[0]
    user = ObservedUser(
        user_id=_require_zero(row[0], "user.user_id"),
        agent_id=_require_zero(row[1], "user.agent_id"),
        user_name=_require_text(row[2], "user.user_name"),
        name=_require_text(row[3], "user.name"),
        bio=_require_text(row[4], "user.bio"),
        created_at=_require_text(row[5], "user.created_at"),
    )
    if (
        user.user_name != spec.actor.user_name
        or user.name != spec.actor.name
        or user.bio != spec.actor.bio
    ):
        raise ArtifactVerificationError(
            "persisted user does not match submitted actor: "
            f"expected ({spec.actor.user_name!r}, {spec.actor.name!r}, {spec.actor.bio!r}), "
            f"observed ({user.user_name!r}, {user.name!r}, {user.bio!r})"
        )
    return user


def _read_posts(connection: sqlite3.Connection, spec: JobSpec) -> tuple[ObservedPost, ...]:
    rows = connection.execute(
        "SELECT post_id, user_id, original_post_id, content, quote_content, created_at "
        "FROM post ORDER BY post_id"
    ).fetchall()
    if len(rows) != len(spec.posts):
        raise ArtifactVerificationError(
            f"expected {len(spec.posts)} post rows, observed {len(rows)}"
        )
    observed_posts: list[ObservedPost] = []
    for position, (row, expected_post) in enumerate(zip(rows, spec.posts, strict=True)):
        _require_none(row[2], f"post[{position}].original_post_id")
        _require_none(row[4], f"post[{position}].quote_content")
        observed_post = ObservedPost(
            post_id=_require_int(row[0], f"post[{position}].post_id"),
            user_id=_require_zero(row[1], f"post[{position}].user_id"),
            content=_require_text(row[3], f"post[{position}].content"),
            created_at=_require_text(row[5], f"post[{position}].created_at"),
        )
        expected_post_id = position + 1
        if observed_post.post_id != expected_post_id:
            raise ArtifactVerificationError(
                f"post IDs are not contiguous: expected {expected_post_id}, "
                f"observed {observed_post.post_id}"
            )
        if observed_post.content != expected_post.content:
            raise ArtifactVerificationError(
                f"persisted post[{position}] content does not match submitted content"
            )
        observed_posts.append(observed_post)
    return tuple(observed_posts)


def _read_traces(
    connection: sqlite3.Connection,
    spec: JobSpec,
) -> tuple[ObservedTrace, ...]:
    rows = connection.execute(
        "SELECT rowid, user_id, created_at, action, info FROM trace ORDER BY rowid"
    ).fetchall()
    expected_count = len(spec.posts) + 1
    if len(rows) != expected_count:
        raise ArtifactVerificationError(
            f"expected {expected_count} trace rows, observed {len(rows)}"
        )

    traces: list[ObservedTrace] = []
    signup_row = rows[0]
    signup_rowid = _require_int(signup_row[0], "trace[0].rowid")
    if signup_rowid != 1:
        raise ArtifactVerificationError(
            f"trace row IDs are not contiguous: expected 1, observed {signup_rowid}"
        )
    signup_action = _require_text(signup_row[3], "trace[0].action")
    if signup_action != "sign_up":
        raise ArtifactVerificationError(
            f"expected first trace action 'sign_up', observed {signup_action!r}"
        )
    signup_payload = _parse_json_object(signup_row[4], "trace[0].info")
    _verify_keys(signup_payload, {"name", "user_name", "bio"}, "trace[0].info")
    signup_info = SignupTraceInfo(
        name=_require_text(signup_payload["name"], "trace[0].info.name"),
        user_name=_require_text(signup_payload["user_name"], "trace[0].info.user_name"),
        bio=_require_text(signup_payload["bio"], "trace[0].info.bio"),
    )
    if (
        signup_info.name != spec.actor.name
        or signup_info.user_name != spec.actor.user_name
        or signup_info.bio != spec.actor.bio
    ):
        raise ArtifactVerificationError("sign_up trace does not match submitted actor")
    traces.append(
        SignupTrace(
            position=0,
            user_id=_require_zero(signup_row[1], "trace[0].user_id"),
            created_at=_require_text(signup_row[2], "trace[0].created_at"),
            action="sign_up",
            info=signup_info,
        )
    )

    for position, (row, expected_post) in enumerate(
        zip(rows[1:], spec.posts, strict=True), start=1
    ):
        rowid = _require_int(row[0], f"trace[{position}].rowid")
        expected_rowid = position + 1
        if rowid != expected_rowid:
            raise ArtifactVerificationError(
                f"trace row IDs are not contiguous: expected {expected_rowid}, observed {rowid}"
            )
        action = _require_text(row[3], f"trace[{position}].action")
        if action != "create_post":
            raise ArtifactVerificationError(
                f"expected trace[{position}] action 'create_post', observed {action!r}"
            )
        payload = _parse_json_object(row[4], f"trace[{position}].info")
        _verify_keys(payload, {"content", "post_id"}, f"trace[{position}].info")
        trace_info = CreatePostTraceInfo(
            content=_require_text(payload["content"], f"trace[{position}].info.content"),
            post_id=_require_int(payload["post_id"], f"trace[{position}].info.post_id"),
        )
        if trace_info.content != expected_post.content or trace_info.post_id != position:
            raise ArtifactVerificationError(
                f"create_post trace[{position}] does not match persisted post {position}"
            )
        traces.append(
            CreatePostTrace(
                position=position,
                user_id=_require_zero(row[1], f"trace[{position}].user_id"),
                created_at=_require_text(row[2], f"trace[{position}].created_at"),
                action="create_post",
                info=trace_info,
            )
        )
    return tuple(traces)


def _inspect_artifact(database_path: Path, spec: JobSpec) -> ObservedState:
    if not database_path.is_file():
        raise ArtifactVerificationError(
            f"OASIS did not create the expected SQLite artifact: {database_path}"
        )
    try:
        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        try:
            integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
            integrity = None if integrity_row is None else integrity_row[0]
            if integrity != "ok":
                raise ArtifactVerificationError(
                    f"SQLite integrity_check failed for {database_path}: {integrity!r}"
                )
            user = _read_user(connection, spec)
            posts = _read_posts(connection, spec)
            traces = _read_traces(connection, spec)
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ArtifactVerificationError(
            f"cannot inspect SQLite artifact {database_path}: {error}"
        ) from error
    return ObservedState(user=user, posts=posts, traces=traces)


def _sha256_file(path: Path, chunk_size: int) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as artifact:
            while chunk := artifact.read(chunk_size):
                digest.update(chunk)
    except OSError as error:
        raise ArtifactVerificationError(f"cannot hash SQLite artifact {path}: {error}") from error
    return digest.hexdigest()


async def run_job(spec: JobSpec) -> JobResult:
    """Run one key-free OASIS smoke job and verify its persisted SQLite state."""
    verify_runtime_dependencies()
    database_path = _prepare_artifact_path(spec)
    output_directory = database_path.parent
    try:
        with _working_directory(output_directory):
            await _execute_oasis(spec, database_path)
        observed = _inspect_artifact(database_path, spec)
        artifact = ArtifactResult(
            database_path=str(database_path),
            sha256=_sha256_file(database_path, 1024 * 1024),
            size_bytes=database_path.stat().st_size,
        )
    except OasisWorkerError:
        raise
    except OSError as error:
        raise OasisExecutionError(
            f"filesystem operation failed for run_id={spec.run_id}: {error}"
        ) from error

    return JobResult(
        schema_version=spec.schema_version,
        run_id=spec.run_id,
        seed=spec.seed,
        engine="camel-oasis",
        engine_version=EXPECTED_OASIS_VERSION,
        camel_version=EXPECTED_CAMEL_VERSION,
        mode="reddit_manual_smoke",
        artifact=artifact,
        observed=observed,
        limitations=LIMITATIONS,
    )
