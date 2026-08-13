"""Strict contracts for deterministic, evidence-linked reports."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, FiniteFloat, StringConstraints, model_validator

from app.shared.contracts import ContractModel, Sha256Digest

type ReportSectionKind = Literal["scope", "comparison", "limitations", "provenance"]
type MetricName = Literal[
    "observed_action_count",
    "authored_content_count",
    "reaction_count",
    "do_nothing_count",
]
type ReportTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type ReportBody = Annotated[str, StringConstraints(min_length=1, max_length=40_000)]


class DecisionReportMetric(ContractModel):
    metric: MetricName
    alternative_id: UUID
    alternative_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    baseline_mean: FiniteFloat
    alternative_mean: FiniteFloat
    mean_delta: FiniteFloat
    stddev_delta: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]
    paired_seed_count: Annotated[int, Field(ge=1, le=2)]


class DecisionReportSection(ContractModel):
    position: Annotated[int, Field(ge=0, le=3)]
    kind: ReportSectionKind
    title: ReportTitle
    body_markdown: ReportBody
    metrics: tuple[DecisionReportMetric, ...]


class DecisionReport(ContractModel):
    id: UUID
    experiment_id: UUID
    experiment_sha256: Sha256Digest
    scenario_id: UUID
    scenario_sha256: Sha256Digest
    cohort_id: UUID
    cohort_sha256: Sha256Digest
    title: ReportTitle
    report_sha256: Sha256Digest
    generator_version: Literal["deterministic-findings/v1"]
    created_at: AwareDatetime
    sections: Annotated[tuple[DecisionReportSection, ...], Field(min_length=4, max_length=4)]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        if tuple(section.position for section in self.sections) != (0, 1, 2, 3):
            raise ValueError("report section positions must be contiguous from zero")
        if tuple(section.kind for section in self.sections) != (
            "scope",
            "comparison",
            "limitations",
            "provenance",
        ):
            raise ValueError("report sections must use the fixed findings outline")
        return self


class DecisionReportsResponse(ContractModel):
    items: tuple[DecisionReport, ...]
    total: Annotated[int, Field(ge=0)]
