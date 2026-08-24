"""Strict worker-side ReportAgent cited draft generation."""

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

from oasis_worker.report_agent_draft_contracts import (
    ClaimedReportAgentDraft,
    ReportAgentDraftEvidence,
    ReportAgentDraftPlanSection,
)
from oasis_worker.report_agent_draft_engine import (
    _bounded_unique_quote,
    generate_report_agent_draft,
)
from oasis_worker.report_agent_draft_hashing import (
    draft_sha256,
    research_run_sha256,
    research_run_v2_sha256,
)


class StaticDraftModel:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert messages
        assert tools[0]["function"]["name"] == "submit_cited_draft"  # type: ignore[index]
        return self.response


class SequenceDraftModel:
    def __init__(self, responses: list[ChatCompletion]) -> None:
        self.responses = responses
        self.calls = 0

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert tools[0]["function"]["name"] == "submit_cited_draft"  # type: ignore[index]
        response = self.responses[self.calls]
        if self.calls == 1:
            assert "rejected by deterministic validation" in str(messages[-1]["content"])
        self.calls += 1
        return response


def _tool_response(arguments: object) -> ChatCompletion:
    return ChatCompletion(
        id="report-agent-draft-response",
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
                            id="report-agent-draft-tool-call",
                            type="function",
                            function=Function(
                                name="submit_cited_draft",
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


def test_report_agent_draft_normalizes_exact_citation_offsets() -> None:
    input_digest = "e" * 64
    job = ClaimedReportAgentDraft(
        id=UUID("10000000-0000-4000-8000-000000000001"),
        run_id=UUID("10000000-0000-4000-8000-000000000002"),
        run_sha256="a" * 64,
        evidence_call_count=1,
        evidence_calls_sha256="b" * 64,
        input_sha256=input_digest,
        model_name="qwen",
        semantic_config_sha256="c" * 64,
        prompt_schema_version="bounded-report-agent-cited-draft/v1",
        created_at=datetime.now(UTC),
        objective="Summarize evidence and limitations.",
        outline=(
            ReportAgentDraftPlanSection(position=0, title="Evidence", focus="Observed facts"),
            ReportAgentDraftPlanSection(position=1, title="Limits", focus="Unsupported claims"),
        ),
        evidence=(
            ReportAgentDraftEvidence(
                evidence_position=0,
                tool_call_position=2,
                evidence_kind="media_article",
                target_id=UUID("10000000-0000-4000-8000-000000000003"),
                source_label="Source: title",
                captured_text="Prefix exact frozen quote suffix.",
                content_sha256="d" * 64,
            ),
        ),
    )
    model = StaticDraftModel(
        _tool_response(
            {
                "title": "Bounded draft",
                "sections": [
                    {
                        "position": 0,
                        "title": "Evidence",
                        "body_markdown": "The evidence contains a frozen statement.",
                        "citations": [{"evidence_position": 0, "quote_position": 0}],
                    },
                    {
                        "position": 1,
                        "title": "Limits",
                        "body_markdown": "Only supplied text is covered.",
                        "citations": [{"evidence_position": 0, "quote_position": 0}],
                    },
                ],
            }
        )
    )

    result = asyncio.run(generate_report_agent_draft(job, model))  # type: ignore[arg-type]

    assert result.sections[0].citations[0].start_offset == 0
    assert result.sections[0].citations[0].end_offset == len("Prefix exact frozen quote suffix.")
    assert result.draft_sha256 == draft_sha256(input_digest, result.title, result.sections)


def test_report_agent_draft_corrects_one_invalid_citation_without_weakening_validation() -> None:
    job = ClaimedReportAgentDraft(
        id=UUID("10000000-0000-4000-8000-000000000001"),
        run_id=UUID("10000000-0000-4000-8000-000000000002"),
        run_sha256="a" * 64,
        evidence_call_count=1,
        evidence_calls_sha256="b" * 64,
        input_sha256="e" * 64,
        model_name="qwen",
        semantic_config_sha256="c" * 64,
        prompt_schema_version="bounded-report-agent-cited-draft/v1",
        created_at=datetime.now(UTC),
        objective="Summarize evidence and limitations.",
        outline=(
            ReportAgentDraftPlanSection(position=0, title="Evidence", focus="Observed facts"),
            ReportAgentDraftPlanSection(position=1, title="Limits", focus="Unsupported claims"),
        ),
        evidence=(
            ReportAgentDraftEvidence(
                evidence_position=0,
                tool_call_position=0,
                evidence_kind="simulation_run",
                target_id=UUID("10000000-0000-4000-8000-000000000003"),
                source_label="Frozen run",
                captured_text="repeated value; repeated value; unique frozen statement.",
                content_sha256="d" * 64,
            ),
        ),
    )
    invalid = {
        "title": "Bounded draft",
        "sections": [
            {
                "position": section.position,
                "title": section.title,
                "body_markdown": "Bounded observation.",
                "citations": [{"evidence_position": 0, "quote_position": 19}],
            }
            for section in job.outline
        ],
    }
    corrected = {
        "title": "Bounded draft",
        "sections": [
            {
                "position": section.position,
                "title": section.title,
                "body_markdown": "Bounded observation.",
                "citations": [{"evidence_position": 0, "quote_position": 0}],
            }
            for section in job.outline
        ],
    }
    model = SequenceDraftModel([_tool_response(invalid), _tool_response(corrected)])

    result = asyncio.run(generate_report_agent_draft(job, model))  # type: ignore[arg-type]

    assert model.calls == 2
    assert result.sections[0].citations[0].quote == job.evidence[0].captured_text


def test_report_agent_quote_normalizer_preserves_exact_unique_bounded_source_text() -> None:
    repeated_source = "first context repeated value; second context repeated value; final context"
    normalized_repeated = _bounded_unique_quote(repeated_source, "repeated value")
    long_quote = "".join(f"{position:04d}" for position in range(175))
    long_source = "prefix " + long_quote + " suffix"
    normalized_long = _bounded_unique_quote(long_source, long_quote)

    assert len(normalized_repeated) <= 500
    assert repeated_source.find(normalized_repeated) == repeated_source.rfind(normalized_repeated)
    assert "repeated value" in normalized_repeated
    assert len(normalized_long) == 500
    assert long_source.find(normalized_long) == long_source.rfind(normalized_long)


def test_research_run_report_agent_hash_binds_sealed_report() -> None:
    outline = (
        ReportAgentDraftPlanSection(position=0, title="观察", focus="合成事件"),
        ReportAgentDraftPlanSection(position=1, title="限制", focus="边界"),
    )
    arguments = (
        UUID("10000000-0000-4000-8000-000000000001"),
        UUID("10000000-0000-4000-8000-000000000002"),
        "a" * 64,
        UUID("10000000-0000-4000-8000-000000000003"),
    )

    first = research_run_sha256(*arguments, "b" * 64, "整理单次运行", outline, 1)
    second = research_run_sha256(*arguments, "c" * 64, "整理单次运行", outline, 1)

    assert first != second
    assert research_run_v2_sha256(*arguments, "b" * 64, "整理单次运行", outline, 1) != first
