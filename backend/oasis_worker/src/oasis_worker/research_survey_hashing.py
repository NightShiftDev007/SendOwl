"""Worker-side hashes for native research surveys."""

import hashlib
import json

from oasis_worker.research_survey_contracts import (
    AttentionPriorityAnswer,
    ContextClarityAnswer,
    UnansweredQuestionAnswer,
)


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def research_survey_config_sha256(base_url: str, model_name: str) -> str:
    return _digest(
        {
            "schema": "sandowl-research-survey-runtime-config/v1",
            "provider": "openai_compatible",
            "base_url": base_url,
            "model_name": model_name,
            "runner_version": "1.0.0",
            "prompt_schema_version": "sandowl-research-survey/v1",
            "instrument_schema_version": "single-context-observation/v1",
            "model_config": {
                "context_token_limit": 32768,
                "output_max_tokens": 1024,
                "tool_choice": "required",
                "enable_thinking": False,
            },
            "tool_name": "submit_research_observation",
        }
    )


def research_survey_answers_sha256(
    trial_sha: str,
    answers: tuple[ContextClarityAnswer, AttentionPriorityAnswer, UnansweredQuestionAnswer],
) -> str:
    return _digest(
        {
            "schema": "sandowl-research-survey-answers/v1",
            "trial_sha256": trial_sha,
            "answers": [item.model_dump(mode="json") for item in answers],
        }
    )
