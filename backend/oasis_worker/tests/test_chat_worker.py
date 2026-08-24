from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from uuid import UUID

import pytest
from camel.types import (
    ChatCompletion,
    ChatCompletionMessage,
    Choice,
    CompletionUsage,
)
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)
from pydantic import ValidationError

from oasis_worker.chat_contracts import (
    CHAT_FEEDBACK_SCHEMA_VERSION,
    CHAT_SUT_SPEC_SHA256,
    CHAT_TASK_SPEC_SHA256,
    ChatEvaluation,
    ChatFeedback,
    ChatMessage,
    ChatRuntimeConfig,
    ClaimedChatTrial,
)
from oasis_worker.chat_engine import (
    AcmeSupportClient,
    _single_tool_call,
    probe_chat_runtime,
    run_chat_trial,
)
from oasis_worker.chat_hashing import (
    chat_config_sha256,
    evaluation_sha256,
    feedback_sha256,
    result_sha256,
    transcript_sha256,
    trial_sha256,
)
from oasis_worker.chat_queue import _validate_claim
from oasis_worker.errors import OasisExecutionError


class SequenceChatModel:
    def __init__(self, responses: tuple[ChatCompletion, ...]) -> None:
        self._responses = list(responses)
        self.tool_names: list[tuple[str, ...]] = []

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert messages
        self.tool_names.append(
            tuple(str(tool["function"]["name"]) for tool in tools)  # type: ignore[index]
        )
        return self._responses.pop(0)


class RecordingSut:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, message: str) -> str:
        self.messages.append(message)
        if len(self.messages) == 1:
            return (
                "Thanks for confirming. Order #4521 is still in transit. Is the shipping "
                "address still correct?"
            )
        return (
            "The carrier scan shows the order left the regional hub. If it hasn't arrived "
            "by Friday, reply here and we'll open a trace."
        )


def _tool_response(tool_name: str, arguments: object) -> ChatCompletion:
    return ChatCompletion(
        id="chat-response",
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
                            id="chat-tool-call",
                            type="function",
                            function=Function(
                                name=tool_name,
                                arguments=json.dumps(arguments, ensure_ascii=False),
                            ),
                        )
                    ],
                ),
                logprobs=None,
            )
        ],
        usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
    )


