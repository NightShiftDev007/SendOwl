import { useEffect, useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { formatMediaTimestamp } from "./mediaPresentation";
import {
  createTaskGalleryHash,
  type TaskGalleryRoute,
} from "./taskGalleryRoute";
import type {
  TrialArchiveItem,
  TrialArchiveKind,
  TrialArchiveStatus,
} from "./trialArchiveContracts";
import { useTrialArchive, useTrialIntegrityVerification } from "./useTrialArchive";
import "./trialArchive.css";

const archivePageSize = 20;
const statusLabels: Readonly<Record<TrialArchiveStatus, string>> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
};
const kindLabels: Readonly<Record<TrialArchiveKind, string>> = {
  survey: "Survey",
  chat: "Chat",
  web: "Web",
  linux: "Linux",
};
const integrityCheckLabels: Readonly<Record<string, string>> = {
  sealed_parent: "封存父任务",
  trial_address: "Trial 内容地址",
  state_shape: "生命周期字段",
  survey_answers: "Survey 答案哈希",
  chat_transcript: "Chat transcript 哈希",
  chat_feedback: "Chat feedback 哈希",
  chat_result: "Chat result 哈希",
  web_trace: "Web observation trace 哈希",
  web_result: "Web result 哈希",
  linux_artifact: "Linux artifact 哈希",
  linux_result: "Linux result 哈希",
};

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function rootFields(): Pick<
  TaskGalleryRoute,
  "experimentId" | "evaluationId" | "trialId" | "registryId" | "archiveKind" | "archiveStatus" | "page"
> {
  return {
    experimentId: null,
    evaluationId: null,
    trialId: null,
    registryId: null,
    archiveKind: null,
    archiveStatus: null,
    page: null,
  };
}

function parentDetailHash(item: TrialArchiveItem, route: TaskGalleryRoute): string {
  const common = {
    projectId: route.projectId ?? null,
    runId: route.runId ?? null,
    archiveKind: null,
    archiveStatus: null,
    page: null,
    trialId: item.id,
    registryId: null,
  } as const;
  if (item.kind === "survey") {
    if (item.task.version === "scenario-preference/v1") return item.source_detail_path;
    return createTaskGalleryHash({
      task: "survey",
      experimentId: item.parent_id,
      evaluationId: null,
      ...common,
    });
  }
  if (item.kind === "chat" || item.kind === "web") {
    return createTaskGalleryHash({
      task: item.kind,
      experimentId: null,
      evaluationId: item.parent_id,
      ...common,
      page: 1,
    });
  }
  return createTaskGalleryHash({
    task: "linux",
    experimentId: null,
    evaluationId: null,
    ...common,
    page: 1,
  });
}

function statusTimestamp(item: TrialArchiveItem): string {
  if (item.completed_at !== null) return formatMediaTimestamp(item.completed_at);
  if (item.started_at !== null) return formatMediaTimestamp(item.started_at);
  return formatMediaTimestamp(item.created_at);
}

function TrialRow({
  item,
  selected,
  onSelect,
}: {
  readonly item: TrialArchiveItem;
  readonly selected: boolean;
  readonly onSelect: () => void;
}): JSX.Element {
  return (
    <li data-status={item.status}>
      <button type="button" aria-pressed={selected} onClick={onSelect}>
        <span className="trial-archive-row-kind" data-kind={item.kind}>{kindLabels[item.kind]}</span>
        <span className="trial-archive-row-task">
          <strong>{item.task.title}</strong>
          <small>{item.kind === "survey" && item.task.version === "scenario-preference/v1" ? "历史 ADC · " : ""}{item.task.version} · {item.persona.display_name}</small>
        </span>
        <span className="trial-archive-row-persona">
          <strong>{item.persona.persona_id}</strong>
          <small>Persona {item.persona.position + 1}</small>
        </span>
        <span className="trial-archive-row-status" data-status={item.status}>
          <strong>{statusLabels[item.status]}</strong>
          <small>{statusTimestamp(item)}</small>
        </span>
        <code>{shortHash(item.trial_sha256)}</code>
      </button>
    </li>
  );
}

