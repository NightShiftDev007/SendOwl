"""MatrAIx Web worker contracts, hashes, and runtime configuration."""

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID

import pytest
from camel.types import ChatCompletion, ChatCompletionMessage, Choice, CompletionUsage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)
from pydantic import ValidationError

from oasis_worker.daemon import load_daemon_settings
from oasis_worker.semantic_contracts import PersonaProfile, PersonaProvenance, SemanticPersona
from oasis_worker.web_contracts import (
    WEB_EXECUTOR_SPEC_SHA256,
    WEB_TASK_SPEC_SHA256,
    BrowserObservation,
    BrowserPage,
    BrowserQuote,
    ClaimedWebTrial,
    WebEvaluation,
)
from oasis_worker.web_engine import run_web_trial
from oasis_worker.web_hashing import (
    evaluation_sha256,
    result_sha256,
    trace_sha256,
    trial_sha256,
    web_config_sha256,
)


def _persona() -> SemanticPersona:
    profile = PersonaProfile(
        display_name="Web Persona",
        dimensions={"interest": "literature", "style": "reflective"},
        persona_id="web-persona",
        provenance=PersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool=None,
        ),
        source="matraix",
        version="1.0.0",
    )
    return SemanticPersona(
        id=UUID("22000000-0000-4000-8000-000000000001"),
        position=0,
        persona_id=profile.persona_id,
        display_name=profile.display_name,
        source=profile.source,
        profile=profile,
        profile_sha256="c" * 64,
    )


def _pages() -> tuple[BrowserPage, BrowserPage, BrowserPage]:
    pages: list[BrowserPage] = []
    for page_position in range(3):
        quote_position = page_position
        pages.append(
            BrowserPage(
                position=page_position,
                url=(
                    "https://quotes.toscrape.com/"
                    if page_position == 0
                    else f"https://quotes.toscrape.com/page/{page_position + 1}/"
                ),
                title="Quotes to Scrape",
                screenshot_sha256=str(page_position + 1) * 64,
                quotes=(
                    BrowserQuote(
                        position=quote_position,
                        quote_id=str(page_position + 4) * 64,
                        text=f"Observed quote {page_position}",
                        author=f"Author {page_position}",
                        tags=("literature",),
                    ),
                ),
            )
        )
    return pages[0], pages[1], pages[2]


def test_web_hashes_match_control_plane_contract() -> None:
    persona = _persona()
    config_sha = web_config_sha256("https://provider.example/v1", "qwen-plus")
    evaluation_sha = evaluation_sha256(
        WEB_TASK_SPEC_SHA256,
        WEB_EXECUTOR_SPEC_SHA256,
        UUID("21000000-0000-4000-8000-000000000001"),
        "a" * 64,
        "b" * 64,
        1,
        "qwen-plus",
        config_sha,
        None,
        1,
    )
    trial_sha = trial_sha256(
        evaluation_sha,
        persona.position,
        persona.id,
        persona.persona_id,
        persona.display_name,
        persona.profile_sha256,
    )
    pages = _pages()
    trace = trace_sha256(trial_sha, pages)
    result = result_sha256(
        trial_sha,
        trace,
        pages[0].quotes[0].quote_id,
        pages[0].quotes[0].text,
        "taste",
        "This observed quote matches the synthetic Persona after comparing candidates.",
        pages[0].quotes[0].author,
        "yes",
        "yes",
        8,
    )

    assert len(config_sha) == 64
    assert len(evaluation_sha) == 64
    assert len(trial_sha) == 64
    assert len(trace) == 64
    assert len(result) == 64


def test_browser_observation_rejects_noncontiguous_or_external_data() -> None:
    pages = _pages()
    valid = {
        "task_id": "matraix/quotes-playwright-choice",
        "task_version": "1.0.0",
        "executor_schema_version": "matraix-web-browser-executor/v1",
        "executor_spec_sha256": WEB_EXECUTOR_SPEC_SHA256,
        "pages": pages,
    }
    observation = BrowserObservation.model_validate(valid)
    assert len(observation.pages) == 3

    with pytest.raises(ValidationError):
        BrowserObservation.model_validate(
            {
                **valid,
                "pages": (
                    pages[0],
                    {**pages[1].model_dump(), "url": "https://example.com/page/2/"},
                    pages[2],
                ),
            }
        )


def test_browser_observation_accepts_json_arrays_without_weakening_python_validation() -> None:
    pages = _pages()
    payload = {
        "task_id": "matraix/quotes-playwright-choice",
        "task_version": "1.0.0",
        "executor_schema_version": "matraix-web-browser-executor/v1",
        "executor_spec_sha256": WEB_EXECUTOR_SPEC_SHA256,
        "pages": [page.model_dump(mode="json") for page in pages],
    }

    with pytest.raises(ValidationError):
        BrowserObservation.model_validate(payload)

    observation = BrowserObservation.model_validate_json(json.dumps(payload))
    assert isinstance(observation.pages, tuple)
    assert isinstance(observation.pages[0].quotes, tuple)
    assert isinstance(observation.pages[0].quotes[0].tags, tuple)


