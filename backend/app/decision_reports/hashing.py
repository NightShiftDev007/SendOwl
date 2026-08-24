"""Deterministic report content addressing."""

import hashlib
import json
from uuid import UUID

from app.decision_reports.contracts import DecisionReportSection, DecisionReportV2Section


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


def serialize_report_v2_data(section: DecisionReportV2Section) -> str:
    """Serialize one typed V2 section payload into canonical JSON."""
    return json.dumps(
        section.data.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_report_v2_sha256(
    experiment_sha256: str,
    scenario_sha256: str,
    cohort_sha256: str,
    world_snapshot_id: UUID,
    world_snapshot_sha256: str,
    title: str,
    sections: tuple[DecisionReportV2Section, ...],
) -> str:
    """Calculate the immutable content address for a seven-section V2 report."""
    components = [
        "decision-report/v2",
        experiment_sha256,
        scenario_sha256,
        cohort_sha256,
        str(world_snapshot_id),
        world_snapshot_sha256,
        title,
    ]
    for section in sections:
        components.extend(
            (
                str(section.position),
                section.kind,
                section.title,
                section.body_markdown,
                serialize_report_v2_data(section),
            )
        )
    canonical = "".join(_frame(component) for component in components)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
