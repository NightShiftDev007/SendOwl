"""Strict worker-side evidence answer normalization."""

from uuid import uuid4

from oasis_worker.report_qa_contracts import ExtractedReportAnswer, ReportQACandidate
from oasis_worker.report_qa_hashing import answer_sha256, question_sha256


def test_report_question_digest_matches_frozen_inputs() -> None:
    assert question_sha256("a" * 64, "b" * 64, "What changed?") == (
        "1c2200fa77f9d0f51f16317c3d29a5ff464818b96af9659f1c8e9670ff678776"
    )


def test_report_answer_digest_changes_with_exact_quote() -> None:
    article_id = uuid4()
    first = ReportQACandidate(
        position=0,
        article_id=article_id,
        object_label="Observed object",
        quote="Exact evidence",
        start_offset=4,
        end_offset=18,
    )
    second = first.model_copy(update={"quote": "Other evidence", "end_offset": 18})

    assert answer_sha256("a" * 64, "Bounded answer", (first,)) != answer_sha256(
        "a" * 64,
        "Bounded answer",
        (second,),
    )


def test_report_answer_normalizes_unique_citation_positions() -> None:
    extracted = ExtractedReportAnswer(
        answer_markdown="Bounded answer",
        citation_positions=(3, 1),
    )

    assert extracted.citation_positions == (1, 3)
