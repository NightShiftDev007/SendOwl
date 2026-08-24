"""Deterministic report generation and immutable persistence."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.decision_reports.contracts import (
    DecisionReport,
    DecisionReportMetric,
    DecisionReportSection,
    DecisionReportsResponse,
    DecisionReportsV2Response,
    DecisionReportV2,
    DecisionReportV2AnalysisPayload,
    DecisionReportV2AnalysisStatement,
    DecisionReportV2AssumptionsPayload,
    DecisionReportV2ComparisonPayload,
    DecisionReportV2EventClockBoundary,
    DecisionReportV2EvidenceBoundary,
    DecisionReportV2EvidencePayload,
    DecisionReportV2EvidenceSource,
    DecisionReportV2ExperimentPayload,
    DecisionReportV2ExperimentRef,
    DecisionReportV2Intervention,
    DecisionReportV2LimitationItem,
    DecisionReportV2LimitationsPayload,
    DecisionReportV2Metric,
    DecisionReportV2MetricAlternative,
    DecisionReportV2MetricVariant,
    DecisionReportV2NormalizedCounts,
    DecisionReportV2ObservationPayload,
    DecisionReportV2ObservationStatement,
    DecisionReportV2ObservationTrial,
    DecisionReportV2PayloadUnion,
    DecisionReportV2ScenarioRef,
    DecisionReportV2Section,
    DecisionReportV2SnapshotRef,
    DecisionReportV2Trial,
    DecisionReportV2TrialFailure,
    DecisionReportV2Variant,
)
from app.decision_reports.errors import DecisionReportNotFoundError, DecisionReportUnavailableError
from app.decision_reports.hashing import (
    calculate_report_sha256,
    calculate_report_v2_sha256,
    serialize_report_metrics,
    serialize_report_v2_data,
)
from app.decision_reports.models import DecisionReportRecord, DecisionReportSectionRecord
from app.scenarios.contracts import Intervention, ScenarioDetail, ScenarioVariant
from app.scenarios.repository import get_scenario
from app.semantic_experiments.contracts import (
    SemanticExperimentComparison,
    SemanticExperimentDetail,
    SemanticMetricComparison,
    SemanticTrial,
)
from app.semantic_experiments.models import SemanticTrialEventRecord
from app.semantic_experiments.repository import (
    compare_semantic_experiment,
    get_semantic_experiment,
)
from app.world_models.contracts import SnapshotDetail
from app.world_models.models import WorldSnapshotRecord
from app.world_models.repository import get_world_snapshot

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
        select(DecisionReportRecord).where(
            DecisionReportRecord.experiment_id == experiment_id,
            DecisionReportRecord.generator_version == "deterministic-findings/v1",
        )
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
            data_json="{}",
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
                select(DecisionReportRecord)
                .where(DecisionReportRecord.generator_version == "deterministic-findings/v1")
                .order_by(DecisionReportRecord.created_at.desc(), DecisionReportRecord.id)
            )
        ).all()
    )
    reports = tuple([await _load_report(session, record) for record in records])
    return DecisionReportsResponse(items=reports, total=len(reports))


V2_PAYLOAD_ADAPTER = TypeAdapter(DecisionReportV2PayloadUnion)


def _canonical_event_json(event: SemanticTrialEventRecord) -> str:
    recorded_at = (
        event.recorded_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    return json.dumps(
        {
            "sequence": event.sequence,
            "round": event.round,
            "phase": event.phase,
            "actor_kind": event.actor_kind,
            "persona_id": None if event.persona_id is None else str(event.persona_id),
            "agent_position": event.agent_position,
            "action_type": event.action_type,
            "content": event.content,
            "post_id": event.post_id,
            "comment_id": event.comment_id,
            "target_post_id": event.target_post_id,
            "observed_at_raw": event.observed_at_raw,
            "recorded_at": recorded_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _events_sha256(events: tuple[SemanticTrialEventRecord, ...]) -> str:
    canonical = "".join(
        f"{len(value.encode('utf-8'))}:{value}"
        for value in (_canonical_event_json(event) for event in events)
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _v2_source_rows(snapshot: SnapshotDetail) -> tuple[DecisionReportV2EvidenceSource, ...]:
    media_rows = tuple(
        DecisionReportV2EvidenceSource(
            evidence_kind="media_article",
            source_id=item.article_id,
            source_name=item.source_name,
            original_url=item.original_url,
            title=item.title,
            published_at=item.published_at,
            publication_date=None,
            captured_at=item.captured_at,
            content_sha256=item.captured_text_sha256,
            identity_sha256=item.captured_text_sha256,
            excerpt=item.excerpt,
        )
        for item in snapshot.evidence
    )
    policy_rows = tuple(
        DecisionReportV2EvidenceSource(
            evidence_kind="policy_document",
            source_id=item.policy_version_id,
            source_name=item.authority_name,
            original_url=item.original_url,
            title=item.title,
            published_at=None,
            publication_date=item.publication_date,
            captured_at=item.captured_at,
            content_sha256=item.content_sha256,
            identity_sha256=item.version_sha256,
            excerpt=(
                "Policy version metadata; exact text is available through the evidence endpoint."
            ),
        )
        for item in snapshot.policy_evidence
    )
    return media_rows + policy_rows


def _v2_intervention(intervention: Intervention) -> DecisionReportV2Intervention:
    content = intervention.content
    return DecisionReportV2Intervention(
        id=intervention.id,
        kind=intervention.kind,
        actor=intervention.actor,
        channel=intervention.channel,
        content=content,
        offset_minutes=intervention.offset_minutes,
        provenance="scenario_assumption",
        synthetic_label="synthetic demo data" if "synthetic demo data" in content else None,
    )


def _v2_variant(variant: ScenarioVariant, position: int, role: str) -> DecisionReportV2Variant:
    return DecisionReportV2Variant(
        id=variant.id,
        position=position,
        role=role,
        name=variant.name,
        hypothesis=variant.hypothesis,
        interventions=tuple(_v2_intervention(item) for item in variant.interventions),
    )


def _v2_scenario_variants(
    scenario: ScenarioDetail,
    experiment: SemanticExperimentDetail,
) -> tuple[DecisionReportV2Variant, ...]:
    alternatives = {variant.id: variant for variant in scenario.alternatives}
    selected: list[DecisionReportV2Variant] = []
    for frozen in experiment.variants:
        if frozen.role == "baseline":
            selected.append(_v2_variant(scenario.baseline, frozen.position, "baseline"))
            continue
        variant = alternatives.get(frozen.id)
        if variant is None:
            raise RuntimeError(
                f"Scenario alternative {frozen.id} is missing from its sealed parent"
            )
        selected.append(_v2_variant(variant, frozen.position, "alternative"))
    return tuple(selected)


def _v2_trial_failure(trial: SemanticTrial) -> DecisionReportV2TrialFailure | None:
    if trial.error is None:
        return None
    return DecisionReportV2TrialFailure(code=trial.error.code, message=trial.error.message)


def _v2_trial(
    trial: SemanticTrial,
    variant_id: UUID,
    role: str,
) -> DecisionReportV2Trial:
    artifact_sha256 = None if trial.result is None else trial.result.artifact_sha256
    rounds_completed = None if trial.result is None else trial.result.rounds_completed
    return DecisionReportV2Trial(
        id=trial.id,
        variant_id=variant_id,
        role=role,
        seed=trial.seed,
        trial_sha256=trial.trial_sha256,
        status=trial.status,
        created_at=trial.created_at,
        started_at=trial.started_at,
        completed_at=trial.completed_at,
        artifact_sha256=artifact_sha256,
        rounds_completed=rounds_completed,
        failure=_v2_trial_failure(trial),
    )


def _v2_counts(events: tuple[SemanticTrialEventRecord, ...]) -> DecisionReportV2NormalizedCounts:
    scenario_initial_posts = sum(
        event.phase == "intervention" and event.action_type == "create_post" for event in events
    )
    generated_posts = sum(
        event.phase == "audience" and event.action_type == "create_post" for event in events
    )
    comments = sum(event.action_type == "create_comment" for event in events)
    reactions = sum(event.action_type in ("like_post", "dislike_post") for event in events)
    do_nothing = sum(event.action_type == "do_nothing" for event in events)
    return DecisionReportV2NormalizedCounts(
        scenario_initial_posts=scenario_initial_posts,
        generated_posts=generated_posts,
        comments=comments,
        reactions=reactions,
        do_nothing=do_nothing,
        observed_actions=len(events),
        authored_content=generated_posts + comments,
    )


def _v2_observation_statement(
    trial_id: UUID,
    counts: DecisionReportV2NormalizedCounts,
) -> DecisionReportV2ObservationStatement:
    return DecisionReportV2ObservationStatement(
        statement=(
            f"Trial {trial_id} persisted {counts.observed_actions} normalized events: "
            f"{counts.scenario_initial_posts} scenario_initial_posts, "
            f"{counts.generated_posts} generated_posts, {counts.comments} create_comment, "
            f"{counts.reactions} reactions, and {counts.do_nothing} do_nothing."
        ),
        basis=(f"observation:trial:{trial_id}",),
    )


def _v2_metric(
    comparison_metric: SemanticMetricComparison,
    experiment: SemanticExperimentDetail,
) -> DecisionReportV2Metric:
    variants = tuple(
        DecisionReportV2MetricVariant(
            variant_id=variant.id,
            name=variant.name,
            role=variant.role,
            mean=variant.mean,
            stddev=variant.stddev,
            n=variant.n,
        )
        for variant in comparison_metric.variants
    )
    baseline_trials = {
        trial.seed
        for variant in experiment.variants
        if variant.position == 0
        for trial in variant.trials
        if trial.status == "succeeded"
    }
    alternative_rows: list[DecisionReportV2MetricAlternative] = []
    variant_by_id = {variant.id: variant for variant in comparison_metric.variants}
    for delta in comparison_metric.paired_deltas:
        alternative = next(
            variant for variant in experiment.variants if variant.id == delta.alternative_id
        )
        alternative_seeds = {
            trial.seed for trial in alternative.trials if trial.status == "succeeded"
        }
        paired_seeds = tuple(sorted(baseline_trials & alternative_seeds))
        observation = variant_by_id[delta.alternative_id]
        alternative_rows.append(
            DecisionReportV2MetricAlternative(
                variant_id=delta.alternative_id,
                name=delta.alternative_name,
                mean=observation.mean,
                stddev=observation.stddev,
                n=observation.n,
                mean_delta=delta.mean_delta,
                stddev_delta=delta.stddev_delta,
                paired_seeds=paired_seeds,
                paired_seed_count=len(paired_seeds),
            )
        )
    return DecisionReportV2Metric(
        metric=comparison_metric.metric,
        variants=variants,
        alternatives=tuple(alternative_rows),
    )


async def _v2_events_by_trial(
    session: AsyncSession,
    experiment: SemanticExperimentDetail,
) -> dict[UUID, tuple[SemanticTrialEventRecord, ...]]:
    trial_ids = tuple(trial.id for variant in experiment.variants for trial in variant.trials)
    if not trial_ids:
        return {}
    rows = tuple(
        (
            await session.scalars(
                select(SemanticTrialEventRecord)
                .where(SemanticTrialEventRecord.trial_id.in_(trial_ids))
                .order_by(SemanticTrialEventRecord.trial_id, SemanticTrialEventRecord.sequence)
            )
        ).all()
    )
    grouped: dict[UUID, list[SemanticTrialEventRecord]] = {trial_id: [] for trial_id in trial_ids}
    for row in rows:
        grouped[row.trial_id].append(row)
    return {trial_id: tuple(events) for trial_id, events in grouped.items()}


def _v2_comparison_body(comparison: DecisionReportV2ComparisonPayload) -> str:
    labels = {
        "observed_action_count": "观察动作",
        "authored_content_count": "创作内容",
        "reaction_count": "反应",
        "do_nothing_count": "未采取动作",
    }
    lines = ["本章节只陈述成功 trial 的同 seed 配对观测差异，不构成预测或方案推荐。"]
    for metric in comparison.metrics:
        lines.extend(("", f"### {labels[metric.metric]}"))
        for alternative in metric.alternatives:
            seeds = ", ".join(str(seed) for seed in alternative.paired_seeds)
            lines.append(
                f"- **{alternative.name} − 基线**：基线/备选均值 "
                f"{next(item.mean for item in metric.variants if item.role == 'baseline'):.2f} / "
                f"{alternative.mean:.2f}，Δ {alternative.mean_delta:.2f}，"
                f"配对 seeds [{seeds}]。"
            )
        if not metric.alternatives:
            lines.append("- 没有足够的成功配对 Trial，不能计算差异。")
    return "\n".join(lines)


def _v2_event_body(observation: DecisionReportV2ObservationPayload) -> str:
    lines = ["本章节只描述持久化的 normalized events、计数和事件时钟，不推断立场或现实影响。"]
    for trial in observation.trials:
        counts = trial.normalized_counts
        lines.append(
            f"- Trial `{trial.trial_id}`：{trial.event_count} events；"
            f"scenario_initial_posts={counts.scenario_initial_posts}、"
            f"generated_posts={counts.generated_posts}、create_comment={counts.comments}、"
            f"reaction={counts.reactions}、do_nothing={counts.do_nothing}；"
            f"events SHA-256 `{trial.events_sha256}`。"
        )
    return "\n".join(lines)


def _v2_assumptions_body(assumptions: DecisionReportV2AssumptionsPayload) -> str:
    lines = [
        f"Scenario **{assumptions.scenario.title}** 绑定 snapshot "
        f"`{assumptions.scenario.snapshot_sha256}`。以下内容是实验假设，不是 Evidence。"
    ]
    for variant in assumptions.scenario.variants:
        lines.append(f"- **{variant.name}**（{variant.role}）：{variant.hypothesis}")
        for intervention in variant.interventions:
            label = intervention.synthetic_label or "未声明 synthetic 标签"
            lines.append(
                f"  - intervention `{intervention.id}`，offset {intervention.offset_minutes} min，"
                f"provenance `{intervention.provenance}`，label `{label}`。"
            )
    return "\n".join(lines)


def _v2_evidence_body(evidence: DecisionReportV2EvidencePayload) -> str:
    snapshot = evidence.world_snapshot
    lines = [
        f"WorldSnapshot `{snapshot.world_snapshot_id}` version {snapshot.version} 已封存，"
        f"snapshot SHA-256 `{snapshot.snapshot_sha256}`，verification `{snapshot.verification}`。"
    ]
    for source in evidence.sources:
        published = source.published_at or source.publication_date or "未提供"
        lines.append(
            f"- `{source.evidence_kind}` `{source.source_id}`：{source.source_name} / "
            f"{source.title}；published {published}；captured {source.captured_at}；"
            f"content SHA-256 `{source.content_sha256}`。"
        )
    lines.extend(f"- 边界：{statement}" for statement in evidence.evidence_boundary.statements)
    return "\n".join(lines)


def _v2_experiment_body(experiment: DecisionReportV2ExperimentPayload) -> str:
    item = experiment.experiment
    lines = [
        f"Experiment `{item.id}`（`{item.experiment_sha256}`）状态 `{item.status}`；"
        f"Cohort `{item.cohort_id}`，{item.persona_count} personas；"
        f"seeds [{', '.join(str(seed) for seed in item.seeds)}]，"
        f"rounds={item.rounds}，minutes_per_round={item.minutes_per_round}。",
        f"Model `{item.model_name}`，config `{item.semantic_config_sha256}`，"
        f"prompt `{item.prompt_schema_version}`。",
    ]
    for trial in experiment.trials:
        status = trial.status
        detail = ""
        if trial.failure is not None:
            detail = f"；failure `{trial.failure.code}`：{trial.failure.message}"
        lines.append(
            f"- Trial `{trial.id}` variant `{trial.variant_id}` seed {trial.seed} "
            f"`{status}`{detail}"
        )
    return "\n".join(lines)


def _v2_analysis_body(analysis: DecisionReportV2AnalysisPayload) -> str:
    lines = ["以下仅解释 Evidence、Assumptions、Experiment、Observation 和 Comparison 中已有事实。"]
    lines.extend(f"- {statement.text}" for statement in analysis.statements)
    lines.append("- 禁止：未来预测、因果结论、总体比例、最佳方案或决策推荐。")
    return "\n".join(lines)


def _v2_limitations_body(limitations: DecisionReportV2LimitationsPayload) -> str:
    return "\n".join(f"- `{item.code}`：{item.text}" for item in limitations.items)


def _v2_section_data_json(section: DecisionReportV2Section) -> str:
    return serialize_report_v2_data(section)


async def build_report_v2_sections(
    session: AsyncSession,
    experiment: SemanticExperimentDetail,
    comparison: SemanticExperimentComparison,
    scenario: ScenarioDetail,
    snapshot: SnapshotDetail,
    snapshot_sealed_at: datetime,
) -> tuple[DecisionReportV2Section, ...]:
    variants = _v2_scenario_variants(scenario, experiment)
    if scenario.snapshot.snapshot_sha256 != snapshot.snapshot_sha256:
        raise RuntimeError("Scenario snapshot identity does not match the loaded WorldSnapshot")
    snapshot_ref = DecisionReportV2SnapshotRef(
        world_model_id=snapshot.world_model_id,
        world_snapshot_id=snapshot.id,
        version=snapshot.version,
        snapshot_sha256=snapshot.snapshot_sha256,
        created_at=snapshot.created_at,
        sealed_at=snapshot_sealed_at,
        verification=snapshot.verification,
    )
    evidence = DecisionReportV2EvidencePayload(
        payload_kind="evidence",
        world_snapshot=snapshot_ref,
        sources=_v2_source_rows(snapshot),
        evidence_boundary=DecisionReportV2EvidenceBoundary(
            status="frozen_source_copy_not_independent_fact_check",
            statements=(
                "Evidence proves that these source copies existed in SandOwl and were frozen.",
                "Frozen media or Policy text is not an independent fact check "
                "of every source claim.",
            ),
        ),
    )
    scenario_ref = DecisionReportV2ScenarioRef(
        id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        title=scenario.title,
        decision_question=scenario.decision_question,
        world_snapshot_id=scenario.snapshot.world_snapshot_id,
        snapshot_sha256=scenario.snapshot.snapshot_sha256,
        variants=variants,
    )
    assumptions = DecisionReportV2AssumptionsPayload(
        payload_kind="assumptions",
        scenario=scenario_ref,
        assumption_boundary=(
            "Scenario interventions are experiment assumptions, not AgendaScope evidence.",
            "synthetic demo data labels are preserved when present in the intervention text.",
        ),
    )
    runtime_pairs = {
        (trial.result.engine_version, trial.result.camel_version)
        for variant in experiment.variants
        for trial in variant.trials
        if trial.result is not None
    }
    engine_version = next(iter(runtime_pairs))[0] if len(runtime_pairs) == 1 else None
    camel_version = next(iter(runtime_pairs))[1] if len(runtime_pairs) == 1 else None
    experiment_ref = DecisionReportV2ExperimentRef(
        id=experiment.id,
        experiment_sha256=experiment.experiment_sha256,
        status=experiment.status,
        scenario_id=experiment.scenario.id,
        scenario_sha256=experiment.scenario.scenario_sha256,
        cohort_id=experiment.cohort.id,
        cohort_sha256=experiment.cohort.cohort_sha256,
        dataset_sha256=experiment.cohort.dataset_sha256,
        persona_count=experiment.cohort.persona_count,
        variants=variants,
        seeds=experiment.seeds,
        rounds=experiment.rounds,
        minutes_per_round=experiment.minutes_per_round,
        model_name=experiment.model_name,
        semantic_config_sha256=experiment.semantic_config_sha256,
        prompt_schema_version=experiment.prompt_schema_version,
        engine_version=engine_version,
        camel_version=camel_version,
    )
    trial_rows = tuple(
        _v2_trial(trial, variant.id, variant.role)
        for variant in experiment.variants
        for trial in variant.trials
    )
    experiment_payload = DecisionReportV2ExperimentPayload(
        payload_kind="experiment",
        experiment=experiment_ref,
        trials=trial_rows,
    )
    events_by_trial = await _v2_events_by_trial(session, experiment)
    observation_trials: list[DecisionReportV2ObservationTrial] = []
    observation_statements: list[DecisionReportV2ObservationStatement] = []
    for variant in experiment.variants:
        for trial in variant.trials:
            events = events_by_trial.get(trial.id, ())
            counts = _v2_counts(events)
            observation_trials.append(
                DecisionReportV2ObservationTrial(
                    trial_id=trial.id,
                    variant_id=variant.id,
                    seed=trial.seed,
                    status=trial.status,
                    event_count=len(events),
                    events_sha256=_events_sha256(events),
                    event_endpoint=f"/api/v2/semantic-trials/{trial.id}/events",
                    normalized_counts=counts,
                    event_clock_boundary=DecisionReportV2EventClockBoundary(
                        observed_at_raw_semantics=(
                            "OASIS simulation clock string; not a SandOwl wall-clock timestamp."
                        ),
                        recorded_at_semantics=(
                            "SandOwl persistence timestamp for the normalized event."
                        ),
                    ),
                )
            )
            observation_statements.append(_v2_observation_statement(trial.id, counts))
    observation = DecisionReportV2ObservationPayload(
        payload_kind="observation",
        trials=tuple(observation_trials),
        behavior_changes=tuple(observation_statements),
    )
    comparison_payload = DecisionReportV2ComparisonPayload(
        payload_kind="comparison",
        metrics=tuple(_v2_metric(metric, experiment) for metric in comparison.metrics),
        comparison_state=comparison.state,
        pairing_rule="successful baseline/alternative trials with the same recorded seed",
        comparison_boundary=comparison.limitations,
    )
    analysis_statements = [
        DecisionReportV2AnalysisStatement(
            statement_id="scope_explanation",
            text=(
                "Comparison describes this bounded experiment's normalized actions; "
                "it is not a population estimate."
            ),
            basis=("experiment:config", "comparison:metrics"),
            allowed_type="scope_explanation",
        ),
        DecisionReportV2AnalysisStatement(
            statement_id="event_accounting",
            text=(
                "Alternative observed-action totals include any scenario intervention "
                "events defined in Assumptions."
            ),
            basis=("assumptions:variants", "observation:trials"),
            allowed_type="accounting_explanation",
        ),
        DecisionReportV2AnalysisStatement(
            statement_id="seed_boundary",
            text=(
                "Paired deltas describe only successful trials sharing the recorded seed; "
                "they do not establish stability outside this experiment."
            ),
            basis=("experiment:trials", "comparison:pairing"),
            allowed_type="boundary_explanation",
        ),
    ]
    analysis = DecisionReportV2AnalysisPayload(
        payload_kind="analysis",
        statements=tuple(analysis_statements),
        prohibited_claims=(
            "future prediction",
            "causal claim",
            "best option",
            "population estimate",
        ),
    )
    successful = sum(
        trial.status == "succeeded" for variant in experiment.variants for trial in variant.trials
    )
    failed = experiment.trial_count - successful
    limitations = DecisionReportV2LimitationsPayload(
        payload_kind="limitations",
        items=(
            DecisionReportV2LimitationItem(
                code="sample_size",
                text=(
                    f"The cohort has {experiment.cohort.persona_count} personas and the matrix has "
                    f"{len(experiment.seeds)} seed(s), {experiment.trial_count} trial(s) "
                    f"({successful} succeeded, {failed} failed); this is not a population estimate."
                ),
                severity="material",
            ),
            DecisionReportV2LimitationItem(
                code="synthetic_inputs",
                text=(
                    "Scenario interventions are assumptions and are not AgendaScope evidence; "
                    "explicit synthetic labels are preserved."
                ),
                severity="material",
            ),
            DecisionReportV2LimitationItem(
                code="model_dependency",
                text=(
                    f"Observed behavior depends on model {experiment.model_name}, its config "
                    "digest, and provider execution."
                ),
                severity="material",
            ),
            DecisionReportV2LimitationItem(
                code="simulation_boundary",
                text=(
                    "OASIS events are bounded synthetic observations; the comparison does not "
                    "infer stance, reach, persuasion, business impact, or a verdict."
                ),
                severity="material",
            ),
            DecisionReportV2LimitationItem(
                code="evidence_boundary",
                text=(
                    "Frozen source copies are traceable inputs, not independent fact checks "
                    "of every source claim."
                ),
                severity="context",
            ),
            DecisionReportV2LimitationItem(
                code="clock_semantics",
                text=(
                    "OASIS observed_at_raw and SandOwl recorded_at use different clock "
                    "semantics and must not be compared as one timeline."
                ),
                severity="context",
            ),
            DecisionReportV2LimitationItem(
                code="no_prediction_or_recommendation",
                text=(
                    "This report does not predict the future, make a deterministic "
                    "conclusion, or select a best option."
                ),
                severity="material",
            ),
        ),
    )
    sections = (
        DecisionReportV2Section(
            position=0,
            kind="evidence",
            title="Evidence",
            body_markdown=_v2_evidence_body(evidence),
            data=evidence,
        ),
        DecisionReportV2Section(
            position=1,
            kind="assumptions",
            title="Assumptions",
            body_markdown=_v2_assumptions_body(assumptions),
            data=assumptions,
        ),
        DecisionReportV2Section(
            position=2,
            kind="experiment",
            title="Experiment",
            body_markdown=_v2_experiment_body(experiment_payload),
            data=experiment_payload,
        ),
        DecisionReportV2Section(
            position=3,
            kind="observation",
            title="Observation",
            body_markdown=_v2_event_body(observation),
            data=observation,
        ),
        DecisionReportV2Section(
            position=4,
            kind="comparison",
            title="Comparison",
            body_markdown=_v2_comparison_body(comparison_payload),
            data=comparison_payload,
        ),
        DecisionReportV2Section(
            position=5,
            kind="analysis",
            title="Analysis",
            body_markdown=_v2_analysis_body(analysis),
            data=analysis,
        ),
        DecisionReportV2Section(
            position=6,
            kind="limitations",
            title="Limitations",
            body_markdown=_v2_limitations_body(limitations),
            data=limitations,
        ),
    )
    return sections


def _project_report_v2(
    record: DecisionReportRecord,
    section_records: tuple[DecisionReportSectionRecord, ...],
) -> DecisionReportV2:
    if record.world_snapshot_id is None or record.world_snapshot_sha256 is None:
        raise RuntimeError(f"V2 decision report {record.id} has no WorldSnapshot identity")
    sections = tuple(
        DecisionReportV2Section(
            position=section.position,
            kind=section.kind,
            title=section.title,
            body_markdown=section.body_markdown,
            data=V2_PAYLOAD_ADAPTER.validate_json(section.data_json, strict=True),
        )
        for section in section_records
    )
    report = DecisionReportV2(
        id=record.id,
        experiment_id=record.experiment_id,
        experiment_sha256=record.experiment_sha256,
        scenario_id=record.scenario_id,
        scenario_sha256=record.scenario_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        world_snapshot_id=record.world_snapshot_id,
        world_snapshot_sha256=record.world_snapshot_sha256,
        title=record.title,
        report_sha256=record.report_sha256,
        generator_version="decision-report/v2",
        created_at=record.created_at,
        sections=sections,
    )
    expected = calculate_report_v2_sha256(
        report.experiment_sha256,
        report.scenario_sha256,
        report.cohort_sha256,
        report.world_snapshot_id,
        report.world_snapshot_sha256,
        report.title,
        report.sections,
    )
    if expected != report.report_sha256:
        raise RuntimeError(f"decision report {record.id} failed V2 content integrity verification")
    return report


async def _load_report_v2(
    session: AsyncSession,
    record: DecisionReportRecord,
) -> DecisionReportV2:
    sections = tuple(
        (
            await session.scalars(
                select(DecisionReportSectionRecord)
                .where(DecisionReportSectionRecord.report_id == record.id)
                .order_by(DecisionReportSectionRecord.position)
            )
        ).all()
    )
    return _project_report_v2(record, sections)


async def generate_decision_report_v2(
    session: AsyncSession,
    experiment_id: UUID,
) -> DecisionReportV2:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:identity, 0))"),
        {"identity": f"{experiment_id}:decision-report/v2"},
    )
    existing = await session.scalar(
        select(DecisionReportRecord).where(
            DecisionReportRecord.experiment_id == experiment_id,
            DecisionReportRecord.generator_version == "decision-report/v2",
        )
    )
    if existing is not None:
        return await _load_report_v2(session, existing)
    experiment = await get_semantic_experiment(session, experiment_id)
    comparison = await compare_semantic_experiment(session, experiment_id)
    if experiment.status not in ("succeeded", "failed"):
        raise DecisionReportUnavailableError("V2 report generation requires a terminal experiment")
    if not any(metric.paired_deltas for metric in comparison.metrics):
        raise DecisionReportUnavailableError(
            "V2 report generation requires at least one successful baseline/alternative seed pair"
        )
    scenario = await get_scenario(session, experiment.scenario.id)
    snapshot = await get_world_snapshot(
        session,
        scenario.snapshot.world_model_id,
        scenario.snapshot.world_snapshot_id,
    )
    snapshot_record = await session.scalar(
        select(WorldSnapshotRecord).where(WorldSnapshotRecord.id == snapshot.id)
    )
    if snapshot_record is None or snapshot_record.sealed_at is None:
        raise DecisionReportUnavailableError(
            f"V2 report requires a sealed WorldSnapshot for scenario {scenario.id}"
        )
    sections = await build_report_v2_sections(
        session,
        experiment,
        comparison,
        scenario,
        snapshot,
        snapshot_record.sealed_at,
    )
    title = f"决策报告 V2：{experiment.scenario.title}"
    report_sha256 = calculate_report_v2_sha256(
        experiment.experiment_sha256,
        experiment.scenario.scenario_sha256,
        experiment.cohort.cohort_sha256,
        snapshot.id,
        snapshot.snapshot_sha256,
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
        world_snapshot_id=snapshot.id,
        world_snapshot_sha256=snapshot.snapshot_sha256,
        title=title,
        report_sha256=report_sha256,
        generator_version="decision-report/v2",
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
            metrics_json="[]",
            data_json=_v2_section_data_json(section),
        )
        for section in sections
    )
    await session.flush()
    record.sealed_at = now
    await session.commit()
    return DecisionReportV2(
        id=record.id,
        experiment_id=record.experiment_id,
        experiment_sha256=record.experiment_sha256,
        scenario_id=record.scenario_id,
        scenario_sha256=record.scenario_sha256,
        cohort_id=record.cohort_id,
        cohort_sha256=record.cohort_sha256,
        world_snapshot_id=record.world_snapshot_id,
        world_snapshot_sha256=record.world_snapshot_sha256,
        title=record.title,
        report_sha256=record.report_sha256,
        generator_version="decision-report/v2",
        created_at=record.created_at,
        sections=sections,
    )


async def get_decision_report_v2(
    session: AsyncSession,
    report_id: UUID,
) -> DecisionReportV2:
    record = await session.scalar(
        select(DecisionReportRecord).where(
            DecisionReportRecord.id == report_id,
            DecisionReportRecord.generator_version == "decision-report/v2",
        )
    )
    if record is None:
        raise DecisionReportNotFoundError(f"V2 decision report {report_id} was not found")
    return await _load_report_v2(session, record)


async def list_decision_reports_v2(session: AsyncSession) -> DecisionReportsV2Response:
    records = tuple(
        (
            await session.scalars(
                select(DecisionReportRecord)
                .where(DecisionReportRecord.generator_version == "decision-report/v2")
                .order_by(DecisionReportRecord.created_at.desc(), DecisionReportRecord.id)
            )
        ).all()
    )
    reports: list[DecisionReportV2] = []
    for record in records:
        reports.append(await _load_report_v2(session, record))
    return DecisionReportsV2Response(items=tuple(reports), total=len(reports))


def render_report_v2_markdown(report: DecisionReportV2) -> str:
    lines = [f"# {report.title}", "", "Report version: `decision-report/v2`", ""]
    for section in report.sections:
        lines.extend((f"## {section.title}", "", section.body_markdown, ""))
    lines.extend((f"Report SHA-256: `{report.report_sha256}`", ""))
    return "\n".join(lines)
