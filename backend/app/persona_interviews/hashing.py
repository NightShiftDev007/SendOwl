"""Content addressing for Persona interviews and their answers."""

import hashlib
import json


def interview_sha256(
    report_sha256: str,
    cohort_sha256: str,
    persona_id: str,
    profile_sha256: str,
    question: str,
    semantic_config_sha256: str,
) -> str:
    canonical = "\0".join(
        (
            "persona-report-interview/v1",
            report_sha256,
            cohort_sha256,
            persona_id,
            profile_sha256,
            question,
            semantic_config_sha256,
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def answer_sha256(interview_digest: str, answer_markdown: str, positions: tuple[int, ...]) -> str:
    positions_json = json.dumps(positions, separators=(",", ":"))
    canonical = "\0".join(
        ("persona-report-interview-answer/v1", interview_digest, answer_markdown, positions_json)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def interview_session_sha256(
    report_sha256: str,
    cohort_sha256: str,
    personas: tuple[tuple[str, str], ...],
    question: str,
    semantic_config_sha256: str,
) -> str:
    canonical_personas = json.dumps(personas, ensure_ascii=False, separators=(",", ":"))
    canonical = "\0".join(
        (
            "persona-report-interview-session/v1",
            report_sha256,
            cohort_sha256,
            canonical_personas,
            question,
            semantic_config_sha256,
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
