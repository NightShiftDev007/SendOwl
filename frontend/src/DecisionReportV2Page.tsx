import { useEffect, useState } from "react";

import {
  createDecisionReportV2MarkdownUrl,
  fetchDecisionReportV2,
  type DecisionReportV2,
  type DecisionReportV2Section,
} from "./decisionReportV2Contracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import { createWorldHash } from "./worldRoute";
import "./decisionReportV2.css";

const metricLabels = {
  observed_action_count: "观察动作",
  authored_content_count: "创作内容",
  reaction_count: "反应",
  do_nothing_count: "未采取动作",
} as const;

const sectionLabels = {
  evidence: "现实证据",
  assumptions: "合成假设",
  experiment: "实验设置",
  observation: "合成观察",
  comparison: "对比结果",
  analysis: "边界内解释",
  limitations: "限制与适用范围",
} as const;

const statusLabels = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已成功",
  failed: "失败",
} as const;

const roleLabels = {
  baseline: "基线",
  alternative: "备选方案",
} as const;

const limitationLabels = {
  sample_size: "样本规模",
  synthetic_inputs: "合成输入",
  model_dependency: "模型依赖",
  simulation_boundary: "模拟边界",
  evidence_boundary: "证据边界",
  clock_semantics: "时间语义",
  no_prediction_or_recommendation: "不预测、不推荐",
} as const;

