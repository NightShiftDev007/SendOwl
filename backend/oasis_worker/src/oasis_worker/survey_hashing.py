"""Canonical survey identities shared with the MatrAIx Survey control plane."""

from __future__ import annotations

import hashlib
import json

from oasis_worker.semantic_contracts import LOW_INFORMATION_VALUES, MAX_PROFILE_ATTRIBUTES
from oasis_worker.survey_contracts import (
    SURVEY_ANSWER_IDS,
    SURVEY_INSTRUMENT_SCHEMA_VERSION,
    SURVEY_PROFILE_SCHEMA_VERSION,
    SURVEY_PROMPT_SCHEMA_VERSION,
    SURVEY_RUNNER_VERSION,
    SURVEY_TOOL_NAME,
    PositionedSurveyAnswer,
    ScenarioPreferenceInstrument,
    SurveyChoice,
    SurveyExperiment,
    SurveyQuestion,
)

SURVEY_CONTEXT_TOKEN_LIMIT = 32_768
SURVEY_OUTPUT_MAX_TOKENS = 1024
SURVEY_TOOL_CHOICE = "required"
SURVEY_ENABLE_THINKING = False
SURVEY_PROFILE_TEMPLATE_TEXT = """
# ROLE
You are one simulated survey respondent in a bounded scenario-preference experiment.

# IDENTITY
Display name: {display_name}
Persona source: {source}
Persona profile digest: {profile_sha256}

# BOUNDED PERSONA PROFILE
{profile_projection}

# RESPONSE BOUNDARY
Answer as this synthetic persona. This is a simulated preference observation, not a prediction
of any real person's behavior and not a decision recommendation.
""".strip()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def survey_config_sha256(base_url: str, model_name: str) -> str:
    return _digest(
        {
            "schema": "matraix-survey-runtime-config/v1",
            "provider": "openai_compatible",
            "base_url": base_url,
            "model_name": model_name,
            "runner_version": SURVEY_RUNNER_VERSION,
            "prompt_schema_version": SURVEY_PROMPT_SCHEMA_VERSION,
            "instrument_schema_version": SURVEY_INSTRUMENT_SCHEMA_VERSION,
            "model_config": {
                "context_token_limit": SURVEY_CONTEXT_TOKEN_LIMIT,
                "output_max_tokens": SURVEY_OUTPUT_MAX_TOKENS,
                "tool_choice": SURVEY_TOOL_CHOICE,
                "enable_thinking": SURVEY_ENABLE_THINKING,
            },
            "tool": {
                "name": SURVEY_TOOL_NAME,
                "required_answer_ids": list(SURVEY_ANSWER_IDS),
            },
            "profile_projection": {
                "schema": SURVEY_PROFILE_SCHEMA_VERSION,
                "template_sha256": hashlib.sha256(
                    SURVEY_PROFILE_TEMPLATE_TEXT.encode("utf-8")
                ).hexdigest(),
                "low_information_values": sorted(LOW_INFORMATION_VALUES),
                "max_attributes": MAX_PROFILE_ATTRIBUTES,
            },
        }
    )


