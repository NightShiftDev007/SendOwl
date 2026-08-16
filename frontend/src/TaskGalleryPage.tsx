import { useCallback, useMemo, useState } from "react";

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
  useOasisReadiness,
  type OasisReadinessLoadState,
} from "./useOasisRuns";
import {
  useSemanticReadiness,
  type SemanticReadinessLoadState,
} from "./useSemanticExperiments";
import { useSurveyReadiness } from "./useSurveyExperiments";
import { useSystemCapabilities } from "./useSystemCapabilities";
import { SurveyPlaygroundPage } from "./SurveyPlaygroundPage";
import { TrialArchivePage } from "./TrialArchivePage";
import { WebEvaluationPage } from "./WebEvaluationPage";
import { LinuxArtifactPage } from "./LinuxArtifactPage";
import {
  useChatReadiness,
  type ChatReadinessLoadState,
} from "./useChatEvaluations";
import { useWebReadiness, type WebReadinessLoadState } from "./useWebEvaluations";
import { useLinuxReadiness } from "./useLinuxArtifacts";
import "./taskGallery.css";

type TaskKind = "social" | "survey" | "chat" | "archive" | "web" | "linux" | "os_app" | "batch";
type SurveyReadinessLoadState = ReturnType<typeof useSurveyReadiness>["state"];

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
    id: "semantic-social-experiment",
    kind: "social",
    eyebrow: "OASIS / SEMANTIC",
    title: "基线与备选方案群体实验",
    summary: "将封存 Scenario 与 MatrAIx Cohort 组成 Variant × Seed 矩阵，运行真实 LLM Persona 动作。",
    source: "MatrAIx Persona + OASIS",
    capabilityName: "simulations.oasis",
    expectedState: "runtime_ready",
    readinessKind: "semantic",
    output: "类型化事件 · SQLite artifact · paired counts",
    href: "#/runs?mode=semantic",
  },
  {
    id: "platform-smoke",
    kind: "social",
    eyebrow: "OASIS / PLATFORM",
    title: "Reddit 平台接线验证",
    summary: "不读取 Cohort、不调用 LLM，仅验证 OASIS Reddit、队列、SQLite 与手工 CREATE_POST。",
    source: "OASIS",
    capabilityName: "simulations.oasis",
    expectedState: "runtime_ready",
    readinessKind: "platform",
    output: "平台生命周期 · artifact integrity",
    href: "#/runs?mode=platform",
  },
  {
    id: "survey-task",
    kind: "survey",
    eyebrow: "MATRAIX / SURVEY",
    title: "Survey Persona Trial",
    summary: "把封存 Scenario 与 1–8 Persona Cohort 编译为固定问卷，由千问逐 Persona 返回严格类型化回答。",
    source: "MatrAIx Playground",
    capabilityName: "tasks.matraix.survey",
    expectedState: "runtime_ready",
    readinessKind: "survey",
    output: "typed responses · exact counts · provenance",
    href: "#/tasks?task=survey",
  },
  {
    id: "chat-task",
    kind: "chat",
    eyebrow: "MATRAIX / CHAT",
    title: "Chatbot Evaluation",
    summary: "冻结 Cohort，让每个合成 Persona 显式通过 REST 或 MCP Acme source sample 完成真实多轮对话并封存逐条证据。",
    source: "MatrAIx Playground · Acme REST + MCP source samples",
    capabilityName: "tasks.matraix.chat",
    expectedState: "runtime_ready",
    readinessKind: "chat",
    output: "transcript · ATIF-v1.7 projection · self-report · provenance",
    href: "#/tasks?task=chat",
  },
  {
    id: "trial-archive",
    kind: "archive",
    eyebrow: "MATRAIX / ARCHIVE",
    title: "Unified Trial Archive",
    summary: "统一检索本库已持久化的 Survey、Chat、Web 与 Linux Trial，并逐条核对状态、Persona、错误和运行 provenance。",
    source: "MatrAIx Survey + Chat + Web + Linux durable records",
    capabilityName: "trials.matraix.archive",
    expectedState: "runtime_ready",
    readinessKind: "archive",
    output: "真实状态 · 精确聚合 · Persona · provenance · error",
    href: "#/tasks?task=trials&page=1",
  },
  {
    id: "persona-interview-task",
    kind: "chat",
    eyebrow: "MIROFISH / PERSONA INTERVIEW",
    title: "Persona 证据访谈",
    summary: "选择报告绑定 Cohort 中的冻结 Persona，进行单人追问或一次封存 2–8 人的同问题会话；回答只引用报告章节。",
    source: "MiroFish Interaction + MatrAIx Persona + Qwen",
    capabilityName: "tasks.mirofish.persona_interview",
    expectedState: "runtime_ready",
    readinessKind: "semantic",
    output: "single / group session · section citations · content hashes",
    href: "#/reports",
  },
  {
    id: "web-task",
    kind: "web",
    eyebrow: "MATRAIX / WEB",
    title: "Web Agent Evaluation",
    summary: "固定来源样例由隔离 Chromium 读取真实 DOM 与三页截图，再由冻结 Persona 从实际观察到的引文中完成选择。",
    source: "MatrAIx Playground",
    capabilityName: "tasks.matraix.web",
    expectedState: "runtime_ready",
    readinessKind: "web",
    output: "真实 DOM · screenshots · observed quote · Persona choice",
    href: "#/tasks?task=web&page=1",
  },
  {
    id: "linux-artifact-task",
    kind: "linux",
    eyebrow: "MATRAIX / LINUX SOURCE SAMPLE",
    title: "Note → CSV Artifact Evaluation",
    summary: "千问生成受约束解释与合成反馈，隔离 Runner 写入并校验固定产物，并将单个真实 Trial 封存为可登记的 Evaluation 父资源。",
    source: "MatrAIx Playground fixed Linux source sample",
    capabilityName: "tasks.matraix.linux_artifact",
    expectedState: "runtime_ready",
    readinessKind: "linux",
    output: "verified CSV · fixed artifacts · content hashes · Persona feedback",
    href: "#/tasks?task=linux&page=1",
  },
  {
    id: "os-app-task",
    kind: "os_app",
    eyebrow: "MATRAIX / OS APP",
    title: "OS App Evaluation",
    summary: "桌面应用环境、Computer Use 轨迹与录屏产物尚未进入当前部署拓扑。",
    source: "MatrAIx Playground",
    capabilityName: "tasks.matraix.os_app",
    expectedState: "runtime_ready",
    readinessKind: null,
    output: "待接：actions · recording · result",
    href: null,
  },
  {
    id: "batch-registry",
    kind: "batch",
    eyebrow: "MATRAIX / BATCH REGISTRY",
    title: "MatrAIx Batch Registry",
    summary: "一次原子提交创建 SendOwl-native Survey / Chat 父运行并封存不可变目录，也可登记已有 Web / Linux Evaluation。",
    source: "MatrAIx durable Survey + Chat + Web + Linux parent records",
    capabilityName: "jobs.matraix.batch_registry",
    expectedState: "runtime_ready",
    readinessKind: "archive",
    output: "atomic native enqueue · sealed membership · exact observed counts",
    href: "#/tasks?task=batch&page=1",
  },
  {
    id: "harbor-batch",
    kind: "batch",
    eyebrow: "MATRAIX / HARBOR",
    title: "Harbor 批量 Trial",
    summary: "完整 Harbor 执行器尚未迁移；原生 Survey/Chat 原子入队不等于 Harbor Docker/Web/OS 执行面。",
    source: "MatrAIx Harbor",
    capabilityName: "tasks.matraix.harbor",
    expectedState: "runtime_ready",
    readinessKind: null,
    output: "待接：launch · retry · verifier · artifacts · authorized export",
    href: null,
  },
];

