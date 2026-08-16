"""Content addresses for frozen Web task inputs and recorded browser output."""

from hashlib import sha256

from app.matraix_web.contracts import WebCohortRef, WebPageObservation, WebPersonaRef
from app.matraix_web.tasks import PROMPT_SCHEMA_VERSION


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode()).hexdigest()


def calculate_task_spec_sha256(payload: dict[str, object]) -> str:
    source = payload["source"]
    limitations = payload["limitations"]
    if not isinstance(source, dict):
        raise TypeError("web task source must be a dictionary")
    if not isinstance(limitations, tuple) or not all(isinstance(item, str) for item in limitations):
        raise TypeError("web task limitations must be a tuple of strings")
    return _digest(
        (
            "matraix-web-task-spec/v1",
            str(payload["task_id"]),
            str(payload["version"]),
            str(payload["schema_version"]),
            str(payload["title"]),
            str(payload["domain"]),
            str(source["kind"]),
            str(source["project"]),
            str(source["canonical_path"]),
            "false",
            str(payload["transport"]),
            str(payload["target_origin"]),
            str(payload["instruction"]),
            str(payload["context"]),
            str(payload["page_count"]),
            str(payload["maximum_quote_count"]),
            str(payload["executor_schema_version"]),
            str(payload["executor_spec_sha256"]),
            *limitations,
        )
    )


def calculate_evaluation_sha256(
    task_spec_sha256: str,
    executor_spec_sha256: str,
    cohort: WebCohortRef,
    model_name: str,
    web_config_sha256: str,
    retry_of_evaluation_sha256: str | None,
    attempt_number: int,
) -> str:
    base = (
        task_spec_sha256,
        executor_spec_sha256,
        str(cohort.id),
        cohort.cohort_sha256,
        cohort.dataset_sha256,
        str(cohort.persona_count),
        model_name,
        web_config_sha256,
        PROMPT_SCHEMA_VERSION,
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


def calculate_trial_sha256(evaluation_sha256: str, persona: WebPersonaRef) -> str:
    return _digest(
        (
            "matraix-web-trial/v1",
            evaluation_sha256,
            str(persona.position),
            str(persona.id),
            persona.persona_id,
            persona.display_name,
            persona.profile_sha256,
        )
    )


def calculate_trace_sha256(
    trial_sha256: str,
    pages: tuple[WebPageObservation, ...],
) -> str:
    parts = ["matraix-web-trace/v1", trial_sha256]
    for page in pages:
        parts.extend(
            (
                str(page.position),
                page.url,
                page.title,
                page.screenshot_sha256,
            )
        )
        for quote in page.quotes:
            parts.extend(
                (
                    str(quote.position),
                    quote.quote_id,
                    quote.text,
                    quote.author,
                    *quote.tags,
                )
            )
    return _digest(tuple(parts))


def calculate_result_sha256(
    trial_sha256: str,
    trace_sha256: str,
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
            trial_sha256,
            trace_sha256,
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
