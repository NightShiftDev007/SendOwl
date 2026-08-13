"""Deterministic report contracts, hashing, and HTTP availability."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import load_runtime_settings
from app.decision_reports.contracts import DecisionReportMetric, DecisionReportSection
from app.decision_reports.hashing import calculate_report_sha256
from app.main import create_app


def _sections(delta: float) -> tuple[DecisionReportSection, ...]:
    return (
        DecisionReportSection(
            position=0,
            kind="scope",
            title="范围与问题",
            body_markdown="只陈述有界实验范围。",
            metrics=(),
        ),
        DecisionReportSection(
            position=1,
            kind="comparison",
            title="配对观测差异",
            body_markdown="只比较相同 seed。",
            metrics=(
                DecisionReportMetric(
                    metric="observed_action_count",
                    alternative_id=uuid4(),
                    alternative_name="透明说明",
                    baseline_mean=2.0,
                    alternative_mean=2.0 + delta,
                    mean_delta=delta,
                    stddev_delta=0.0,
                    paired_seed_count=1,
                ),
            ),
        ),
        DecisionReportSection(
            position=2,
            kind="limitations",
            title="解释限制",
            body_markdown="- 不是现实预测。",
            metrics=(),
        ),
        DecisionReportSection(
            position=3,
            kind="provenance",
            title="来源与完整性",
            body_markdown="- Experiment: `abc`",
            metrics=(),
        ),
    )


def test_report_hash_changes_with_observed_delta() -> None:
    first = calculate_report_sha256("a" * 64, "b" * 64, "c" * 64, "决策发现", _sections(1.0))
    second = calculate_report_sha256("a" * 64, "b" * 64, "c" * 64, "决策发现", _sections(2.0))

    assert first != second
    assert len(first) == 64


def test_decision_report_endpoints_return_explicit_503_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    report_id = uuid4()
    experiment_id = uuid4()

    responses = (
        client.get("/api/v2/decision-reports"),
        client.post(f"/api/v2/decision-reports/from-experiment/{experiment_id}"),
        client.get(f"/api/v2/decision-reports/{report_id}"),
        client.get(f"/api/v2/decision-reports/{report_id}/markdown"),
    )

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Decision reports are unavailable because DATABASE_URL is not configured"
        }