def _trial() -> ClaimedChatTrial:
    from semantic_fixtures import build_trial

    semantic = build_trial(persona_count=1, selected_position=0)
    persona = semantic.cohort.personas[0]
    evaluation = ChatEvaluation(
        id=UUID("91000000-0000-4000-8000-000000000001"),
        cohort_id=semantic.cohort.id,
        cohort_sha256=semantic.cohort.cohort_sha256,
        cohort_title=semantic.cohort.title,
        dataset_sha256=semantic.dataset.dataset_sha256,
        persona_count=1,
        task_id="matraix/acme-support-order-4521",
        task_version="1.0.0",
        task_schema_version="matraix-chat-task/acme-support-v1",
        task_spec_sha256=CHAT_TASK_SPEC_SHA256,
        sut_spec_sha256=CHAT_SUT_SPEC_SHA256,
        model_name="provider-model",
        chat_config_sha256=chat_config_sha256(
            "https://provider.example/v1",
            "provider-model",
        ),
        prompt_schema_version="matraix-chat-acme-support/v1",
        evaluation_sha256="0" * 64,
        retry_of_evaluation_id=None,
        retry_of_evaluation_sha256=None,
        attempt_number=1,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    evaluation = evaluation.model_copy(update={"evaluation_sha256": evaluation_sha256(evaluation)})
    frozen_trial_sha = trial_sha256(
        evaluation.evaluation_sha256,
        persona.position,
        persona.id,
        persona.persona_id,
        persona.display_name,
        persona.profile_sha256,
    )
    return ClaimedChatTrial(
        id=UUID("92000000-0000-4000-8000-000000000001"),
        status="running",
        created_at=evaluation.created_at,
        persona_position=persona.position,
        persona_id=persona.id,
        persona_external_id=persona.persona_id,
        persona_display_name=persona.display_name,
        persona_profile_sha256=persona.profile_sha256,
        trial_sha256=frozen_trial_sha,
        evaluation=evaluation,
        persona=persona,
    )


def _feedback() -> dict[str, object]:
    return {
        "schema_version": CHAT_FEEDBACK_SCHEMA_VERSION,
        "need_constraint_satisfaction": "partially",
        "personal_preference_satisfaction": "yes",
        "overall_experience_rating": 7,
        "reason": "The support path is concrete, but delivery is still pending.",
        "asked_useful_clarification_questions": True,
        "clarifying_notes": "The address question helped confirm the order details.",
    }


def _runtime_config(trial: ClaimedChatTrial) -> ChatRuntimeConfig:
    return ChatRuntimeConfig(
        api_key="provider-secret",
        provider_base_url="https://provider.example/v1",
        rest_sut_base_url="http://acme-support-sample:8000",
        mcp_sut_url="http://acme-support-mcp-sample:8000/mcp",
        model_name=trial.evaluation.model_name,
        config_sha256=trial.evaluation.chat_config_sha256,
        prompt_schema_version=trial.evaluation.prompt_schema_version,
        sut_task_id="sandowl/matraix-acme-rest-mcp-suite",
        sut_task_version="1.0.0",
        sut_spec_sha256="0c4499c79be0d62ff6a3159e5d27abafb65724b2c064499aa08ac1472acec91a",
    )


def _claim_row(trial: ClaimedChatTrial) -> dict[str, object]:
    evaluation = trial.evaluation
    return {
        "id": trial.id,
        "created_at": trial.created_at,
        "persona_position": trial.persona_position,
        "persona_id": trial.persona_id,
        "persona_external_id": trial.persona_external_id,
        "persona_display_name": trial.persona_display_name,
        "persona_profile_sha256": trial.persona_profile_sha256,
        "trial_sha256": trial.trial_sha256,
        "evaluation_id": evaluation.id,
        "cohort_id": evaluation.cohort_id,
        "cohort_sha256": evaluation.cohort_sha256,
        "cohort_title": evaluation.cohort_title,
        "dataset_sha256": evaluation.dataset_sha256,
        "persona_count": evaluation.persona_count,
        "task_id": evaluation.task_id,
        "task_version": evaluation.task_version,
        "task_schema_version": evaluation.task_schema_version,
        "task_spec_sha256": evaluation.task_spec_sha256,
        "sut_spec_sha256": evaluation.sut_spec_sha256,
        "evaluation_model_name": evaluation.model_name,
        "evaluation_chat_config_sha256": evaluation.chat_config_sha256,
        "evaluation_prompt_schema_version": evaluation.prompt_schema_version,
        "evaluation_sha256": evaluation.evaluation_sha256,
        "retry_of_evaluation_id": evaluation.retry_of_evaluation_id,
        "retry_of_evaluation_sha256": evaluation.retry_of_evaluation_sha256,
        "attempt_number": evaluation.attempt_number,
        "evaluation_created_at": evaluation.created_at,
        "profile_json": trial.persona.profile.model_dump(mode="json"),
    }


def test_chat_hashes_match_control_plane_golden_values() -> None:
    trial = _trial()
    messages = (
        ChatMessage(position=0, role="customer", content="My order #4521 is late."),
        ChatMessage(position=1, role="support", content="Is the address correct?"),
        ChatMessage(position=2, role="customer", content="Yes. What does tracking show?"),
        ChatMessage(position=3, role="support", content="It left the regional hub."),
    )
    feedback = ChatFeedback.model_validate(_feedback())
    transcript_digest = transcript_sha256(trial.trial_sha256, messages)
    feedback_digest = feedback_sha256(trial.trial_sha256, feedback)
    from oasis_worker.chat_engine import _derive_result

    result = _derive_result(messages, feedback)

    assert trial.evaluation.task_spec_sha256 == (
        "4624a4ab5611ca216f7f2bdb34e44f8849233f8ce3f1a6b789fd7936779154b1"
    )
    assert trial.evaluation.evaluation_sha256 == (
        "d3675547665b34bbcb88a505d6ed33a38e937e971228dd2f59ae50635e893705"
    )
    assert trial.trial_sha256 == (
        "f85ae117d5b124795dcd1a2166c4e424bb844efbdff0b8e0ec31455264d36b36"
    )
    assert transcript_digest == "900130bc8be15fb5dbb7ef7ce52243a4210ed9e1438fa4cdc1b1a5996a011c0d"
    assert feedback_digest == "22d7f267033412c216a11c0ef6fc37db43bada319987ca8f407e44616f3659f6"
    assert (
        result_sha256(
            trial.trial_sha256,
            transcript_digest,
            feedback_digest,
            result,
        )
        == "1b3238eb7b2510db52d0778690401aaf237a1efb862e2d592a09a398a23841a0"
    )


def test_chat_claim_rejects_corrupted_fixed_task_spec_before_execution() -> None:
    trial = _trial()
    row = _claim_row(trial)
    row["task_spec_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="task hashes"):
        _validate_claim(row, _runtime_config(trial))


def test_chat_message_limit_matches_0021_persisted_content_contract() -> None:
    accepted = ChatMessage(position=0, role="customer", content="x" * 8000)

    assert len(accepted.content) == 8000
    with pytest.raises(ValidationError, match="at most 8000"):
        ChatMessage(position=0, role="customer", content="x" * 8001)


def test_chat_trial_executes_two_real_sut_turns_then_strict_feedback() -> None:
    trial = _trial()
    model = SequenceChatModel(
        (
            _tool_response(
                "send_customer_message",
                {"message": "My NovaBuds order #4521 is late. Can you check it?"},
            ),
            _tool_response(
                "send_customer_message",
                {"message": "The address is correct. What does tracking show now?"},
            ),
            _tool_response("submit_chat_feedback", _feedback()),
        )
    )
    sut = RecordingSut()
    persisted: list[ChatMessage] = []

    success = asyncio.run(run_chat_trial(trial, model, sut, persisted.append))  # type: ignore[arg-type]

    assert len(success.messages) == 4
    assert tuple(message.role for message in success.messages) == (
        "customer",
        "support",
        "customer",
        "support",
    )
    assert tuple(persisted) == success.messages
    assert len(sut.messages) == 2
    assert model.tool_names == [
        ("send_customer_message",),
        ("send_customer_message",),
        ("send_customer_message", "submit_chat_feedback"),
    ]
    assert success.result.message_count == 4
    assert success.result.customer_turn_count == 2
    assert success.result.support_turn_count == 2
    assert success.result.next_step_owner == "user"


def test_chat_trial_never_neutral_fills_invalid_feedback() -> None:
    trial = _trial()
    invalid = _feedback()
    invalid["overall_experience_rating"] = 0
    model = SequenceChatModel(
        (
            _tool_response("send_customer_message", {"message": "Order #4521 is late."}),
            _tool_response("send_customer_message", {"message": "What is the next step?"}),
            _tool_response("submit_chat_feedback", invalid),
        )
    )

    with pytest.raises(OasisExecutionError, match="strict validation"):
        asyncio.run(run_chat_trial(trial, model, RecordingSut(), lambda _message: None))  # type: ignore[arg-type]


def test_chat_trial_rejects_nul_delimiter_in_provider_tool_text() -> None:
    trial = _trial()
    model = SequenceChatModel(
        (_tool_response("send_customer_message", {"message": "Order #4521\x00 is late."}),)
    )
    persisted: list[ChatMessage] = []

    with pytest.raises(OasisExecutionError, match="strict validation"):
        asyncio.run(run_chat_trial(trial, model, RecordingSut(), persisted.append))  # type: ignore[arg-type]

    assert persisted == []


def test_chat_provider_protocol_rejects_non_tool_finish_and_mixed_text() -> None:
    completion = _tool_response("send_customer_message", {"message": "Order #4521 is late."})
    choice = completion.choices[0]
    wrong_finish = completion.model_copy(
        update={"choices": [choice.model_copy(update={"finish_reason": "stop"})]}
    )
    mixed_text = completion.model_copy(
        update={
            "choices": [
                choice.model_copy(
                    update={
                        "message": choice.message.model_copy(
                            update={"content": "unstructured fallback"}
                        )
                    }
                )
            ]
        }
    )

    with pytest.raises(OasisExecutionError, match="finish with a tool call"):
        _single_tool_call(wrong_finish)
    with pytest.raises(OasisExecutionError, match="mixed assistant text"):
        _single_tool_call(mixed_text)


def test_chat_readiness_rejects_wrong_sut_identity_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AcmeSupportClient("http://acme-support-sample:8000")
    monkeypatch.setattr(
        client,
        "_request_json_with_retries",
        lambda _method, _path, _body: {
            "status": "ready",
            "sut_id": "wrong/sut",
            "sut_version": "1.0.0",
            "task_schema_version": "matraix-chat-task/acme-support-v1",
            "sut_spec_sha256": CHAT_SUT_SPEC_SHA256,
            "capabilities": ["text_chat"],
        },
    )
    model = SequenceChatModel((_tool_response("send_customer_message", {"message": "readiness"}),))

    with pytest.raises(OasisExecutionError, match="readiness identity"):
        asyncio.run(probe_chat_runtime(model, (client, client)))  # type: ignore[arg-type]
    assert model.tool_names == []


def test_sut_retry_logs_structured_safe_fields_without_url_or_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = AcmeSupportClient("http://user:secret@private-sut.example:8000")
    calls = 0

    def request(_method: str, _path: str, _body: dict[str, str] | None) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.URLError("private response body with secret")
        return {"reply": "Bounded support reply."}

    monkeypatch.setattr(client, "_request_json", request)
    caplog.set_level(logging.WARNING, logger="oasis_worker.chat")

    reply = asyncio.run(client.send_message("private customer body"))

    assert reply == "Bounded support reply."
    assert calls == 3
    assert len(caplog.records) == 2
    for record in caplog.records:
        assert record.method == "POST"  # type: ignore[attr-defined]
        assert record.path == "/v1/messages"  # type: ignore[attr-defined]
        assert record.error_type == "URLError"  # type: ignore[attr-defined]
        rendered = record.getMessage()
        assert "private-sut" not in rendered
        assert "private customer" not in rendered
        assert "secret" not in rendered


def test_acme_client_uses_real_stateless_source_sample_http_contract() -> None:
    backend_directory = Path(__file__).resolve().parents[2]
    backend_path = str(backend_directory)
    inserted_path = backend_path not in sys.path
    if inserted_path:
        sys.path.insert(0, backend_path)
    try:
        from acme_support_sample.server import create_server
    finally:
        if inserted_path:
            sys.path.remove(backend_path)

    server = create_server("127.0.0.1", 0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    client = AcmeSupportClient(f"http://{host}:{port}")

    try:
        asyncio.run(client.probe_readiness())
        first_reply = asyncio.run(client.send_message("My NovaBuds delivery is late."))
        second_reply = asyncio.run(client.send_message("The order number is #4521."))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert "order number" in first_reply
    assert "still in transit" in second_reply
    assert "carrier trace" in second_reply
    assert not thread.is_alive()


def test_chat_config_identity_is_stable_and_binds_provider_model() -> None:
    first = chat_config_sha256("https://provider.example/v1", "provider-model")
    second = chat_config_sha256("https://provider.example/v1", "other-model")

    assert first == "ab29bbd3b2df793641a236ab3649e0e7fa8b664f773bee5887da7abdfa330429"
    assert first != second