def test_daemon_web_runtime_is_disabled_without_llm_and_complete_when_configured() -> None:
    base = {
        "DATABASE_URL": "postgresql://sandowl:sandowl@postgres/sandowl",
        "OASIS_ARTIFACT_ROOT": "/artifacts",
        "OASIS_WORKER_ID": "web-worker",
        "OASIS_WORKER_DOMAIN": "evaluation",
        "MATRAIX_WEB_BROWSER_URL": "http://matraix-web-browser:8000",
    }
    disabled = load_daemon_settings(base)
    assert disabled.web_config is None

    configured = load_daemon_settings(
        {
            **base,
            "LLM_API_KEY": "secret",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "qwen-plus",
        }
    )
    assert configured.web_config is not None
    assert configured.web_config.executor_spec_sha256 == WEB_EXECUTOR_SPEC_SHA256
    assert "secret" not in repr(configured)


def test_claimed_web_trial_requires_exact_persona_binding() -> None:
    persona = _persona()
    evaluation = WebEvaluation(
        id=UUID("23000000-0000-4000-8000-000000000001"),
        cohort_id=UUID("21000000-0000-4000-8000-000000000001"),
        cohort_sha256="a" * 64,
        cohort_title="Web Cohort",
        dataset_sha256="b" * 64,
        persona_count=1,
        task_id="matraix/quotes-playwright-choice",
        task_version="1.0.0",
        task_schema_version="matraix-web-task/quote-choice-v1",
        task_spec_sha256=WEB_TASK_SPEC_SHA256,
        executor_schema_version="matraix-web-browser-executor/v1",
        executor_spec_sha256=WEB_EXECUTOR_SPEC_SHA256,
        model_name="qwen-plus",
        web_config_sha256="d" * 64,
        prompt_schema_version="matraix-web-quotes-choice/v1",
        evaluation_sha256="e" * 64,
        retry_of_evaluation_id=None,
        retry_of_evaluation_sha256=None,
        attempt_number=1,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    with pytest.raises(ValidationError):
        ClaimedWebTrial(
            id=UUID("24000000-0000-4000-8000-000000000001"),
            status="running",
            created_at=evaluation.created_at,
            persona_position=0,
            persona_id=persona.id,
            persona_external_id=persona.persona_id,
            persona_display_name="Different Persona",
            persona_profile_sha256=persona.profile_sha256,
            trial_sha256="f" * 64,
            evaluation=evaluation,
            persona=persona,
        )


class StaticWebBrowser:
    async def observe(self, trial_id: object) -> BrowserObservation:
        assert str(trial_id) == "24000000-0000-4000-8000-000000000011"
        return BrowserObservation(
            task_id="matraix/quotes-playwright-choice",
            task_version="1.0.0",
            executor_schema_version="matraix-web-browser-executor/v1",
            executor_spec_sha256=WEB_EXECUTOR_SPEC_SHA256,
            pages=_pages(),
        )


class CorrectingWebModel:
    def __init__(self) -> None:
        self.calls = 0

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        self.calls += 1
        if self.calls == 2:
            assert "Do not return a second tool call" in str(messages[-1]["content"])
        quote_id = _pages()[0].quotes[0].quote_id
        arguments = json.dumps(
            {
                "decision_subject_id": quote_id,
                "basis_primary": "taste",
                "reason": "This observed quote best matches the frozen synthetic Persona taste.",
                "need_constraint_satisfaction": "yes",
                "personal_preference_satisfaction": "yes",
                "overall_experience_rating": 8,
            }
        )
        calls = [
            ChatCompletionMessageFunctionToolCall(
                id=f"web-call-{self.calls}-1",
                type="function",
                function=Function(name="submit_quote_choice", arguments=arguments),
            )
        ]
        if self.calls == 1:
            calls.append(
                ChatCompletionMessageFunctionToolCall(
                    id="web-call-1-2",
                    type="function",
                    function=Function(name="submit_quote_choice", arguments=arguments),
                )
            )
        return ChatCompletion(
            id=f"web-response-{self.calls}",
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
                        tool_calls=calls,
                    ),
                    logprobs=None,
                )
            ],
            usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
        )


def test_web_trial_retries_multiple_tool_calls_once() -> None:
    persona = _persona()
    evaluation = WebEvaluation(
        id=UUID("23000000-0000-4000-8000-000000000011"),
        cohort_id=UUID("21000000-0000-4000-8000-000000000011"),
        cohort_sha256="a" * 64,
        cohort_title="Web Cohort",
        dataset_sha256="b" * 64,
        persona_count=1,
        task_id="matraix/quotes-playwright-choice",
        task_version="1.0.0",
        task_schema_version="matraix-web-task/quote-choice-v1",
        task_spec_sha256=WEB_TASK_SPEC_SHA256,
        executor_schema_version="matraix-web-browser-executor/v1",
        executor_spec_sha256=WEB_EXECUTOR_SPEC_SHA256,
        model_name="qwen-plus",
        web_config_sha256="d" * 64,
        prompt_schema_version="matraix-web-quotes-choice/v1",
        evaluation_sha256="e" * 64,
        retry_of_evaluation_id=None,
        retry_of_evaluation_sha256=None,
        attempt_number=1,
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
    )
    trial = ClaimedWebTrial(
        id=UUID("24000000-0000-4000-8000-000000000011"),
        status="running",
        created_at=evaluation.created_at,
        persona_position=0,
        persona_id=persona.id,
        persona_external_id=persona.persona_id,
        persona_display_name=persona.display_name,
        persona_profile_sha256=persona.profile_sha256,
        trial_sha256="f" * 64,
        evaluation=evaluation,
        persona=persona,
    )
    model = CorrectingWebModel()

    result = asyncio.run(
        run_web_trial(trial, model, StaticWebBrowser())  # type: ignore[arg-type]
    )

    assert model.calls == 2
    assert result.decision_subject_id == _pages()[0].quotes[0].quote_id
