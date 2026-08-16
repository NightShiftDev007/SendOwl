import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { createSurveyExperiment, fetchSurveyReadiness, retrySurveyExperiment, type SurveyExperimentDetail, type SurveyTrial } from "./surveyContracts";
import { resolveSurveyTrialSelection } from "./surveyTrialSelection";
import { useCohorts } from "./usePopulations";
import { useScenarioDetail, useScenarios } from "./useScenarios";
import { useSurveyExperiment, useSurveyExperiments, useSurveyReadiness } from "./useSurveyExperiments";
import "./surveyPlayground.css";

function shortHash(value: string): string { return `${value.slice(0, 10)}…${value.slice(-8)}`; }

function TrialAnswer({ trial }: { readonly trial: SurveyTrial }): JSX.Element {
  return (
    <li data-status={trial.status}>
      <header><span>{trial.persona.position + 1}</span><div><strong>{trial.persona.display_name}</strong><small>{trial.persona.persona_id}</small></div><em>{trial.status}</em></header>
      {trial.result !== null ? <dl>
        <div><dt>选择</dt><dd>{trial.result.answers[0].value === "baseline" ? "基线" : "备选方案"}</dd></div>
        <div><dt>支持度</dt><dd>{trial.result.answers[1].value} / 5</dd></div>
        <div><dt>主要理由</dt><dd>{trial.result.answers[2].value}</dd></div>
      </dl> : null}
      {trial.error !== null ? <p role="alert"><strong>{trial.error.code}</strong> · {trial.error.message}</p> : null}
      <details className="survey-trial-provenance">
        <summary>Trial provenance 与内容哈希</summary>
        <dl>
          <div><dt>trial_sha256</dt><dd><code>{trial.trial_sha256}</code></dd></div>
          <div><dt>profile_sha256</dt><dd><code>{trial.persona.profile_sha256}</code></dd></div>
          {trial.result !== null ? <div><dt>answers_sha256</dt><dd><code>{trial.result.answers_sha256}</code></dd></div> : null}
        </dl>
      </details>
    </li>
  );
}

function SurveyResults({
  experiment,
  selectedTrialId,
  onSelectTrial,
}: {
  readonly experiment: SurveyExperimentDetail;
  readonly selectedTrialId: string | null;
  readonly onSelectTrial: (trialId: string) => void;
}): JSX.Element {
  const support = experiment.aggregate.alternative_support;
  const selection = resolveSurveyTrialSelection(experiment.trials, selectedTrialId);
  return <>
    <section className="survey-result-ledger" aria-label="Survey 可复算聚合">
      <div><span>基线</span><strong>{experiment.aggregate.preferred_variant.baseline_count}</strong></div>
      <div><span>备选</span><strong>{experiment.aggregate.preferred_variant.alternative_count}</strong></div>
      <div><span>支持度</span><strong>{support.mean === null ? "—" : support.mean.toFixed(2)}</strong><small>{support.n} 份有效回答</small></div>
      <div><span>失败</span><strong>{experiment.aggregate.failed_trial_count}</strong></div>
    </section>
    <nav className="survey-trial-switcher" aria-label="选择 Survey Persona trial">
      {experiment.trials.map((trial) => (
        <button
          key={trial.id}
          type="button"
          aria-pressed={trial.id === selectedTrialId}
          data-status={trial.status}
          onClick={() => onSelectTrial(trial.id)}
        >
          <span>{trial.persona.position + 1}</span>
          <span><strong>{trial.persona.display_name}</strong><small>{trial.status}</small></span>
        </button>
      ))}
    </nav>
    {selection.status === "selected" ? (
      <ol className="survey-trial-list"><TrialAnswer trial={selection.trial} /></ol>
    ) : (
      <div
        className="survey-empty survey-trial-selection-empty"
        role={selection.status === "idle" ? "status" : "alert"}
      >
        <strong>{selection.status === "idle" ? "明确选择一个 Persona trial" : "这个 trial 不属于当前 Survey 实验"}</strong>
        <p>{selection.status === "idle"
          ? "每份 Persona 回答彼此独立；系统不会默认打开第一条。"
          : "系统没有回退到第一条或相似记录。请从上方当前实验的 Persona trial 中重新选择。"}</p>
      </div>
    )}
  </>;
}

