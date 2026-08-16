"""Strict provider and isolated runner for the fixed Linux artifact task."""

from __future__ import annotations

import asyncio
import json
import logging
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from camel.messages import OpenAIMessage
from camel.models import BaseModelBackend, ModelFactory
from camel.types import ModelPlatformType
from openai.types.chat import ChatCompletion
from pydantic import ValidationError

from oasis_worker.errors import OasisExecutionError
from oasis_worker.linux_contracts import (
    LINUX_PROMPT_SCHEMA_VERSION,
    LINUX_RUNNER_SCHEMA_VERSION,
    LINUX_RUNNER_SPEC_SHA256,
    LINUX_RUNNER_VERSION,
    LINUX_TASK_ID,
    LINUX_TASK_VERSION,
    LINUX_TOOL_NAME,
    LinuxFileHashes,
    LinuxFrozenTrial,
    LinuxRunnerResponse,
    LinuxRuntimeConfig,
    LinuxSubmission,
    LinuxSuccess,
)
from oasis_worker.linux_hashing import result_sha256
from oasis_worker.semantic_contracts import LOW_INFORMATION_VALUES, MAX_PROFILE_ATTRIBUTES
from oasis_worker.semantic_engine import (
    MODEL_MAX_RETRIES,
    MODEL_TIMEOUT_SECONDS,
    SemanticOpenAIBackend,
)

LOGGER = logging.getLogger("oasis_worker.linux_engine")
REQUEST_TIMEOUT_SECONDS = 30
REQUEST_MAX_BYTES = 65_536
REQUEST_ATTEMPTS = 3


