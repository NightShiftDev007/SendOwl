import { useEffect, useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { DecisionReportV2Document } from "./DecisionReportV2Page";
import {
  createDecisionReportV2MarkdownUrl,
  type DecisionReportV2,
} from "./decisionReportV2Contracts";
import {
  createDecisionReportMarkdownUrl,
  type DecisionReport,
  type DecisionReportMetric,
} from "./decisionReportContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import { createRunStudioHash } from "./runStudioRoute";
import {
  type ReportQuestion,
} from "./reportQuestionContracts";
import type {
  SemanticExperimentComparison,
  SemanticExperimentDetail,
  SemanticExperimentSummary,
} from "./semanticExperimentContracts";
import {
  useSemanticComparison,
  useSemanticExperimentDetail,
  useSemanticExperiments,
} from "./useSemanticExperiments";
import { useDecisionReports } from "./useDecisionReports";
import { useDecisionReportsV2 } from "./useDecisionReportsV2";
import { useReportQuestions } from "./useReportQuestions";
import "./decisionReports.css";

const metricLabels = {
  observed_action_count: "观察动作",
  authored_content_count: "创作内容",
  reaction_count: "反应",
  do_nothing_count: "未采取动作",
} as const;

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 10)}…${digest.slice(-8)}`;
}

function isTerminal(experiment: SemanticExperimentSummary): boolean {
  return experiment.status === "succeeded" || experiment.status === "failed";
}

function ReportDirectory({
  items,
  reportsByExperiment,
  selectedId,
  onSelect,
}: {
  readonly items: readonly SemanticExperimentSummary[];
  readonly reportsByExperiment: ReadonlyMap<string, DecisionReport>;
  readonly selectedId: string | null;
  readonly onSelect: (experimentId: string) => void;
}): JSX.Element {
  if (items.length === 0) {
    return (
      <div className="decision-report-empty">
        <strong>还没有可核验的终态实验</strong>
        <p>先在 Playground 完成一组基线与备选方案 Trial。</p>
      </div>
    );
  }

  return (
    <ul className="decision-report-directory-list">
      {items.map((item) => (
        <li key={item.id}>
          <button
            type="button"
            data-selected={item.id === selectedId}
            aria-pressed={item.id === selectedId}
            onClick={() => onSelect(item.id)}
          >
            <span data-status={item.status}>
              {reportsByExperiment.has(item.id)
                ? "已封存"
                : item.status === "succeeded" ? "未封存" : "运行未完成"}
            </span>
            <strong>{item.scenario.title}</strong>
            <small>{item.cohort.title} · {item.trial_count} Trials</small>
            <time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time>
            <code>{abbreviatedDigest(item.experiment_sha256)}</code>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ReportMetricLedger({ metrics }: { readonly metrics: readonly DecisionReportMetric[] }): JSX.Element | null {
  if (metrics.length === 0) {
    return null;
  }
  return (
    <div className="decision-report-ledger" aria-label="配对观测计数">
      {metrics.map((metric) => (
        <article key={`${metric.metric}:${metric.alternative_id}`}>
          <span>{metricLabels[metric.metric]}</span>
          <strong>{metric.alternative_name}</strong>
          <dl>
            <div><dt>基线</dt><dd>{metric.baseline_mean.toFixed(2)}</dd></div>
            <div><dt>备选</dt><dd>{metric.alternative_mean.toFixed(2)}</dd></div>
            <div><dt>配对差异</dt><dd>{metric.mean_delta >= 0 ? "+" : ""}{metric.mean_delta.toFixed(2)}</dd></div>
            <div><dt>样本</dt><dd>{metric.paired_seed_count} seeds</dd></div>
          </dl>
        </article>
      ))}
    </div>
  );
}

function renderInlineReportText(value: string): readonly (string | JSX.Element)[] {
  return value.split(/(\*\*[^*]+\*\*|`[^`]+`)/u).filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}

function ReportMarkdown({ value }: { readonly value: string }): JSX.Element {
  return (
    <div className="decision-report-markdown">
      {value.split("\n").map((line, index) => {
        if (line.length === 0) {
          return <span key={index} className="decision-report-paragraph-gap" aria-hidden="true" />;
        }
        if (line.startsWith("### ")) {
          return <h4 key={index}>{renderInlineReportText(line.slice(4))}</h4>;
        }
        if (line.startsWith("- ")) {
          return <div key={index} className="decision-report-bullet">{renderInlineReportText(line.slice(2))}</div>;
        }
        return <p key={index}>{renderInlineReportText(line)}</p>;
      })}
    </div>
  );
}

