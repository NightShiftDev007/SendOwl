"""Worker-side hashes for run-grounded Persona interviews."""

import hashlib
import json

from oasis_worker.research_interview_contracts import ResearchInterviewCitation


def source_sha256(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def interview_sha256(
    run_spec_sha256: str,
    graph_memory_sha256: str,
    cohort_sha256: str,
    persona_id: str,
    profile_sha256: str,
    question: str,
    source_digest: str,
    semantic_config_sha256: str,
) -> str:
    canonical = "\0".join(
        (
            "sandowl-run-persona-interview/v1",
            run_spec_sha256,
            graph_memory_sha256,
            cohort_sha256,
            persona_id,
            profile_sha256,
            question,
            source_digest,
            semantic_config_sha256,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def answer_sha256(
    interview_digest: str,
    answer_markdown: str,
    citations: tuple[ResearchInterviewCitation, ...],
) -> str:
    citations_json = json.dumps(
        [item.model_dump(mode="json") for item in citations],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    canonical = "\0".join(
        (
            "sandowl-run-persona-interview-answer/v1",
            interview_digest,
            answer_markdown,
            citations_json,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
