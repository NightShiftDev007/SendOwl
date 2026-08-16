import { useEffect, useMemo, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import {
  createBatchRegistry,
  type MatraixBatchObservedStatus,
  type MatraixBatchRegistryCreateRequest,
  type MatraixBatchRegistryCandidate,
  type MatraixBatchRegistryDetail,
  type MatraixBatchRegistryItem,
  type MatraixBatchRegistryKind,
  type MatraixBatchRegistrySummary,
} from "./batchRegistryContracts";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaTimestamp } from "./mediaPresentation";
import { NativeBatchLaunchComposer } from "./NativeBatchLaunchComposer";
import {
  createTaskGalleryHash,
  type TaskGalleryRoute,
} from "./taskGalleryRoute";
import {
  useBatchRegistries,
  useBatchRegistry,
  useBatchRegistryCandidates,
} from "./useBatchRegistries";
import "./batchRegistry.css";

const pageSize = 20;
const kindLabels: Readonly<Record<MatraixBatchRegistryKind, string>> = {
  survey: "Survey",
  chat: "Chat",
  web: "Web",
  linux: "Linux",
};
const observedStatusLabels: Readonly<Record<MatraixBatchObservedStatus, string>> = {
  queued: "底层排队中",
  running: "底层运行中",
  succeeded: "底层已完成",
  failed: "底层失败",
};

type SubmissionState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly error: Error; readonly ambiguous: boolean };

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function candidateKey(candidate: MatraixBatchRegistryCandidate): string {
  return `${candidate.kind}:${candidate.parent_id}`;
}

function sourceRunHash(item: MatraixBatchRegistryItem): string {
  if (item.kind === "survey") {
    return createTaskGalleryHash({
        task: "survey",
        experimentId: item.parent_id,
        evaluationId: null,
        trialId: null,
        registryId: null,
        archiveKind: null,
        archiveStatus: null,
        page: null,
      });
  }
  if (item.kind === "chat") {
    return createTaskGalleryHash({
        task: "chat",
        experimentId: null,
        evaluationId: item.parent_id,
        trialId: null,
        registryId: null,
        archiveKind: null,
        archiveStatus: null,
        page: null,
      });
  }
  if (item.kind === "web") {
    return createTaskGalleryHash({
      task: "web",
      experimentId: null,
      evaluationId: item.parent_id,
      trialId: null,
      registryId: null,
      archiveKind: null,
      archiveStatus: null,
      page: 1,
    });
  }
  return createTaskGalleryHash({
    task: "linux",
    experimentId: null,
    evaluationId: item.parent_id,
    trialId: null,
    registryId: null,
    archiveKind: null,
    archiveStatus: null,
    page: 1,
  });
}

function normalizedBatchRoute(page: number, registryId: string | null): TaskGalleryRoute {
  return {
    task: "batch",
    experimentId: null,
    evaluationId: null,
    trialId: null,
    registryId,
    archiveKind: null,
    archiveStatus: null,
    page,
  };
}

function CandidateRow({
  candidate,
  selected,
  disabled,
  onToggle,
}: {
  readonly candidate: MatraixBatchRegistryCandidate;
  readonly selected: boolean;
  readonly disabled: boolean;
  readonly onToggle: () => void;
}): JSX.Element {
  return (
    <label className="batch-registry-candidate" data-kind={candidate.kind}>
      <input
        type="checkbox"
        checked={selected}
        disabled={disabled}
        onChange={onToggle}
      />
      <span>
        <span className="batch-registry-kind">{kindLabels[candidate.kind]}</span>
        <strong>{candidate.title}</strong>
        <small>
          {candidate.version} · {observedStatusLabels[candidate.observed_status]} · {candidate.trial_count} trials
        </small>
        <code>{shortHash(candidate.parent_sha256)}</code>
      </span>
    </label>
  );
}

