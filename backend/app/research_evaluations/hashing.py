"""Canonical content addresses for Project-bound evaluation task bundles."""

import json
from hashlib import sha256

from app.research_evaluations.contracts import (
    ResearchEvaluationTargetPayload,
    ResearchEvaluationTaskBundlePayload,
)


def canonical_task_bundle_json(payload: ResearchEvaluationTaskBundlePayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_task_bundle_sha256(payload: ResearchEvaluationTaskBundlePayload) -> str:
    return sha256(canonical_task_bundle_json(payload).encode("utf-8")).hexdigest()


def calculate_survey_artifact_sha256(
    bundle_sha256: str,
    answer_digests: tuple[tuple[int, str], ...],
) -> str:
    encoded = json.dumps(
        {
            "schema_version": "sandowl-research-survey-artifact/v1",
            "bundle_sha256": bundle_sha256,
            "answers": answer_digests,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def canonical_evaluation_target_json(payload: ResearchEvaluationTargetPayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_evaluation_target_sha256(payload: ResearchEvaluationTargetPayload) -> str:
    return sha256(canonical_evaluation_target_json(payload).encode("utf-8")).hexdigest()


def calculate_evaluation_job_sha256(
    target_sha256: str,
    project_sha256: str,
    run_spec_sha256: str,
    cohort_sha256: str,
    retry_of_job_sha256: str | None,
    attempt_number: int,
) -> str:
    if attempt_number == 1 and retry_of_job_sha256 is None:
        payload = {
            "schema_version": "sandowl-research-evaluation-job/v1",
            "target_sha256": target_sha256,
            "project_sha256": project_sha256,
            "run_spec_sha256": run_spec_sha256,
            "cohort_sha256": cohort_sha256,
        }
    elif 2 <= attempt_number <= 5 and retry_of_job_sha256 is not None:
        payload = {
            "schema_version": "sandowl-research-evaluation-job-retry/v1",
            "target_sha256": target_sha256,
            "project_sha256": project_sha256,
            "run_spec_sha256": run_spec_sha256,
            "cohort_sha256": cohort_sha256,
            "retry_of_job_sha256": retry_of_job_sha256,
            "attempt_number": attempt_number,
        }
    else:
        raise ValueError("Harbor job retry lineage is invalid")
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()