function PersistedReportDocument({ report }: { readonly report: DecisionReport }): JSX.Element {
  return (
    <article className="decision-report-document decision-report-findings" aria-labelledby="decision-report-title">
      <header>
        <span>SEALED FINDINGS / {report.generator_version}</span>
        <h3 id="decision-report-title">{report.title}</h3>
        <time dateTime={report.created_at}>{formatMediaTimestamp(report.created_at)}</time>
        <code>{report.report_sha256}</code>
      </header>
      <div className="decision-report-chapters">
        {report.sections.map((section) => (
          <section key={section.kind} id={`report-section-${section.kind}`}>
            <header>
              <span>{String(section.position + 1).padStart(2, "0")}</span>
              <h3>{section.title}</h3>
            </header>
            <ReportMarkdown value={section.body_markdown} />
            <ReportMetricLedger metrics={section.metrics} />
          </section>
        ))}
      </div>
    </article>
  );
}

function ComparisonBoard({
  comparison,
}: {
  readonly comparison: SemanticExperimentComparison;
}): JSX.Element {
  return (
    <section className="decision-report-comparison" aria-labelledby="report-comparison-title">
      <header>
        <div>
          <span>OBSERVED / PAIRED BY SEED</span>
          <h3 id="report-comparison-title">基线与备选的可复算计数</h3>
        </div>
        <strong data-state={comparison.state}>{comparison.state}</strong>
      </header>
      <div className="decision-report-metric-grid">
        {comparison.metrics.map((metric) => (
          <article key={metric.metric}>
            <header>
              <span>{metricLabels[metric.metric]}</span>
              <small>{metric.variants.length === 0 ? "无成功样本" : `${metric.variants.length} 个实验臂`}</small>
            </header>
            {metric.variants.length === 0 ? (
              <p>该指标没有足够的成功 Trial，不能计算差异。</p>
            ) : (
              <ol>
                {metric.variants.map((variant) => (
                  <li key={variant.id} data-role={variant.role}>
                    <span>{variant.role === "baseline" ? "基线" : `备选 ${variant.position}`}</span>
                    <strong>{variant.name}</strong>
                    <code>mean {variant.mean.toFixed(2)} · std {variant.stddev.toFixed(2)} · n {variant.n}</code>
                  </li>
                ))}
              </ol>
            )}
            {metric.paired_deltas.length > 0 ? (
              <dl>
                {metric.paired_deltas.map((delta) => (
                  <div key={delta.alternative_id}>
                    <dt>{delta.alternative_name} − 基线</dt>
                    <dd>Δ {delta.mean_delta.toFixed(2)} · std {delta.stddev_delta.toFixed(2)} · n {delta.n}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}

function ReportProvenance({
  experiment,
  report,
  reportV2,
}: {
  readonly experiment: SemanticExperimentDetail;
  readonly report: DecisionReport | null;
  readonly reportV2: DecisionReportV2 | null;
}): JSX.Element {
  const trials = experiment.variants.flatMap((variant) => variant.trials);
  const succeeded = trials.filter((trial) => trial.status === "succeeded").length;
  const failed = trials.filter((trial) => trial.status === "failed").length;

  return (
    <aside className="decision-report-provenance" aria-labelledby="report-provenance-title">
      <header>
        <span>PROVENANCE / VERIFIED</span>
        <h3 id="report-provenance-title">报告边界与来源</h3>
      </header>
      <dl>
        <div><dt>场景</dt><dd>{experiment.scenario.title}<code>{experiment.scenario.scenario_sha256}</code></dd></div>
        <div><dt>人群</dt><dd>{experiment.cohort.title} · {experiment.cohort.persona_count} 人<code>{experiment.cohort.cohort_sha256}</code></dd></div>
        <div><dt>数据集</dt><dd><code>{experiment.cohort.dataset_sha256}</code></dd></div>
        <div><dt>模型</dt><dd>{experiment.model_name}<code>{experiment.semantic_config_sha256}</code></dd></div>
        <div><dt>Prompt schema</dt><dd>{experiment.prompt_schema_version}</dd></div>
        <div><dt>矩阵</dt><dd>{experiment.variant_count} 方案 × {experiment.seeds.length} seeds</dd></div>
        <div><dt>Trial 完整性</dt><dd>{succeeded} 成功 · {failed} 失败</dd></div>
        <div><dt>Experiment</dt><dd><code>{experiment.experiment_sha256}</code></dd></div>
        {report !== null ? <div><dt>Report V1</dt><dd>{report.generator_version}<small>ID</small><code>{report.id}</code><small>SHA-256</small><code>{report.report_sha256}</code></dd></div> : null}
        {reportV2 !== null ? <div><dt>Report V2</dt><dd>{reportV2.generator_version}<small>ID</small><code>{reportV2.id}</code><small>SHA-256</small><code>{reportV2.report_sha256}</code></dd></div> : null}
      </dl>
      {report !== null ? (
        <a className="button button-primary" href={createDecisionReportMarkdownUrl(report.id)} download>
          下载 V1 Markdown
        </a>
      ) : null}
      {reportV2 !== null ? (
        <a className="button button-secondary" href={createDecisionReportV2MarkdownUrl(reportV2.id)} download>
          下载 V2 Markdown
        </a>
      ) : null}
      <a
        className="button button-secondary"
        href={createRunStudioHash({
          mode: "semantic",
          cohortId: experiment.cohort.id,
          scenarioId: experiment.scenario.id,
          experimentId: experiment.id,
          trialId: null,
          panel: "provenance",
        })}
      >
        返回 Playground 核验 Trial →
      </a>
      {report !== null ? <ReportQuestionPanel report={report} /> : null}
    </aside>
  );
}

function ReportQuestionResult({ item }: { readonly item: ReportQuestion }): JSX.Element {
  return (
    <article className="report-question-result" data-status={item.status}>
      <header>
        <span>{item.status}</span>
        <time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time>
      </header>
      <h4>{item.question}</h4>
      {item.conversation_depth > 0 ? <small>线程第 {item.conversation_depth + 1} 轮</small> : null}
      {item.status === "queued" || item.status === "running" ? (
        <p role="status">模型正在报告与证据图的有界范围内核验回答…</p>
      ) : null}
      {item.status === "failed" ? (
        <div className="report-question-failure" role="alert">
          <strong>{item.error_code}</strong>
          <p>{item.error_message}</p>
        </div>
      ) : null}
      {item.status === "succeeded" && item.answer_markdown !== null ? (
        <>
          <ReportMarkdown value={item.answer_markdown} />
          <ol className="report-question-citations" aria-label="回答引用的冻结证据">
            {item.citations.map((citation) => (
              <li key={`${citation.article_id}:${citation.start_offset}`}>
                <blockquote>{citation.quote}</blockquote>
                <code>{citation.article_id}</code>
                <span>{citation.start_offset}–{citation.end_offset}</span>
              </li>
            ))}
          </ol>
          <details>
            <summary>回答完整性</summary>
            <dl>
              <div><dt>Answer</dt><dd><code>{item.answer_sha256}</code></dd></div>
              <div><dt>Graph</dt><dd><code>{item.graph_sha256}</code></dd></div>
              <div><dt>Model</dt><dd>{item.model_name}</dd></div>
            </dl>
          </details>
        </>
      ) : null}
    </article>
  );
}

function ReportQuestionPanel({ report }: { readonly report: DecisionReport }): JSX.Element {
  const { state, reload } = useReportQuestions(report.id);

  return (
    <section className="report-question-panel" aria-labelledby="report-question-title">
      <header>
        <span>LEGACY Q&amp;A / READ-ONLY</span>
        <h3 id="report-question-title">历史报告问答</h3>
        <p>保留已经持久化的问题、回答、引用与哈希；新问题请在原生 ReportAgent 报告中使用 Agent Interaction。</p>
      </header>
      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取报告追问"
          error={state.error}
          isRetrying={false}
          onRetry={reload}
        />
      ) : null}
      <div className="report-question-history" aria-live="polite">
        {(state.data?.items ?? []).length === 0 ? (
          <p className="report-question-empty">这份历史报告没有已保存的问答记录。</p>
        ) : (state.data?.items ?? []).map((item) => (
          <ReportQuestionResult key={item.id} item={item} />
        ))}
      </div>
    </section>
  );
}

export function DecisionReportsPage({
  initialExperimentId,
}: {
  readonly initialExperimentId: string | null;
}): JSX.Element {
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(initialExperimentId);
  useEffect(() => {
    setSelectedExperimentId(initialExperimentId);
  }, [initialExperimentId]);
  const { state: experimentsState, reload: reloadExperiments } = useSemanticExperiments();
  const { state: reportsState, reload: reloadReports } = useDecisionReports();
  const { state: reportsV2State, reload: reloadReportsV2 } = useDecisionReportsV2();
  const reportsByExperiment = useMemo(
    () => new Map((reportsState.data?.items ?? []).map((report) => [report.experiment_id, report])),
    [reportsState.data],
  );
  const persistedReport = selectedExperimentId === null
    ? null
    : reportsByExperiment.get(selectedExperimentId) ?? null;
  const reportsV2ByExperiment = useMemo(
    () => new Map((reportsV2State.data?.items ?? []).map((report) => [report.experiment_id, report])),
    [reportsV2State.data],
  );
  const persistedReportV2 = selectedExperimentId === null
    ? null
    : reportsV2ByExperiment.get(selectedExperimentId) ?? null;
  const terminalExperiments = useMemo(
    () => (experimentsState.data?.items ?? []).filter(isTerminal),
    [experimentsState.data],
  );
  const { state: detailState, reload: reloadDetail } = useSemanticExperimentDetail(selectedExperimentId);
  const detail = detailState.status === "idle" || detailState.data?.id !== selectedExperimentId
    ? null
    : detailState.data;
  const { state: comparisonState, reload: reloadComparison } = useSemanticComparison(
    persistedReport === null && (detail?.status === "succeeded" || detail?.status === "failed")
      ? detail.id
      : null,
  );

  return (
    <div className="decision-reports-page">
      <header className="decision-reports-hero">
        <div>
          <span>LEGACY ADC REPORTS / READ-ONLY</span>
          <h1>历史 DecisionReport 归档</h1>
          <p>保留旧实验的报告正文、下载、来源哈希和 Trial 深链；不再生成 V1/V2、追问或 Persona Interview。</p>
        </div>
      <div className="decision-reports-boundary" role="note">
          <strong>只读兼容边界</strong>
          <p>新的报告与追问已经迁移到单次 Simulation Run → ReportAgent → Agent Interaction。</p>
          <a className="button button-primary" href="#/reports">返回原生报告</a>
        </div>
      </header>

      <div className="decision-reports-layout">
        <aside className="decision-report-directory" aria-labelledby="decision-report-directory-title">
          <header>
            <div><span>ARCHIVE / TERMINAL</span><h3 id="decision-report-directory-title">实验报告目录</h3></div>
            <button type="button" onClick={() => { reloadExperiments(); reloadReports(); reloadReportsV2(); }}>刷新</button>
          </header>
          {experimentsState.status === "error" ? <ApiErrorPanel title="无法读取实验报告目录" error={experimentsState.error} isRetrying={false} onRetry={reloadExperiments} /> : null}
          {reportsState.status === "error" ? <ApiErrorPanel title="无法读取持久报告目录" error={reportsState.error} isRetrying={false} onRetry={reloadReports} /> : null}
          {reportsV2State.status === "error" ? <ApiErrorPanel title="无法读取 DecisionReport V2 目录" error={reportsV2State.error} isRetrying={false} onRetry={reloadReportsV2} /> : null}
          <ReportDirectory items={terminalExperiments} reportsByExperiment={reportsByExperiment} selectedId={selectedExperimentId} onSelect={setSelectedExperimentId} />
        </aside>

        <section className="decision-report-stage" aria-label="决策报告正文">
          {selectedExperimentId === null ? <div className="decision-report-stage-empty"><strong>选择一组终态实验</strong><p>系统不会自动选择第一份报告，避免把旧实验当成当前决策上下文。</p></div> : null}
          {detailState.status === "error" ? <ApiErrorPanel title="无法读取报告实验详情" error={detailState.error} isRetrying={false} onRetry={reloadDetail} /> : null}
          {detailState.status === "loading" && detail === null ? <div className="decision-report-skeleton" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
          {persistedReportV2 !== null ? <DecisionReportV2Document report={persistedReportV2} /> : null}
          {persistedReportV2 === null && persistedReport !== null ? <PersistedReportDocument report={persistedReport} /> : null}
          {persistedReportV2 === null && persistedReport !== null ? (
            <section className="decision-report-archive-note" role="note">
              <strong>仅保留已有 V1</strong>
              <p>这条历史记录没有封存 V2；归档不会补生成或改写旧产物。</p>
            </section>
          ) : null}
          {persistedReport === null && comparisonState.status === "error" ? <ApiErrorPanel title="无法读取实验计数比较" error={comparisonState.error} isRetrying={false} onRetry={reloadComparison} /> : null}
          {persistedReport === null && detail !== null ? (
            <section className="decision-report-document" aria-labelledby="decision-report-title">
              <header><span>REPORT / {detail.status.toUpperCase()}</span><h3 id="decision-report-title">{detail.scenario.title}</h3><p>{detail.scenario.decision_question}</p><time dateTime={detail.created_at}>{formatMediaTimestamp(detail.created_at)}</time></header>
              {comparisonState.status === "success" ? <ComparisonBoard comparison={comparisonState.data} /> : comparisonState.status === "loading" ? <div className="decision-report-skeleton" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
              {comparisonState.status === "success" ? <section className="decision-report-limitations"><h3>解释限制</h3><ul>{comparisonState.data.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></section> : null}
              <div className="decision-report-archive-note" role="note">
                <strong>未封存历史报告</strong>
                <p>保留实验与只读比较视图，但不会再为旧 ADC 实验创建新报告。</p>
              </div>
            </section>
          ) : null}
        </section>

        {detail !== null ? (
          <ReportProvenance
            experiment={detail}
            report={persistedReport}
            reportV2={persistedReportV2}
          />
        ) : <aside className="decision-report-provenance decision-report-provenance-empty"><strong>等待报告选择</strong><p>选中后显示场景、Cohort、模型、配置和 Experiment 哈希。</p></aside>}
      </div>
    </div>
  );
}
