"""Content addresses for run-grounded Persona interviews."""

import json
from hashlib import sha256

from app.research_interviews.contracts import ResearchInterviewCitation


def calculate_source_sha256(source_text: str) -> str:
    return sha256(source_text.encode("utf-8")).hexdigest()


def calculate_interview_sha256(
    run_spec_sha256: str,
    graph_memory_sha256: str,
    cohort_sha256: str,
    persona_id: str,
    profile_sha256: str,
    question: str,
    source_sha256: str,
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
            source_sha256,
            semantic_config_sha256,
        )
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def calculate_answer_sha256(
    interview_sha256: str,
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
            interview_sha256,
            answer_markdown,
            citations_json,
        )
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def calculate_session_sha256(
    run_spec_sha256: str,
    graph_memory_sha256: str,
    cohort_sha256: str,
    personas: tuple[tuple[str, str], ...],
    question: str,
    source_sha256: str,
    semantic_config_sha256: str,
) -> str:
    canonical = json.dumps(
        {
            "schema": "sandowl-run-persona-interview-session/v1",
            "run_spec_sha256": run_spec_sha256,
            "graph_memory_sha256": graph_memory_sha256,
            "cohort_sha256": cohort_sha256,
            "personas": personas,
            "question": question,
            "source_sha256": source_sha256,
            "semantic_config_sha256": semantic_config_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
