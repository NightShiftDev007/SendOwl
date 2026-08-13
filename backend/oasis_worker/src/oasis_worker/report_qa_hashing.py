"""Worker-side answer digest matching the control plane."""

import hashlib
import json

from oasis_worker.report_qa_contracts import ReportQACandidate


def question_sha256(report_sha256: str, graph_sha256: str, question: str) -> str:
    canonical = "\0".join(("report-evidence-qa/v1", report_sha256, graph_sha256, question))
    return hashlib.sha256(canonical.encode()).hexdigest()


def answer_sha256(
    question_sha256: str,
    answer_markdown: str,
    citations: tuple[ReportQACandidate, ...],
) -> str:
    citations_json = json.dumps(
        [
            {
                "position": citation.position,
                "article_id": str(citation.article_id),
                "quote": citation.quote,
                "start_offset": citation.start_offset,
                "end_offset": citation.end_offset,
            }
            for citation in citations
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical = "\0".join(
        ("report-evidence-answer/v1", question_sha256, answer_markdown, citations_json)
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
