import { useEffect, useMemo, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import {
  createResearchSurvey,
  fetchResearchSurvey,
  fetchResearchSurveyReadiness,
  fetchResearchSurveys,
  type ResearchSurveyDetail,
  type ResearchSurveyReadiness,
  type ResearchSurveySummary,
  type ResearchSurveyTrial,
} from "./researchSurveyContracts";
import { fetchResearchRuns, type ResearchRun } from "./researchProjectContracts";
import { useResearchProjects } from "./useResearchProjects";
import "./surveyPlayground.css";

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

const focusLabel = {
  evidence: "证据",
  process: "过程",
  timing: "时间",
  impact: "影响",
} as const;

function Trial({ trial }: { readonly trial: ResearchSurveyTrial }): JSX.Element {
  return (
    <li data-status={trial.status}>
      <header>
        <span>{trial.persona.position + 1}</span>
        <div><strong>{trial.persona.display_name}</strong><small>{trial.persona.persona_id}</small></div>
        <em>{trial.status}</em>
      </header>
      {trial.result !== null ? (
        <dl>
          <div><dt>上下文清晰度</dt><dd>{trial.result.answers[0].value} / 5</dd></div>
          <div><dt>下一关注点</dt><dd>{focusLabel[trial.result.answers[1].value]}</dd></div>
          <div><dt>未解问题</dt><dd>{trial.result.answers[2].value}</dd></div>
        </dl>
      ) : null}
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

export function SurveyPlaygroundPage({
  initialProjectId,
  initialRunId,
  initialExperimentId,
  initialTrialId,
  onBack,
  onSelectionChange,
}: {
  readonly initialProjectId: string | null;
  readonly initialRunId: string | null;
  readonly page: number;
  readonly initialExperimentId: string | null;
  readonly initialTrialId: string | null;
  readonly onBack: () => void;
  readonly onSelectionChange: (page: number, experimentId: string | null, trialId: string | null) => void;
}): JSX.Element {
  const projects = useResearchProjects();
  const [projectId, setProjectId] = useState<string | null>(initialProjectId);
  const [runId, setRunId] = useState<string | null>(initialRunId);
  const [runs, setRuns] = useState<readonly ResearchRun[]>([]);
  const [readiness, setReadiness] = useState<ResearchSurveyReadiness | null>(null);
  const [directory, setDirectory] = useState<readonly ResearchSurveySummary[]>([]);
  const [detail, setDetail] = useState<ResearchSurveyDetail | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const activeRequest = useRef<AbortController | null>(null);
  const ready = readiness?.survey_runtime_ready === true;
  const selectedRun = runs.find((item) => item.id === runId) ?? null;
  const selectedTrial = detail?.trials.find((item) => item.id === initialTrialId) ?? null;
  const succeededRuns = useMemo(
    () => runs.filter((item) => item.status === "succeeded" && item.initial_post !== null),
    [runs],
  );

  const loadDirectory = (): void => {
    const controller = new AbortController();
    void fetchResearchSurveys(controller.signal)
      .then((data) => setDirectory(data.items))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason : new Error("读取原生 Survey 目录失败")));
  };

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      fetchResearchSurveyReadiness(controller.signal),
      fetchResearchSurveys(controller.signal),
    ]).then(([nextReadiness, nextDirectory]) => {
      setReadiness(nextReadiness);
      setDirectory(nextDirectory.items);
    }).catch((reason: unknown) => {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason : new Error("读取 Survey 工作区失败"));
      }
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (projectId === null) {
      setRuns([]);
      setRunId(null);
      return;
    }
    const controller = new AbortController();
    void fetchResearchRuns(projectId, controller.signal)
      .then((data) => {
        setRuns(data.items);
        setRunId((current) => current !== null && data.items.some((item) => item.id === current)
          ? current
          : null);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason : new Error("读取项目运行失败"));
        }
      });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    if (initialExperimentId === null) { setDetail(null); return; }
    const controller = new AbortController();
    const load = (): void => {
      void fetchResearchSurvey(initialExperimentId, controller.signal)
        .then(setDetail)
        .catch((reason: unknown) => {
          if (!(reason instanceof DOMException && reason.name === "AbortError")) {
            setError(reason instanceof Error ? reason : new Error("读取 Survey 失败"));
          }
        });
    };
    load();
    const timer = window.setInterval(load, 2_500);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [initialExperimentId]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const submit = (): void => {
    if (!ready || !confirmed || projectId === null || runId === null || submitting) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setSubmitting(true);
    setError(null);
    void fetchResearchSurveyReadiness(controller.signal)
      .then((state) => {
        if (!state.survey_runtime_ready) throw new Error("Survey runtime 已离线，提交尚未发送。");
        return createResearchSurvey(projectId, runId, controller.signal);
      })
      .then((created) => {
        onSelectionChange(1, created.id, null);
        loadDirectory();
        setConfirmed(false);
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason : new Error("创建原生 Survey 失败"));
        }
      })
      .finally(() => { activeRequest.current = null; setSubmitting(false); });
  };

  return (
    <div className="survey-playground-page">
      <header className="survey-playground-header">
        <button type="button" onClick={onBack}>← 返回评测中心</button>
        <div>
          <span>SANDOWL / 研究问卷</span>
          <h1>单一研究上下文人物问卷</h1>
          <p>绑定一个研究项目、一次已完成模拟及其冻结人群；记录独立合成观察，不比较或推荐方案。</p>
        </div>
        <div data-ready={ready}><strong>{ready ? "SURVEY READY" : "RUNTIME LOCKED"}</strong><small>{readiness?.model_name ?? "核验中"}</small></div>
      </header>
      {error !== null ? <ApiErrorPanel title="Survey 工作区出现问题" error={error} isRetrying={false} onRetry={() => window.location.reload()} /> : null}
      <div className="survey-cockpit">
        <aside className="survey-composer">
          <header><span>NATIVE INPUT / FROZEN</span><h3>研究范围</h3></header>
          <label htmlFor="survey-project">研究项目
            <select id="survey-project" value={projectId ?? ""} onChange={(event) => { setProjectId(event.target.value || null); setConfirmed(false); }}>
              <option value="">选择研究项目</option>
              {projects.state.status === "success" ? projects.state.data.items.map((item) => <option key={item.id} value={item.id}>{item.title}</option>) : null}
            </select>
          </label>
          <label htmlFor="survey-run">已完成的模拟运行
            <select id="survey-run" value={runId ?? ""} disabled={projectId === null} onChange={(event) => { setRunId(event.target.value || null); setConfirmed(false); }}>
              <option value="">选择已完成的单次运行</option>
              {succeededRuns.map((item) => <option key={item.id} value={item.id}>{item.simulation_requirement.slice(0, 54)} · {item.cohort.persona_count} Persona</option>)}
            </select>
          </label>
          {selectedRun !== null ? <section className="survey-variant-preview"><article><span>SINGLE CONTEXT</span><strong>{selectedRun.simulation_requirement}</strong><p>{selectedRun.initial_post}</p></article><article><span>FROZEN COHORT</span><strong>{selectedRun.cohort.persona_count} 个 Persona</strong><p>cohort_sha256 · {shortHash(selectedRun.cohort.cohort_sha256)}</p></article></section> : null}
          <label className="survey-confirm"><input type="checkbox" checked={confirmed} disabled={!ready || selectedRun === null} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认输出仅是单一合成上下文中的 Persona 观察，不是真人调研、现实预测或方案选择。</span></label>
          <button className="survey-launch" type="button" disabled={!ready || !confirmed || selectedRun === null || submitting} onClick={submit}>{submitting ? "正在冻结 Survey…" : "启动原生 Persona Survey"}</button>
          <a className="survey-legacy-link" href="#/tasks?task=trials&kind=survey">查看旧 ADC Survey 历史归档 →</a>
        </aside>
        <section className="survey-stage" aria-labelledby="survey-stage-title">
          <header><div><span>INSTRUMENT / SINGLE-CONTEXT-OBSERVATION-V1</span><h3 id="survey-stage-title">合成观察</h3></div>{detail !== null ? <strong data-status={detail.status}>{detail.status}</strong> : null}</header>
          {detail === null ? <div className="survey-empty"><strong>选择单次已完成运行</strong><p>系统会对 Run 自带的 Cohort 提交固定三题：上下文清晰度、下一关注点、一个未解问题。</p></div> : <>
            <section className="survey-instrument"><header><div><strong>{detail.project.title}</strong><p>{detail.project.research_question}</p></div><code>{shortHash(detail.instrument_sha256)}</code></header><ol><li><span>1</span><div><strong>这个研究上下文对该 Persona 有多清晰？</strong><small>Likert · 1–5</small></div></li><li><span>2</span><div><strong>该 Persona 下一步最关注什么？</strong><small>证据 / 过程 / 时间 / 影响</small></div></li><li><span>3</span><div><strong>最重要的一个未解问题是什么？</strong><small>Free text</small></div></li></ol></section>
            <section className="survey-result-ledger" aria-label="Survey 聚合"><div><span>有效回答</span><strong>{detail.aggregate.succeeded_trial_count}</strong></div><div><span>清晰度均值</span><strong>{detail.aggregate.context_clarity_mean?.toFixed(2) ?? "—"}</strong></div><div><span>未解问题</span><strong>{detail.aggregate.unanswered_questions.length}</strong></div><div><span>失败</span><strong>{detail.aggregate.failed_trial_count}</strong></div></section>
            <nav className="survey-trial-switcher" aria-label="选择 Persona trial">{detail.trials.map((trial) => <button key={trial.id} type="button" aria-pressed={trial.id === initialTrialId} data-status={trial.status} onClick={() => onSelectionChange(1, detail.id, trial.id)}><span>{trial.persona.position + 1}</span><span><strong>{trial.persona.display_name}</strong><small>{trial.status}</small></span></button>)}</nav>
            {selectedTrial !== null ? <ol className="survey-trial-list"><Trial trial={selectedTrial} /></ol> : <div className="survey-empty survey-trial-selection-empty"><strong>选择一个 Persona trial</strong><p>系统不会默认打开第一条回答。</p></div>}
          </>}
        </section>
        <aside className="survey-directory">
          <header><div><span>NATIVE SURVEY DIRECTORY</span><h3>原生 Survey</h3></div><button type="button" onClick={loadDirectory}>刷新</button></header>
          {directory.length === 0 ? <div className="survey-empty"><strong>尚无原生 Survey</strong><p>旧 Scenario Preference 数据只保留在历史归档中。</p></div> : <ol>{directory.map((item) => <li key={item.id}><button type="button" data-selected={item.id === initialExperimentId} onClick={() => onSelectionChange(1, item.id, null)}><span><strong>{item.project.title}</strong><small>{item.cohort.title} · {item.trial_count} Persona</small></span><em data-status={item.status}>{item.status}</em><code>{shortHash(item.survey_sha256)}</code></button></li>)}</ol>}
          {readiness !== null ? <details className="survey-provenance"><summary>运行边界与 provenance</summary><dl><div><dt>Model</dt><dd>{readiness.model_name ?? "—"}</dd></div><div><dt>Config</dt><dd><code>{readiness.survey_config_sha256 ?? "—"}</code></dd></div><div><dt>Worker</dt><dd>{readiness.live_worker_count}</dd></div></dl><ul>{readiness.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
        </aside>
      </div>
    </div>
  );
}
