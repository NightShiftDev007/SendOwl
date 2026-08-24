import { useEffect, useMemo, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import {
  createNativeBatchLaunch,
  type MatraixBatchRegistryDetail,
  type MatraixNativeBatchLaunchItem,
  type MatraixNativeBatchLaunchRequest,
} from "./batchRegistryContracts";
import { fetchChatReadiness } from "./chatEvaluationContracts";
import { fetchResearchRuns, type ResearchRun } from "./researchProjectContracts";
import { fetchResearchSurveyReadiness } from "./researchSurveyContracts";
import { useChatReadiness, useChatTasks } from "./useChatEvaluations";
import { useCohorts } from "./usePopulations";
import { useResearchProjects } from "./useResearchProjects";
import { useResearchSurveyReadiness } from "./useResearchSurveys";

type DraftKind = "survey" | "chat";
type SubmissionState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly error: Error; readonly ambiguous: boolean };

function itemKey(item: MatraixNativeBatchLaunchItem): string {
  return item.kind === "survey"
    ? `survey:${item.research_project_id}:${item.research_simulation_run_id}`
    : `chat:${item.cohort_id}:${item.task_id}:${item.task_version}`;
}

function compactId(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

export function NativeBatchLaunchComposer({
  onCreated,
  onAmbiguous,
}: {
  readonly onCreated: (registry: MatraixBatchRegistryDetail) => void;
  readonly onAmbiguous: () => void;
}): JSX.Element {
  const { state: projects, reload: reloadProjects } = useResearchProjects();
  const { state: cohorts, reload: reloadCohorts } = useCohorts();
  const { state: surveyReadiness, reload: reloadSurveyReadiness } = useResearchSurveyReadiness();
  const { state: chatReadiness, reload: reloadChatReadiness } = useChatReadiness();
  const { state: chatTasks, reload: reloadChatTasks } = useChatTasks();
  const [title, setTitle] = useState<string>("");
  const [kind, setKind] = useState<DraftKind>("survey");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [researchRuns, setResearchRuns] = useState<readonly ResearchRun[]>([]);
  const [researchRunsError, setResearchRunsError] = useState<Error | null>(null);
  const [researchRunsVersion, setResearchRunsVersion] = useState(0);
  const [cohortId, setCohortId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [items, setItems] = useState<readonly MatraixNativeBatchLaunchItem[]>([]);
  const [confirmed, setConfirmed] = useState<boolean>(false);
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });
  const controllerRef = useRef<AbortController | null>(null);
  const selectedProject = projects.status === "success"
    ? projects.data.items.find((project) => project.id === projectId) ?? null
    : null;
  const selectedRun = researchRuns.find((run) => run.id === runId) ?? null;
  const selectedCohort = cohorts.data?.items.find((cohort) => cohort.id === cohortId) ?? null;
  const selectedTask = chatTasks.items.find((task) => task.task_id === taskId) ?? null;
  const surveyReady = surveyReadiness.status === "success"
    && surveyReadiness.data.survey_runtime_ready;
  const chatReady = chatReadiness.status === "success"
    && chatReadiness.data.chat_runtime_ready
    && !chatReadiness.data.configuration_conflict;
  const requiredKinds = useMemo(() => new Set(items.map((item) => item.kind)), [items]);
  const runtimeReady = (!requiredKinds.has("survey") || surveyReady)
    && (!requiredKinds.has("chat") || chatReady);
  const submitting = submission.status === "submitting";
  const canAdd = items.length < 20
    && (kind === "survey"
      ? surveyReady && selectedProject !== null && selectedRun?.status === "succeeded"
      : chatReady && selectedCohort !== null && selectedCohort.persona_count <= 8
        && selectedTask !== null);
  const canSubmit = title.trim().length > 0
    && items.length > 0
    && runtimeReady
    && confirmed
    && !submitting;

  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    setRunId(null);
    setResearchRuns([]);
    setResearchRunsError(null);
    if (projectId === null) return;
    const controller = new AbortController();
    void fetchResearchRuns(projectId, controller.signal)
      .then((response) => setResearchRuns(response.items))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setResearchRunsError(error instanceof Error ? error : new Error("读取研究运行失败。"));
      });
    return () => controller.abort();
  }, [projectId, researchRunsVersion]);
  useEffect(() => {
    setConfirmed(false);
    setSubmission({ status: "idle" });
  }, [items]);

  const addItem = (): void => {
    if (!canAdd) return;
    const item: MatraixNativeBatchLaunchItem | null = kind === "survey"
      ? projectId !== null && runId !== null
        ? { kind: "survey", research_project_id: projectId, research_simulation_run_id: runId }
        : null
      : selectedTask === null || selectedCohort === null
        ? null
        : { kind: "chat", cohort_id: selectedCohort.id, task_id: selectedTask.task_id, task_version: selectedTask.version };
    if (item === null || items.some((existing) => itemKey(existing) === itemKey(item))) return;
    setItems((current) => [...current, item]);
  };

  const submit = (): void => {
    if (!canSubmit || controllerRef.current !== null) return;
    const request: MatraixNativeBatchLaunchRequest = { title: title.trim(), items: [...items] };
    const controller = new AbortController();
    controllerRef.current = controller;
    setSubmission({ status: "submitting" });
    const preflight: Promise<void>[] = [];
    if (requiredKinds.has("survey")) {
      preflight.push(fetchResearchSurveyReadiness(controller.signal).then((readiness) => {
        if (!readiness.survey_runtime_ready) {
          throw new Error("Survey runtime 在提交前已不可用；POST 尚未发送。");
        }
      }));
    }
    if (requiredKinds.has("chat")) {
      preflight.push(fetchChatReadiness(controller.signal).then((readiness) => {
        const tasksReady = request.items.filter((item) => item.kind === "chat").every(
          (item) => readiness.tasks.some((task) => task.task_id === item.task_id && task.version === item.task_version),
        );
        if (!readiness.chat_runtime_ready || readiness.configuration_conflict || !tasksReady) {
          throw new Error("Chat runtime 或任务规格在提交前已变化；POST 尚未发送。");
        }
      }));
    }
    void Promise.all(preflight)
      .then(() => createNativeBatchLaunch(request, controller.signal))
      .then((result) => {
        if (controller.signal.aborted || controllerRef.current !== controller) return;
        setTitle("");
        setItems([]);
        setConfirmed(false);
        setSubmission({ status: "idle" });
        onCreated(result.registry);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controllerRef.current !== controller) return;
        const normalized = error instanceof Error ? error : new Error("创建原生批次失败：请求抛出了非标准错误。");
        const ambiguous = isAmbiguousPostResultError(normalized);
        if (ambiguous) {
          setItems([]);
          onAmbiguous();
        }
        setConfirmed(false);
        setSubmission({ status: "error", error: normalized, ambiguous });
      })
      .finally(() => {
        if (controllerRef.current === controller) controllerRef.current = null;
      });
  };

  return (
    <aside className="batch-registry-composer batch-native-composer" aria-labelledby="batch-native-title">
      <header><span>SANDOWL / ATOMIC</span><h3 id="batch-native-title">创建并登记原生批次</h3><p>按冻结顺序创建研究 Survey / Chat 运行并封存批次；任一输入失败，整次请求回滚。</p></header>
      <div className="batch-native-readiness" aria-label="批量运行就绪状态"><span data-ready={surveyReady}>Survey {surveyReady ? "READY" : "LOCKED"}</span><span data-ready={chatReady}>Chat {chatReady ? "READY" : "LOCKED"}</span></div>
      {surveyReadiness.status === "error" ? <ApiErrorPanel title="无法核验 Survey runtime" error={surveyReadiness.error} isRetrying={surveyReadiness.isRetrying} onRetry={reloadSurveyReadiness} /> : null}
      {chatReadiness.status === "error" ? <ApiErrorPanel title="无法核验 Chat runtime" error={chatReadiness.error} isRetrying={chatReadiness.isRetrying} onRetry={reloadChatReadiness} /> : null}
      {projects.status === "error" ? <ApiErrorPanel title="无法读取研究项目" error={projects.error} isRetrying={false} onRetry={reloadProjects} /> : null}
      {researchRunsError !== null ? <ApiErrorPanel title="无法读取研究运行" error={researchRunsError} isRetrying={false} onRetry={() => setResearchRunsVersion((current) => current + 1)} /> : null}
      {cohorts.status === "error" ? <ApiErrorPanel title="无法读取 Cohort" error={cohorts.error} isRetrying={cohorts.isRetrying} onRetry={reloadCohorts} /> : null}
      {chatTasks.status === "error" ? <ApiErrorPanel title="无法读取 Chat tasks" error={chatTasks.error} isRetrying={chatTasks.isRetrying} onRetry={reloadChatTasks} /> : null}
      <label className="batch-registry-title" htmlFor="batch-native-title-input"><span>批次标题</span><input id="batch-native-title-input" name="batch_native_title" type="text" maxLength={200} value={title} disabled={submitting} onChange={(event) => setTitle(event.target.value)} /></label>
      <div className="batch-native-kind" role="group" aria-label="新增运行类型"><button type="button" aria-pressed={kind === "survey"} disabled={submitting} onClick={() => setKind("survey")}>Survey</button><button type="button" aria-pressed={kind === "chat"} disabled={submitting} onClick={() => setKind("chat")}>Chat</button></div>
      {kind === "survey" ? (
        <div className="batch-native-fields">
          <label htmlFor="batch-native-project"><span>研究项目</span><select id="batch-native-project" name="batch_native_project" value={projectId ?? ""} disabled={submitting} onChange={(event) => setProjectId(event.target.value || null)}><option value="">明确选择研究项目</option>{projects.status === "success" ? projects.data.items.map((project) => <option key={project.id} value={project.id}>{project.title}</option>) : null}</select></label>
          <label htmlFor="batch-native-run"><span>已成功运行</span><select id="batch-native-run" name="batch_native_run" value={runId ?? ""} disabled={submitting || projectId === null} onChange={(event) => setRunId(event.target.value || null)}><option value="">明确选择已成功运行</option>{researchRuns.filter((run) => run.status === "succeeded").map((run) => <option key={run.id} value={run.id}>{compactId(run.id)} · {run.cohort.persona_count} Persona</option>)}</select></label>
          <div className="batch-native-inherited"><span>继承 Cohort</span><strong>{selectedRun === null ? "由运行自动确定" : `${compactId(selectedRun.cohort.cohort_id)} · ${selectedRun.cohort.persona_count} Persona`}</strong></div>
        </div>
      ) : (
        <div className="batch-native-fields">
          <label htmlFor="batch-native-chat-cohort"><span>Cohort</span><select id="batch-native-chat-cohort" name="batch_native_chat_cohort" value={cohortId ?? ""} disabled={submitting} onChange={(event) => setCohortId(event.target.value || null)}><option value="">明确选择 1–8 Persona Cohort</option>{cohorts.data?.items.map((cohort) => <option key={cohort.id} value={cohort.id} disabled={cohort.persona_count > 8}>{cohort.title} · {cohort.persona_count}</option>)}</select></label>
          <label htmlFor="batch-native-task"><span>Chat task</span><select id="batch-native-task" name="batch_native_task" value={taskId ?? ""} disabled={submitting} onChange={(event) => setTaskId(event.target.value || null)}><option value="">明确选择 source sample</option>{chatTasks.items.map((task) => <option key={task.task_id} value={task.task_id}>{task.transport === "mcp_streamable_http" ? "MCP" : "REST"} · {task.title}</option>)}</select></label>
        </div>
      )}
      <button className="batch-native-add" type="button" disabled={!canAdd || submitting} onClick={addItem}>加入批次计划</button>
      <section className="batch-native-plan" aria-labelledby="batch-native-plan-title"><header><strong id="batch-native-plan-title">原子计划</strong><span>{items.length} / 20</span></header>{items.length === 0 ? <p>尚未加入运行；不会自动选择研究项目、运行、Cohort 或任务。</p> : <ol>{items.map((item, position) => <li key={itemKey(item)}><span>{String(position + 1).padStart(2, "0")} · {item.kind === "survey" ? "研究 Survey" : "Chat"}</span><code>{item.kind === "survey" ? `${compactId(item.research_project_id)} / ${compactId(item.research_simulation_run_id)}` : `${item.task_id.split("/").at(-1)} / ${compactId(item.cohort_id)}`}</code><button type="button" disabled={submitting} onClick={() => setItems((current) => current.filter((entry) => itemKey(entry) !== itemKey(item)))}>移除</button></li>)}</ol>}</section>
      <label className="batch-native-confirm"><input type="checkbox" checked={confirmed} disabled={items.length === 0 || !runtimeReady || submitting} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认这是 SandOwl 原生研究 Survey / Chat 入队；Survey 只观察单一冻结研究上下文，不创建或比较备选方案。</span></label>
      {submission.status === "error" ? <div className="batch-registry-submit-error" role="alert"><strong>{submission.ambiguous ? "结果存在歧义，已清除计划" : "原生批次未创建"}</strong><p>{submission.error.message}</p><small>{submission.ambiguous ? "目录已刷新，请先核对是否已经封存；不会自动重发 POST。" : "数据库已回滚整次请求，可修正输入后重新明确提交。"}</small></div> : null}
      <button className="batch-registry-submit" type="button" disabled={!canSubmit} onClick={submit}>{submitting ? "正在原子提交…" : "创建运行并封存 Registry"}</button>
      <p className="batch-registry-boundary">批次注册表仍是只读观测层；本入口只把 SandOwl 原生研究 Survey / Chat 创建动作合并成一个原子事务。</p>
    </aside>
  );
}
