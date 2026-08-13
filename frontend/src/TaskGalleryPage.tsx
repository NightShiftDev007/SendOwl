import { useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type { CapabilityDescriptor } from "./systemCapabilities";
import { useSystemCapabilities } from "./useSystemCapabilities";
import { SurveyPlaygroundPage } from "./SurveyPlaygroundPage";
import "./taskGallery.css";

type TaskKind = "social" | "survey" | "chat" | "web" | "os_app" | "batch";
type TaskAvailability = "runtime" | "contract" | "missing";

interface TaskDefinition {
  readonly id: string;
  readonly kind: TaskKind;
  readonly eyebrow: string;
  readonly title: string;
  readonly summary: string;
  readonly source: string;
  readonly capabilityName: string;
  readonly expectedState: "runtime_ready" | "contract_ready";
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
    output: "平台生命周期 · artifact integrity",
    href: "#/runs?mode=platform",
  },
  {
    id: "matraix-evaluation-spec",
    kind: "survey",
    eyebrow: "MATRAIX / EVALUATION",
    title: "MatrAIx Evaluation Spec",
    summary: "统一评测规格和 EngineResult 契约已经存在，但 Survey 执行器尚未进入当前 worker。",
    source: "MatrAIx",
    capabilityName: "simulations.matraix",
    expectedState: "contract_ready",
    output: "契约已定义 · runtime 未接通",
    href: null,
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
    output: "typed responses · exact counts · provenance",
    href: "#/tasks?task=survey",
  },
  {
    id: "chat-task",
    kind: "chat",
    eyebrow: "MATRAIX / CHAT",
    title: "Chatbot Evaluation",
    summary: "多轮 Persona 对话、应用 sidecar 和任务评分尚未进入统一控制面。",
    source: "MatrAIx Playground",
    capabilityName: "tasks.matraix.chat",
    expectedState: "runtime_ready",
    output: "待接：transcript · scorecard · debrief",
    href: null,
  },
  {
    id: "web-task",
    kind: "web",
    eyebrow: "MATRAIX / WEB",
    title: "Web Agent Evaluation",
    summary: "浏览器任务、轨迹、截图与结构化 web_result 尚未进入统一 worker。",
    source: "MatrAIx Playground",
    capabilityName: "tasks.matraix.web",
    expectedState: "runtime_ready",
    output: "待接：trajectory · screenshots · result",
    href: null,
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
    output: "待接：actions · recording · result",
    href: null,
  },
  {
    id: "harbor-batch",
    kind: "batch",
    eyebrow: "MATRAIX / HARBOR",
    title: "Harbor 批量 Trial",
    summary: "批量 launch、失败重试、聚合报告和 Trial 产物下载尚未迁移。",
    source: "MatrAIx Harbor",
    capabilityName: "tasks.matraix.harbor",
    expectedState: "runtime_ready",
    output: "待接：jobs · retries · aggregation · export",
    href: null,
  },
];

const taskKindLabels: Readonly<Record<TaskKind | "all", string>> = {
  all: "全部",
  social: "Social",
  survey: "Survey",
  chat: "Chat",
  web: "Web",
  os_app: "OS App",
  batch: "Harbor",
};

function capabilityByName(
  capabilities: readonly CapabilityDescriptor[],
  name: string,
): CapabilityDescriptor | null {
  return capabilities.find((capability) => capability.name === name) ?? null;
}

function availability(
  definition: TaskDefinition,
  capabilities: readonly CapabilityDescriptor[],
): TaskAvailability {
  const capability = capabilityByName(capabilities, definition.capabilityName);
  if (capability?.state === "runtime_ready" && definition.expectedState === "runtime_ready") {
    return "runtime";
  }
  if (capability !== null) {
    return "contract";
  }
  return "missing";
}

function statusLabel(value: TaskAvailability): string {
  if (value === "runtime") return "可运行";
  if (value === "contract") return "仅契约";
  return "未接通";
}

export function TaskGalleryPage({ initialTaskId }: { readonly initialTaskId: string | null }): JSX.Element {
  const { state, reload } = useSystemCapabilities();
  const [kind, setKind] = useState<TaskKind | "all">("all");
  const [query, setQuery] = useState<string>("");
  const capabilities = state.status === "success" ? state.data.capabilities : [];
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
    (task) => availability(task, capabilities) === "runtime",
  ).length;

  if (initialTaskId === "survey") {
    return <SurveyPlaygroundPage onBack={() => { window.location.hash = "#/tasks"; }} />;
  }

  return (
    <div className="task-gallery-page">
      <header className="task-gallery-hero">
        <div>
          <span>MATRAIX / TASK GALLERY</span>
          <h2>选择一个真实可执行的评测任务</h2>
          <p>任务卡的可用性直接来自后端 capabilities。没有运行时的 MatrAIx 能力会保留在融合路线中，但不会显示假启动按钮。</p>
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
        <button type="button" disabled={state.status === "loading"} onClick={reload}>{state.status === "loading" ? "核验中…" : "刷新能力"}</button>
      </section>

      {state.status === "error" ? <ApiErrorPanel title="无法核验任务能力" error={state.error} isRetrying={state.isRetrying} onRetry={reload} /> : null}
      {state.status === "loading" ? <div className="task-gallery-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}

      <main className="task-gallery-stage" aria-labelledby="task-gallery-stage-title">
        <header><div><span>CATALOG / VERIFIED</span><h3 id="task-gallery-stage-title">跨类型任务目录</h3></div><p>{tasks.length} / {taskDefinitions.length} 项</p></header>
        {state.status === "success" && tasks.length > 0 ? (
          <ul className="task-gallery-grid">
            {tasks.map((task) => {
              const taskAvailability = availability(task, capabilities);
              const capability = capabilityByName(capabilities, task.capabilityName);
              return (
                <li key={task.id} data-availability={taskAvailability}>
                  <header><span>{task.eyebrow}</span><strong>{statusLabel(taskAvailability)}</strong></header>
                  <h4>{task.title}</h4>
                  <p>{task.summary}</p>
                  <dl><div><dt>来源</dt><dd>{task.source}</dd></div><div><dt>输出</dt><dd>{task.output}</dd></div><div><dt>Capability</dt><dd><code>{task.capabilityName}</code></dd></div>{capability !== null ? <div><dt>Contracts</dt><dd>{capability.contracts.join(" · ")}</dd></div> : null}</dl>
                  {taskAvailability === "runtime" && task.href !== null ? <a href={task.href}>打开 Playground →</a> : <div className="task-gallery-locked" role="note"><strong>{taskAvailability === "contract" ? "执行器尚未接通" : "当前后端没有该 capability"}</strong><small>目录不会把上游能力伪装成当前可运行任务。</small></div>}
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
