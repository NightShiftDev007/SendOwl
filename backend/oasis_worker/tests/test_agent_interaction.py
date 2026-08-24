"""Strict worker-side Agent Interaction generation."""

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

from oasis_worker.agent_interaction_contracts import ClaimedAgentInteraction
from oasis_worker.agent_interaction_engine import answer_agent_interaction
from oasis_worker.agent_interaction_hashing import answer_sha256, interaction_sha256


class StaticInteractionModel:
    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert messages
        assert tools[0]["function"]["name"] == "submit_agent_interaction"  # type: ignore[index]
        return ChatCompletion(
            id="agent-interaction-response",
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
                                id="agent-interaction-tool-call",
                                type="function",
                                function=Function(
                                    name="submit_agent_interaction",
                                    arguments=json.dumps(
                                        {
                                            "answer_markdown": "这次仅记录了两条评论。",
                                            "citation_quotes": ["两条评论"],
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


def test_agent_interaction_normalizes_exact_single_run_citation() -> None:
    project_id = UUID("10000000-0000-4000-8000-000000000001")
    simulation_run_id = UUID("10000000-0000-4000-8000-000000000002")
    digest = interaction_sha256(
        project_id,
        simulation_run_id,
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "记录了什么？",
        None,
        None,
    )
    job = ClaimedAgentInteraction(
        id=UUID("10000000-0000-4000-8000-000000000003"),
        research_project_id=project_id,
        research_simulation_run_id=simulation_run_id,
        report_agent_run_id=UUID("10000000-0000-4000-8000-000000000004"),
        report_agent_run_sha256="a" * 64,
        report_agent_draft_id=UUID("10000000-0000-4000-8000-000000000005"),
        report_agent_draft_sha256="b" * 64,
        source_sha256="c" * 64,
        question="记录了什么？",
        interaction_sha256=digest,
        model_name="qwen",
        semantic_config_sha256="d" * 64,
        prompt_schema_version="sandowl-agent-interaction/v1",
        parent_interaction_sha256=None,
        parent_answer_sha256=None,
        conversation_depth=0,
        created_at=datetime.now(UTC),
        report_title="单次运行报告",
        report_markdown="## 观察\n本次记录两条评论。",
        source_text='{"summary":"两条评论","observation":"本次记录两条评论。"}',
        conversation_context=(),
    )

    result = asyncio.run(answer_agent_interaction(job, StaticInteractionModel()))  # type: ignore[arg-type]

    assert result.citations[0].target_id == simulation_run_id
    assert "两条评论" in result.citations[0].quote
    assert job.source_text.count(result.citations[0].quote) == 1
    assert result.answer_sha256 == answer_sha256(digest, result.answer_markdown, result.citations)
