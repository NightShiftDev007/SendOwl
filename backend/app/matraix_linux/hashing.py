"""Content addressing for fixed MatrAIx Linux trials and sealed parents."""

import json
from hashlib import sha256
from uuid import UUID

from app.matraix_linux.contracts import (
    LinuxArtifactHashes,
    LinuxCohortRef,
    LinuxPersonaRef,
)


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()


def calculate_trial_sha256(
    task_spec_sha256: str,
    runner_spec_sha256: str,
    cohort: LinuxCohortRef,
    persona: LinuxPersonaRef,
    model_name: str,
    linux_config_sha256: str,
    prompt_schema_version: str,
    retry_of_trial_sha256: str | None,
    attempt_number: int,
) -> str:
    base = (
        task_spec_sha256,
        runner_spec_sha256,
        str(cohort.id),
        cohort.cohort_sha256,
        cohort.dataset_sha256,
        str(persona.id),
        str(persona.position),
        persona.persona_id,
        persona.profile_sha256,
        model_name,
        linux_config_sha256,
        prompt_schema_version,
    )
    if attempt_number == 1 and retry_of_trial_sha256 is None:
        return _digest(("matraix-linux-trial/v1", *base))
    if not 2 <= attempt_number <= 5 or retry_of_trial_sha256 is None:
        raise ValueError("Linux retry requires a parent digest and attempt 2..5")
    return _digest(
        (
            "matraix-linux-trial-retry/v1",
            retry_of_trial_sha256,
            str(attempt_number),
            *base,
        )
    )


def calculate_evaluation_sha256(trial_id: UUID, trial_sha256: str) -> str:
    payload = {
        "schema_version": "matraix-linux-evaluation/v1",
        "trial_id": str(trial_id),
        "trial_sha256": trial_sha256,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def calculate_result_sha256(
    trial_sha256: str,
    artifact_sha256: str,
    file_sha256: LinuxArtifactHashes,
    reason: str,
    need_constraint_satisfaction: str,
    personal_preference_satisfaction: str,
    overall_experience_rating: int,
    feedback_reason: str,
) -> str:
    return _digest(
        (
            "matraix-linux-result/v1",
            trial_sha256,
            artifact_sha256,
            file_sha256.cleaned_list_csv,
            file_sha256.submission_json,
            file_sha256.user_feedback_json,
            file_sha256.verifier_json,
            reason,
            need_constraint_satisfaction,
            personal_preference_satisfaction,
            str(overall_experience_rating),
            feedback_reason,
        )
    )
