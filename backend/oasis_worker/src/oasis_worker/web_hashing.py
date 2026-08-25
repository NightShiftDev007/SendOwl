"""Canonical runtime and result identities for bounded MatrAIx Web trials."""

from hashlib import sha256

from oasis_worker.semantic_contracts import LOW_INFORMATION_VALUES, MAX_PROFILE_ATTRIBUTES
from oasis_worker.web_contracts import (
    WEB_EXECUTOR_SPEC_SHA256,
    WEB_PROMPT_SCHEMA_VERSION,
    WEB_RUNNER_VERSION,
    WEB_TASK_SPEC_SHA256,
    BrowserPage,
)

WEB_CONTEXT_TOKEN_LIMIT = 32_768
WEB_OUTPUT_MAX_TOKENS = 1024
WEB_TOOL_CHOICE = "required"
WEB_ENABLE_THINKING = False
WEB_PARALLEL_TOOL_CALLS = False


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode()).hexdigest()


def web_config_sha256(provider_base_url: str, model_name: str) -> str:
    return _digest(
        (
            "matraix-web-runtime-config/v1",
            "openai_compatible",
            provider_base_url,
            model_name,
            WEB_RUNNER_VERSION,
            WEB_PROMPT_SCHEMA_VERSION,
            str(WEB_CONTEXT_TOKEN_LIMIT),
            str(WEB_OUTPUT_MAX_TOKENS),
            WEB_TOOL_CHOICE,
            "false" if not WEB_ENABLE_THINKING else "true",
            "false" if not WEB_PARALLEL_TOOL_CALLS else "true",
            "submit_quote_choice",
            str(MAX_PROFILE_ATTRIBUTES),
            *sorted(LOW_INFORMATION_VALUES),
            WEB_TASK_SPEC_SHA256,
            WEB_EXECUTOR_SPEC_SHA256,
            "fixed_three_page_same_origin_observation",
        )
    )


def evaluation_sha256(
    task_spec_sha256: str,
    executor_spec_sha256: str,
    cohort_id: object,
    cohort_sha256: str,
    dataset_sha256: str,
    persona_count: int,
    model_name: str,
    config_sha256: str,
    retry_of_evaluation_sha256: str | None,
    attempt_number: int,
) -> str:
    base = (
        task_spec_sha256,
        executor_spec_sha256,
        str(cohort_id),
        cohort_sha256,
        dataset_sha256,
        str(persona_count),
        model_name,
        config_sha256,
        WEB_PROMPT_SCHEMA_VERSION,
    )
    if attempt_number == 1 and retry_of_evaluation_sha256 is None:
        return _digest(("matraix-web-evaluation/v1", *base))
    if not 2 <= attempt_number <= 5 or retry_of_evaluation_sha256 is None:
        raise ValueError("Web retry requires a parent digest and attempt 2..5")
    return _digest(
        (
            "matraix-web-evaluation-retry/v1",
            retry_of_evaluation_sha256,
            str(attempt_number),
            *base,
        )
    )


def trial_sha256(
    frozen_evaluation_sha256: str,
    persona_position: int,
    persona_id: object,
    persona_external_id: str,
    persona_display_name: str,
    persona_profile_sha256: str,
) -> str:
    return _digest(
        (
            "matraix-web-trial/v1",
            frozen_evaluation_sha256,
            str(persona_position),
            str(persona_id),
            persona_external_id,
            persona_display_name,
            persona_profile_sha256,
        )
    )


def trace_sha256(frozen_trial_sha256: str, pages: tuple[BrowserPage, ...]) -> str:
    parts = ["matraix-web-trace/v1", frozen_trial_sha256]
    for page in pages:
        parts.extend((str(page.position), page.url, page.title, page.screenshot_sha256))
        for quote in page.quotes:
            parts.extend(
                (str(quote.position), quote.quote_id, quote.text, quote.author, *quote.tags)
            )
    return _digest(tuple(parts))


def result_sha256(
    frozen_trial_sha256: str,
    frozen_trace_sha256: str,
    decision_subject_id: str,
    decision_subject_label: str,
    basis_primary: str,
    reason: str,
    task_author: str,
    need_constraint_satisfaction: str,
    personal_preference_satisfaction: str,
    overall_experience_rating: int,
) -> str:
    return _digest(
        (
            "matraix-web-result/v1",
            frozen_trial_sha256,
            frozen_trace_sha256,
            decision_subject_id,
            decision_subject_label,
            "selected",
            basis_primary,
            "compared_multiple",
            reason,
            task_author,
            need_constraint_satisfaction,
            personal_preference_satisfaction,
            str(overall_experience_rating),
        )
    )
