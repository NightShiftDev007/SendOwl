from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from semantic_fixtures import build_trial

from oasis_worker.daemon import load_daemon_settings
from oasis_worker.semantic_contracts import SemanticEvent, SemanticSuccess
from oasis_worker.semantic_hashing import experiment_sha256, trial_sha256

if TYPE_CHECKING:
    from camel.models import BaseModelBackend


def _deterministic_model() -> BaseModelBackend:
    import time

    from camel.models import StubModel
    from camel.types import (
        ChatCompletion,
        ChatCompletionMessage,
        Choice,
        CompletionUsage,
        ModelType,
    )
    from openai import AsyncStream
    from openai.types.chat import ChatCompletionChunk
    from openai.types.chat.chat_completion_message_function_tool_call import (
        ChatCompletionMessageFunctionToolCall,
        Function,
    )
    from pydantic import BaseModel

    class DeterministicDoNothingModel(StubModel):
        """Local CAMEL backend that always performs one real OASIS tool call."""

        async def _arun(
            self,
            messages: list[dict[str, object]],
            response_format: type[BaseModel] | None = None,
            tools: list[dict[str, object]] | None = None,
        ) -> ChatCompletion | AsyncStream[ChatCompletionChunk]:
            del messages, response_format, tools
            return ChatCompletion(
                id="deterministic-semantic-model",
                model="stub",
                object="chat.completion",
                created=int(time.time()),
                choices=[
                    Choice(
                        finish_reason="tool_calls",
                        index=0,
                        message=ChatCompletionMessage(
                            content=None,
                            role="assistant",
                            tool_calls=[
                                ChatCompletionMessageFunctionToolCall(
                                    id="deterministic-do-nothing",
                                    type="function",
                                    function=Function(name="do_nothing", arguments="{}"),
                                )
                            ],
                        ),
                        logprobs=None,
                    )
                ],
                usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
            )

    return DeterministicDoNothingModel(model_type=ModelType.STUB)


def _run_local_trial(
    artifact_root: Path,
    persona_count: int,
    selected_position: int,
) -> tuple[SemanticSuccess, tuple[tuple[int, tuple[SemanticEvent, ...]], ...]]:
    from oasis_worker.semantic_engine import run_semantic_trial

    trial = build_trial(persona_count=persona_count, selected_position=selected_position)
    appended: list[tuple[int, tuple[SemanticEvent, ...]]] = []

    def append_round(round_number: int, events: Sequence[SemanticEvent]) -> None:
        appended.append((round_number, tuple(events)))

    result = asyncio.run(
        run_semantic_trial(
            trial,
            artifact_root,
            _deterministic_model(),
            append_round,
        )
    )
    return result, tuple(appended)


def test_provider_backend_separates_context_budget_from_output_budget() -> None:
    from oasis_worker.semantic_engine import create_provider_model

    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://unused:unused@localhost/unused",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "provider-contract-test",
            "LLM_API_KEY": "secret-key",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "provider-model",
        }
    )
    assert settings.semantic_config is not None

    backend = create_provider_model(settings.semantic_config)

    assert backend.token_limit == 32_768
    assert backend.model_config_dict == {
        "max_tokens": 512,
        "tool_choice": "required",
        "extra_body": {"enable_thinking": False},
    }


def test_semantic_runtime_probe_requires_one_real_tool_call() -> None:
    from camel.models import StubModel
    from camel.types import ModelType

    from oasis_worker.errors import OasisExecutionError
    from oasis_worker.semantic_engine import probe_semantic_runtime

    asyncio.run(probe_semantic_runtime(_deterministic_model()))

    with pytest.raises(OasisExecutionError, match="requires exactly one tool call"):
        asyncio.run(probe_semantic_runtime(StubModel(model_type=ModelType.STUB)))


def test_strict_social_agent_rejects_swallowed_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oasis import SocialAgent

    from oasis_worker.errors import OasisExecutionError
    from oasis_worker.semantic_engine import StrictSocialAgent

    async def return_none(_agent: SocialAgent) -> None:
        return None

    monkeypatch.setattr(SocialAgent, "perform_action_by_llm", return_none)
    agent = object.__new__(StrictSocialAgent)
    agent.social_agent_id = 7

    with pytest.raises(OasisExecutionError, match="did not return a ChatAgentResponse"):
        asyncio.run(agent.perform_action_by_llm())


