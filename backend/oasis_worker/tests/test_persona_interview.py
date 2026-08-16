"""Strict worker-side Persona interview content addressing and tool execution."""

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

from oasis_worker.persona_interview_contracts import (
    ClaimedPersonaInterview,
    ExtractedPersonaInterviewAnswer,
    InterviewReportSection,
)
from oasis_worker.persona_interview_engine import answer_persona_interview
from oasis_worker.persona_interview_hashing import answer_sha256, interview_sha256
from oasis_worker.semantic_contracts import PersonaProfile, PersonaProvenance


class StaticInterviewModel:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert messages
        assert tools[0]["function"]["name"] == "submit_persona_interview_answer"  # type: ignore[index]
        return self.response


def _tool_response(arguments: object) -> ChatCompletion:
    return ChatCompletion(
        id="persona-interview-response",
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
                            id="persona-interview-tool-call",
                            type="function",
                            function=Function(
                                name="submit_persona_interview_answer",
                                arguments=json.dumps(arguments),
                            ),
                        )
                    ],
                ),
                logprobs=None,
            )
        ],
        usage=CompletionUsage(completion_tokens=1, prompt_tokens=1, total_tokens=2),
    )


def test_persona_interview_digest_binds_profile_and_runtime() -> None:
    first = interview_sha256(
        "a" * 64,
        "b" * 64,
        "10000000-0000-4000-8000-000000000001",
        "c" * 64,
        "What matters?",
        "d" * 64,
    )
    second = interview_sha256(
        "a" * 64,
        "b" * 64,
        "10000000-0000-4000-8000-000000000001",
        "e" * 64,
        "What matters?",
        "d" * 64,
    )

    assert first != second


def test_persona_interview_answer_normalizes_section_positions() -> None:
    extracted = ExtractedPersonaInterviewAnswer(
        answer_markdown="Synthetic perspective.",
        cited_section_positions=(3, 1),
    )

    assert extracted.cited_section_positions == (1, 3)
    assert answer_sha256("a" * 64, extracted.answer_markdown, (1, 3)) != answer_sha256(
        "a" * 64,
        extracted.answer_markdown,
        (1, 2),
    )


def test_persona_interview_executes_one_strict_grounded_tool_call() -> None:
    interview_digest = "a" * 64
    job = ClaimedPersonaInterview(
        id=UUID("10000000-0000-4000-8000-000000000001"),
        report_id=UUID("10000000-0000-4000-8000-000000000002"),
        report_sha256="b" * 64,
        cohort_id=UUID("10000000-0000-4000-8000-000000000003"),
        cohort_sha256="c" * 64,
        persona_id=UUID("10000000-0000-4000-8000-000000000004"),
        persona_position=0,
        persona_external_id="persona-1",
        persona_display_name="Persona One",
        persona_profile=PersonaProfile(
            display_name="Persona One",
            dimensions={"region": "East Asia"},
            persona_id="persona-1",
            provenance=PersonaProvenance(
                hf_repo=None,
                origin_persona_id=None,
                origin_source_row_index=None,
                parent_pool=None,
            ),
            source="matraix",
            version="v1",
        ),
        persona_profile_sha256="d" * 64,
        question="What matters?",
        interview_sha256=interview_digest,
        model_name="qwen",
        semantic_config_sha256="e" * 64,
        prompt_schema_version="persona-report-interview/v1",
        created_at=datetime.now(UTC),
        report_title="Sealed findings",
        report_sections=tuple(
            InterviewReportSection(
                position=position,
                kind=kind,
                title=kind.title(),
                body_markdown=f"Bounded {kind} text.",
            )
            for position, kind in enumerate(("scope", "comparison", "limitations", "provenance"))
        ),
    )
    model = StaticInterviewModel(
        _tool_response(
            {
                "answer_markdown": "As a synthetic perspective, I need more evidence.",
                "cited_section_positions": [2, 0],
            }
        )
    )

    result = asyncio.run(answer_persona_interview(job, model))  # type: ignore[arg-type]

    assert result.cited_section_positions == (0, 2)
    assert result.answer_sha256 == answer_sha256(
        interview_digest,
        result.answer_markdown,
        (0, 2),
    )