def build_survey_instrument(
    baseline_name: str,
    baseline_hypothesis: str,
    alternative_name: str,
    alternative_hypothesis: str,
) -> ScenarioPreferenceInstrument:
    """Mirror the control plane's exact deterministic scenario-preference instrument."""
    return ScenarioPreferenceInstrument(
        schema_version=SURVEY_INSTRUMENT_SCHEMA_VERSION,
        title="Scenario preference",
        description=(
            "Answer as the supplied synthetic persona. Compare the sealed baseline and "
            "alternative; this records a simulated response, not a prediction of real people."
        ),
        questions=(
            SurveyQuestion(
                position=0,
                id="preferred_variant",
                type="single_choice",
                prompt="Which path would you prefer in this decision scenario?",
                required=True,
                options=(
                    SurveyChoice(
                        id="baseline",
                        label=baseline_name,
                        description=baseline_hypothesis,
                    ),
                    SurveyChoice(
                        id="alternative",
                        label=alternative_name,
                        description=alternative_hypothesis,
                    ),
                ),
                min_value=None,
                max_value=None,
            ),
            SurveyQuestion(
                position=1,
                id="alternative_support",
                type="likert",
                prompt=(
                    f"How strongly would you support the alternative “{alternative_name}”? "
                    "Use 1 for strongly oppose and 5 for strongly support."
                ),
                required=True,
                options=(),
                min_value=1,
                max_value=5,
            ),
            SurveyQuestion(
                position=2,
                id="primary_reason",
                type="free_text",
                prompt="What is the main reason for your preference and support rating?",
                required=True,
                options=(),
                min_value=None,
                max_value=None,
            ),
        ),
    )


def instrument_sha256(instrument: ScenarioPreferenceInstrument) -> str:
    return _digest(
        {
            "schema": "matraix-survey-instrument/scenario-preference-v1",
            "instrument": instrument.model_dump(mode="json"),
        }
    )


def experiment_sha256(experiment: SurveyExperiment) -> str:
    payload = {
        "schema": "matraix-survey-experiment/v1",
        "scenario": {
            "id": str(experiment.scenario_id),
            "title": experiment.scenario_title,
            "decision_question": experiment.decision_question,
            "scenario_sha256": experiment.scenario_sha256,
        },
        "cohort": {
            "id": str(experiment.cohort_id),
            "title": experiment.cohort_title,
            "cohort_sha256": experiment.cohort_sha256,
            "dataset_sha256": experiment.dataset_sha256,
            "persona_count": experiment.persona_count,
        },
        "baseline": {
            "id": str(experiment.baseline_id),
            "position": experiment.baseline_position,
            "name": experiment.baseline_name,
            "hypothesis": experiment.baseline_hypothesis,
        },
        "alternative": {
            "id": str(experiment.alternative_id),
            "position": experiment.alternative_position,
            "name": experiment.alternative_name,
            "hypothesis": experiment.alternative_hypothesis,
        },
        "instrument": {
            "schema_version": SURVEY_INSTRUMENT_SCHEMA_VERSION,
            "instrument_sha256": experiment.instrument_sha256,
        },
        "model": {
            "name": experiment.model_name,
            "config_sha256": experiment.survey_config_sha256,
            "prompt_schema_version": experiment.prompt_schema_version,
        },
    }
    if experiment.attempt_number > 1:
        if experiment.retry_of_experiment_sha256 is None:
            raise ValueError("Survey retry experiment has no parent digest")
        payload = {
            "schema": "matraix-survey-experiment-retry/v1",
            "retry_of_experiment_sha256": experiment.retry_of_experiment_sha256,
            "attempt_number": experiment.attempt_number,
            "experiment": payload,
        }
    return _digest(payload)


def trial_sha256(
    frozen_experiment_sha256: str,
    persona_position: int,
    persona_id: object,
    persona_external_id: str,
    persona_display_name: str,
    persona_profile_sha256: str,
) -> str:
    return _digest(
        {
            "schema": "matraix-survey-trial/v1",
            "experiment_sha256": frozen_experiment_sha256,
            "persona": {
                "position": persona_position,
                "id": str(persona_id),
                "persona_id": persona_external_id,
                "display_name": persona_display_name,
                "profile_sha256": persona_profile_sha256,
            },
            "prompt_schema_version": SURVEY_PROMPT_SCHEMA_VERSION,
        }
    )


def answers_sha256(
    frozen_trial_sha256: str,
    answers: tuple[PositionedSurveyAnswer, ...],
) -> str:
    return _digest(
        {
            "schema": "matraix-survey-answers/v1",
            "trial_sha256": frozen_trial_sha256,
            "answers": [answer.model_dump(mode="json") for answer in answers],
        }
    )