@pytest.mark.integration
def test_real_oasis_semantic_trial_maps_one_persona_to_public_position_one(
    tmp_path: Path,
) -> None:
    result, appended = _run_local_trial(tmp_path, persona_count=1, selected_position=0)

    assert result.user_count == 2
    assert result.initial_post_count == 0
    assert result.do_nothing_count == 1
    assert result.observed_action_count == 1
    assert len(appended) == 1
    assert [(event.actor_kind, event.agent_position) for event in appended[0][1]] == [
        ("persona", 1)
    ]


@pytest.mark.integration
def test_real_oasis_semantic_trial_maps_scenario_and_multiple_personas(
    tmp_path: Path,
) -> None:
    result, appended = _run_local_trial(tmp_path, persona_count=2, selected_position=1)

    assert result.user_count == 3
    assert result.initial_post_count == 1
    assert result.do_nothing_count == 2
    assert result.observed_action_count == 3
    assert [(event.actor_kind, event.agent_position) for event in appended[0][1]] == [
        ("scenario", 0),
        ("persona", 1),
        ("persona", 2),
    ]


@pytest.mark.integration
def test_real_oasis_semantic_trial_uses_artifact_db_with_read_only_install_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oasis.social_platform import database

    install_tree = tmp_path / "read-only-install"
    install_tree.mkdir()
    install_tree.chmod(stat.S_IRUSR | stat.S_IXUSR)
    environment_before = dict(os.environ)
    original_get_db_path = database.get_db_path

    def read_only_default_path() -> str:
        configured = os.environ.get("OASIS_DB_PATH")
        if configured:
            return configured
        raise PermissionError("simulated read-only OASIS package data directory")

    monkeypatch.setattr(database, "get_db_path", read_only_default_path)
    monkeypatch.setattr(
        "oasis.social_agent.agent_environment.get_db_path",
        read_only_default_path,
    )
    monkeypatch.delenv("OASIS_DB_PATH", raising=False)
    try:
        result, _appended = _run_local_trial(
            tmp_path / "artifacts", persona_count=1, selected_position=0
        )
    finally:
        install_tree.chmod(stat.S_IRWXU)
        monkeypatch.setattr(database, "get_db_path", original_get_db_path)

    assert result.user_count == 2
    assert dict(os.environ) == environment_before


@pytest.mark.external_provider
def test_external_provider_semantic_smoke_when_explicitly_enabled(tmp_path: Path) -> None:
    from oasis_worker.semantic_engine import (
        create_provider_model,
        probe_semantic_runtime,
        run_semantic_trial,
    )

    if os.environ.get("OASIS_EXTERNAL_PROVIDER_SMOKE") != "1":
        pytest.skip("set OASIS_EXTERNAL_PROVIDER_SMOKE=1 to make one real provider call")
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://unused:unused@localhost/unused",
            "OASIS_ARTIFACT_ROOT": str(tmp_path),
            "OASIS_WORKER_ID": "external-provider-test",
            "LLM_API_KEY": os.environ["LLM_API_KEY"],
            "LLM_BASE_URL": os.environ["LLM_BASE_URL"],
            "LLM_MODEL_NAME": os.environ["LLM_MODEL_NAME"],
        }
    )
    assert settings.semantic_config is not None
    model_backend = create_provider_model(settings.semantic_config)
    asyncio.run(probe_semantic_runtime(model_backend))
    trial = build_trial(persona_count=1, selected_position=1)
    experiment = trial.experiment.model_copy(
        update={
            "model_name": settings.semantic_config.model_name,
            "semantic_config_sha256": settings.semantic_config.config_sha256,
            "experiment_sha256": "0" * 64,
        }
    )
    experiment = experiment.model_copy(update={"experiment_sha256": experiment_sha256(experiment)})
    trial = trial.model_copy(
        update={
            "experiment": experiment,
            "trial_sha256": trial_sha256(experiment, trial.variant_position, trial.seed),
        }
    )
    appended: list[tuple[int, tuple[SemanticEvent, ...]]] = []

    result = asyncio.run(
        run_semantic_trial(
            trial,
            tmp_path,
            model_backend,
            lambda round_number, events: appended.append((round_number, tuple(events))),
        )
    )

    assert result.observed_action_count == 2
    assert len(appended) == 1
