"""Deterministic report contracts, hashing, and HTTP availability."""

import asyncio
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_runtime_settings
from app.decision_reports import repository
from app.decision_reports.contracts import (
    DecisionReportMetric,
    DecisionReportSection,
    DecisionReportV2,
    DecisionReportV2EventClockBoundary,
    DecisionReportV2NormalizedCounts,
    DecisionReportV2ObservationPayload,
    DecisionReportV2ObservationTrial,
)
from app.decision_reports.hashing import calculate_report_sha256
from app.decision_reports.models import DecisionReportRecord
from app.legacy_adc import LEGACY_ADC_WRITE_RETIRED_DETAIL
from app.main import create_app


class _FakeScalarResult:
    def __init__(self, records: tuple[DecisionReportRecord, ...]) -> None:
        self._records = records

    def all(self) -> tuple[DecisionReportRecord, ...]:
        return self._records


class _FakeSession:
    def __init__(self, records: tuple[DecisionReportRecord, ...]) -> None:
        self._records = records

    async def scalars(self, statement: object) -> _FakeScalarResult:
        del statement
        return _FakeScalarResult(self._records)


@dataclass(frozen=True)
class _FakeV2Response:
    items: tuple[DecisionReportV2, ...]
    total: int


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

    read_responses = (
        client.get("/api/v2/decision-reports"),
        client.get(f"/api/v2/decision-reports/{report_id}"),
        client.get(f"/api/v2/decision-reports/{report_id}/markdown"),
        client.get("/api/v2/decision-reports/v2"),
        client.get(f"/api/v2/decision-reports/v2/{report_id}"),
        client.get(f"/api/v2/decision-reports/v2/{report_id}/markdown"),
    )
    write_responses = (
        client.post(f"/api/v2/decision-reports/from-experiment/{experiment_id}"),
        client.post(f"/api/v2/decision-reports/v2/from-experiment/{experiment_id}"),
    )

    for response in read_responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Decision reports are unavailable because DATABASE_URL is not configured"
        }

    for response in write_responses:
        assert response.status_code == 410
        assert response.json() == {"detail": LEGACY_ADC_WRITE_RETIRED_DETAIL}


def test_v2_directory_awaits_each_report_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    records = (
        cast(DecisionReportRecord, object()),
        cast(DecisionReportRecord, object()),
    )
    projected = (
        cast(DecisionReportV2, object()),
        cast(DecisionReportV2, object()),
    )
    projected_by_record = dict(zip(map(id, records), projected, strict=True))

    async def load_report(
        session: AsyncSession,
        record: DecisionReportRecord,
    ) -> DecisionReportV2:
        del session
        return projected_by_record[id(record)]

    def build_response(
        *,
        items: tuple[DecisionReportV2, ...],
        total: int,
    ) -> _FakeV2Response:
        return _FakeV2Response(items=items, total=total)

    monkeypatch.setattr(repository, "_load_report_v2", load_report)
    monkeypatch.setattr(repository, "DecisionReportsV2Response", build_response)

    result = asyncio.run(
        repository.list_decision_reports_v2(
            cast(AsyncSession, _FakeSession(records)),
        )
    )

    assert isinstance(result, _FakeV2Response)
    assert result.items == projected
    assert result.total == 2


def test_v2_observation_text_separates_scenario_and_generated_posts() -> None:
    trial_id = uuid4()
    second_trial_id = uuid4()
    counts = DecisionReportV2NormalizedCounts(
        scenario_initial_posts=1,
        generated_posts=0,
        comments=2,
        reactions=3,
        do_nothing=0,
        observed_actions=6,
        authored_content=2,
    )
    observation = DecisionReportV2ObservationPayload(
        payload_kind="observation",
        trials=(
            DecisionReportV2ObservationTrial(
                trial_id=trial_id,
                variant_id=uuid4(),
                seed=20_260_816,
                status="succeeded",
                event_count=6,
                events_sha256="a" * 64,
                event_endpoint=f"/api/v2/semantic-trials/{trial_id}/events",
                normalized_counts=counts,
                event_clock_boundary=DecisionReportV2EventClockBoundary(
                    observed_at_raw_semantics="simulation clock",
                    recorded_at_semantics="persistence clock",
                ),
            ),
            DecisionReportV2ObservationTrial(
                trial_id=second_trial_id,
                variant_id=uuid4(),
                seed=20_260_816,
                status="succeeded",
                event_count=6,
                events_sha256="b" * 64,
                event_endpoint=f"/api/v2/semantic-trials/{second_trial_id}/events",
                normalized_counts=counts,
                event_clock_boundary=DecisionReportV2EventClockBoundary(
                    observed_at_raw_semantics="simulation clock",
                    recorded_at_semantics="persistence clock",
                ),
            ),
        ),
        behavior_changes=(repository._v2_observation_statement(trial_id, counts),),
    )

    statement = observation.behavior_changes[0].statement
    body = repository._v2_event_body(observation)

    assert "1 scenario_initial_posts" in statement
    assert "0 generated_posts" in statement
    assert "scenario_initial_posts=1" in body
    assert "generated_posts=0" in body