const taskKindLabels: Readonly<Record<TaskKind | "all", string>> = {
  all: "全部",
  social: "Social",
  survey: "Survey",
  chat: "Chat",
  archive: "Archive",
  web: "Web",
  linux: "Linux",
  os_app: "OS App",
  batch: "批次",
};

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

function platformReadinessProbe(
  state: OasisReadinessLoadState,
): RuntimeReadinessProbe {
  if (state.status === "loading" || (state.status === "error" && state.isRetrying)) {
    return { status: "loading" };
  }

  if (state.status === "error") {
    return {
      status: "error",
      reason: `无法完成 OASIS platform readiness 核验：${state.error.message}`,
    };
  }

  if (state.data.worker_online && state.data.platform_runtime_ready) {
    return { status: "ready" };
  }

  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线 OASIS worker",
        state.data.platform_runtime_ready ? null : "platform_runtime_ready 未通过",
      ],
      "OASIS platform runtime 未通过后端 readiness 核验。",
    ),
  };
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
        state.data.worker_online ? null : "没有在线 OASIS worker",
        state.data.configuration_conflict ? "检测到不一致的语义运行配置" : null,
        hasCompleteConfiguration ? null : "在线 worker 未暴露完整语义模型配置",
      ],
      "semantic_runtime_ready 未通过后端核验。",
    ),
  };
}

