import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { ChatEvaluationPage } from "./ChatEvaluationPage";
import { BatchRegistryPage } from "./BatchRegistryPage";
import type { CapabilityDescriptor } from "./systemCapabilities";
import {
  taskGalleryRootRoute,
  type TaskGalleryRoute,
} from "./taskGalleryRoute";
import {
  evaluateTaskAvailability,
  type RuntimeReadinessByKind,
  type RuntimeReadinessProbe,
  type TaskAvailability,
  type TaskAvailabilityDecision,
  type TaskRuntimeKind,
} from "./taskRuntimeReadiness";
import {
  useSemanticReadiness,
  type SemanticReadinessLoadState,
} from "./useSemanticExperiments";
import { useResearchSurveyReadiness, type ResearchSurveyReadinessLoadState } from "./useResearchSurveys";
import { useSystemCapabilities } from "./useSystemCapabilities";
import { SurveyPlaygroundPage } from "./SurveyPlaygroundPage";
import { TrialArchivePage } from "./TrialArchivePage";
import { WebEvaluationPage } from "./WebEvaluationPage";
import { LinuxArtifactPage } from "./LinuxArtifactPage";
import { ResearchEvaluationTargetsPanel } from "./ResearchEvaluationTargetsPanel";
import {
  useChatReadiness,
  type ChatReadinessLoadState,
} from "./useChatEvaluations";
import { useWebReadiness, type WebReadinessLoadState } from "./useWebEvaluations";
import { useLinuxReadiness } from "./useLinuxArtifacts";
import "./taskGallery.css";
import {
  createResearchEvaluationTaskBundle,
  fetchResearchEvaluationWorkspace,
  type ResearchEvaluationWorkspace,
} from "./researchEvaluationContracts";

type TaskKind = "survey" | "chat" | "archive" | "web" | "app" | "linux" | "batch";

interface TaskDefinition {
  readonly id: string;
  readonly kind: TaskKind;
  readonly eyebrow: string;
  readonly title: string;
  readonly summary: string;
  readonly source: string;
  readonly capabilityName: string;
  readonly expectedState: "runtime_ready" | "contract_ready";
  readonly readinessKind: TaskRuntimeKind | null;
  readonly output: string;
  readonly href: string | null;
}

