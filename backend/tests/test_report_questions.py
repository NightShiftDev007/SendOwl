"""Evidence-bound report question contracts, digests, and HTTP availability."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.legacy_adc import LEGACY_ADC_WRITE_RETIRED_DETAIL
from app.main import create_app
from app.report_questions.contracts import (
    ReportAnswerCitation,
    ReportQuestion,
    ReportQuestionContext,
)
from app.report_questions.hashing import answer_sha256, question_sha256


def test_report_question_and_answer_digests_bind_evidence() -> None:
    citation = ReportAnswerCitation(
        position=0,
        article_id=uuid4(),
        quote="Exact evidence",
        start_offset=4,
        end_offset=18,
    )
    first_question = question_sha256("a" * 64, "b" * 64, "What changed?", None, None)
    second_question = question_sha256("a" * 64, "c" * 64, "What changed?", None, None)
    follow_up = question_sha256(
        "a" * 64,
        "b" * 64,
        "What about that?",
        first_question,
        "d" * 64,
    )

    assert first_question != second_question
    assert follow_up != first_question
    assert answer_sha256(first_question, "Bounded answer", (citation,)) != answer_sha256(
        first_question,
        "Different answer",
        (citation,),
    )


def test_succeeded_report_question_requires_exact_citations() -> None:
    citation = ReportAnswerCitation(
        position=0,
        article_id=uuid4(),
        quote="Exact evidence",
        start_offset=4,
        end_offset=18,
    )
    question_digest = "a" * 64

    result = ReportQuestion(
        id=uuid4(),
        report_id=uuid4(),
        report_sha256="b" * 64,
        graph_id=uuid4(),
        graph_sha256="c" * 64,
        question="What changed?",
        question_sha256=question_digest,
        model_name="qwen",
        semantic_config_sha256="d" * 64,
        prompt_schema_version="report-evidence-qa/v1",
        parent_question_id=None,
        parent_question_sha256=None,
        parent_answer_sha256=None,
        conversation_depth=0,
        status="succeeded",
        created_at=datetime.now(UTC),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        answer_markdown="Bounded answer",
        citations=(citation,),
        answer_sha256=answer_sha256(question_digest, "Bounded answer", (citation,)),
        error_code=None,
        error_message=None,
    )

    assert result.citations == (citation,)
    assert ReportQuestionContext(current_question_id=result.id, items=(result,)).items == (result,)


def test_report_question_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    report_id = uuid4()
    question_id = uuid4()

    read_responses = (
        client.get(f"/api/v2/decision-reports/{report_id}/questions"),
        client.get(f"/api/v2/report-questions/{question_id}"),
        client.get(f"/api/v2/report-questions/{question_id}/context"),
    )

    for response in read_responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Report questions are unavailable because DATABASE_URL is not configured"
        }

    write_response = client.post(
        f"/api/v2/decision-reports/{report_id}/questions",
        json={"question": "What does the evidence establish?"},
    )
    assert write_response.status_code == 410
    assert write_response.json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL}