function RegistryComposer({
  candidates,
  candidatesLoading,
  candidatesError,
  candidatePage,
  candidateTotal,
  candidatePageSize,
  candidateKind,
  candidateObservedAt,
  reloadCandidates,
  onCandidatePageChange,
  onCandidateKindChange,
  onCreated,
  onAmbiguous,
}: {
  readonly candidates: readonly MatraixBatchRegistryCandidate[];
  readonly candidatesLoading: boolean;
  readonly candidatesError: Error | null;
  readonly candidatePage: number;
  readonly candidateTotal: number | null;
  readonly candidatePageSize: number;
  readonly candidateKind: MatraixBatchRegistryKind | null;
  readonly candidateObservedAt: string | null;
  readonly reloadCandidates: () => void;
  readonly onCandidatePageChange: (page: number) => void;
  readonly onCandidateKindChange: (kind: MatraixBatchRegistryKind | null) => void;
  readonly onCreated: (registry: MatraixBatchRegistryDetail) => void;
  readonly onAmbiguous: () => void;
}): JSX.Element {
  const [title, setTitle] = useState<string>("");
  const [selectedCandidates, setSelectedCandidates] = useState<readonly MatraixBatchRegistryCandidate[]>([]);
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });
  const controllerRef = useRef<AbortController | null>(null);
  const selectedSet = useMemo(
    () => new Set(selectedCandidates.map(candidateKey)),
    [selectedCandidates],
  );
  const submitting = submission.status === "submitting";
  const canSubmit = title.trim().length > 0
    && selectedCandidates.length >= 1
    && selectedCandidates.length <= 20
    && !submitting;

  useEffect(() => () => controllerRef.current?.abort(), []);

  const toggle = (candidate: MatraixBatchRegistryCandidate): void => {
    const key = candidateKey(candidate);
    setSubmission({ status: "idle" });
    setSelectedCandidates((current) => current.some((item) => candidateKey(item) === key)
      ? current.filter((item) => candidateKey(item) !== key)
      : current.length >= 20
        ? current
        : [...current, candidate]);
  };

  const submit = (): void => {
    if (!canSubmit || controllerRef.current !== null) return;
    const request: MatraixBatchRegistryCreateRequest = {
      title: title.trim(),
      items: selectedCandidates.map((candidate) => ({
        kind: candidate.kind,
        parent_id: candidate.parent_id,
      })),
    };
    const controller = new AbortController();
    controllerRef.current = controller;
    setSubmission({ status: "submitting" });
    void createBatchRegistry(request, controller.signal)
      .then((registry) => {
        controllerRef.current = null;
        setTitle("");
        setSelectedCandidates([]);
        setSubmission({ status: "idle" });
        onCreated(registry);
      })
      .catch((error: unknown) => {
        controllerRef.current = null;
        if (error instanceof DOMException && error.name === "AbortError") return;
        const normalized = error instanceof Error
          ? error
          : new Error("封存 Batch Registry 失败：请求抛出了非标准错误。");
        const ambiguous = isAmbiguousPostResultError(normalized);
        if (ambiguous) {
          setSelectedCandidates([]);
          onAmbiguous();
        }
        setSubmission({ status: "error", error: normalized, ambiguous });
      });
  };

  return (
    <aside className="batch-registry-composer" aria-labelledby="batch-registry-composer-title">
      <header>
        <span>REGISTER / IMMUTABLE</span>
        <h3 id="batch-registry-composer-title">建立批次登记</h3>
        <p>将已封存的 Survey、Chat、Web 或 Linux 父运行绑定到一个不可变目录；不会启动或重试 Trial。</p>
      </header>
      <label className="batch-registry-title" htmlFor="batch-registry-title">
        <span>登记标题</span>
        <input
          id="batch-registry-title"
          type="text"
          maxLength={200}
          value={title}
          disabled={submitting}
          placeholder="例如：基准与服务对话对照批次"
          onChange={(event) => {
            setTitle(event.target.value);
            setSubmission({ status: "idle" });
          }}
        />
      </label>
      <div className="batch-registry-selection-heading">
        <div><strong>已封存父运行</strong><small>选择 1–20 项，不自动预选</small></div>
        <span>{selectedCandidates.length} / 20</span>
      </div>
      <div className="batch-registry-candidate-controls">
        <label htmlFor="batch-registry-candidate-kind">
          <span>类型</span>
          <select
            id="batch-registry-candidate-kind"
            value={candidateKind ?? ""}
            disabled={submitting}
            onChange={(event) => onCandidateKindChange(
              event.target.value === "" ? null : event.target.value as MatraixBatchRegistryKind,
            )}
          >
            <option value="">Survey + Chat + Web + Linux</option>
            <option value="survey">Survey</option>
            <option value="chat">Chat</option>
            <option value="web">Web</option>
            <option value="linux">Linux</option>
          </select>
        </label>
        <small>{candidateObservedAt === null ? "等待观测" : `观测于 ${formatMediaTimestamp(candidateObservedAt)}`}</small>
      </div>
      {candidatesError !== null ? (
        <ApiErrorPanel
          title="无法读取候选父运行"
          error={candidatesError}
          isRetrying={candidatesLoading}
          onRetry={reloadCandidates}
        />
      ) : null}
      {candidatesLoading && candidates.length === 0 ? (
        <div className="batch-registry-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div>
      ) : null}
      {!candidatesLoading && candidatesError === null && candidates.length === 0 ? (
        <div className="batch-registry-empty" role="status">
          <strong>尚无可登记的父运行</strong>
          <p>先封存一个 Survey、Chat、Web 或 Linux Evaluation；本页不会生成示例条目。</p>
        </div>
      ) : null}
      {candidates.length > 0 ? (
        <div className="batch-registry-candidates">
          {candidates.map((candidate) => (
            <CandidateRow
              key={candidateKey(candidate)}
              candidate={candidate}
              selected={selectedSet.has(candidateKey(candidate))}
              disabled={submitting || (!selectedSet.has(candidateKey(candidate)) && selectedCandidates.length >= 20)}
              onToggle={() => toggle(candidate)}
            />
          ))}
        </div>
      ) : null}
      {candidateTotal !== null && (candidateTotal > 0 || candidatePage > 1) ? (
        <nav className="batch-registry-candidate-pagination" aria-label="候选父运行分页">
          <button type="button" disabled={candidatePage <= 1 || candidatesLoading || submitting} onClick={() => onCandidatePageChange(candidatePage - 1)}>上一页</button>
          <span>第 {candidatePage} / {Math.max(1, Math.ceil(candidateTotal / candidatePageSize))} 页</span>
          <button type="button" disabled={candidatePage >= Math.max(1, Math.ceil(candidateTotal / candidatePageSize)) || candidatesLoading || submitting} onClick={() => onCandidatePageChange(candidatePage + 1)}>下一页</button>
        </nav>
      ) : null}
      {submission.status === "error" ? (
        <div className="batch-registry-submit-error" role="alert">
          <strong>{submission.ambiguous ? "结果存在歧义，已清除选择" : "登记未封存"}</strong>
          <p>{submission.error.message}</p>
          <small>{submission.ambiguous
            ? "目录已刷新。请先核对是否已创建，不会自动重发 POST。"
            : "请核对输入后再明确提交；POST 不会自动重试。"}</small>
        </div>
      ) : null}
      <button className="batch-registry-submit" type="button" disabled={!canSubmit} onClick={submit}>
        {submitting ? "正在封存登记…" : "封存 Batch Registry"}
      </button>
      <p className="batch-registry-boundary">Registry 只封存成员和观测计数。Harbor launch、retry、verifier、artifacts 与 authorized export 均未接通。</p>
    </aside>
  );
}