const taskDefinitions: readonly TaskDefinition[] = [
  {
    id: "survey-task",
    kind: "survey",
    eyebrow: "合成人群 / 问卷",
    title: "单一研究上下文问卷",
    summary: "把一次已完成模拟及其冻结人群编译为固定问卷，逐个人物记录清晰度、关注点和未解问题。",
    source: "SandOwl 原生研究问卷",
    capabilityName: "tasks.matraix.survey",
    expectedState: "runtime_ready",
    readinessKind: "survey",
    output: "typed responses · exact counts · provenance",
    href: "#/tasks?task=survey",
  },
  {
    id: "chat-task",
    kind: "chat",
    eyebrow: "合成人群 / 对话",
    title: "对话系统评测",
    summary: "冻结合成人群，让每个人物通过 REST 或 MCP 固定样例完成真实多轮对话并封存逐条证据。",
    source: "SandOwl 对话评测",
    capabilityName: "tasks.matraix.chat",
    expectedState: "runtime_ready",
    readinessKind: "chat",
    output: "transcript · ATIF-v1.7 projection · self-report · provenance",
    href: "#/tasks?task=chat",
  },
  {
    id: "trial-archive",
    kind: "archive",
    eyebrow: "统一试验档案",
    title: "试验档案",
    summary: "统一检索已持久化的问卷、对话、网页与 Linux 试验，并逐条核对状态、人物、错误和运行来源。",
    source: "SandOwl 持久试验记录",
    capabilityName: "trials.matraix.archive",
    expectedState: "runtime_ready",
    readinessKind: "archive",
    output: "真实状态 · 精确聚合 · Persona · provenance · error",
    href: "#/tasks?task=trials&page=1",
  },
  {
    id: "persona-interview-task",
    kind: "chat",
    eyebrow: "单次运行 / 报告追问",
    title: "报告追问",
    summary: "围绕一份原生单次运行引用报告继续追问；回答必须引用报告中的冻结内容，不创建方案比较。",
    source: "SandOwl 引用报告",
    capabilityName: "agent_interactions",
    expectedState: "runtime_ready",
    readinessKind: "semantic",
    output: "cited answer · bounded follow-up · content hashes",
    href: "#/reports",
  },
  {
    id: "web-task",
    kind: "web",
    eyebrow: "隔离浏览器 / 网页",
    title: "网页任务评测",
    summary: "固定来源样例由隔离 Chromium 读取真实 DOM 与三页截图，再由冻结人物从实际观察到的引文中完成选择。",
    source: "SandOwl 网页评测",
    capabilityName: "tasks.matraix.web",
    expectedState: "runtime_ready",
    readinessKind: "web",
    output: "真实 DOM · screenshots · observed quote · Persona choice",
    href: "#/tasks?task=web&page=1",
  },
  {
    id: "linux-artifact-task",
    kind: "linux",
    eyebrow: "隔离运行器 / LINUX",
    title: "Note → CSV 固定产物评测",
    summary: "千问生成受约束解释与合成反馈，隔离 Runner 写入并校验固定产物，并将单个真实 Trial 封存为可登记的 Evaluation 父资源。",
    source: "SandOwl Linux 产物评测",
    capabilityName: "tasks.matraix.linux_artifact",
    expectedState: "runtime_ready",
    readinessKind: "linux",
    output: "verified CSV · fixed artifacts · content hashes · Persona feedback",
    href: "#/tasks?task=linux&page=1",
  },
  {
    id: "app-task",
    kind: "app",
    eyebrow: "隔离应用 / HARBOR",
    title: "App 任务评测",
    summary: "把当前研究与受许可的 MatrAIx Harbor Task Package 绑定，在独立 Rootless DinD 中运行并封存轨迹、产物、校验和评分。",
    source: "SandOwl + MatrAIx Harbor",
    capabilityName: "tasks.matraix.app",
    expectedState: "runtime_ready",
    readinessKind: "archive",
    output: "trajectory · artifacts · verifier · reward",
    href: null,
  },
  {
    id: "batch-registry",
    kind: "batch",
    eyebrow: "批量试验 / 注册表",
    title: "批量试验注册表",
    summary: "一次原子提交创建 SandOwl 原生问卷或对话父运行并封存不可变目录，也可登记已有网页或 Linux 评测。",
    source: "SandOwl 批量试验记录",
    capabilityName: "jobs.matraix.batch_registry",
    expectedState: "runtime_ready",
    readinessKind: "archive",
    output: "atomic native enqueue · sealed membership · exact observed counts",
    href: "#/tasks?task=batch&page=1",
  },
];

const taskKindLabels: Readonly<Record<TaskKind | "all", string>> = {
  all: "全部",
  survey: "问卷",
  chat: "对话",
  archive: "档案",
  web: "网页",
  app: "App",
  linux: "Linux",
  batch: "批次",
};

const bundleExecutionLabel = {
  queued: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
} as const;

const bundleVerifierLabel = {
  pending: "等待校验",
  passed: "已通过",
  failed: "未通过",
} as const;

const bundleArtifactLabel = {
  unavailable: "尚无产物",
  partial: "部分产物",
  sealed: "已封存",
} as const;

function capabilityByName(
  capabilities: readonly CapabilityDescriptor[],
  name: string,
): CapabilityDescriptor | null {
  return capabilities.find((capability) => capability.name === name) ?? null;
}

function nonNullReason(reason: string | null): reason is string {
  return reason !== null;
}

function safeReason(reasons: readonly (string | null)[], genericReason: string): string {
  const presentReasons = reasons.filter(nonNullReason);

  return presentReasons.length === 0
    ? genericReason
    : `${presentReasons.join("；")}。`;
}

