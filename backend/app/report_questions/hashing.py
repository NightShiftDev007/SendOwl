"""Content addressing for evidence-bound report questions."""

import hashlib
import json

from app.report_questions.contracts import ReportAnswerCitation


def question_sha256(
    report_sha256: str,
    graph_sha256: str,
    question: str,
    parent_question_sha256: str | None,
    parent_answer_sha256: str | None,
) -> str:
    if parent_question_sha256 is None and parent_answer_sha256 is None:
        parts = ("report-evidence-qa/v1", report_sha256, graph_sha256, question)
    elif parent_question_sha256 is not None and parent_answer_sha256 is not None:
        parts = (
            "report-evidence-qa/v2",
            report_sha256,
            graph_sha256,
            question,
            parent_question_sha256,
            parent_answer_sha256,
        )
    else:
        raise ValueError("parent question and answer digests must be provided together")
    canonical = "\0".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def answer_sha256(
    question_digest: str,
    answer_markdown: str,
    citations: tuple[ReportAnswerCitation, ...],
) -> str:
    citations_json = json.dumps(
        [citation.model_dump(mode="json") for citation in citations],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical = "\0".join(
        ("report-evidence-answer/v1", question_digest, answer_markdown, citations_json)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