export function SurveyPlaygroundPage({
  page,
  initialExperimentId,
  initialTrialId,
  onBack,
  onSelectionChange,
}: {
  readonly page: number;
  readonly initialExperimentId: string | null;
  readonly initialTrialId: string | null;
  readonly onBack: () => void;
  readonly onSelectionChange: (
    page: number,
    experimentId: string | null,
    trialId: string | null,
  ) => void;
}): JSX.Element {
  const { state: readiness, reload: reloadReadiness } = useSurveyReadiness();
  const { state: scenarios } = useScenarios();
  const { state: cohorts } = useCohorts();
  const { state: directory, reload: reloadDirectory } = useSurveyExperiments(page);
  const [scenarioId, setScenarioId] = useState<string | null>(null);
  const [cohortId, setCohortId] = useState<string | null>(null);
  const { state: scenarioDetail } = useScenarioDetail(scenarioId);
  const [alternativeId, setAlternativeId] = useState<string | null>(null);
  const selectedExperimentId = initialExperimentId;
  const selectedTrialId = initialTrialId;
  const { state: selectedExperiment, reload: reloadExperiment } = useSurveyExperiment(selectedExperimentId);
  const [confirmed, setConfirmed] = useState(false);
  const [submission, setSubmission] = useState<{ readonly status: "idle" | "submitting" | "error"; readonly message?: string }>({ status: "idle" });
  const [retrying, setRetrying] = useState(false);
  const activeController = useRef<AbortController | null>(null);

  useEffect(() => () => activeController.current?.abort(), []);
  useEffect(() => { setAlternativeId(null); setConfirmed(false); }, [scenarioId]);
  useEffect(() => setConfirmed(false), [cohortId, alternativeId]);

  const detail = scenarioDetail.status === "success" ? scenarioDetail.data : null;
  const selectedCohort = cohorts.data?.items.find((cohort) => cohort.id === cohortId) ?? null;
  const ready = readiness.status === "success" && readiness.data.survey_runtime_ready;
  const canSubmit = ready && detail !== null && selectedCohort !== null && selectedCohort.persona_count <= 8 && alternativeId !== null && confirmed && submission.status !== "submitting";

  const submit = (): void => {
    if (!canSubmit || scenarioId === null || cohortId === null || alternativeId === null || activeController.current !== null) return;
    const controller = new AbortController();
    activeController.current = controller;
    setSubmission({ status: "submitting" });
    void fetchSurveyReadiness(controller.signal).then((currentReadiness) => {
      if (!currentReadiness.survey_runtime_ready) throw new Error("Survey worker 已离线或配置发生冲突，POST 尚未发送。");
      return createSurveyExperiment({ scenario_id: scenarioId, cohort_id: cohortId, alternative_id: alternativeId }, controller.signal);
    }).then((experiment) => {
      if (activeController.current !== controller) return;
      onSelectionChange(1, experiment.id, null); setSubmission({ status: "idle" }); setConfirmed(false); reloadDirectory();
    }).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      if (activeController.current !== controller) return;
      const normalized = error instanceof Error ? error : new Error("创建 Survey 实验失败。请查看后端日志。");
      setSubmission({ status: "error", message: isAmbiguousPostResultError(normalized) ? `提交结果未知，请先刷新实验目录核对。${normalized.message}` : normalized.message });
    }).finally(() => { if (activeController.current === controller) activeController.current = null; });
  };
  const retry = (): void => {
    if (selectedExperiment.status !== "success" || selectedExperiment.data.status !== "failed" || selectedExperiment.data.attempt_number >= 5 || !ready || activeController.current !== null) return;
    const controller = new AbortController(); activeController.current = controller; setRetrying(true);
    void fetchSurveyReadiness(controller.signal).then((state) => {
      if (!state.survey_runtime_ready) throw new Error("Survey runtime 在重试前已不可用，POST 尚未发送。");
      return retrySurveyExperiment(selectedExperiment.data.id, controller.signal);
    }).then((created) => { if (activeController.current === controller) { onSelectionChange(1, created.id, null); reloadDirectory(); } })
      .catch((error: unknown) => { if (!(error instanceof DOMException && error.name === "AbortError")) setSubmission({ status: "error", message: error instanceof Error ? error.message : "创建 Survey 重试 attempt 失败。" }); })
      .finally(() => { if (activeController.current === controller) activeController.current = null; setRetrying(false); });
  };

  return <div className="survey-playground-page">
    <header className="survey-playground-header"><button type="button" onClick={onBack}>← Task Gallery</button><div><span>MATRAIX / SURVEY PLAYGROUND</span><h2>Scenario Preference Persona Survey</h2><p>让封存 Cohort 逐 Persona 回答同一份严格问卷；输出是合成人格响应，不是真人调研或人口代表性结论。</p></div><div data-ready={ready}><strong>{ready ? "SURVEY READY" : "RUNTIME LOCKED"}</strong><small>{readiness.status === "success" ? readiness.data.model_name ?? "无一致模型配置" : "核验中"}</small></div></header>
    {readiness.status === "error" ? <ApiErrorPanel title="无法核验 Survey runtime" error={readiness.error} isRetrying={readiness.isRetrying} onRetry={reloadReadiness} /> : null}
    <div className="survey-cockpit">
      <aside className="survey-composer">
        <header><span>INPUT / FROZEN</span><h3>实验输入</h3></header>
        <label htmlFor="survey-scenario">Scenario<select id="survey-scenario" name="survey_scenario" value={scenarioId ?? ""} onChange={(event) => setScenarioId(event.target.value || null)}><option value="">选择封存 Scenario</option>{scenarios.data?.items.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.title}</option>)}</select></label>
        <label htmlFor="survey-cohort">Cohort<select id="survey-cohort" name="survey_cohort" value={cohortId ?? ""} onChange={(event) => setCohortId(event.target.value || null)}><option value="">选择 1–8 Persona Cohort</option>{cohorts.data?.items.map((cohort) => <option key={cohort.id} value={cohort.id} disabled={cohort.persona_count > 8}>{cohort.title} · {cohort.persona_count}</option>)}</select></label>
        <label htmlFor="survey-alternative">备选方案<select id="survey-alternative" name="survey_alternative" value={alternativeId ?? ""} disabled={detail === null} onChange={(event) => setAlternativeId(event.target.value || null)}><option value="">选择与基线对照的方案</option>{detail?.alternatives.map((alternative) => <option key={alternative.id} value={alternative.id}>{alternative.name}</option>)}</select></label>
        {detail !== null ? <section className="survey-variant-preview"><article><span>BASELINE</span><strong>{detail.baseline.name}</strong><p>{detail.baseline.hypothesis}</p></article>{detail.alternatives.filter((item) => item.id === alternativeId).map((item) => <article key={item.id}><span>ALTERNATIVE</span><strong>{item.name}</strong><p>{item.hypothesis}</p></article>)}</section> : null}
        <label className="survey-confirm"><input type="checkbox" checked={confirmed} disabled={!ready || alternativeId === null || selectedCohort === null} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认这是合成 Persona Survey，结果不代表真实人口意见，也不会写回现实证据图。</span></label>
        <button className="survey-launch" type="button" disabled={!canSubmit} onClick={submit}>{submission.status === "submitting" ? "正在冻结实验…" : "启动 Persona Survey"}</button>
        {submission.status === "error" ? <p className="survey-submit-error" role="alert">{submission.message}</p> : null}
      </aside>

      <section className="survey-stage" aria-labelledby="survey-stage-title">
        <header><div><span>QUESTIONNAIRE / SCENARIO-PREFERENCE-V1</span><h3 id="survey-stage-title">问卷与 Persona 回答</h3></div>{selectedExperiment.status === "success" ? <div className="survey-attempt-actions"><strong data-status={selectedExperiment.data.status}>attempt {selectedExperiment.data.attempt_number} · {selectedExperiment.data.status}</strong>{selectedExperiment.data.status === "failed" ? <button type="button" disabled={!ready || retrying || selectedExperiment.data.attempt_number >= 5} onClick={retry}>{retrying ? "正在创建…" : "保留失败并重试"}</button> : null}</div> : null}</header>
        {selectedExperimentId === null ? <div className="survey-empty"><strong>先冻结实验输入</strong><p>选择 Scenario、Cohort 和一个备选方案后，这里会显示固定三题问卷、运行状态与逐 Persona 原始回答。</p></div> : null}
        {selectedExperiment.status === "loading" ? <div className="survey-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
        {selectedExperiment.status === "error" ? <ApiErrorPanel title="无法读取 Survey 实验" error={selectedExperiment.error} isRetrying={selectedExperiment.isRetrying} onRetry={reloadExperiment} /> : null}
        {selectedExperiment.status === "success" ? <><section className="survey-instrument"><header><div><strong>{selectedExperiment.data.instrument.title}</strong><p>{selectedExperiment.data.instrument.description}</p></div><code>{shortHash(selectedExperiment.data.instrument.instrument_sha256)}</code></header><ol>{selectedExperiment.data.instrument.questions.map((question) => <li key={question.id}><span>{question.position + 1}</span><div><strong>{question.prompt}</strong><small>{question.type}{question.min_value === null ? "" : ` · ${question.min_value}–${question.max_value}`}</small></div></li>)}</ol></section><SurveyResults experiment={selectedExperiment.data} selectedTrialId={selectedTrialId} onSelectTrial={(trialId) => onSelectionChange(page, selectedExperiment.data.id, trialId)} /></> : null}
      </section>

      <aside className="survey-directory">
        <header><div><span>TRIAL ARCHIVE</span><h3>Survey 实验目录</h3></div><button type="button" disabled={directory.status === "loading"} onClick={reloadDirectory}>刷新</button></header>
        {directory.status === "error" ? <ApiErrorPanel title="无法读取实验目录" error={directory.error} isRetrying={directory.isRetrying} onRetry={reloadDirectory} /> : null}
        {directory.status === "success" && directory.items.length === 0 ? <div className="survey-empty"><strong>尚无 Survey</strong><p>完成第一组严格输入后，实验会持久保存在这里。</p></div> : null}
        {directory.status === "success" ? <ol>{directory.items.map((experiment) => <li key={experiment.id}><button type="button" data-selected={experiment.id === selectedExperimentId} onClick={() => onSelectionChange(page, experiment.id, null)}><span><strong>{experiment.scenario.title}</strong><small>attempt {experiment.attempt_number} · {experiment.cohort.title} · {experiment.trial_count} Persona</small></span><em data-status={experiment.status}>{experiment.status}</em><code>{shortHash(experiment.experiment_sha256)}</code></button></li>)}</ol> : null}
        <nav aria-label="Survey 实验分页"><button type="button" disabled={page <= 1} onClick={() => onSelectionChange(page - 1, null, null)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(directory.total / directory.pageSize))}</span><button type="button" disabled={page >= Math.max(1, Math.ceil(directory.total / directory.pageSize))} onClick={() => onSelectionChange(page + 1, null, null)}>下一页</button></nav>
        {readiness.status === "success" ? <details className="survey-provenance"><summary>运行边界与 provenance</summary><dl><div><dt>Model</dt><dd>{readiness.data.model_name ?? "—"}</dd></div><div><dt>Config</dt><dd><code>{readiness.data.survey_config_sha256 ?? "—"}</code></dd></div><div><dt>Worker</dt><dd>{readiness.data.live_worker_count}</dd></div></dl><ul>{readiness.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
      </aside>
    </div>
  </div>;
}