function semanticReadinessProbe(
  state: SemanticReadinessLoadState,
): RuntimeReadinessProbe {
  if (state.status === "loading") {
    return { status: "loading" };
  }

  if (state.status === "error") {
    return {
      status: "error",
      reason: `无法完成 semantic readiness 核验：${state.error.message}`,
    };
  }

  if (state.data.semantic_runtime_ready) {
    return { status: "ready" };
  }

  const hasCompleteConfiguration = state.data.model_name !== null
    && state.data.semantic_config_sha256 !== null
    && state.data.prompt_schema_version !== null;

  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线的模拟运行 worker",
        state.data.configuration_conflict ? "检测到不一致的语义运行配置" : null,
        hasCompleteConfiguration ? null : "在线 worker 未暴露完整语义模型配置",
      ],
      "semantic_runtime_ready 未通过后端核验。",
    ),
  };
}

function surveyReadinessProbe(
  state: ResearchSurveyReadinessLoadState,
): RuntimeReadinessProbe {
  if (state.status === "loading" || (state.status === "error" && state.isRetrying)) {
    return { status: "loading" };
  }

  if (state.status === "error") {
    return {
      status: "error",
      reason: `无法完成 Survey readiness 核验：${state.error.message}`,
    };
  }

  if (state.data.survey_runtime_ready) {
    return { status: "ready" };
  }

  return {
    status: "unready",
    reason: state.data.live_worker_count === 0
      ? "没有在线的原生 Survey evaluation worker。"
      : "原生 Survey worker 未暴露完整一致的运行配置。",
  };
}

function chatReadinessProbe(
  state: ChatReadinessLoadState,
): RuntimeReadinessProbe {
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") {
    return {
      status: "error",
      reason: `无法完成 Chat readiness 核验：${state.error.message}`,
    };
  }
  if (state.data.chat_runtime_ready) return { status: "ready" };

  const hasCompleteConfiguration = state.data.model_name !== null
    && state.data.chat_config_sha256 !== null
    && state.data.prompt_schema_version !== null;
  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线 Chat worker",
        state.data.configuration_conflict ? "检测到不一致的 Chat 运行配置" : null,
        hasCompleteConfiguration ? null : "在线 worker 未暴露完整 Chat 模型配置",
      ],
      "chat_runtime_ready 未通过后端核验。",
    ),
  };
}

function webReadinessProbe(state: WebReadinessLoadState): RuntimeReadinessProbe {
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") {
    return { status: "error", reason: `无法完成 Web readiness 核验：${state.error.message}` };
  }
  if (state.data.web_runtime_ready) return { status: "ready" };
  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线 Web worker",
        state.data.configuration_conflict ? "检测到不一致的 Web 运行配置" : null,
        state.data.model_name === null ? "在线 worker 未暴露完整千问与浏览器配置" : null,
      ],
      "web_runtime_ready 未通过后端核验。",
    ),
  };
}

function linuxReadinessProbe(
  state: ReturnType<typeof useLinuxReadiness>["state"],
): RuntimeReadinessProbe {
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") {
    return { status: "error", reason: `无法完成 Linux readiness 核验：${state.error.message}` };
  }
  if (state.data.linux_runtime_ready) return { status: "ready" };
  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线 Linux worker",
        state.data.configuration_conflict ? "检测到不一致的 Linux 运行配置" : null,
        state.data.model_name === null ? "在线 worker 未暴露完整千问与 Runner 配置" : null,
      ],
      "linux_runtime_ready 未通过后端核验。",
    ),
  };
}

function availabilityDecision(
  definition: TaskDefinition,
  capabilities: readonly CapabilityDescriptor[],
  readiness: RuntimeReadinessByKind,
): TaskAvailabilityDecision {
  const capability = capabilityByName(capabilities, definition.capabilityName);

  return evaluateTaskAvailability(
    {
      expectedState: definition.expectedState,
      readinessKind: definition.readinessKind,
    },
    capability?.state ?? null,
    readiness,
  );
}

function statusLabel(value: TaskAvailability): string {
  if (value === "runtime") return "可运行";
  if (value === "verifying") return "核验中";
  if (value === "unready") return "运行时未就绪";
  if (value === "contract") return "仅契约";
  return "未接通";
}

function lockedTitle(value: TaskAvailability): string {
  if (value === "verifying") return "正在核验运行时";
  if (value === "unready") return "运行时未就绪";
  if (value === "contract") return "执行器尚未接通";
  if (value === "missing") return "当前后端没有该 capability";
  return "运行入口未配置";
}