function SectionBody({ section }: { readonly section: DecisionReportV2Section }): JSX.Element {
  const data = section.data;
  if (data.payload_kind === "evidence") {
    return (
      <>
        <dl className="decision-report-v2-ledger">
          <div><dt>WorldSnapshot</dt><dd><code>{data.world_snapshot.world_snapshot_id}</code></dd></div>
          <div><dt>Snapshot SHA-256</dt><dd><code>{data.world_snapshot.snapshot_sha256}</code></dd></div>
          <div><dt>确认方式</dt><dd>人工确认</dd></div>
        </dl>
        <ul className="decision-report-v2-list">
          {data.sources.map((source) => (
            <li key={`${source.evidence_kind}:${source.source_id}`}>
              <strong>{source.title}</strong>
              <span>{source.source_name} · {source.evidence_kind}</span>
              <span>
                发布 {source.published_at === null
                  ? source.publication_date ?? "未提供"
                  : formatMediaTimestamp(source.published_at)} ·
                捕获 {formatMediaTimestamp(source.captured_at)}
              </span>
              <code>{source.content_sha256}</code>
              <nav className="decision-report-v2-evidence-actions" aria-label={`${source.title} 证据入口`}>
                <a href={createWorldHash({
                  worldModelId: data.world_snapshot.world_model_id,
                  snapshotId: data.world_snapshot.world_snapshot_id,
                  evidenceId: null,
                })}>查看冻结副本 →</a>
                <a href={source.original_url} target="_blank" rel="noreferrer">查看原始来源 ↗</a>
              </nav>
            </li>
          ))}
        </ul>
        <p className="decision-report-v2-boundary">这些来源副本已被 SandOwl 冻结，但这不代表 SandOwl 独立核实了来源中的每一项陈述。</p>
      </>
    );
  }
  if (data.payload_kind === "assumptions") {
    return (
      <>
        <p>{data.scenario.decision_question}</p>
        <ul className="decision-report-v2-list">
          {data.scenario.variants.map((variant) => (
            <li key={variant.id}>
              <strong>{variant.name} · {roleLabels[variant.role]}</strong>
              <span>{variant.hypothesis}</span>
              {variant.interventions.map((intervention) => (
                <code key={intervention.id}>
                  {intervention.synthetic_label ?? "合成假设"} · {intervention.content}
                </code>
              ))}
            </li>
          ))}
        </ul>
        <p className="decision-report-v2-boundary">本章节中的声明与干预由 Scenario 构造，用于实验对比，不属于现实 Evidence。</p>
      </>
    );
  }
  if (data.payload_kind === "experiment") {
    return (
      <>
        <dl className="decision-report-v2-ledger">
          <div><dt>状态</dt><dd>{statusLabels[data.experiment.status]}</dd></div>
          <div><dt>Persona 人群</dt><dd>{data.experiment.persona_count} 人 · <code>{data.experiment.cohort_sha256}</code></dd></div>
          <div><dt>模型</dt><dd>{data.experiment.model_name}</dd></div>
          <div><dt>随机种子</dt><dd>{data.experiment.seeds.join(", ")}</dd></div>
        </dl>
        <ul className="decision-report-v2-list">
          {data.trials.map((trial) => (
            <li key={trial.id}>
              <strong>{trial.id} · {statusLabels[trial.status]}</strong>
              <span>方案 {trial.variant_id} · 随机种子 {trial.seed}</span>
              {trial.failure !== null ? <code>{trial.failure.code}: {trial.failure.message}</code> : null}
            </li>
          ))}
        </ul>
      </>
    );
  }
  if (data.payload_kind === "observation") {
    return (
      <>
        <ul className="decision-report-v2-list">
          {data.trials.map((trial) => (
            <li key={trial.trial_id}>
              <strong>{trial.trial_id} · {trial.event_count} 条事件</strong>
              <span>
                场景初始帖 {trial.normalized_counts.scenario_initial_posts} ·
                模拟生成帖 {trial.normalized_counts.generated_posts} · 评论 {trial.normalized_counts.comments} ·
                反应 {trial.normalized_counts.reactions} · 未动作 {trial.normalized_counts.do_nothing}
              </span>
              <code>{trial.events_sha256}</code>
              <a href={trial.event_endpoint}>查看事件 →</a>
            </li>
          ))}
        </ul>
        <p className="decision-report-v2-boundary">模拟内时间与 SandOwl 持久化时间含义不同，不能拼接成同一条现实时间线。</p>
      </>
    );
  }
  if (data.payload_kind === "comparison") {
    return (
      <div className="decision-report-v2-comparison">
        {data.metrics.map((metric) => (
          <article key={metric.metric}>
            <h4>{metricLabels[metric.metric]}</h4>
            <ul className="decision-report-v2-list">
              {metric.variants.map((variant) => (
                <li key={variant.variant_id}>
                  <strong>{variant.name} · {roleLabels[variant.role]}</strong>
                  <span>均值 {variant.mean.toFixed(2)} · 标准差 {variant.stddev.toFixed(2)} · 样本数 {variant.n}</span>
                </li>
              ))}
              {metric.alternatives.map((alternative) => (
                <li key={`${metric.metric}:${alternative.variant_id}`}>
                  <strong>{alternative.name} − 基线</strong>
                  <span>差值 Δ {alternative.mean_delta.toFixed(2)} · 配对种子 {alternative.paired_seeds.join(", ")}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    );
  }
  if (data.payload_kind === "analysis") {
    return (
      <>
        <div className="decision-report-v2-warning">解释层：不是预测、因果结论或最佳方案。</div>
        <ul className="decision-report-v2-list">
          {data.statements.map((statement) => <li key={statement.statement_id}><span>{statement.text}</span><code>{statement.basis.join(" · ")}</code></li>)}
        </ul>
      </>
    );
  }
  return (
    <ul className="decision-report-v2-list">
      {data.items.map((item) => <li key={item.code}><strong>{limitationLabels[item.code]}</strong><span>{item.text}</span><code>{item.severity === "material" ? "重要限制" : "背景限制"}</code></li>)}
    </ul>
  );
}

export function DecisionReportV2Document({ report }: { readonly report: DecisionReportV2 }): JSX.Element {
  return (
    <article className="decision-report-v2-document" aria-labelledby="decision-report-v2-title">
      <header>
        <span>已封存决策报告 / {report.generator_version}</span>
        <h2 id="decision-report-v2-title">{report.title}</h2>
        <time dateTime={report.created_at}>{formatMediaTimestamp(report.created_at)}</time>
        <dl className="decision-report-v2-ledger decision-report-v2-identity">
          <div><dt>Report ID</dt><dd><code>{report.id}</code></dd></div>
          <div><dt>Report SHA-256</dt><dd><code>{report.report_sha256}</code></dd></div>
        </dl>
      </header>
      {report.sections.map((section) => (
        <section key={section.kind} aria-labelledby={`decision-report-v2-${section.kind}`}>
          <header>
            <span>{String(section.position + 1).padStart(2, "0")}</span>
            <h3 id={`decision-report-v2-${section.kind}`}>{sectionLabels[section.kind]} <small>{section.title}</small></h3>
          </header>
          <SectionBody section={section} />
          <details className="decision-report-v2-raw">
            <summary>查看封存原文与技术明细</summary>
            <p className="decision-report-v2-markdown">{section.body_markdown}</p>
          </details>
        </section>
      ))}
      <a className="button button-secondary" href={createDecisionReportV2MarkdownUrl(report.id)} download>
        下载 V2 Markdown
      </a>
    </article>
  );
}

export function DecisionReportV2Page({ reportId }: { readonly reportId: string }): JSX.Element {
  const [report, setReport] = useState<DecisionReportV2 | null>(null);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setReport(null);
    setError(null);
    void fetchDecisionReportV2(reportId, controller.signal)
      .then(setReport)
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason : new Error("读取 DecisionReport V2 失败。"));
        }
      });
    return () => controller.abort();
  }, [reportId]);

  if (error !== null) {
    return <p role="alert">{error.message}</p>;
  }
  if (report === null) {
    return <p role="status">正在读取 sealed DecisionReport V2…</p>;
  }
  return <DecisionReportV2Document report={report} />;
}
