from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
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

from oasis_worker.daemon import load_daemon_settings
from oasis_worker.errors import OasisExecutionError
from oasis_worker.survey_contracts import (
    ClaimedSurveyTrial,
    SurveyCohortMember,
    SurveyExperiment,
)
from oasis_worker.survey_engine import (
    create_survey_model,
    probe_survey_runtime,
    run_survey_trial,
)
from oasis_worker.survey_hashing import (
    answers_sha256,
    build_survey_instrument,
    experiment_sha256,
    instrument_sha256,
    survey_config_sha256,
    trial_sha256,
)
from oasis_worker.survey_queue import _claimed_survey_trial_from_row


class StaticSurveyModel:
    def __init__(self, response: ChatCompletion) -> None:
        self.response = response
        self.tools: list[dict[str, object]] | None = None

    async def arun(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
    ) -> ChatCompletion:
        del messages
        self.tools = tools
        return self.response


def _tool_response(arguments: object, tool_name: str) -> ChatCompletion:
    return ChatCompletion(
        id="survey-response",
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
                            id="survey-tool-call",
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


def _valid_envelope() -> dict[str, object]:
    return {
        "answers": [
            {
                "question_id": "preferred_variant",
                "type": "single_choice",
                "value": "alternative",
            },
            {
                "question_id": "alternative_support",
                "type": "likert",
                "value": 4,
            },
            {
                "question_id": "primary_reason",
                "type": "free_text",
                "value": "  The bounded alternative fits this persona.  ",
            },
        ]
    }


def _trial() -> ClaimedSurveyTrial:
    from semantic_fixtures import build_trial

    semantic = build_trial(persona_count=1, selected_position=1)
    persona = semantic.cohort.personas[0]
    baseline = semantic.scenario.variants[0]
    alternative = semantic.scenario.variants[2]
    instrument = build_survey_instrument(
        baseline.name,
        baseline.hypothesis,
        alternative.name,
        alternative.hypothesis,
    )
    config_sha256 = survey_config_sha256(
        "https://provider.example/v1",
        "provider-model",
    )
    experiment = SurveyExperiment(
        id=UUID("71000000-0000-4000-8000-000000000001"),
        scenario_id=semantic.scenario.id,
        scenario_sha256=semantic.scenario.scenario_sha256,
        scenario_title=semantic.scenario.title,
        decision_question=semantic.scenario.decision_question,
        cohort_id=semantic.cohort.id,
        cohort_sha256=semantic.cohort.cohort_sha256,
        cohort_title=semantic.cohort.title,
        dataset_sha256=semantic.dataset.dataset_sha256,
        persona_count=1,
        baseline_id=baseline.id,
        baseline_position=baseline.position,
        baseline_name=baseline.name,
        baseline_hypothesis=baseline.hypothesis,
        alternative_id=alternative.id,
        alternative_position=alternative.position,
        alternative_name=alternative.name,
        alternative_hypothesis=alternative.hypothesis,
        instrument_schema_version="scenario-preference/v1",
        instrument=instrument,
        instrument_sha256=instrument_sha256(instrument),
        model_name="provider-model",
        survey_config_sha256=config_sha256,
        prompt_schema_version="matraix-survey-scenario-preference/v1",
        experiment_sha256="0" * 64,
        retry_of_experiment_id=None,
        retry_of_experiment_sha256=None,
        attempt_number=1,
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
    )
    experiment = experiment.model_copy(update={"experiment_sha256": experiment_sha256(experiment)})
    frozen_trial_sha256 = trial_sha256(
        experiment.experiment_sha256,
        persona.position,
        persona.id,
        persona.persona_id,
        persona.display_name,
        persona.profile_sha256,
    )
    return ClaimedSurveyTrial(
        id=UUID("72000000-0000-4000-8000-000000000001"),
        status="running",
        created_at=experiment.created_at,
        persona_position=persona.position,
        persona_id=persona.id,
        persona_external_id=persona.persona_id,
        persona_display_name=persona.display_name,
        persona_profile_sha256=persona.profile_sha256,
        trial_sha256=frozen_trial_sha256,
        experiment=experiment,
        persona=persona,
        cohort_members=(
            SurveyCohortMember(
                position=persona.position,
                persona_id=persona.persona_id,
                profile_sha256=persona.profile_sha256,
            ),
        ),
    )


def test_claimed_survey_trial_projects_only_public_trial_columns() -> None:
    expected = _trial()
    row = {
        "id": expected.id,
        "experiment_id": expected.experiment.id,
        "persona_position": expected.persona_position,
        "persona_id": expected.persona_id,
        "persona_external_id": expected.persona_external_id,
        "persona_display_name": expected.persona_display_name,
        "persona_profile_sha256": expected.persona_profile_sha256,
        "trial_sha256": expected.trial_sha256,
        "created_at": expected.created_at,
    }

    projected = _claimed_survey_trial_from_row(
        row,
        expected.experiment,
        expected.persona,
        expected.cohort_members,
    )

    assert projected == expected


def test_survey_runtime_config_is_independent_and_stable() -> None:
    assert (
        survey_config_sha256(
            "https://provider.example/v1",
            "provider-model",
        )
        == "b953e613c53968cff2f82a910f6103f85d5a0772fc786194149dc062e7344731"
    )


def test_survey_provider_backend_uses_the_frozen_model_contract() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://unused:unused@localhost/unused",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "survey-provider-contract-test",
            "OASIS_WORKER_DOMAIN": "evaluation",
            "LLM_API_KEY": "secret-key",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL_NAME": "provider-model",
        }
    )
    assert settings.survey_config is not None

    backend = create_survey_model(settings.survey_config)

    assert backend.token_limit == 32_768
    assert backend.model_config_dict == {
        "max_tokens": 1024,
        "tool_choice": "required",
        "extra_body": {"enable_thinking": False},
    }