function TaskGalleryCatalog({
  projectId,
  runId,
}: {
  readonly projectId: string | null;
  readonly runId: string | null;
}): JSX.Element {
  const { state, reload: reloadCapabilities } = useSystemCapabilities();
  const {
    state: semanticReadinessState,
    reload: reloadSemanticReadiness,
  } = useSemanticReadiness();
  const {
    state: surveyReadinessState,
    reload: reloadSurveyReadiness,
  } = useResearchSurveyReadiness();
  const {
    state: chatReadinessState,
    reload: reloadChatReadiness,
  } = useChatReadiness();
  const { state: webReadinessState, reload: reloadWebReadiness } = useWebReadiness();
  const { state: linuxReadinessState, reload: reloadLinuxReadiness } = useLinuxReadiness();
  const [kind, setKind] = useState<TaskKind | "all">("all");
  const [query, setQuery] = useState<string>("");
  const [workspace, setWorkspace] = useState<ResearchEvaluationWorkspace | null>(null);
  const [workspaceError, setWorkspaceError] = useState<Error | null>(null);
  const [bundleSubmitting, setBundleSubmitting] = useState(false);
  const [bundleError, setBundleError] = useState<Error | null>(null);
  const loadWorkspace = useCallback(async (signal: AbortSignal): Promise<void> => {
    if (projectId === null || runId === null) {
      setWorkspace(null);
      setWorkspaceError(null);
      return;
    }
    try {
      setWorkspace(await fetchResearchEvaluationWorkspace(projectId, runId, signal));
      setWorkspaceError(null);
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setWorkspaceError(
          reason instanceof Error ? reason : new Error("读取研究评测上下文失败"),
        );
      }
    }
  }, [projectId, runId]);
  useEffect(() => {
    const controller = new AbortController();
    void loadWorkspace(controller.signal);
    return () => controller.abort();
  }, [loadWorkspace]);
  const prepareTaskBundle = async (): Promise<void> => {
    if (projectId === null || runId === null || bundleSubmitting) return;
    const controller = new AbortController();
    setBundleSubmitting(true);
    setBundleError(null);
    try {
      await createResearchEvaluationTaskBundle(projectId, runId, controller.signal);
      await loadWorkspace(controller.signal);
    } catch (reason: unknown) {
      setBundleError(
        reason instanceof Error ? reason : new Error("准备研究评测任务包失败"),
      );
    } finally {
      setBundleSubmitting(false);
    }
  };
  const refreshWorkspace = async (): Promise<void> => {
    const controller = new AbortController();
    await loadWorkspace(controller.signal);
  };
  const capabilities = state.status === "success" ? state.data.capabilities : [];
  const readiness = useMemo<RuntimeReadinessByKind>(
    () => ({
      platform: { status: "unready", reason: "历史平台验证入口只读。" },
      semantic: semanticReadinessProbe(semanticReadinessState),
      survey: surveyReadinessProbe(surveyReadinessState),
      chat: chatReadinessProbe(chatReadinessState),
      web: webReadinessProbe(webReadinessState),
      linux: linuxReadinessProbe(linuxReadinessState),
      archive: { status: "ready" },
    }),
    [chatReadinessState, linuxReadinessState, semanticReadinessState, surveyReadinessState, webReadinessState],
  );
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const tasks = useMemo(
    () => taskDefinitions.filter((task) => {
      const matchesKind = kind === "all" || task.kind === kind;
      const matchesQuery = normalizedQuery === ""
        || `${task.title}\n${task.summary}\n${task.source}`.toLocaleLowerCase().includes(normalizedQuery);
      return matchesKind && matchesQuery;
    }),
    [kind, normalizedQuery],
  );
  const runtimeCount = taskDefinitions.filter(
    (task) => availabilityDecision(task, capabilities, readiness).availability === "runtime",
  ).length;
  const taskBundle = workspace?.task_bundles.at(0) ?? null;
  const isVerifying = state.status === "loading"
    || (state.status === "error" && state.isRetrying)
    || readiness.semantic.status === "loading"
    || readiness.survey.status === "loading"
    || readiness.chat.status === "loading"
    || readiness.web.status === "loading"
    || readiness.linux.status === "loading";
  const reloadAll = useCallback((): void => {
    reloadCapabilities();
    reloadSemanticReadiness();
    reloadSurveyReadiness();
    reloadChatReadiness();
    reloadWebReadiness();
    reloadLinuxReadiness();
  }, [
    reloadCapabilities,
    reloadSemanticReadiness,
    reloadSurveyReadiness,
    reloadChatReadiness,
    reloadWebReadiness,
    reloadLinuxReadiness,
  ]);

  return (
    <div className="task-gallery-page">
      <header className="task-gallery-hero">
        <div>
          <span>SANDOWL / 评测中心</span>
          <h1>选择一个真实可执行的评测任务</h1>
          <p>任务卡同时核验后端 capability、在线 worker 与对应运行时 readiness。任何一层未通过时都会保留安全原因，但不会显示假启动按钮。</p>
        </div>
        <dl>
          <div><dt>目录任务</dt><dd>{taskDefinitions.length}</dd></div>
          <div><dt>当前可运行</dt><dd>{state.status === "success" ? runtimeCount : "—"}</dd></div>
          <div><dt>能力来源</dt><dd>{state.status === "success" ? state.data.api_version : "核验中"}</dd></div>
        </dl>
      </header>

      {projectId !== null && runId !== null ? (
        <section className="task-gallery-research-scope" aria-label="当前研究评测上下文">
          {workspaceError !== null ? (
            <ApiErrorPanel title="无法核验当前研究评测上下文" error={workspaceError} isRetrying={false} onRetry={() => window.location.reload()} />
          ) : workspace === null ? (
            <p role="status">正在核验 Project / Run / Cohort…</p>
          ) : (
            <>
              <div><span>当前研究主链</span><h3>{workspace.project.title}</h3><p>成功 Run 与 {workspace.cohort.persona_count} 人冻结 Cohort 已通过身份核验。</p></div>
              <dl><div><dt>可原生启动</dt><dd>{workspace.capabilities.filter((item) => item.can_launch_for_scope).length} / {workspace.capabilities.length}</dd></div><div><dt>Persona 可用档案</dt><dd>{workspace.persona_quality.populated_profile_count} / {workspace.persona_quality.profile_count}<small>每人 {workspace.persona_quality.minimum_dimension_count}–{workspace.persona_quality.maximum_dimension_count} 个有效维度</small></dd></div></dl>
              <p className="task-gallery-scope-warning">Chat / Web / App 必须先封存当前研究的被测对象或 Harbor Task；提交后由独立 Rootless DinD 执行。旧 Acme、Quotes 与 Linux 固定样例仍只用于历史验证。</p>
              <section className="task-gallery-task-bundle" aria-label="当前研究评测任务包">
                {taskBundle === null ? <>
                  <div><strong>Survey 任务包尚未封存</strong><p>先把当前 Project、Run、Cohort、Persona 档案哈希和固定问卷编译成不可变输入。此操作不调用模型，也不启动评测。</p></div>
                  <button type="button" disabled={bundleSubmitting} onClick={() => { void prepareTaskBundle(); }}>{bundleSubmitting ? "正在准备…" : "准备 Survey 任务包"}</button>
                </> : <>
                  <div><strong>已封存 Survey 任务包 · {taskBundle.payload.persona_profile_sha256s.length} 人</strong><p>结构校验、观察轨迹、类型化产物和“不适用评分”政策均已固定。</p></div>
                  <dl><div><dt>执行</dt><dd>{taskBundle.execution === null ? "尚未启动" : bundleExecutionLabel[taskBundle.execution.status]}</dd></div><div><dt>校验</dt><dd>{taskBundle.execution === null ? "等待执行" : bundleVerifierLabel[taskBundle.execution.verifier_state]}</dd></div><div><dt>产物</dt><dd>{taskBundle.execution === null ? "等待执行" : bundleArtifactLabel[taskBundle.execution.artifact_state]}</dd></div></dl>
                </>}
                {bundleError !== null ? <p className="task-gallery-task-bundle-error" role="alert">{bundleError.message}</p> : null}
              </section>
              <ResearchEvaluationTargetsPanel projectId={workspace.project.id} runId={workspace.run.id} targets={workspace.targets} jobs={workspace.jobs} onChanged={refreshWorkspace} />
            </>
          )}
        </section>
      ) : null}

      <section className="task-gallery-controls" aria-label="评测任务筛选">
        <label htmlFor="task-gallery-query"><span>搜索任务</span><input id="task-gallery-query" name="task_query" type="search" value={query} placeholder="名称、能力或来源" onChange={(event) => setQuery(event.target.value)} /></label>
        <nav aria-label="任务类型">
          {(Object.keys(taskKindLabels) as readonly (TaskKind | "all")[]).map((item) => (
            <button key={item} type="button" aria-pressed={kind === item} onClick={() => setKind(item)}>{taskKindLabels[item]}</button>
          ))}
        </nav>
        <button type="button" disabled={isVerifying} onClick={reloadAll}>{isVerifying ? "核验中…" : "刷新能力与运行时"}</button>
      </section>

      {state.status === "error" ? <ApiErrorPanel title="无法核验任务能力" error={state.error} isRetrying={state.isRetrying} onRetry={reloadAll} /> : null}
      {state.status === "loading" ? <div className="task-gallery-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}

      <section className="task-gallery-stage" aria-labelledby="task-gallery-stage-title">
        <header><div><span>CATALOG / VERIFIED</span><h3 id="task-gallery-stage-title">跨类型任务目录</h3></div><p>{tasks.length} / {taskDefinitions.length} 项</p></header>
        {state.status === "success" && tasks.length > 0 ? (
          <ul className="task-gallery-grid">
            {tasks.map((task) => {
              const decision = availabilityDecision(task, capabilities, readiness);
              const taskAvailability = decision.availability;
              const capability = capabilityByName(capabilities, task.capabilityName);
              const canInspectLinuxBoundary = task.id === "linux-artifact-task"
                && capability?.state === "runtime_ready";
              const scopedCapability = workspace?.capabilities.find((item) => item.kind === task.kind) ?? null;
              const blockedByResearchScope = workspace !== null
                && ["chat-task", "web-task", "app-task", "linux-artifact-task"].includes(task.id)
                && scopedCapability?.can_launch_for_scope !== true;
              const scopedHref = workspace !== null && task.id === "persona-interview-task"
                  ? `#/reports?project_id=${encodeURIComponent(workspace.project.id)}&run_id=${encodeURIComponent(workspace.run.id)}`
                  : workspace !== null && task.kind === "app"
                    ? `#/tasks?project_id=${encodeURIComponent(workspace.project.id)}&run_id=${encodeURIComponent(workspace.run.id)}`
                    : workspace !== null && task.href !== null
                      ? `${task.href}&project_id=${encodeURIComponent(workspace.project.id)}&run_id=${encodeURIComponent(workspace.run.id)}`
                      : task.href;
              return (
                <li key={task.id} data-availability={taskAvailability}>
                  <header><span>{task.eyebrow}</span><strong>{statusLabel(taskAvailability)}</strong></header>
                  <h4>{task.title}</h4>
                  <p>{task.summary}</p>
                  <dl><div><dt>来源</dt><dd>{task.source}</dd></div><div><dt>输出</dt><dd>{task.output}</dd></div></dl>
                  <details><summary>技术契约</summary><dl><div><dt>运行能力</dt><dd><code>{task.capabilityName}</code></dd></div>{capability !== null ? <div><dt>数据契约</dt><dd>{capability.contracts.join(" · ")}</dd></div> : null}</dl></details>
                  {blockedByResearchScope ? <div className="task-gallery-locked" role="note"><strong>尚未绑定当前研究</strong><small>{scopedCapability?.explanation}</small></div> : (taskAvailability === "runtime" || canInspectLinuxBoundary) && scopedHref !== null ? <a href={scopedHref}>{task.id === "trial-archive" ? "打开试验档案 →" : task.id === "batch-registry" ? "打开批量注册表 →" : task.id === "persona-interview-task" && workspace !== null ? "打开当前报告追问 →" : task.kind === "app" && workspace !== null ? "打开当前研究执行区 →" : canInspectLinuxBoundary && taskAvailability !== "runtime" ? "查看固定任务边界 →" : task.kind === "survey" && workspace !== null ? "用当前 Run 启动 Survey →" : "打开评测 →"}</a> : <div className="task-gallery-locked" role="note"><strong>{lockedTitle(taskAvailability)}</strong><small>{decision.reason}</small></div>}
                </li>
              );
            })}
          </ul>
        ) : null}
        {state.status === "success" && tasks.length === 0 ? <div className="task-gallery-empty"><strong>没有匹配任务</strong><p>调整任务类型或搜索词。</p></div> : null}
      </section>
    </div>
  );
}

