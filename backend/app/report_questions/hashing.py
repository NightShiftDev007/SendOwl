"""Content addressing for evidence-bound report questions."""

import hashlib
import json

from app.report_questions.contracts import ReportAnswerCitation


def question_sha256(report_sha256: str, graph_sha256: str, question: str) -> str:
    canonical = "\0".join(("report-evidence-qa/v1", report_sha256, graph_sha256, question))
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