function surveyReadinessProbe(
  state: SurveyReadinessLoadState,
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

  const hasCompleteConfiguration = state.data.model_name !== null
    && state.data.survey_config_sha256 !== null
    && state.data.prompt_schema_version !== null;

  return {
    status: "unready",
    reason: safeReason(
      [
        state.data.worker_online ? null : "没有在线 Survey worker",
        state.data.configuration_conflict ? "检测到不一致的 Survey 运行配置" : null,
        hasCompleteConfiguration ? null : "在线 worker 未暴露完整 Survey 模型配置",
      ],
      "survey_runtime_ready 未通过后端核验。",
    ),
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

function TaskGalleryCatalog(): JSX.Element {
  const { state, reload: reloadCapabilities } = useSystemCapabilities();
  const { state: oasisReadinessState, reload: reloadOasisReadiness } = useOasisReadiness();
  const {
    state: semanticReadinessState,
    reload: reloadSemanticReadiness,
  } = useSemanticReadiness();
  const {
    state: surveyReadinessState,
    reload: reloadSurveyReadiness,
  } = useSurveyReadiness();
  const {
    state: chatReadinessState,
    reload: reloadChatReadiness,
  } = useChatReadiness();
  const { state: webReadinessState, reload: reloadWebReadiness } = useWebReadiness();
  const { state: linuxReadinessState, reload: reloadLinuxReadiness } = useLinuxReadiness();
  const [kind, setKind] = useState<TaskKind | "all">("all");
  const [query, setQuery] = useState<string>("");
  const capabilities = state.status === "success" ? state.data.capabilities : [];
  const readiness = useMemo<RuntimeReadinessByKind>(
    () => ({
      platform: platformReadinessProbe(oasisReadinessState),
      semantic: semanticReadinessProbe(semanticReadinessState),
      survey: surveyReadinessProbe(surveyReadinessState),
      chat: chatReadinessProbe(chatReadinessState),
      web: webReadinessProbe(webReadinessState),
      linux: linuxReadinessProbe(linuxReadinessState),
      archive: { status: "ready" },
    }),
    [chatReadinessState, linuxReadinessState, oasisReadinessState, semanticReadinessState, surveyReadinessState, webReadinessState],
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
  const isVerifying = state.status === "loading"
    || (state.status === "error" && state.isRetrying)
    || readiness.platform.status === "loading"
    || readiness.semantic.status === "loading"
    || readiness.survey.status === "loading"
    || readiness.chat.status === "loading"
    || readiness.web.status === "loading"
    || readiness.linux.status === "loading";
  const reloadAll = useCallback((): void => {
    reloadCapabilities();
    reloadOasisReadiness();
    reloadSemanticReadiness();
    reloadSurveyReadiness();
    reloadChatReadiness();
    reloadWebReadiness();
    reloadLinuxReadiness();
  }, [
    reloadCapabilities,
    reloadOasisReadiness,
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
          <span>MATRAIX / TASK GALLERY</span>
          <h2>选择一个真实可执行的评测任务</h2>
          <p>任务卡同时核验后端 capability、在线 worker 与对应运行时 readiness。任何一层未通过时都会保留安全原因，但不会显示假启动按钮。</p>
        </div>
        <dl>
          <div><dt>目录任务</dt><dd>{taskDefinitions.length}</dd></div>
          <div><dt>当前可运行</dt><dd>{state.status === "success" ? runtimeCount : "—"}</dd></div>
          <div><dt>能力来源</dt><dd>{state.status === "success" ? state.data.api_version : "核验中"}</dd></div>
        </dl>
      </header>

      <section className="task-gallery-controls" aria-label="Task Gallery 筛选">
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

      <main className="task-gallery-stage" aria-labelledby="task-gallery-stage-title">
        <header><div><span>CATALOG / VERIFIED</span><h3 id="task-gallery-stage-title">跨类型任务目录</h3></div><p>{tasks.length} / {taskDefinitions.length} 项</p></header>
        {state.status === "success" && tasks.length > 0 ? (
          <ul className="task-gallery-grid">
            {tasks.map((task) => {
              const decision = availabilityDecision(task, capabilities, readiness);
              const taskAvailability = decision.availability;
              const capability = capabilityByName(capabilities, task.capabilityName);
              const canInspectLinuxBoundary = task.id === "linux-artifact-task"
                && capability?.state === "runtime_ready";
              return (
                <li key={task.id} data-availability={taskAvailability}>
                  <header><span>{task.eyebrow}</span><strong>{statusLabel(taskAvailability)}</strong></header>
                  <h4>{task.title}</h4>
                  <p>{task.summary}</p>
                  <dl><div><dt>来源</dt><dd>{task.source}</dd></div><div><dt>输出</dt><dd>{task.output}</dd></div><div><dt>Capability</dt><dd><code>{task.capabilityName}</code></dd></div>{capability !== null ? <div><dt>Contracts</dt><dd>{capability.contracts.join(" · ")}</dd></div> : null}</dl>
                  {(taskAvailability === "runtime" || canInspectLinuxBoundary) && task.href !== null ? <a href={task.href}>{task.id === "trial-archive" ? "打开 Trial Archive →" : task.id === "batch-registry" ? "打开 Batch Registry →" : canInspectLinuxBoundary && taskAvailability !== "runtime" ? "查看固定任务边界 →" : "打开 Playground →"}</a> : <div className="task-gallery-locked" role="note"><strong>{lockedTitle(taskAvailability)}</strong><small>{decision.reason}</small></div>}
                </li>
              );
            })}
          </ul>
        ) : null}
        {state.status === "success" && tasks.length === 0 ? <div className="task-gallery-empty"><strong>没有匹配任务</strong><p>调整任务类型或搜索词。</p></div> : null}
      </main>
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
  if (route.task === "survey") {
    return (
      <SurveyPlaygroundPage
        page={route.page ?? 1}
        initialExperimentId={route.experimentId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onSelectionChange={(page, experimentId, trialId) => {
          onRouteChange({
            task: "survey",
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
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "chat",
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
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "web",
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
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onRouteChange={onRouteChange}
      />
    );
  }

  if (route.task === "linux") {
    return (
      <LinuxArtifactPage
        page={route.page ?? 1}
        initialEvaluationId={route.evaluationId}
        initialTrialId={route.trialId}
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onSelectionChange={(page, evaluationId, trialId) => {
          onRouteChange({
            task: "linux",
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
        onBack={() => onRouteChange(taskGalleryRootRoute())}
        onRouteChange={onRouteChange}
      />
    );
  }

  return <TaskGalleryCatalog />;
}