function ProvenanceRows({ item }: { readonly item: TrialArchiveItem }): JSX.Element {
  if (item.kind === "survey") {
    return (
      <dl>
        <div><dt>Runner</dt><dd>{item.provenance.runner_version ?? "尚未产生"}</dd></div>
        <div><dt>Model</dt><dd>{item.provenance.model_name}</dd></div>
        <div><dt>Prompt</dt><dd>{item.provenance.prompt_schema_version}</dd></div>
        <div><dt>Config</dt><dd><code>{item.provenance.parent_config_sha256}</code></dd></div>
        <div><dt>Answers</dt><dd>{item.provenance.answers_sha256 === null ? "尚未产生" : <code>{item.provenance.answers_sha256}</code>}</dd></div>
      </dl>
    );
  }
  if (item.kind === "web") {
    return (
      <dl>
        <div><dt>Runner</dt><dd>{item.provenance.runner_version ?? "尚未产生"}</dd></div>
        <div><dt>Model</dt><dd>{item.provenance.model_name}</dd></div>
        <div><dt>Prompt</dt><dd>{item.provenance.prompt_schema_version}</dd></div>
        <div><dt>Config</dt><dd><code>{item.provenance.parent_config_sha256}</code></dd></div>
        <div><dt>Trace</dt><dd>{item.provenance.trace_sha256 === null ? "尚未产生" : <code>{item.provenance.trace_sha256}</code>}</dd></div>
        <div><dt>Result</dt><dd>{item.provenance.result_sha256 === null ? "尚未产生" : <code>{item.provenance.result_sha256}</code>}</dd></div>
      </dl>
    );
  }
  if (item.kind === "linux") {
    return (
      <dl>
        <div><dt>Runner</dt><dd>{item.provenance.runner_version ?? "尚未产生"}</dd></div>
        <div><dt>Model</dt><dd>{item.provenance.model_name}</dd></div>
        <div><dt>Prompt</dt><dd>{item.provenance.prompt_schema_version}</dd></div>
        <div><dt>Config</dt><dd><code>{item.provenance.parent_config_sha256}</code></dd></div>
        <div><dt>Artifact</dt><dd>{item.provenance.artifact_sha256 === null ? "尚未产生" : <code>{item.provenance.artifact_sha256}</code>}</dd></div>
        <div><dt>Result</dt><dd>{item.provenance.result_sha256 === null ? "尚未产生" : <code>{item.provenance.result_sha256}</code>}</dd></div>
      </dl>
    );
  }
  return (
    <dl>
      <div><dt>Runner</dt><dd>{item.provenance.runner_version ?? "尚未产生"}</dd></div>
      <div><dt>Model</dt><dd>{item.provenance.model_name}</dd></div>
      <div><dt>Prompt</dt><dd>{item.provenance.prompt_schema_version}</dd></div>
      <div><dt>Config</dt><dd><code>{item.provenance.parent_config_sha256}</code></dd></div>
      <div><dt>Transcript</dt><dd>{item.provenance.transcript_sha256 === null ? "尚未产生" : <code>{item.provenance.transcript_sha256}</code>}</dd></div>
      <div><dt>Feedback</dt><dd>{item.provenance.feedback_sha256 === null ? "尚未产生" : <code>{item.provenance.feedback_sha256}</code>}</dd></div>
      <div><dt>Result</dt><dd>{item.provenance.result_sha256 === null ? "尚未产生" : <code>{item.provenance.result_sha256}</code>}</dd></div>
    </dl>
  );
}