class FixedLinuxRunnerClient:
    """Connector for the isolated allowlisted artifact runner."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def _request(self, path: str, payload: bytes | None) -> object:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._base_url}{path}",
            data=payload,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise OasisExecutionError(
                        f"Linux artifact runner returned unexpected HTTP {response.status}"
                    )
                raw = response.read(REQUEST_MAX_BYTES + 1)
        except HTTPError as error:
            raise OasisExecutionError(
                f"Linux artifact runner rejected the request with HTTP {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise OasisExecutionError(
                f"Linux artifact runner request failed with {type(error).__name__}"
            ) from error
        if len(raw) > REQUEST_MAX_BYTES:
            raise OasisExecutionError("Linux artifact runner response exceeded the size limit")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OasisExecutionError(
                "Linux artifact runner returned invalid UTF-8 JSON"
            ) from error

    def _bounded_request(self, path: str, payload: bytes | None) -> object:
        last_error: OasisExecutionError | None = None
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            try:
                return self._request(path, payload)
            except OasisExecutionError as error:
                last_error = error
                if attempt < REQUEST_ATTEMPTS:
                    LOGGER.warning(
                        "Linux artifact runner request will retry",
                        extra={"attempt": attempt, "error_type": type(error).__name__},
                    )
                    sleep(attempt)
        if last_error is None:
            raise RuntimeError("Linux artifact runner retry loop produced no result")
        raise last_error

    async def probe(self) -> None:
        raw = await asyncio.to_thread(self._bounded_request, "/ready", None)
        expected = {
            "status": "ready",
            "task_id": LINUX_TASK_ID,
            "task_version": LINUX_TASK_VERSION,
            "task_schema_version": "matraix-linux-task/note-to-csv-v1",
            "runner_schema_version": LINUX_RUNNER_SCHEMA_VERSION,
            "runner_spec_sha256": LINUX_RUNNER_SPEC_SHA256,
            "execution_kind": "linux_artifact_runner",
            "computer_use": False,
        }
        if raw != expected:
            raise OasisExecutionError("Linux artifact runner readiness identity mismatch")

    async def run(
        self, trial: LinuxFrozenTrial, submission: LinuxSubmission
    ) -> LinuxRunnerResponse:
        payload = json.dumps(
            {
                "trial_id": str(trial.id),
                "task_id": LINUX_TASK_ID,
                "task_version": LINUX_TASK_VERSION,
                "rows": [
                    {"item": "oat milk", "quantity": 2, "priority": "urgent"},
                    {"item": "batteries", "quantity": 4, "priority": "normal"},
                    {"item": "trash bags", "quantity": 1, "priority": "low"},
                ],
                "reason": submission.reason,
                "feedback": {
                    "need_constraint_satisfaction": submission.need_constraint_satisfaction,
                    "personal_preference_satisfaction": submission.personal_preference_satisfaction,
                    "overall_experience_rating": submission.overall_experience_rating,
                    "reason": submission.feedback_reason,
                },
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        raw = await asyncio.to_thread(
            self._bounded_request,
            "/v1/note-to-csv-runs",
            payload,
        )
        try:
            return LinuxRunnerResponse.model_validate(raw)
        except ValidationError as error:
            issue = error.errors(include_url=False, include_input=False)[0]
            location = ".".join(str(part) for part in issue["loc"]) or "response"
            raise OasisExecutionError(
                f"Linux artifact runner response failed validation at {location}: {issue['type']}"
            ) from error


def create_linux_model(config: LinuxRuntimeConfig) -> BaseModelBackend:
    backend = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=config.model_name,
        model_config_dict={
            "max_tokens": 512,
            "tool_choice": "required",
            "extra_body": {"enable_thinking": False},
        },
        api_key=config.api_key,
        url=config.provider_base_url,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
    )
    wrapped = SemanticOpenAIBackend(backend)
    if wrapped.token_limit != 32_768:
        raise RuntimeError("Linux model context token limit does not match the runtime contract")
    return wrapped


def _tool_schema() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": LINUX_TOOL_NAME,
            "description": "Submit reasoning and typed synthetic feedback for the fixed CSV task.",
            "parameters": LinuxSubmission.model_json_schema(),
        },
    }


def _parse_submission(response: object) -> LinuxSubmission:
    if not isinstance(response, ChatCompletion) or len(response.choices) != 1:
        raise OasisExecutionError("Linux provider did not return one chat completion choice")
    calls = response.choices[0].message.tool_calls
    if calls is None or len(calls) != 1 or calls[0].function.name != LINUX_TOOL_NAME:
        raise OasisExecutionError("Linux provider must return exactly the expected tool call")
    try:
        return LinuxSubmission.model_validate_json(calls[0].function.arguments)
    except ValidationError as error:
        issue = error.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in issue["loc"]) or "submission"
        raise OasisExecutionError(
            f"Linux provider output failed strict validation at {location}: {issue['type']}"
        ) from error


def _profile_projection(trial: LinuxFrozenTrial) -> str:
    dimensions = sorted(trial.persona.profile.dimensions.items(), key=lambda item: item[0])
    included = tuple(
        item for item in dimensions if item[1].strip().casefold() not in LOW_INFORMATION_VALUES
    )[:MAX_PROFILE_ATTRIBUTES]
    return "\n".join(f"- {name}: {value}" for name, value in included)


async def run_linux_trial(
    trial: LinuxFrozenTrial,
    model: BaseModelBackend,
    runner: FixedLinuxRunnerClient,
) -> LinuxSuccess:
    messages: list[OpenAIMessage] = [
        {
            "role": "system",
            "content": (
                "You are one bounded synthetic Persona reviewing a fixed note-to-CSV task. "
                "Return exactly one submit_note_to_csv tool call. The file rows are fixed and "
                "will be written by an isolated deterministic runner. Do not claim shell, "
                "desktop, Harbor, benchmark reward, or human feedback."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Prompt schema: {LINUX_PROMPT_SCHEMA_VERSION}\n"
                f"Persona: {trial.persona.display_name}\n"
                f"Frozen profile:\n{_profile_projection(trial)}\n\n"
                "Task: Convert the frozen shopping note to a CSV with item,quantity,priority.\n"
                "Rows: oat milk|2|urgent; batteries|4|normal; trash bags|1|low.\n"
                "Explain the transformation and provide synthetic task feedback."
            ),
        },
    ]
    try:
        response = await model.arun(messages, tools=[_tool_schema()])
    except Exception as error:
        raise OasisExecutionError(
            f"Linux model request failed with {type(error).__name__} after bounded retries"
        ) from error
    submission = _parse_submission(response)
    artifact = await runner.run(trial, submission)
    files = LinuxFileHashes(
        cleaned_list_csv=artifact.file_sha256["cleaned_list.csv"],
        submission_json=artifact.file_sha256["submission.json"],
        user_feedback_json=artifact.file_sha256["user_feedback.json"],
        verifier_json=artifact.file_sha256["verifier.json"],
    )
    digest = result_sha256(
        trial.trial_sha256,
        artifact.artifact_sha256,
        files,
        submission.reason,
        submission.need_constraint_satisfaction,
        submission.personal_preference_satisfaction,
        submission.overall_experience_rating,
        submission.feedback_reason,
    )
    return LinuxSuccess(
        runner_version=LINUX_RUNNER_VERSION,
        model_name=trial.model_name,
        linux_config_sha256=trial.linux_config_sha256,
        prompt_schema_version=LINUX_PROMPT_SCHEMA_VERSION,
        runner_schema_version=LINUX_RUNNER_SCHEMA_VERSION,
        runner_spec_sha256=LINUX_RUNNER_SPEC_SHA256,
        artifact_sha256=artifact.artifact_sha256,
        file_sha256=files,
        result_sha256=digest,
        reason=submission.reason,
        need_constraint_satisfaction=submission.need_constraint_satisfaction,
        personal_preference_satisfaction=submission.personal_preference_satisfaction,
        overall_experience_rating=submission.overall_experience_rating,
        feedback_reason=submission.feedback_reason,
    )


async def probe_linux_runtime(
    model: BaseModelBackend,
    runner: FixedLinuxRunnerClient,
) -> None:
    await runner.probe()
    messages: list[OpenAIMessage] = [
        {"role": "system", "content": "Return exactly one submit_note_to_csv tool call."},
        {"role": "user", "content": "Readiness only. Provide complete typed feedback."},
    ]
    try:
        response = await model.arun(messages, tools=[_tool_schema()])
    except Exception as error:
        raise OasisExecutionError(
            f"Linux provider readiness probe failed with {type(error).__name__}"
        ) from error
    _parse_submission(response)
