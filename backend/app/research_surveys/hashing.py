"""Canonical content addresses for native research surveys."""

import json
from hashlib import sha256
from uuid import UUID


def digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def instrument_sha256() -> str:
    return digest(
        {
            "schema": "sandowl-research-survey-instrument/v1",
            "questions": [
                ["context_clarity", "likert", 1, 5],
                [
                    "attention_priority",
                    "single_choice",
                    ["evidence", "process", "timing", "impact"],
                ],
                ["unanswered_question", "free_text", 2000],
            ],
        }
    )


def survey_sha256(
    project_sha: str, run_sha: str, cohort_sha: str, model: str, config_sha: str
) -> str:
    return digest(
        {
            "schema": "sandowl-research-survey/v1",
            "project_sha256": project_sha,
            "run_spec_sha256": run_sha,
            "cohort_sha256": cohort_sha,
            "instrument_sha256": instrument_sha256(),
            "model": model,
            "config_sha256": config_sha,
            "prompt_schema_version": "sandowl-research-survey/v1",
        }
    )


def trial_sha256(survey_sha: str, position: int, persona_id: UUID, profile_sha: str) -> str:
    return digest(
        {
            "schema": "sandowl-research-survey-trial/v1",
            "survey_sha256": survey_sha,
            "position": position,
            "persona_id": str(persona_id),
            "profile_sha256": profile_sha,
        }
    )


def answers_sha256(trial_sha: str, answers: list[dict[str, object]]) -> str:
    return digest(
        {
            "schema": "sandowl-research-survey-answers/v1",
            "trial_sha256": trial_sha,
            "answers": answers,
        }
    )
