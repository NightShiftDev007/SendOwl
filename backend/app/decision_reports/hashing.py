"""Deterministic report content addressing."""

import hashlib
import json

from app.decision_reports.contracts import DecisionReportSection


def serialize_report_metrics(section: DecisionReportSection) -> str:
    return json.dumps(
        [metric.model_dump(mode="json") for metric in section.metrics],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _frame(value: str) -> str:
    return f"{len(value.encode('utf-8'))}:{value}"


def calculate_report_sha256(
    experiment_sha256: str,
    scenario_sha256: str,
    cohort_sha256: str,
    title: str,
    sections: tuple[DecisionReportSection, ...],
) -> str:
    components = [
        "deterministic-findings/v1",
        experiment_sha256,
        scenario_sha256,
        cohort_sha256,
        title,
    ]
    for section in sections:
        components.extend(
            (
                str(section.position),
                section.kind,
                section.title,
                section.body_markdown,
                serialize_report_metrics(section),
            )
        )
    canonical = "".join(_frame(component) for component in components)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
