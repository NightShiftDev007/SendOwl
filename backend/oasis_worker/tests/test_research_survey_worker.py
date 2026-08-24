from __future__ import annotations

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

from oasis_worker.research_survey_contracts import (
    ClaimedResearchSurveyTrial,
    ResearchSurveyContext,
)
from oasis_worker.research_survey_engine import run_research_survey_trial
from oasis_worker.research_survey_hashing import (
    research_survey_answers_sha256,
    research_survey_config_sha256,
)


class StaticModel:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response
        self.messages: list[dict[str, object]] | None = None

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        assert tools[0]["function"]["name"] == "submit_research_observation"  # type: ignore[index]
        self.messages = messages
        return self.response


def _response() -> ChatCompletion:
    arguments = {
        "answers": [
            {"position": 0, "question_id": "context_clarity", "type": "likert", "value": 4},
            {
                "position": 1,
                "question_id": "attention_priority",
                "type": "single_choice",
                "value": "evidence",
            },
            {
                "position": 2,
                "question_id": "unanswered_question",
                "type": "free_text",
                "value": "Which evidence will be published next?",
            },
        ]
    }
    return ChatCompletion(
        id="native-survey-response",
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
                            id="native-survey-tool-call",
                            type="function",
                            function=Function(
                                name="submit_research_observation",
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


def _trial() -> ClaimedResearchSurveyTrial:
    from semantic_fixtures import build_trial

    persona = build_trial(persona_count=1, selected_position=1).cohort.personas[0]
    config = research_survey_config_sha256("https://provider.example/v1", "provider-model")
    survey = ResearchSurveyContext(
        id=UUID("91000000-0000-4000-8000-000000000001"),
        project_id=UUID("91000000-0000-4000-8000-000000000002"),
        run_id=UUID("91000000-0000-4000-8000-000000000003"),
        project_title="Native research project",
        research_question="What remains unclear?",
        simulation_requirement="Observe one bounded response context.",
        initial_post="A single synthetic statement.",
        project_sha256="a" * 64,
        run_spec_sha256="b" * 64,
        cohort_id=UUID("91000000-0000-4000-8000-000000000004"),
        cohort_sha256="c" * 64,
        persona_count=1,
        model_name="provider-model",
        survey_config_sha256=config,
        survey_sha256="d" * 64,
    )
    return ClaimedResearchSurveyTrial(
        id=UUID("91000000-0000-4000-8000-000000000005"),
        created_at=datetime(2026, 8, 17, tzinfo=UTC),
        persona_position=persona.position,
        persona_id=persona.id,
        persona_external_id=persona.persona_id,
        persona_display_name=persona.display_name,
        persona_profile_sha256=persona.profile_sha256,
        trial_sha256="e" * 64,
        survey=survey,
        persona=persona,
    )


def test_native_research_survey_returns_three_single_context_answers() -> None:
    trial = _trial()
    model = StaticModel(_response())

    result = asyncio.run(run_research_survey_trial(trial, model))  # type: ignore[arg-type]

    assert tuple(answer.question_id for answer in result.answers) == (
        "context_clarity",
        "attention_priority",
        "unanswered_question",
    )
    assert result.prompt_schema_version == "sandowl-research-survey/v1"
    assert result.answers_sha256 == research_survey_answers_sha256(
        trial.trial_sha256,
        result.answers,
    )
    assert model.messages is not None
    assert "Baseline" not in str(model.messages)
    assert "Alternative" not in str(model.messages)
