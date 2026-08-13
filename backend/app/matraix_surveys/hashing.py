"""Canonical JSON addresses for MatrAIx scenario-preference surveys."""

import json
from hashlib import sha256

from app.matraix_surveys.contracts import (
    SurveyAnswer,
    SurveyCohortRef,
    SurveyPersonaRef,
    SurveyScenarioRef,
    SurveyVariantRef,
)
from app.matraix_surveys.instrument import PROMPT_SCHEMA_VERSION, instrument_without_digest


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: object) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_survey_instrument_json(
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
) -> str:
    payload = {
        "schema": "matraix-survey-instrument/scenario-preference-v1",
        "instrument": instrument_without_digest(baseline, alternative),
    }
    return _canonical_json(payload)


def calculate_survey_instrument_sha256(
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
) -> str:
    canonical = canonical_survey_instrument_json(baseline, alternative)
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_survey_experiment_json(
    scenario: SurveyScenarioRef,
    cohort: SurveyCohortRef,
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
    instrument_sha256: str,
    model_name: str,
    survey_config_sha256: str,
) -> str:
    payload = {
        "schema": "matraix-survey-experiment/v1",
        "scenario": {
            "id": str(scenario.id),
            "title": scenario.title,
            "decision_question": scenario.decision_question,
            "scenario_sha256": scenario.scenario_sha256,
        },
        "cohort": {
            "id": str(cohort.id),
            "title": cohort.title,
            "cohort_sha256": cohort.cohort_sha256,
            "dataset_sha256": cohort.dataset_sha256,
            "persona_count": cohort.persona_count,
        },
        "baseline": {
            "id": str(baseline.id),
            "position": baseline.position,
            "name": baseline.name,
            "hypothesis": baseline.hypothesis,
        },
        "alternative": {
            "id": str(alternative.id),
            "position": alternative.position,
            "name": alternative.name,
            "hypothesis": alternative.hypothesis,
        },
        "instrument": {
            "schema_version": "scenario-preference/v1",
            "instrument_sha256": instrument_sha256,
        },
        "model": {
            "name": model_name,
            "config_sha256": survey_config_sha256,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        },
    }
    return _canonical_json(payload)


def calculate_survey_experiment_sha256(
    scenario: SurveyScenarioRef,
    cohort: SurveyCohortRef,
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
    instrument_sha256: str,
    model_name: str,
    survey_config_sha256: str,
) -> str:
    canonical = canonical_survey_experiment_json(
        scenario,
        cohort,
        baseline,
        alternative,
        instrument_sha256,
        model_name,
        survey_config_sha256,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_survey_trial_json(
    experiment_sha256: str,
    persona: SurveyPersonaRef,
) -> str:
    payload = {
        "schema": "matraix-survey-trial/v1",
        "experiment_sha256": experiment_sha256,
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "persona": {
            "position": persona.position,
            "id": str(persona.id),
            "persona_id": persona.persona_id,
            "display_name": persona.display_name,
            "profile_sha256": persona.profile_sha256,
        },
    }
    return _canonical_json(payload)


def calculate_survey_trial_sha256(
    experiment_sha256: str,
    persona: SurveyPersonaRef,
) -> str:
    canonical = canonical_survey_trial_json(experiment_sha256, persona)
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_survey_answers_json(
    trial_sha256: str,
    answers: tuple[SurveyAnswer, ...],
) -> str:
    if tuple(answer.position for answer in answers) != (0, 1, 2):
        raise ValueError("survey answers must contain positions zero through two")
    payload = {
        "schema": "matraix-survey-answers/v1",
        "trial_sha256": trial_sha256,
        "answers": [
            {
                "position": answer.position,
                "question_id": answer.question_id,
                "type": answer.type,
                "value": answer.value,
            }
            for answer in answers
        ],
    }
    return _canonical_json(payload)


def calculate_survey_answers_sha256(
    trial_sha256: str,
    answers: tuple[SurveyAnswer, ...],
) -> str:
    return _digest(json.loads(canonical_survey_answers_json(trial_sha256, answers)))