def test_survey_hashes_are_stable_for_exact_frozen_inputs() -> None:
    trial = _trial()

    assert trial.experiment.instrument_sha256 == (
        "d527812d1502e05666349bf3d023ce5c1c2285861e860699d958a1e453e79750"
    )
    assert trial.experiment.experiment_sha256 == (
        "df7bed32cd2242aaee4a9b0c9110d97888a629b5685ba11b4be75611cddf0ce7"
    )
    assert trial.trial_sha256 == (
        "71a1b7b31cc7bc83a66cd64884420dd62fbb219bacbcb33721544e6893dd06e4"
    )


def test_survey_trial_returns_exact_typed_answers_without_defaulting() -> None:
    trial = _trial()
    model = StaticSurveyModel(_tool_response(_valid_envelope(), "submit_scenario_preference"))

    result = asyncio.run(run_survey_trial(trial, model))  # type: ignore[arg-type]

    assert [answer.position for answer in result.answers] == [0, 1, 2]
    assert [answer.value for answer in result.answers] == [
        "alternative",
        4,
        ("The bounded alternative fits this persona."),
    ]
    assert result.answers_sha256 == answers_sha256(trial.trial_sha256, result.answers)
    assert model.tools is not None
    function = model.tools[0]["function"]
    assert isinstance(function, dict)
    assert function["name"] == "submit_scenario_preference"


def test_survey_trial_wraps_provider_failure_without_exposing_provider_details() -> None:
    class AuthenticationError(Exception):
        pass

    class FailingSurveyModel:
        async def arun(
            self,
            messages: list[dict[str, object]],
            tools: list[dict[str, object]],
        ) -> ChatCompletion:
            del messages, tools
            raise AuthenticationError("provider body contained secret material")

    with pytest.raises(OasisExecutionError, match="AuthenticationError") as captured:
        asyncio.run(run_survey_trial(_trial(), FailingSurveyModel()))  # type: ignore[arg-type]

    assert "secret material" not in str(captured.value)
    assert isinstance(captured.value.__cause__, AuthenticationError)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: {"answers": value["answers"][:2]},
        lambda value: {"answers": [*value["answers"], value["answers"][2]]},
        lambda value: {"answers": [value["answers"][0], value["answers"][0], value["answers"][2]]},
        lambda value: {
            "answers": [
                value["answers"][0],
                {"question_id": "unknown", "type": "likert", "value": 3},
                value["answers"][2],
            ]
        },
        lambda value: {
            "answers": [
                value["answers"][0],
                {"question_id": "alternative_support", "type": "likert", "value": True},
                value["answers"][2],
            ]
        },
        lambda value: {
            "answers": [
                value["answers"][0],
                {"question_id": "alternative_support", "type": "likert", "value": 6},
                value["answers"][2],
            ]
        },
        lambda value: {
            "answers": [
                value["answers"][0],
                value["answers"][1],
                {"question_id": "primary_reason", "type": "free_text", "value": "   "},
            ]
        },
        lambda value: {**value, "unexpected": "forbidden"},
    ],
)
def test_survey_trial_rejects_any_invalid_answer_envelope(mutate: object) -> None:
    invalid = mutate(_valid_envelope())  # type: ignore[operator]
    model = StaticSurveyModel(_tool_response(invalid, "submit_scenario_preference"))

    with pytest.raises(OasisExecutionError, match="strict validation"):
        asyncio.run(run_survey_trial(_trial(), model))  # type: ignore[arg-type]


