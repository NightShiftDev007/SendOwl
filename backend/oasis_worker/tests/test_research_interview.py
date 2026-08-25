"""Strict model boundary for run-grounded Persona interviews."""

import asyncio
import json
import time
from datetime import UTC, datetime
from uuid import UUID

from camel.types import ChatCompletion, ChatCompletionMessage, Choice, CompletionUsage
from openai.types.chat.chat_completion_message_function_tool_call import (
    ChatCompletionMessageFunctionToolCall,
    Function,
)

from oasis_worker.research_interview_contracts import ClaimedResearchPersonaInterview
from oasis_worker.research_interview_engine import answer_research_persona_interview
from oasis_worker.research_interview_hashing import answer_sha256, interview_sha256
from oasis_worker.semantic_contracts import PersonaProfile, PersonaProvenance


class StaticResearchInterviewModel:
    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert messages
        assert tools[0]["function"]["name"] == "submit_run_persona_interview"  # type: ignore[index]
        return ChatCompletion(
            id="research-interview-response",
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
                                id="research-interview-call",
                                type="function",
                                function=Function(
                                    name="submit_run_persona_interview",
                                    arguments=json.dumps(
                                        {
                                            "answer_markdown": "作为合成人物，我记录到一条评论。",
                                            "citation_quotes": ["第 1 轮"],
                                        }
                                    ),
                                ),
                            )
                        ],
                    ),
                    logprobs=None,
                )
            ],
            usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
        )


class CorrectingResearchInterviewModel:
    def __init__(self) -> None:
        self.calls = 0

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        self.calls += 1
        if self.calls == 2:
            assert "character-for-character" in str(messages[-1]["content"])
        quote = "not copied from the source" if self.calls == 1 else "事件 #2"
        return ChatCompletion(
            id=f"research-interview-response-{self.calls}",
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
                                id=f"research-interview-call-{self.calls}",
                                type="function",
                                function=Function(
                                    name="submit_run_persona_interview",
                                    arguments=json.dumps(
                                        {
                                            "answer_markdown": "作为合成人物，我只引用冻结记录。",
                                            "citation_quotes": [quote],
                                        }
                                    ),
                                ),
                            )
                        ],
                    ),
                    logprobs=None,
                )
            ],
            usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
        )


def test_research_interview_requires_exact_frozen_run_quote() -> None:
    run_id = UUID("20000000-0000-4000-8000-000000000002")
    persona_id = UUID("20000000-0000-4000-8000-000000000003")
    source = "事件 #1；第 1 轮；实验预置\n事件 #2；第 1 轮；Persona；动作：create_comment"
    digest = interview_sha256(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        str(persona_id),
        "d" * 64,
        "你为什么评论？",
        "e" * 64,
        "f" * 64,
    )
    job = ClaimedResearchPersonaInterview(
        id=UUID("20000000-0000-4000-8000-000000000001"),
        research_project_id=UUID("20000000-0000-4000-8000-000000000004"),
        research_simulation_run_id=run_id,
        run_spec_sha256="a" * 64,
        graph_memory_sha256="b" * 64,
        cohort_id=UUID("20000000-0000-4000-8000-000000000005"),
        cohort_sha256="c" * 64,
        persona_id=persona_id,
        persona_position=0,
        persona_external_id="persona-1",
        persona_display_name="合成人物一",
        persona_profile=PersonaProfile(
            display_name="合成人物一",
            dimensions={"locale": "zh-CN"},
            persona_id="persona-1",
            provenance=PersonaProvenance(
                hf_repo=None,
                origin_persona_id=None,
                origin_source_row_index=None,
                parent_pool=None,
            ),
            source="test",
            version="v1",
        ),
        persona_profile_sha256="d" * 64,
        question="你为什么评论？",
        source_text=source,
        source_sha256="e" * 64,
        interview_sha256=digest,
        model_name="qwen",
        semantic_config_sha256="f" * 64,
        prompt_schema_version="sandowl-run-persona-interview/v1",
        created_at=datetime.now(UTC),
    )

    result = asyncio.run(
        answer_research_persona_interview(job, StaticResearchInterviewModel())  # type: ignore[arg-type]
    )

    assert result.citations[0].target_id == run_id
    assert "第 1 轮" in result.citations[0].quote
    assert source.count(result.citations[0].quote) == 1
    assert result.answer_sha256 == answer_sha256(digest, result.answer_markdown, result.citations)


def test_research_interview_retries_one_invalid_citation_with_exact_copy_instruction() -> None:
    run_id = UUID("20000000-0000-4000-8000-000000000012")
    persona_id = UUID("20000000-0000-4000-8000-000000000013")
    source = "事件 #1；第 1 轮；实验预置\n事件 #2；第 2 轮；Persona；动作：create_comment"
    digest = interview_sha256(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        str(persona_id),
        "d" * 64,
        "你为什么评论？",
        "e" * 64,
        "f" * 64,
    )
    job = ClaimedResearchPersonaInterview(
        id=UUID("20000000-0000-4000-8000-000000000011"),
        research_project_id=UUID("20000000-0000-4000-8000-000000000014"),
        research_simulation_run_id=run_id,
        run_spec_sha256="a" * 64,
        graph_memory_sha256="b" * 64,
        cohort_id=UUID("20000000-0000-4000-8000-000000000015"),
        cohort_sha256="c" * 64,
        persona_id=persona_id,
        persona_position=0,
        persona_external_id="persona-1",
        persona_display_name="合成人物一",
        persona_profile=PersonaProfile(
            display_name="合成人物一",
            dimensions={"locale": "zh-CN"},
            persona_id="persona-1",
            provenance=PersonaProvenance(
                hf_repo=None,
                origin_persona_id=None,
                origin_source_row_index=None,
                parent_pool=None,
            ),
            source="test",
            version="v1",
        ),
        persona_profile_sha256="d" * 64,
        question="你为什么评论？",
        source_text=source,
        source_sha256="e" * 64,
        interview_sha256=digest,
        model_name="qwen",
        semantic_config_sha256="f" * 64,
        prompt_schema_version="sandowl-run-persona-interview/v1",
        created_at=datetime.now(UTC),
    )
    model = CorrectingResearchInterviewModel()

    result = asyncio.run(answer_research_persona_interview(job, model))  # type: ignore[arg-type]

    assert model.calls == 2
    assert result.citations[0].quote == "事件 #2"
