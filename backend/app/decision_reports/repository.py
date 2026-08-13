"""Deterministic report generation and immutable persistence."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision_reports.contracts import (
    DecisionReport,
    DecisionReportMetric,
    DecisionReportSection,
    DecisionReportsResponse,
)
from app.decision_reports.errors import DecisionReportNotFoundError, DecisionReportUnavailableError
from app.decision_reports.hashing import calculate_report_sha256, serialize_report_metrics
from app.decision_reports.models import DecisionReportRecord, DecisionReportSectionRecord
from app.semantic_experiments.contracts import (
    SemanticExperimentComparison,
    SemanticExperimentDetail,
    SemanticMetricComparison,
)
from app.semantic_experiments.repository import (
    compare_semantic_experiment,
    get_semantic_experiment,
)

METRICS_ADAPTER = TypeAdapter(tuple[DecisionReportMetric, ...])


def _metric_rows(metric: SemanticMetricComparison) -> tuple[DecisionReportMetric, ...]:
    baseline = next((variant for variant in metric.variants if variant.role == "baseline"), None)
    if baseline is None:
        return ()
    alternatives = {
        variant.id: variant for variant in metric.variants if variant.role == "alternative"
    }
    return tuple(
        DecisionReportMetric(
            metric=metric.metric,
            alternative_id=delta.alternative_id,
            alternative_name=delta.alternative_name,
            baseline_mean=baseline.mean,
            alternative_mean=alternatives[delta.alternative_id].mean,
            mean_delta=delta.mean_delta,
            stddev_delta=delta.stddev_delta,
            paired_seed_count=delta.n,
        )
        for delta in metric.paired_deltas
    )


def _comparison_markdown(comparison: SemanticExperimentComparison) -> str:
    labels = {
        "observed_action_count": "观察动作",
        "authored_content_count": "创作内容",
        "reaction_count": "反应",
        "do_nothing_count": "未采取动作",
    }
    lines = ["本章节只陈述同一 seed 下可复算的观测计数差异。"]
    for metric in comparison.metrics:
        lines.extend(("", f"### {labels[metric.metric]}"))
        if not metric.paired_deltas:
            lines.append("没有足够的成功配对 Trial，不能计算差异。")
            continue
        for delta in metric.paired_deltas:
            lines.append(
                f"- **{delta.alternative_name} − 基线**：Δ {delta.mean_delta:.2f}，"
                f"标准差 {delta.stddev_delta:.2f}，配对 seed 数 {delta.n}。"
            )
    return "\n".join(lines)


def build_report_sections(
    experiment: SemanticExperimentDetail,
    comparison: SemanticExperimentComparison,
) -> tuple[DecisionReportSection, ...]:
    metrics = tuple(row for metric in comparison.metrics for row in _metric_rows(metric))
    successful = sum(
        trial.status == "succeeded" for variant in experiment.variants for trial in variant.trials
    )
    failed = experiment.trial_count - successful
    scope = (
        f"本报告对应 **{experiment.scenario.title}**，问题为："
        f"“{experiment.scenario.decision_question}”\n\n"
        f"实验矩阵包含 {experiment.variant_count} 个方案、{len(experiment.seeds)} 个 seeds、"
        f"{experiment.trial_count} 个 Trials；其中 {successful} 个成功、{failed} 个失败。"
    )
    limitations = "\n".join(f"- {item}" for item in comparison.limitations)
    provenance = (
        f"- Scenario: `{experiment.scenario.scenario_sha256}`\n"
        f"- Cohort: `{experiment.cohort.cohort_sha256}`\n"
        f"- Dataset: `{experiment.cohort.dataset_sha256}`\n"
        f"- Experiment: `{experiment.experiment_sha256}`\n"
        f"- Model: `{experiment.model_name}`\n"
        f"- Semantic config: `{experiment.semantic_config_sha256}`\n"
        f"- Prompt schema: `{experiment.prompt_schema_version}`"
    )
    return (
        DecisionReportSection(
            position=0, kind="scope", title="范围与问题", body_markdown=scope, metrics=()
        ),
        DecisionReportSection(
            position=1,
            kind="comparison",
            title="配对观测差异",
            body_markdown=_comparison_markdown(comparison),
            metrics=metrics,
        ),
        DecisionReportSection(
            position=2,
            kind="limitations",
            title="解释限制",
            body_markdown=limitations,
            metrics=(),
        ),
        DecisionReportSection(
            position=3,
            kind="provenance",
            title="来源与完整性",
            body_markdown=provenance,
            metrics=(),
        ),
    )


def render_report_markdown(report: DecisionReport) -> str:
    lines = [f"# {report.title}", ""]
    for section in report.sections:
        lines.extend((f"## {section.title}", "", section.body_markdown, ""))
    lines.extend((f"Report SHA-256: `{report.report_sha256}`", ""))
    return "\n".join(lines)


def _project_report(
    record: DecisionReportRecord,
    section_records: tuple[DecisionReportSectionRecord, ...],
) -> DecisionReport:
    sections = tuple(
        DecisionReportSection(
            position=section.position,
            kind=section.kind,
            title=section.title,
            body_markdown=section.body_markdown,
            metrics=METRICS_ADAPTER.validate_json(section.metrics_json, strict=True),
        )
        for section in section_records
    )
    report = DecisionReport(
        id=record.id,
        experiment_id=record.experiment_id,
        experiment_sha256=record.experiment_sha256,
        scenario_id=record.scenario_id,
        scenario_sha256=record.scenario_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        title=record.title,
        report_sha256=record.report_sha256,
        generator_version=record.generator_version,
        created_at=record.created_at,
        sections=sections,
    )
    expected = calculate_report_sha256(
        report.experiment_sha256,
        report.scenario_sha256,
        report.cohort_sha256,
        report.title,
        report.sections,
    )
    if expected != report.report_sha256:
        raise RuntimeError(f"decision report {report.id} failed content integrity verification")
    return report


async def _load_report(session: AsyncSession, record: DecisionReportRecord) -> DecisionReport:
    sections = tuple(
        (
            await session.scalars(
                select(DecisionReportSectionRecord)
                .where(DecisionReportSectionRecord.report_id == record.id)
                .order_by(DecisionReportSectionRecord.position)
            )
        ).all()
    )
    return _project_report(record, sections)


async def generate_decision_report(session: AsyncSession, experiment_id: UUID) -> DecisionReport:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": str(experiment_id)},
    )
    existing = await session.scalar(
        select(DecisionReportRecord).where(DecisionReportRecord.experiment_id == experiment_id)
    )
    if existing is not None:
        return await _load_report(session, existing)
    experiment = await get_semantic_experiment(session, experiment_id)
    comparison = await compare_semantic_experiment(session, experiment_id)
    if experiment.status not in ("succeeded", "failed"):
        raise DecisionReportUnavailableError("report generation requires a terminal experiment")
    if not any(metric.paired_deltas for metric in comparison.metrics):
        raise DecisionReportUnavailableError(
            "report generation requires at least one successful baseline/alternative seed pair"
        )
    sections = build_report_sections(experiment, comparison)
    title = f"决策发现：{experiment.scenario.title}"
    report_sha256 = calculate_report_sha256(
        experiment.experiment_sha256,
        experiment.scenario.scenario_sha256,
        experiment.cohort.cohort_sha256,
        title,
        sections,
    )
    now = datetime.now(UTC)
    record = DecisionReportRecord(
        id=uuid4(),
        experiment_id=experiment.id,
        experiment_sha256=experiment.experiment_sha256,
        scenario_id=experiment.scenario.id,
        scenario_sha256=experiment.scenario.scenario_sha256,
        cohort_id=experiment.cohort.id,
        cohort_sha256=experiment.cohort.cohort_sha256,
        title=title,
        report_sha256=report_sha256,
        generator_version="deterministic-findings/v1",
        created_at=now,
        sealed_at=None,
    )
    session.add(record)
    await session.flush()
    session.add_all(
        DecisionReportSectionRecord(
            report_id=record.id,
            position=section.position,
            kind=section.kind,
            title=section.title,
            body_markdown=section.body_markdown,
            metrics_json=serialize_report_metrics(section),
        )
        for section in sections
    )
    await session.flush()
    record.sealed_at = now
    await session.commit()
    return DecisionReport(
        id=record.id,
        experiment_id=record.experiment_id,
        experiment_sha256=record.experiment_sha256,
        scenario_id=record.scenario_id,
        scenario_sha256=record.scenario_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        title=record.title,
        report_sha256=record.report_sha256,
        generator_version=record.generator_version,
        created_at=record.created_at,
        sections=sections,
    )


async def get_decision_report(session: AsyncSession, report_id: UUID) -> DecisionReport:
    record = await session.get(DecisionReportRecord, report_id)
    if record is None:
        raise DecisionReportNotFoundError(f"decision report {report_id} was not found")
    return await _load_report(session, record)


async def list_decision_reports(session: AsyncSession) -> DecisionReportsResponse:
    records = tuple(
        (
            await session.scalars(
                select(DecisionReportRecord).order_by(
                    DecisionReportRecord.created_at.desc(), DecisionReportRecord.id
                )
            )
        ).all()
    )
    reports = tuple([await _load_report(session, record) for record in records])
    return DecisionReportsResponse(items=reports, total=len(reports))