def test_survey_trial_rejects_wrong_or_multiple_tool_calls() -> None:
    wrong = StaticSurveyModel(_tool_response(_valid_envelope(), "other_tool"))
    with pytest.raises(OasisExecutionError, match="unexpected tool name"):
        asyncio.run(run_survey_trial(_trial(), wrong))  # type: ignore[arg-type]

    response = _tool_response(_valid_envelope(), "submit_scenario_preference")
    tool_call = response.choices[0].message.tool_calls
    assert tool_call is not None
    response.choices[0].message.tool_calls = [*tool_call, tool_call[0]]
    multiple = StaticSurveyModel(response)
    with pytest.raises(OasisExecutionError, match="exactly one tool call"):
        asyncio.run(run_survey_trial(_trial(), multiple))  # type: ignore[arg-type]


def test_survey_startup_probe_requires_one_complete_strict_response() -> None:
    valid = StaticSurveyModel(_tool_response(_valid_envelope(), "submit_scenario_preference"))
    asyncio.run(probe_survey_runtime(valid))  # type: ignore[arg-type]

    invalid = StaticSurveyModel(_tool_response({"answers": []}, "submit_scenario_preference"))
    with pytest.raises(OasisExecutionError, match="strict validation"):
        asyncio.run(probe_survey_runtime(invalid))  # type: ignore[arg-type]


@pytest.mark.external_provider
def test_external_provider_survey_smoke_when_explicitly_enabled() -> None:
    if os.environ.get("OASIS_EXTERNAL_PROVIDER_SMOKE") != "1":
        pytest.skip("set OASIS_EXTERNAL_PROVIDER_SMOKE=1 to make real provider calls")
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql://unused:unused@localhost/unused",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "external-survey-provider-test",
            "OASIS_WORKER_DOMAIN": "evaluation",
            "LLM_API_KEY": os.environ["LLM_API_KEY"],
            "LLM_BASE_URL": os.environ["LLM_BASE_URL"],
            "LLM_MODEL_NAME": os.environ["LLM_MODEL_NAME"],
        }
    )
    assert settings.survey_config is not None
    model = create_survey_model(settings.survey_config)
    asyncio.run(probe_survey_runtime(model))
    trial = _trial()
    experiment = trial.experiment.model_copy(
        update={
            "model_name": settings.survey_config.model_name,
            "survey_config_sha256": settings.survey_config.config_sha256,
            "experiment_sha256": "0" * 64,
        }
    )
    experiment = experiment.model_copy(update={"experiment_sha256": experiment_sha256(experiment)})
    trial = trial.model_copy(
        update={
            "experiment": experiment,
            "trial_sha256": trial_sha256(
                experiment.experiment_sha256,
                trial.persona_position,
                trial.persona_id,
                trial.persona_external_id,
                trial.persona_display_name,
                trial.persona_profile_sha256,
            ),
        }
    )

    result = asyncio.run(run_survey_trial(trial, model))

    assert tuple(answer.position for answer in result.answers) == (0, 1, 2)
    assert result.answers_sha256 == answers_sha256(trial.trial_sha256, result.answers)