export function TaskGalleryPage({
  route,
  onRouteChange,
}: {
  readonly route: TaskGalleryRoute;
  readonly onRouteChange: (route: TaskGalleryRoute) => void;
}): JSX.Element {
  const scopedRootRoute = (): TaskGalleryRoute => ({
    ...taskGalleryRootRoute(),
    projectId: route.projectId ?? null,
    runId: route.runId ?? null,
  });

  if (route.task === "survey") {
    return (
      <SurveyPlaygroundPage
        initialProjectId={route.projectId ?? null}
        initialRunId={route.runId ?? null}
        page={route.page ?? 1}
        initialExperimentId={route.experimentId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange({ ...taskGalleryRootRoute(), projectId: route.projectId ?? null, runId: route.runId ?? null })}
        onSelectionChange={(page, experimentId, trialId) => {
          onRouteChange({
            task: "survey",
            projectId: route.projectId ?? null,
            runId: route.runId ?? null,
            experimentId,
            evaluationId: null,
            trialId,
            registryId: null,
            archiveKind: null,
            archiveStatus: null,
            page,
          });
        }}
      />
    );
  }

  if (route.task === "chat") {
    return (
      <ChatEvaluationPage
        page={route.page ?? 1}
        initialEvaluationId={route.evaluationId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange(scopedRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "chat",
            projectId: route.projectId ?? null,
            runId: route.runId ?? null,
            experimentId: null,
            evaluationId,
            trialId,
            registryId: null,
            archiveKind: null,
            archiveStatus: null,
            page,
          });
        }}
      />
    );
  }

  if (route.task === "web") {
    return (
      <WebEvaluationPage
        page={route.page ?? 1}
        initialEvaluationId={route.evaluationId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange(scopedRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "web",
            projectId: route.projectId ?? null,
            runId: route.runId ?? null,
            experimentId: null,
            evaluationId,
            trialId,
            registryId: null,
            archiveKind: null,
            archiveStatus: null,
            page,
          });
        }}
      />
    );
  }

  if (route.task === "trials") {
    return (
      <TrialArchivePage
        route={route}
        onBack={() => onRouteChange(scopedRootRoute())}
        onRouteChange={(nextRoute) => onRouteChange({
          ...nextRoute,
          projectId: route.projectId ?? null,
          runId: route.runId ?? null,
        })}
      />
    );
  }

  if (route.task === "linux") {
    return (
      <LinuxArtifactPage
        page={route.page ?? 1}
        initialEvaluationId={route.evaluationId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange(scopedRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "linux",
            projectId: route.projectId ?? null,
            runId: route.runId ?? null,
            experimentId: null,
            evaluationId,
            trialId,
            registryId: null,
            archiveKind: null,
            archiveStatus: null,
            page,
          });
        }}
      />
    );
  }

  if (route.task === "batch") {
    return (
      <BatchRegistryPage
        route={route}
        onBack={() => onRouteChange(scopedRootRoute())}
        onRouteChange={(nextRoute) => onRouteChange({
          ...nextRoute,
          projectId: route.projectId ?? null,
          runId: route.runId ?? null,
        })}
      />
    );
  }

  return <TaskGalleryCatalog projectId={route.projectId ?? null} runId={route.runId ?? null} />;
}