function TrialInspector({
  item,
  route,
  selectionMissing,
}: {
  readonly item: TrialArchiveItem | null;
  readonly route: TaskGalleryRoute;
  readonly selectionMissing: boolean;
}): JSX.Element {
  const verification = useTrialIntegrityVerification(item?.kind ?? null, item?.id ?? null);
  return (
    <aside className="trial-archive-inspector" aria-labelledby="trial-archive-inspector-title">
      <header>
        <span>PROVENANCE / EXACT</span>
        <h3 id="trial-archive-inspector-title">Trial 证据</h3>
      </header>
      {item === null ? (
        <div className="trial-archive-empty" role={selectionMissing ? "alert" : "status"}>
          <strong>{selectionMissing ? "所选 Trial 已不在当前页" : "明确选择一个 Trial"}</strong>
          <p>{selectionMissing
            ? "刷新后的真实分页不再包含这条记录；系统没有回退到第一条或相似记录。"
            : "系统不会自动打开第一页第一条。选择后可核对父任务、Persona、错误和内容哈希。"}</p>
        </div>
      ) : (
        <div className="trial-archive-inspector-body">
          <div className="trial-archive-inspector-heading">
            <span data-kind={item.kind}>{kindLabels[item.kind]}</span>
            <strong>{item.task.title}</strong>
            <small>{item.task.version} · {item.persona.display_name} · {item.persona.persona_id}</small>
          </div>
          <dl className="trial-archive-identities">
            <div><dt>Status</dt><dd>{statusLabels[item.status]}</dd></div>
            <div><dt>Parent ID</dt><dd><code>{item.parent_id}</code></dd></div>
            <div><dt>Trial ID</dt><dd><code>{item.id}</code></dd></div>
            <div><dt>Parent SHA</dt><dd><code>{item.parent_sha256}</code></dd></div>
            <div><dt>Trial SHA</dt><dd><code>{item.trial_sha256}</code></dd></div>
            <div><dt>Profile SHA</dt><dd><code>{item.persona.profile_sha256}</code></dd></div>
            <div><dt>Created</dt><dd><time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time></dd></div>
            <div><dt>Started</dt><dd>{item.started_at === null ? "—" : <time dateTime={item.started_at}>{formatMediaTimestamp(item.started_at)}</time>}</dd></div>
            <div><dt>Completed</dt><dd>{item.completed_at === null ? "—" : <time dateTime={item.completed_at}>{formatMediaTimestamp(item.completed_at)}</time>}</dd></div>
          </dl>
          {item.error !== null ? (
            <section className="trial-archive-error" role="alert">
              <strong>{item.error.code}</strong>
              <p>{item.error.message}</p>
            </section>
          ) : null}
          <section className="trial-archive-provenance" aria-label="运行 provenance">
            <h4>运行 provenance</h4>
            <ProvenanceRows item={item} />
          </section>
          <section className="trial-archive-verification" aria-label="封存完整性核验">
            <header>
              <h4>封存完整性核验</h4>
              {verification.status === "success" ? <span>VERIFIED</span> : null}
            </header>
            {verification.status === "loading" ? <p role="status">正在从封存记录复算内容地址…</p> : null}
            {verification.status === "error" ? (
              <div role="alert"><strong>核验失败</strong><p>{verification.error.message}</p></div>
            ) : null}
            {verification.status === "success" ? (
              <>
                <ol>
                  {verification.data.checks.map((check) => (
                    <li key={check.name} data-status={check.status}>
                      <span>{check.status === "passed" ? "✓" : "—"}</span>
                      <div>
                        <strong>{integrityCheckLabels[check.name] ?? check.name}</strong>
                        <small>{check.status === "passed" ? "已通过确定性复算" : "当前状态尚无封存输出"}</small>
                        {check.content_sha256 === null ? null : <code>{check.content_sha256}</code>}
                      </div>
                    </li>
                  ))}
                </ol>
                <time dateTime={verification.data.verified_at}>核验于 {formatMediaTimestamp(verification.data.verified_at)}</time>
                <ul>{verification.data.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
              </>
            ) : null}
          </section>
          <a className="trial-archive-open" href={parentDetailHash(item, route)}>
            打开所属 {kindLabels[item.kind]} Trial →
          </a>
          <p className="trial-archive-boundary">跳转仅由记录类型、所属父任务和 Trial 标识构造；进入详情后会再次核对父子成员关系。</p>
        </div>
      )}
    </aside>
  );
}

export function TrialArchivePage({
  route,
  onBack,
  onRouteChange,
}: {
  readonly route: TaskGalleryRoute;
  readonly onBack: () => void;
  readonly onRouteChange: (route: TaskGalleryRoute) => void;
}): JSX.Element {
  if (route.task !== "trials" || route.page === null) {
    throw new Error("Trial Archive requires a normalized trials route with explicit page.");
  }
  const archivePage = route.page;
  const query = useMemo(() => ({
    page: archivePage,
    pageSize: archivePageSize,
    kind: route.archiveKind,
    status: route.archiveStatus,
  }), [archivePage, route.archiveKind, route.archiveStatus]);
  const { state, reload } = useTrialArchive(query);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const response = state.data;
  const selectedItem = response?.items.find(
    (item) => `${item.kind}:${item.id}` === selectedKey,
  ) ?? null;
  const selectionMissing = selectedKey !== null
    && response !== null
    && selectedItem === null;
  const totalPages = response === null
    ? null
    : Math.max(1, Math.ceil(response.total / response.page_size));

  useEffect(() => setSelectedKey(null), [archivePage, route.archiveKind, route.archiveStatus]);

  const changeArchiveRoute = (
    kind: TrialArchiveKind | null,
    status: TrialArchiveStatus | null,
    page: number,
  ): void => {
    onRouteChange({
      task: "trials",
      ...rootFields(),
      archiveKind: kind,
      archiveStatus: status,
      page,
    });
  };

  return (
    <div className="trial-archive-page">
      <header className="trial-archive-header">
        <button type="button" onClick={onBack}>← 返回评测中心</button>
        <div>
          <span>SANDOWL / 试验档案</span>
          <h1>Survey、Chat、Web 与 Linux Trial 的统一证据目录</h1>
          <p>只读聚合本库中已经持久化的 Trial；状态、Persona、错误和 provenance 按原记录呈现，并提供当前服务端筛选的精确计数，不计算跨任务分数。</p>
        </div>
        <dl>
          <div><dt>当前筛选</dt><dd>{route.archiveKind === null ? "全部类型" : kindLabels[route.archiveKind]}</dd></div>
          <div><dt>总记录</dt><dd>{response?.total ?? "—"}</dd></div>
          <div><dt>分页</dt><dd>{archivePage} / {totalPages ?? "—"}</dd></div>
        </dl>
      </header>

      <div className="trial-archive-cockpit">
        <aside className="trial-archive-filters" aria-labelledby="trial-archive-filters-title">
          <header><span>FILTER / SERVER</span><h3 id="trial-archive-filters-title">目录范围</h3></header>
          <label htmlFor="trial-archive-kind">
            <span>任务类型</span>
            <select
              id="trial-archive-kind"
              value={route.archiveKind ?? ""}
              onChange={(event) => changeArchiveRoute(
                event.target.value === "" ? null : event.target.value as TrialArchiveKind,
                route.archiveStatus,
                1,
              )}
            >
              <option value="">全部四类 Trial</option>
              <option value="survey">Survey</option>
              <option value="chat">Chat</option>
              <option value="web">Web</option>
              <option value="linux">Linux</option>
            </select>
          </label>
          <label htmlFor="trial-archive-status">
            <span>运行状态</span>
            <select
              id="trial-archive-status"
              value={route.archiveStatus ?? ""}
              onChange={(event) => changeArchiveRoute(
                route.archiveKind,
                event.target.value === "" ? null : event.target.value as TrialArchiveStatus,
                1,
              )}
            >
              <option value="">全部状态</option>
              <option value="queued">排队中</option>
              <option value="running">运行中</option>
              <option value="succeeded">已完成</option>
              <option value="failed">失败</option>
            </select>
          </label>
          <button type="button" disabled={state.status === "loading"} onClick={reload}>
            {state.status === "loading" ? "刷新中…" : "刷新当前页"}
          </button>
          <section className="trial-archive-statistics" aria-labelledby="trial-archive-statistics-title">
            <header>
              <span>AGGREGATE / FILTERED</span>
              <strong id="trial-archive-statistics-title">服务端精确计数</strong>
            </header>
            <dl>
              <div><dt>Survey</dt><dd>{response?.statistics.by_kind.survey ?? "—"}</dd></div>
              <div><dt>Chat</dt><dd>{response?.statistics.by_kind.chat ?? "—"}</dd></div>
              <div><dt>Web</dt><dd>{response?.statistics.by_kind.web ?? "—"}</dd></div>
              <div><dt>Linux</dt><dd>{response?.statistics.by_kind.linux ?? "—"}</dd></div>
              <div><dt>排队</dt><dd>{response?.statistics.by_status.queued ?? "—"}</dd></div>
              <div><dt>运行</dt><dd>{response?.statistics.by_status.running ?? "—"}</dd></div>
              <div><dt>完成</dt><dd>{response?.statistics.by_status.succeeded ?? "—"}</dd></div>
              <div><dt>失败</dt><dd>{response?.statistics.by_status.failed ?? "—"}</dd></div>
            </dl>
            <p>计数对应当前类型与状态筛选，来自同一数据库只读快照，不读取回答、transcript 或 feedback。</p>
          </section>
          <section className="trial-archive-scope">
            <strong>只读边界</strong>
            <ul>
              <li>固定每页 {archivePageSize} 条，排序由服务端定义。</li>
              <li>Archive 不启动、重试或修改 Trial。</li>
              <li>跨任务聚合只统计执行状态，不生成 reward 或综合评分。</li>
              <li>四类 Trial 保留各自 output hash，不强行统一成分数。</li>
            </ul>
          </section>
        </aside>

        <section className="trial-archive-stage" aria-labelledby="trial-archive-stage-title">
          <header>
            <div><span>RECORDS / DURABLE</span><h3 id="trial-archive-stage-title">真实 Trial 目录</h3></div>
            <p>{response === null ? "等待接口" : `本页 ${response.items.length} 条`}</p>
          </header>
          {state.status === "error" ? (
            <ApiErrorPanel title="无法读取试验档案" error={state.error} isRetrying={state.isRetrying} onRetry={reload} />
          ) : null}
          {state.status === "loading" && response === null ? (
            <div className="trial-archive-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /><span className="skeleton-block" /></div>
          ) : null}
          {response !== null && response.items.length === 0 ? (
            <div className="trial-archive-empty" role="status">
              <strong>当前范围没有 Trial</strong>
              <p>这是真实空目录；可调整类型、状态或返回上一页，不会生成示例记录。</p>
            </div>
          ) : null}
          {response !== null && response.items.length > 0 ? (
            <div className="trial-archive-directory">
              <div className="trial-archive-columns" aria-hidden="true"><span>类型</span><span>任务</span><span>Persona</span><span>状态 / 时间</span><span>Trial hash</span></div>
              <ol>
                {response.items.map((item) => (
                  <TrialRow
                    key={`${item.kind}:${item.id}`}
                    item={item}
                    selected={`${item.kind}:${item.id}` === selectedKey}
                    onSelect={() => setSelectedKey(`${item.kind}:${item.id}`)}
                  />
                ))}
              </ol>
            </div>
          ) : null}
          {response !== null
          && totalPages !== null
          && (response.total > 0 || archivePage > 1) ? (
            <nav className="trial-archive-pagination" aria-label="试验档案分页">
              <button
                type="button"
                disabled={archivePage <= 1 || state.status === "loading"}
                onClick={() => changeArchiveRoute(route.archiveKind, route.archiveStatus, archivePage - 1)}
              >上一页</button>
              <span>第 {archivePage} / {totalPages} 页 · 共 {response.total} 条</span>
              <button
                type="button"
                disabled={archivePage >= totalPages || state.status === "loading"}
                onClick={() => changeArchiveRoute(route.archiveKind, route.archiveStatus, archivePage + 1)}
              >下一页</button>
            </nav>
          ) : null}
        </section>

        <TrialInspector item={selectedItem} route={route} selectionMissing={selectionMissing} />
      </div>
    </div>
  );
}