function RegistryDetail({
  registry,
  missing,
}: {
  readonly registry: MatraixBatchRegistryDetail | null;
  readonly missing: boolean;
}): JSX.Element {
  if (registry === null) {
    return (
      <div className="batch-registry-empty" role={missing ? "alert" : "status"}>
        <strong>{missing ? "所选登记无法读取" : "明确选择一条批次登记"}</strong>
        <p>{missing
          ? "系统不会回退到目录第一条。可从右侧重新选择。"
          : "选择后可核对不可变成员顺序、父运行哈希与底层 Trial 观测计数。"}</p>
      </div>
    );
  }

  return (
    <div className="batch-registry-detail-body">
      <section className="batch-registry-summary">
        <div>
          <span>SEALED / REGISTRY ONLY</span>
          <h4>{registry.title}</h4>
          <p>登记已封存 · {observedStatusLabels[registry.observed_trial_status]}</p>
        </div>
        <dl>
          <div><dt>父运行</dt><dd>{registry.item_count}</dd></div>
          <div><dt>Trials</dt><dd>{registry.trial_count}</dd></div>
          <div><dt>底层完成</dt><dd>{registry.succeeded_trial_count}</dd></div>
          <div><dt>底层失败</dt><dd>{registry.failed_trial_count}</dd></div>
        </dl>
        <dl className="batch-registry-identities">
          <div><dt>Registry ID</dt><dd><code>{registry.id}</code></dd></div>
          <div><dt>Registry SHA</dt><dd><code>{registry.registry_sha256}</code></dd></div>
          <div><dt>Observed</dt><dd><time dateTime={registry.observed_at}>{formatMediaTimestamp(registry.observed_at)}</time></dd></div>
          <div><dt>Created</dt><dd><time dateTime={registry.created_at}>{formatMediaTimestamp(registry.created_at)}</time></dd></div>
          <div><dt>Sealed</dt><dd><time dateTime={registry.sealed_at}>{formatMediaTimestamp(registry.sealed_at)}</time></dd></div>
        </dl>
      </section>
      <section className="batch-registry-members" aria-labelledby="batch-registry-members-title">
        <header>
          <div><span>MEMBERS / ORDERED</span><h4 id="batch-registry-members-title">已封存父运行</h4></div>
          <small>顺序与登记内容一致</small>
        </header>
        <ol>
          {registry.items.map((item) => (
            <li key={`${item.kind}:${item.parent_id}`} data-status={item.observed_status}>
              <span className="batch-registry-position">{String(item.position + 1).padStart(2, "0")}</span>
              <div className="batch-registry-member-main">
                <div><span data-kind={item.kind}>{kindLabels[item.kind]}</span><strong>{item.title}</strong></div>
                <small>{item.version} · {observedStatusLabels[item.observed_status]} · {formatMediaTimestamp(item.created_at)}</small>
                <dl>
                  <div><dt>Trial</dt><dd>{item.trial_count}</dd></div>
                  <div><dt>完成</dt><dd>{item.succeeded_trial_count}</dd></div>
                  <div><dt>失败</dt><dd>{item.failed_trial_count}</dd></div>
                  <div><dt>Model</dt><dd>{item.model_name}</dd></div>
                </dl>
                <details>
                  <summary>核对 provenance</summary>
                  <dl className="batch-registry-member-provenance">
                    <div><dt>Parent ID</dt><dd><code>{item.parent_id}</code></dd></div>
                    <div><dt>Parent SHA</dt><dd><code>{item.parent_sha256}</code></dd></div>
                    <div><dt>Config SHA</dt><dd><code>{item.parent_config_sha256}</code></dd></div>
                    <div><dt>Prompt</dt><dd>{item.prompt_schema_version}</dd></div>
                  </dl>
                </details>
                <a href={sourceRunHash(item)}>打开所属 {kindLabels[item.kind]} 运行 →</a>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function DirectoryRow({
  registry,
  selected,
  onSelect,
}: {
  readonly registry: MatraixBatchRegistrySummary;
  readonly selected: boolean;
  readonly onSelect: () => void;
}): JSX.Element {
  return (
    <li>
      <button type="button" aria-pressed={selected} onClick={onSelect}>
        <span><strong>{registry.title}</strong><small>登记已封存 · {observedStatusLabels[registry.observed_trial_status]}</small></span>
        <dl>
          <div><dt>父运行</dt><dd>{registry.item_count}</dd></div>
          <div><dt>Trials</dt><dd>{registry.trial_count}</dd></div>
          <div><dt>完成 / 失败</dt><dd>{registry.succeeded_trial_count} / {registry.failed_trial_count}</dd></div>
        </dl>
        <code>{shortHash(registry.registry_sha256)}</code>
        <time dateTime={registry.observed_at}>观测于 {formatMediaTimestamp(registry.observed_at)}</time>
      </button>
    </li>
  );
}

export function BatchRegistryPage({
  route,
  onBack,
  onRouteChange,
}: {
  readonly route: TaskGalleryRoute;
  readonly onBack: () => void;
  readonly onRouteChange: (route: TaskGalleryRoute) => void;
}): JSX.Element {
  if (route.task !== "batch" || route.page === null) {
    throw new Error("Batch Registry requires a normalized batch route with explicit page.");
  }
  const query = useMemo(() => ({ page: route.page ?? 1, pageSize }), [route.page]);
  const { state: directory, reload: reloadDirectory } = useBatchRegistries(query);
  const { state: detail, reload: reloadDetail } = useBatchRegistry(route.registryId);
  const [composerMode, setComposerMode] = useState<"launch" | "register">("launch");
  const [candidatePage, setCandidatePage] = useState<number>(1);
  const [candidateKind, setCandidateKind] = useState<MatraixBatchRegistryKind | null>(null);
  const candidateQuery = useMemo(() => ({
    page: candidatePage,
    pageSize,
    kind: candidateKind,
  }), [candidateKind, candidatePage]);
  const { state: candidateState, reload: reloadCandidates } = useBatchRegistryCandidates(candidateQuery);
  const candidates = candidateState.data?.items ?? [];
  const candidatesLoading = candidateState.status === "loading";
  const candidatesError = candidateState.status === "error" ? candidateState.error : null;
  const candidateTotal = candidateState.data?.total ?? null;
  const candidateObservedAt = candidateState.data?.observed_at ?? null;
  const directoryData = directory.data;
  const totalPages = directoryData === null
    ? null
    : Math.max(1, Math.ceil(directoryData.total / directoryData.page_size));
  const detailData = detail.status === "success" || detail.status === "loading" || detail.status === "error"
    ? detail.data
    : null;

  const created = (registry: MatraixBatchRegistryDetail): void => {
    reloadDirectory();
    reloadCandidates();
    onRouteChange(normalizedBatchRoute(1, registry.id));
  };
  const ambiguous = (): void => {
    reloadDirectory();
    reloadCandidates();
    onRouteChange(normalizedBatchRoute(route.page ?? 1, null));
  };

  return (
    <div className="batch-registry-page">
      <header className="batch-registry-header">
        <button type="button" onClick={onBack}>← Task Gallery</button>
        <div>
          <span>MATRAIX / BATCH REGISTRY</span>
          <h2>原子创建运行，并封存可核对的批次目录</h2>
          <p>可原子创建 SendOwl-native Survey / Chat，也可登记已有 Survey / Chat / Web / Linux 父运行；Registry 只观测底层 Trial，不冒充完整 Harbor 执行器。</p>
        </div>
        <dl>
          <div><dt>目录总数</dt><dd>{directoryData?.total ?? "—"}</dd></div>
          <div><dt>当前页</dt><dd>{route.page} / {totalPages ?? "—"}</dd></div>
          <div><dt>选中登记</dt><dd>{route.registryId === null ? "未选择" : "已选择"}</dd></div>
        </dl>
      </header>

      <div className="batch-registry-cockpit">
        <div className="batch-registry-left-rail">
          <nav className="batch-registry-mode" aria-label="Batch Registry 创建方式">
            <button type="button" aria-pressed={composerMode === "launch"} onClick={() => setComposerMode("launch")}>创建并登记</button>
            <button type="button" aria-pressed={composerMode === "register"} onClick={() => setComposerMode("register")}>登记已有运行</button>
          </nav>
          {composerMode === "launch" ? (
            <NativeBatchLaunchComposer onCreated={created} onAmbiguous={ambiguous} />
          ) : (
            <RegistryComposer
              candidates={candidates}
              candidatesLoading={candidatesLoading}
              candidatesError={candidatesError}
              candidatePage={candidatePage}
              candidateTotal={candidateTotal}
              candidatePageSize={pageSize}
              candidateKind={candidateKind}
              candidateObservedAt={candidateObservedAt}
              reloadCandidates={reloadCandidates}
              onCandidatePageChange={setCandidatePage}
              onCandidateKindChange={(kind) => {
                setCandidateKind(kind);
                setCandidatePage(1);
              }}
              onCreated={created}
              onAmbiguous={ambiguous}
            />
          )}
        </div>

        <main className="batch-registry-stage" aria-labelledby="batch-registry-stage-title">
          <header>
            <div><span>DETAIL / EXACT</span><h3 id="batch-registry-stage-title">批次登记详情</h3></div>
            {route.registryId !== null ? <button type="button" disabled={detail.status === "loading"} onClick={reloadDetail}>刷新详情</button> : null}
          </header>
          {detail.status === "error" ? (
            <ApiErrorPanel title="无法读取批次登记" error={detail.error} isRetrying={detail.isRetrying} onRetry={reloadDetail} />
          ) : null}
          {detail.status === "loading" && detail.data === null ? (
            <div className="batch-registry-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /><span className="skeleton-block" /></div>
          ) : null}
          {detail.status !== "loading" || detail.data !== null ? (
            <RegistryDetail registry={detailData} missing={detail.status === "error"} />
          ) : null}
        </main>

        <aside className="batch-registry-directory" aria-labelledby="batch-registry-directory-title">
          <header>
            <div><span>DIRECTORY / SEALED</span><h3 id="batch-registry-directory-title">批次登记目录</h3></div>
            <button type="button" disabled={directory.status === "loading"} onClick={reloadDirectory}>刷新</button>
          </header>
          {directory.status === "error" ? (
            <ApiErrorPanel title="无法读取 Batch Registry 目录" error={directory.error} isRetrying={directory.isRetrying} onRetry={reloadDirectory} />
          ) : null}
          {directory.status === "loading" && directory.data === null ? (
            <div className="batch-registry-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div>
          ) : null}
          {directoryData !== null && directoryData.items.length === 0 ? (
            <div className="batch-registry-empty" role="status"><strong>尚无批次登记</strong><p>可从左侧原子创建一组运行，或切换到“登记已有运行”后封存第一条目录。</p></div>
          ) : null}
          {directoryData !== null && directoryData.items.length > 0 ? (
            <ol>
              {directoryData.items.map((registry) => (
                <DirectoryRow
                  key={registry.id}
                  registry={registry}
                  selected={registry.id === route.registryId}
                  onSelect={() => onRouteChange(normalizedBatchRoute(route.page ?? 1, registry.id))}
                />
              ))}
            </ol>
          ) : null}
          {directoryData !== null && totalPages !== null && (directoryData.total > 0 || route.page > 1) ? (
            <nav className="batch-registry-pagination" aria-label="Batch Registry 分页">
              <button type="button" disabled={route.page <= 1 || directory.status === "loading"} onClick={() => onRouteChange(normalizedBatchRoute((route.page ?? 1) - 1, null))}>上一页</button>
              <span>第 {route.page} / {totalPages} 页</span>
              <button type="button" disabled={route.page >= totalPages || directory.status === "loading"} onClick={() => onRouteChange(normalizedBatchRoute((route.page ?? 1) + 1, null))}>下一页</button>
            </nav>
          ) : null}
          <section className="batch-registry-directory-boundary">
            <strong>能力边界</strong>
            <p>“登记已封存”只表示 registry 不可变；“底层运行中 / 完成 / 失败”来自成员 Trial 的观测，不是批次执行状态。</p>
          </section>
        </aside>
      </div>
    </div>
  );
}
