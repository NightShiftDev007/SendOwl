"""Content hashes for fixed MatrAIx Linux trials."""

from hashlib import sha256

from oasis_worker.linux_contracts import LinuxFileHashes


def _digest(parts: tuple[str, ...]) -> str:
    return sha256("\0".join(parts).encode("utf-8")).hexdigest()


def linux_config_sha256(provider_base_url: str, model_name: str) -> str:
    return _digest(
        (
            "matraix-linux-runtime/v1",
            provider_base_url,
            model_name,
            "max_tokens=512",
            "tool_choice=required",
            "enable_thinking=false",
            "profile_projection=v1:max12",
            "fixed-note-to-csv",
        )
    )


def trial_sha256(
    task_spec_sha256: str,
    runner_spec_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    dataset_sha256: str,
    persona_id: str,
    persona_position: int,
    persona_external_id: str,
    persona_profile_sha256: str,
    model_name: str,
    config_sha256: str,
    prompt_schema_version: str,
) -> str:
    return _digest(
        (
            "matraix-linux-trial/v1",
            task_spec_sha256,
            runner_spec_sha256,
            cohort_id,
            cohort_sha256,
            dataset_sha256,
            persona_id,
            str(persona_position),
            persona_external_id,
            persona_profile_sha256,
            model_name,
            config_sha256,
            prompt_schema_version,
        )
    )


def result_sha256(
    trial_digest: str,
    artifact_sha256: str,
    files: LinuxFileHashes,
    reason: str,
    need: str,
    preference: str,
    rating: int,
    feedback_reason: str,
) -> str:
    return _digest(
        (
            "matraix-linux-result/v1",
            trial_digest,
            artifact_sha256,
            files.cleaned_list_csv,
            files.submission_json,
            files.user_feedback_json,
            files.verifier_json,
            reason,
            need,
            preference,
            str(rating),
            feedback_reason,
        )
    )
