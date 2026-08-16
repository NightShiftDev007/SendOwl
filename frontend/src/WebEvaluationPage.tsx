import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaTimestamp } from "./mediaPresentation";
import { PopulationContextPanel } from "./PopulationContextPanel";
import { createWebEvaluation, fetchWebReadiness } from "./webEvaluationContracts";
import {
  useWebEvaluation,
  useWebEvaluations,
  useWebReadiness,
  useWebTasks,
  useWebTrial,
} from "./useWebEvaluations";
import "./webEvaluation.css";

interface WebEvaluationPageProps {
  readonly page: number;
  readonly initialEvaluationId: string | null;
  readonly initialTrialId: string | null;
  readonly onBack: () => void;
  readonly onSelectionChange: (page: number, evaluationId: string | null, trialId: string | null) => void;
}

type SubmissionState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly error: Error; readonly ambiguous: boolean };

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error("创建 Web Evaluation 失败：请求抛出了非标准错误。");
}

export function WebEvaluationPage({
  page,
  initialEvaluationId,
  initialTrialId,
  onBack,
  onSelectionChange,
}: WebEvaluationPageProps): JSX.Element {
  const [cohortId, setCohortId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });
  const activeSubmission = useRef<AbortController | null>(null);
  const readiness = useWebReadiness();
  const tasks = useWebTasks();
  const directory = useWebEvaluations(page);
  const detail = useWebEvaluation(initialEvaluationId);
  const trial = useWebTrial(initialTrialId);
  const ready = readiness.state.status === "success" && readiness.state.data.web_runtime_ready;

  useEffect(() => () => activeSubmission.current?.abort(), []);

  const submit = async (): Promise<void> => {
    if (cohortId === null || !confirmed || !ready || submission.status === "submitting") return;
    const controller = new AbortController();
    activeSubmission.current = controller;
    setSubmission({ status: "submitting" });
    try {
      const fresh = await fetchWebReadiness(controller.signal);
      if (!fresh.web_runtime_ready) throw new Error("Web readiness preflight is no longer ready.");
      const created = await createWebEvaluation(cohortId, controller.signal);
      setSubmission({ status: "idle" });
      setConfirmed(false);
      directory.reload();
      onSelectionChange(1, created.id, null);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const normalized = normalizeError(error);
      const ambiguous = isAmbiguousPostResultError(normalized);
      setSubmission({ status: "error", error: normalized, ambiguous });
      if (ambiguous) onSelectionChange(1, null, null);
      directory.reload();
    } finally {
      if (activeSubmission.current === controller) activeSubmission.current = null;
    }
  };

  const selectedDetail = detail.state.data;
  const selectedTrial = trial.state.data;
  const totalPages = Math.max(1, Math.ceil((directory.state.data?.total ?? 0) / 20));

  return (
    <div className="web-eval-page">
      <header className="web-eval-hero">
        <div>
          <div className="web-eval-kicker">
            <button type="button" onClick={onBack}>← Task Gallery</button>
            <span>MATRAIX / PLAYWRIGHT</span>
          </div>
          <h2>固定来源 Web Persona 评测</h2>
          <p>Playwright 真实读取 Quotes to Scrape 的 3 个页面，保存 DOM 引用与截图，再由冻结 Persona 从已观察候选中选择。它不是通用 Web Agent。</p>
        </div>
        <dl><div><dt>Browser</dt><dd>{readiness.state.data?.task.transport ?? "核验中"}</dd></div><div><dt>Worker</dt><dd>{readiness.state.data?.live_worker_count ?? "—"}</dd></div><div><dt>Runtime</dt><dd data-ready={ready}>{ready ? "ready" : "blocked"}</dd></div></dl>
      </header>

      <div className="web-eval-layout">
        <aside className="web-eval-composer">
          <PopulationContextPanel selectedCohortId={cohortId} onSelectedCohortIdChange={(value) => { setCohortId(value); setConfirmed(false); }} />
          <section className="web-eval-submit">
            <header><span>EXECUTION / 01</span><h3>冻结执行输入</h3></header>
            <dl><div><dt>Task</dt><dd>{tasks.state.data?.[0]?.title ?? "核验中"}</dd></div><div><dt>Origin</dt><dd>quotes.toscrape.com</dd></div><div><dt>Pages</dt><dd>3（固定）</dd></div></dl>
            <label><input type="checkbox" checked={confirmed} disabled={cohortId === null} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认这是来源示例与合成 Persona 输出，不代表真人偏好或通用网页代理能力。</span></label>
            <button type="button" disabled={!ready || cohortId === null || !confirmed || submission.status === "submitting"} onClick={() => { void submit(); }}>{submission.status === "submitting" ? "正在原子入队…" : "创建 Web Evaluation"}</button>
            {!ready ? <p className="web-eval-boundary">当前千问 / worker readiness 未通过；浏览器可用不等于 Persona 评测可执行。</p> : null}
            {submission.status === "error" ? <div role="alert"><strong>{submission.ambiguous ? "提交结果不确定" : "创建失败"}</strong><p>{submission.error.message}</p></div> : null}
          </section>
        </aside>

        <main className="web-eval-stage">
          <header><div><span>OBSERVATION / EVIDENCE</span><h3>浏览证据与选择结果</h3></div>{selectedDetail !== null ? <code>{shortHash(selectedDetail.evaluation_sha256)}</code> : null}</header>
          {initialEvaluationId === null ? <div className="web-eval-empty"><strong>显式选择或创建 Evaluation</strong><p>目录不会自动打开第一条历史记录，避免误认旧上下文。</p></div> : null}
          {detail.state.status === "error" ? <ApiErrorPanel title="无法读取 Web Evaluation" error={detail.state.error} isRetrying={false} onRetry={detail.reload} /> : null}
          {selectedDetail !== null ? <>
            <section className="web-eval-ledger"><div><span>Cohort</span><strong>{selectedDetail.cohort.title}</strong></div><div><span>Status</span><strong data-status={selectedDetail.status}>{selectedDetail.status}</strong></div><div><span>Trials</span><strong>{selectedDetail.succeeded_trial_count} succeeded / {selectedDetail.failed_trial_count} failed</strong></div><div><span>Model</span><strong>{selectedDetail.model_name}</strong></div></section>
            <nav className="web-eval-trials" aria-label="Web Persona trials">{selectedDetail.trials.map((item) => <button key={item.id} type="button" aria-pressed={item.id === initialTrialId} data-status={item.status} onClick={() => onSelectionChange(page, selectedDetail.id, item.id)}><span>{item.persona.position + 1}</span><strong>{item.persona.display_name}</strong><small>{item.status} · {item.observed_page_count} pages · {item.observed_quote_count} quotes</small></button>)}</nav>
          </> : null}
          {initialTrialId !== null && trial.state.status === "error" ? <ApiErrorPanel title="无法读取 Web Trial" error={trial.state.error} isRetrying={false} onRetry={trial.reload} /> : null}
          {selectedTrial !== null ? <section className="web-eval-evidence">
            {selectedTrial.error !== null ? <div className="web-eval-error" role="alert"><strong>{selectedTrial.error.code}</strong><p>{selectedTrial.error.message}</p></div> : null}
            {selectedTrial.pages.map((observedPage) => <article key={observedPage.position}><header><div><span>PAGE {observedPage.position + 1}</span><a href={observedPage.url} target="_blank" rel="noreferrer">{observedPage.title}</a></div><code>{shortHash(observedPage.screenshot_sha256)}</code></header><img src={observedPage.screenshot_path} alt={`Quotes to Scrape 第 ${observedPage.position + 1} 页真实截图`} loading="lazy" /><ol>{observedPage.quotes.map((quote) => <li key={quote.quote_id} data-selected={selectedTrial.result?.decision_subject_id === quote.quote_id}><blockquote>{quote.text}</blockquote><span>— {quote.author}</span><small>{quote.tags.join(" · ") || "无标签"}</small></li>)}</ol></article>)}
            {selectedTrial.result !== null ? <section className="web-eval-result"><header><div><span>PERSONA CHOICE</span><h4>{selectedTrial.result.task_author}</h4></div><strong>{selectedTrial.result.overall_experience_rating} / 10</strong></header><blockquote>{selectedTrial.result.decision_subject_label}</blockquote><p>{selectedTrial.result.reason}</p><dl><div><dt>Basis</dt><dd>{selectedTrial.result.basis_primary}</dd></div><div><dt>Need</dt><dd>{selectedTrial.result.need_constraint_satisfaction}</dd></div><div><dt>Preference</dt><dd>{selectedTrial.result.personal_preference_satisfaction}</dd></div><div><dt>Trace</dt><dd><code>{shortHash(selectedTrial.result.trace_sha256)}</code></dd></div></dl><small>这是合成 Persona 自述，不是 verifier reward、真人偏好或因果结论。</small></section> : null}
          </section> : initialTrialId !== null ? <div className="web-eval-empty"><strong>正在读取 Trial</strong></div> : null}
        </main>

        <aside className="web-eval-directory">
          <header><div><span>ARCHIVE / SEALED</span><h3>Web Evaluation 目录</h3></div><button type="button" onClick={directory.reload}>刷新</button></header>
          {directory.state.status === "error" ? <ApiErrorPanel title="无法读取 Web 目录" error={directory.state.error} isRetrying={false} onRetry={directory.reload} /> : null}
          {directory.state.data?.items.length === 0 ? <div className="web-eval-empty"><strong>尚无 Web Evaluation</strong></div> : null}
          <ol>{directory.state.data?.items.map((item) => <li key={item.id}><button type="button" data-selected={item.id === initialEvaluationId} onClick={() => onSelectionChange(page, item.id, null)}><strong>{item.cohort.title}</strong><span>{item.status} · {item.trial_count} Persona</span><time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time><code>{shortHash(item.evaluation_sha256)}</code></button></li>)}</ol>
          <nav aria-label="Web Evaluation 分页"><button type="button" disabled={page <= 1} onClick={() => onSelectionChange(page - 1, null, null)}>上一页</button><span>{page} / {totalPages}</span><button type="button" disabled={page >= totalPages} onClick={() => onSelectionChange(page + 1, null, null)}>下一页</button></nav>
          {readiness.state.data !== null ? <details><summary>运行边界与 provenance</summary><dl><div><dt>Model</dt><dd>{readiness.state.data.model_name ?? "—"}</dd></div><div><dt>Config</dt><dd><code>{readiness.state.data.web_config_sha256 ?? "—"}</code></dd></div></dl><ul>{readiness.state.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
        </aside>
      </div>
    </div>
  );
}
