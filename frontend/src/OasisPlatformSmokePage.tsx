import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { SemanticExperimentPage } from "./SemanticExperimentPage";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  createPlatformSmokeRun,
  createPlatformSmokeRunRequestSchema,
  fetchOasisReadiness,
  type CreatePlatformSmokeRunRequest,
  type OasisReadiness,
  type PlatformSmokeRunDetail,
  type PlatformSmokeRunSummary,
} from "./oasisContracts";
import type { AlternativeVariant, ScenarioDetail } from "./scenarioContracts";
import type { LegacyRunStudioRoute } from "./runStudioRoute";
import {
  useOasisReadiness,
  usePlatformSmokeRunDetail,
  usePlatformSmokeRuns,
  type OasisReadinessLoadState,
  type PlatformSmokeRunDetailLoadState,
  type PlatformSmokeRunsLoadState,
} from "./useOasisRuns";
import {
  useScenarioDetail,
  useScenarios,
  type ScenarioDetailLoadState,
  type ScenariosLoadState,
} from "./useScenarios";
import "./runStudio.css";

type RunCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly run: PlatformSmokeRunDetail }
  | { readonly status: "error"; readonly error: Error };

interface RunLauncherProps {
  readonly readinessState: OasisReadinessLoadState;
  readonly onReloadReadiness: () => void;
  readonly onRunCreated: (run: PlatformSmokeRunDetail) => void;
  readonly runDirectory: ReactNode;
}

const runStatusLabels: Readonly<Record<PlatformSmokeRunSummary["status"], string>> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
};

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 12)}…${digest.slice(-8)}`;
}

function formatArtifactSize(sizeBytes: number): string {
  if (sizeBytes < 1_024) {
    return `${sizeBytes} B`;
  }

  if (sizeBytes < 1_048_576) {
    return `${(sizeBytes / 1_024).toFixed(1)} KiB`;
  }

  return `${(sizeBytes / 1_048_576).toFixed(2)} MiB`;
}

function isValidSeed(seed: string): boolean {
  if (!/^\d+$/u.test(seed)) {
    return false;
  }

  const parsedSeed = Number(seed);

  return Number.isSafeInteger(parsedSeed)
    && parsedSeed >= 0
    && parsedSeed <= 4_294_967_295;
}

function normalizeRunCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`平台烟雾测试输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("创建 OASIS 平台烟雾测试失败：请求抛出了非标准错误。请检查后端日志。");
}

function isAmbiguousCreationError(error: Error): boolean {
  return isAmbiguousPostResultError(error);
}

function selectedScenario(
  state: ScenarioDetailLoadState,
  scenarioId: string | null,
): ScenarioDetail | null {
  if (scenarioId === null || state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === scenarioId ? state.data : null;
}

function selectedAlternative(
  scenario: ScenarioDetail | null,
  variantId: string | null,
): AlternativeVariant | null {
  if (scenario === null || variantId === null) {
    return null;
  }

  return scenario.alternatives.find((alternative) => alternative.id === variantId) ?? null;
}

function ReadinessPanel({
  state,
  onReload,
}: {
  readonly state: OasisReadinessLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  const readiness = state.data;

  return (
    <section className="oasis-readiness" aria-labelledby="oasis-readiness-title">
      <div className="oasis-section-heading">
        <div>
          <span className="oasis-eyebrow">Runtime boundary</span>
          <h3 id="oasis-readiness-title">OASIS 平台运行边界</h3>
          <p>只在后端工作进程和真实平台运行时都就绪时开放提交。</p>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={state.status === "loading"}
          aria-busy={state.status === "loading"}
          onClick={onReload}
        >
          {state.status === "loading" ? "核验中…" : "重新核验"}
        </button>
      </div>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法核验 OASIS 就绪状态"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && readiness === null ? (
        <div className="oasis-readiness-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在核验 OASIS 平台运行时</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {readiness !== null ? (
        <div className="oasis-readiness-content" aria-busy={state.status === "loading"}>
          <dl className="oasis-readiness-ledger">
            <div>
              <dt>引擎</dt>
              <dd>{readiness.engine} {readiness.engine_version}</dd>
            </div>
            <div>
              <dt>工作进程</dt>
              <dd data-ready={readiness.worker_online}>
                {readiness.worker_online ? "在线" : "离线"}
              </dd>
            </div>
            <div>
              <dt>平台运行时</dt>
              <dd data-ready={readiness.platform_runtime_ready}>
                {readiness.platform_runtime_ready ? "可运行" : "未就绪"}
              </dd>
            </div>
            <div>
              <dt>语义推演</dt>
              <dd data-ready={readiness.semantic_run_ready}>未开放</dd>
            </div>
          </dl>
          <div className="oasis-limitations">
            <strong>已声明限制</strong>
            {readiness.limitations.length === 0 ? (
              <p>接口没有返回限制说明；语义推演仍固定为未开放。</p>
            ) : (
              <ul>
                {readiness.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            )}
          </div>
          <code className="oasis-endpoint-diagnostic">
            GET /api/v2/simulations/oasis/readiness · mode={readiness.mode}
          </code>
        </div>
      ) : null}
    </section>
  );
}

function ScenarioSelectionError({
  scenariosState,
  scenarioDetailState,
  onReloadScenarios,
  onReloadScenarioDetail,
}: {
  readonly scenariosState: ScenariosLoadState;
  readonly scenarioDetailState: ScenarioDetailLoadState;
  readonly onReloadScenarios: () => void;
  readonly onReloadScenarioDetail: () => void;
}): JSX.Element | null {
  if (scenariosState.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取决策实验"
        error={scenariosState.error}
        isRetrying={scenariosState.isRetrying}
        onRetry={onReloadScenarios}
      />
    );
  }

  if (scenarioDetailState.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取实验备选方案"
        error={scenarioDetailState.error}
        isRetrying={scenarioDetailState.isRetrying}
        onRetry={onReloadScenarioDetail}
      />
    );
  }

  return null;
}

function RunInputPreview({
  scenario,
  alternative,
}: {
  readonly scenario: ScenarioDetail;
  readonly alternative: AlternativeVariant;
}): JSX.Element {
  return (
    <section className="oasis-input-preview" aria-labelledby="oasis-input-preview-title">
      <div className="oasis-input-heading">
        <div>
          <span>备选 #{alternative.position}</span>
          <h4 id="oasis-input-preview-title">{alternative.name}</h4>
          <p>{alternative.hypothesis}</p>
        </div>
        <strong>{alternative.interventions.length} 条手工动作</strong>
      </div>
      <div className="oasis-frozen-context">
        <div>
          <span>冻结现实</span>
          <strong>v{scenario.snapshot.version} · {scenario.snapshot.evidence_count} 篇证据</strong>
        </div>
        <div>
          <span>scenario_sha256</span>
          <code>{scenario.scenario_sha256}</code>
        </div>
        <div>
          <span>snapshot_sha256</span>
          <code>{scenario.snapshot.snapshot_sha256}</code>
        </div>
      </div>
      <ol className="oasis-post-preview">
        {alternative.interventions.map((intervention) => (
          <li key={intervention.id}>
            <header>
              <strong>帖子 #{intervention.position + 1}</strong>
              <span>scenario_actor · synthetic</span>
              <span>Reddit</span>
              <time>+{intervention.offset_minutes} 分钟</time>
            </header>
            <p>{intervention.content}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function RunLauncher({
  readinessState,
  onReloadReadiness,
  onRunCreated,
  runDirectory,
}: RunLauncherProps): JSX.Element {
  const { state: scenariosState, reload: reloadScenarios } = useScenarios();
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const {
    state: scenarioDetailState,
    reload: reloadScenarioDetail,
  } = useScenarioDetail(selectedScenarioId);
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null);
  const [seed, setSeed] = useState<string>("");
  const [isScopeAcknowledged, setIsScopeAcknowledged] = useState<boolean>(false);
  const [creationState, setCreationState] = useState<RunCreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const scenario = selectedScenario(scenarioDetailState, selectedScenarioId);
  const alternative = selectedAlternative(scenario, selectedVariantId);
  const readiness = readinessState.status === "success" ? readinessState.data : null;
  const scenarios = scenariosState.data?.items ?? [];
  const isSubmitting = creationState.status === "submitting";
  const canSubmit = readiness !== null
    && readiness.worker_online
    && readiness.platform_runtime_ready
    && scenarioDetailState.status === "success"
    && alternative !== null
    && isValidSeed(seed)
    && isScopeAcknowledged
    && !isSubmitting;

  useEffect(() => {
    if (scenario === null || selectedVariantId === null) {
      return;
    }

    const stillExists = scenario.alternatives.some(
      (candidate) => candidate.id === selectedVariantId,
    );

    if (!stillExists) {
      setSelectedVariantId(null);
      setIsScopeAcknowledged(false);
    }
  }, [scenario, selectedVariantId]);

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  const invalidateAcknowledgement = (): void => {
    setIsScopeAcknowledged(false);
    setCreationState({ status: "idle" });
  };

  const changeScenario = (scenarioId: string): void => {
    if (activeController.current !== null) {
      return;
    }

    setSelectedScenarioId(scenarioId);
    setSelectedVariantId(null);
    invalidateAcknowledgement();
  };

  const submitRun = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (
      !canSubmit
      || activeController.current !== null
      || scenario === null
      || alternative === null
    ) {
      return;
    }

    let request: CreatePlatformSmokeRunRequest;

    try {
      request = createPlatformSmokeRunRequestSchema.parse({
        scenario_id: scenario.id,
        variant_id: alternative.id,
        seed: Number(seed),
      });
    } catch (error: unknown) {
      setCreationState({ status: "error", error: normalizeRunCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setCreationState({ status: "submitting" });

    try {
      let currentReadiness: OasisReadiness;

      try {
        currentReadiness = await fetchOasisReadiness(controller.signal);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error;
        }

        const reason = error instanceof Error
          ? error.message
          : "readiness preflight threw a non-standard error";
        setIsScopeAcknowledged(false);
        onReloadReadiness();
        throw new Error(
          `无法完成 OASIS readiness 提交前核验，POST 尚未发送。reason=${reason}`,
        );
      }

      if (!currentReadiness.worker_online || !currentReadiness.platform_runtime_ready) {
        setIsScopeAcknowledged(false);
        setCreationState({
          status: "error",
          error: new Error(
            `OASIS 运行时已失效：worker_online=${String(currentReadiness.worker_online)}; `
            + `platform_runtime_ready=${String(currentReadiness.platform_runtime_ready)}。`
            + "已重新核验 readiness；请等待工作进程恢复后再次确认并提交。",
          ),
        });
        onReloadReadiness();
        return;
      }

      const run = await createPlatformSmokeRun(request, controller.signal);

      if (activeController.current !== controller || controller.signal.aborted) {
        return;
      }

      setCreationState({ status: "success", run });
      onRunCreated(run);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      if (activeController.current !== controller) {
        return;
      }

      setCreationState({ status: "error", error: normalizeRunCreationError(error) });
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  };

  const hasAmbiguousCreationResult = creationState.status === "error"
    && isAmbiguousCreationError(creationState.error);

  return (
    <section className="oasis-launcher run-studio-launcher" aria-labelledby="oasis-launcher-title">
      <div className="oasis-section-heading run-studio-launch-heading">
        <div>
          <span className="oasis-eyebrow">HISTORICAL ADC / READ ONLY</span>
          <h3 id="oasis-launcher-title">平台烟雾测试历史归档</h3>
          <p>新建入口已停用；下方仅保留旧输入结构用于解释历史运行，现有运行与产物仍可读取。</p>
        </div>
        <span className="contract-endpoint">GET /api/v2/simulation-runs/platform-smoke</span>
      </div>

      <form onSubmit={(event) => void submitRun(event)}>
        <fieldset disabled>
          <legend className="sr-only">OASIS 平台烟雾测试输入</legend>

          <div className="oasis-launcher-content run-studio-launch-grid">
            <div className="run-studio-left-rail" aria-label="运行输入与历史">
              <div className="run-studio-rail-heading">
                <span>INPUT / 01</span>
                <strong>冻结实验输入</strong>
                <p>选择场景、备选动作和可复现随机种子。</p>
              </div>

              <ScenarioSelectionError
                scenariosState={scenariosState}
                scenarioDetailState={scenarioDetailState}
                onReloadScenarios={reloadScenarios}
                onReloadScenarioDetail={reloadScenarioDetail}
              />

              {scenariosState.status === "loading" && scenariosState.data === null ? (
                <div className="oasis-launcher-skeleton" role="status" aria-live="polite">
                  <span className="sr-only">正在读取决策实验</span>
                  <span className="skeleton-block" aria-hidden="true" />
                  <span className="skeleton-block" aria-hidden="true" />
                </div>
              ) : null}

              {scenariosState.data !== null && scenarios.length === 0 ? (
                <div className="oasis-empty-state" role="status">
                  <strong>还没有可运行的决策实验</strong>
                  <p>先在“决策实验”中冻结至少一个包含初始帖子的备选方案。</p>
                </div>
              ) : null}

              {scenarios.length > 0 ? (
              <div className="oasis-run-controls">
                <label htmlFor="oasis-run-scenario">
                  <span>决策实验</span>
                  <select
                    id="oasis-run-scenario"
                    value={selectedScenarioId ?? ""}
                    required
                    onChange={(event) => changeScenario(event.target.value)}
                  >
                    <option value="" disabled>请选择决策实验</option>
                    {scenarios.map((candidate) => (
                      <option value={candidate.id} key={candidate.id}>
                        {candidate.title} · 现实 v{candidate.snapshot.version}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="oasis-run-variant">
                  <span>备选方案（不含基线）</span>
                  <select
                    id="oasis-run-variant"
                    value={selectedVariantId ?? ""}
                    disabled={scenario === null}
                    required
                    onChange={(event) => {
                      setSelectedVariantId(event.target.value);
                      invalidateAcknowledgement();
                    }}
                  >
                    <option value="">请选择一个备选方案</option>
                    {scenario?.alternatives.map((candidate) => (
                      <option value={candidate.id} key={candidate.id}>
                        #{candidate.position} {candidate.name} · {candidate.interventions.length} 条帖子
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="oasis-run-seed">
                  <span>随机种子 · uint32</span>
                  <input
                    id="oasis-run-seed"
                    type="text"
                    value={seed}
                    inputMode="numeric"
                    pattern="[0-9]+"
                    placeholder="0–4294967295"
                    required
                    aria-invalid={seed !== "" && !isValidSeed(seed)}
                    onChange={(event) => {
                      setSeed(event.target.value);
                      invalidateAcknowledgement();
                    }}
                  />
                </label>
                <button
                  className="button button-secondary button-compact oasis-run-refresh"
                  type="button"
                  disabled={selectedScenarioId === null || scenarioDetailState.status === "loading"}
                  aria-busy={scenarioDetailState.status === "loading"}
                  onClick={reloadScenarioDetail}
                >
                  {scenarioDetailState.status === "loading" ? "核验中…" : "重新核验规格"}
                </button>
              </div>
              ) : null}

              <div className="run-studio-history-slot">
                {runDirectory}
              </div>
            </div>

            <div className="run-studio-center-stage">
              <div className="run-studio-stage-label" aria-hidden="true">
                <span>STAGE / PLATFORM INPUT</span>
                <i />
                <span>POST TIMELINE</span>
              </div>

              {scenario !== null && alternative !== null ? (
                <RunInputPreview scenario={scenario} alternative={alternative} />
              ) : (
                <div className="oasis-input-placeholder" role="status">
                  <strong>明确选择一个备选方案</strong>
                  <p>选择后将显示会写入 OASIS SQLite 平台的全部初始帖子和冻结内容哈希。</p>
                </div>
              )}

              {scenarios.length > 0 ? (
                <div className="oasis-submit-bar">
                <label className="oasis-scope-confirmation">
                  <input
                    type="checkbox"
                    checked={isScopeAcknowledged}
                    onChange={(event) => {
                      setIsScopeAcknowledged(event.target.checked);
                      setCreationState({ status: "idle" });
                    }}
                  />
                  <span>
                    <strong>
                      这只是真实 OASIS Reddit 平台 / SQLite / 手工动作烟雾测试，
                      不是 LLM 受众演化或预测
                    </strong>
                    <small>产物证明平台动作链路可执行，不代表现实人群反应、传播结果或方案优劣。</small>
                  </span>
                </label>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={!canSubmit}
                  aria-busy={isSubmitting}
                >
                  {isSubmitting ? "正在入队…" : "启动平台烟雾测试"}
                </button>

                {readiness !== null
                  && (!readiness.worker_online || !readiness.platform_runtime_ready) ? (
                    <div className="oasis-submit-message oasis-submit-warning" role="status">
                      <strong>运行入口已锁定</strong>
                      <p>worker_online={String(readiness.worker_online)}; platform_runtime_ready={String(readiness.platform_runtime_ready)}</p>
                      <button type="button" onClick={onReloadReadiness}>重新核验 readiness</button>
                    </div>
                  ) : null}

                {creationState.status === "error" ? (
                  <div className="oasis-submit-message oasis-submit-error" role="alert">
                    <strong>
                      {hasAmbiguousCreationResult
                        ? "提交结果未知，请先刷新运行目录核对"
                        : "烟雾测试没有入队"}
                    </strong>
                    <p>{creationState.error.message}</p>
                    <small>POST 不会自动重试，以免重复创建运行。</small>
                  </div>
                ) : null}

                {creationState.status === "success" ? (
                  <div className="oasis-submit-message oasis-submit-success" role="status">
                    <strong>运行已入队并开始轮询</strong>
                    <p>run_id={creationState.run.id}; status={creationState.run.status}; input_sha256={creationState.run.input_sha256}</p>
                  </div>
                ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </fieldset>
      </form>
    </section>
  );
}

function RunStatusBadge({
  status,
}: {
  readonly status: PlatformSmokeRunSummary["status"];
}): JSX.Element {
  return (
    <span className="oasis-run-status" data-status={status}>
      {runStatusLabels[status]}
    </span>
  );
}

function RunList({
  state,
  selectedRunId,
  onSelect,
  onReload,
}: {
  readonly state: PlatformSmokeRunsLoadState;
  readonly selectedRunId: string | null;
  readonly onSelect: (run: PlatformSmokeRunSummary) => void;
  readonly onReload: () => void;
}): JSX.Element {
  const response = state.data;

  return (
    <aside className="oasis-run-directory" aria-labelledby="oasis-run-directory-title">
      <div className="oasis-directory-heading">
        <div>
          <h3 id="oasis-run-directory-title">运行目录</h3>
          <p>{response === null ? "等待接口返回" : `${formatMediaCount(response.total)} 次运行`}</p>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={state.status === "loading"}
          aria-busy={state.status === "loading"}
          onClick={onReload}
        >
          {state.status === "loading" ? "读取中…" : "刷新"}
        </button>
      </div>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取运行目录"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && response === null ? (
        <div className="oasis-run-list-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取 OASIS 运行目录</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {response !== null && response.items.length === 0 ? (
        <div className="oasis-empty-state oasis-run-list-empty" role="status">
          <strong>还没有平台烟雾测试</strong>
          <p>上方提交成功后，真实运行会出现在这里；系统不会填充演示记录。</p>
        </div>
      ) : null}

      {response !== null && response.items.length > 0 ? (
        <ul className="oasis-run-list" aria-busy={state.status === "loading"}>
          {response.items.map((run) => {
            const isSelected = run.id === selectedRunId;

            return (
              <li key={run.id}>
                <button
                  type="button"
                  data-selected={isSelected}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(run)}
                >
                  <RunStatusBadge status={run.status} />
                  <span className="oasis-run-list-copy">
                    <strong>{run.scenario.variant_name}</strong>
                    <small>synthetic actor · seed {run.seed}</small>
                    <time dateTime={run.created_at}>{formatMediaTimestamp(run.created_at)}</time>
                    <code title={run.input_sha256}>{abbreviatedDigest(run.input_sha256)}</code>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </aside>
  );
}

function RunDetailView({ run }: { readonly run: PlatformSmokeRunDetail }): JSX.Element {
  return (
    <div className="oasis-run-detail-content">
      <div className="oasis-run-detail-heading">
        <div>
          <RunStatusBadge status={run.status} />
          <h3>{run.scenario.variant_name}</h3>
          <p>合成场景角色 · Reddit manual smoke · seed {run.seed}</p>
        </div>
        <span className="contract-endpoint">GET /api/v2/simulation-runs/platform-smoke/&#123;id&#125;</span>
      </div>

      <dl className="oasis-run-ledger" aria-label="运行生命周期">
        <div>
          <dt>创建</dt>
          <dd>{formatMediaTimestamp(run.created_at)}</dd>
        </div>
        <div>
          <dt>开始</dt>
          <dd>{run.started_at === null ? "—" : formatMediaTimestamp(run.started_at)}</dd>
        </div>
        <div>
          <dt>完成</dt>
          <dd>{run.completed_at === null ? "—" : formatMediaTimestamp(run.completed_at)}</dd>
        </div>
        <div>
          <dt>模式</dt>
          <dd>{run.mode}</dd>
        </div>
      </dl>

      <div className="oasis-run-hashes">
        <div>
          <span>input_sha256</span>
          <code>{run.input_sha256}</code>
        </div>
        <div>
          <span>scenario_sha256</span>
          <code>{run.scenario.scenario_sha256}</code>
        </div>
        <div>
          <span>snapshot_sha256</span>
          <code>{run.scenario.snapshot_sha256}</code>
        </div>
      </div>

      <section className="oasis-run-posts" aria-labelledby={`oasis-run-posts-${run.id}`}>
        <div className="oasis-run-subheading">
          <div>
            <h4 id={`oasis-run-posts-${run.id}`}>冻结输入帖子</h4>
            <p>以下是本次运行实际接收的手工动作输入。</p>
          </div>
          <strong>{run.posts.length} 条</strong>
        </div>
        <ol className="oasis-post-preview">
          {run.posts.map((post) => (
            <li key={post.position}>
              <header>
                <strong>帖子 #{post.position + 1}</strong>
                <span>Reddit</span>
                <time>+{post.offset_minutes} 分钟</time>
              </header>
              <p>{post.content}</p>
            </li>
          ))}
        </ol>
      </section>

      {run.result !== null ? (
        <section className="oasis-artifact" aria-labelledby={`oasis-artifact-${run.id}`}>
          <div className="oasis-run-subheading">
            <div>
              <span className="oasis-eyebrow">Platform artifact</span>
              <h4 id={`oasis-artifact-${run.id}`}>真实平台产物</h4>
              <p>只证明 OASIS 平台、SQLite 和手工动作链路成功执行。</p>
            </div>
            <code>{run.result.engine_version} · CAMEL {run.result.camel_version}</code>
          </div>
          <dl className="oasis-artifact-ledger">
            <div>
              <dt>产物大小</dt>
              <dd>{formatArtifactSize(run.result.artifact_size_bytes)}</dd>
            </div>
            <div>
              <dt>用户</dt>
              <dd>{formatMediaCount(run.result.user_count)}</dd>
            </div>
            <div>
              <dt>帖子</dt>
              <dd>{formatMediaCount(run.result.post_count)}</dd>
            </div>
            <div>
              <dt>轨迹</dt>
              <dd>{formatMediaCount(run.result.trace_count)}</dd>
            </div>
          </dl>
          <div className="oasis-artifact-hash">
            <span>artifact_sha256</span>
            <code>{run.result.artifact_sha256}</code>
          </div>
          <div className="oasis-limitations oasis-result-limitations">
            <strong>产物限制</strong>
            {run.result.limitations.length === 0 ? (
              <p>该产物没有附加限制说明；页面仍不会把它解释为语义推演。</p>
            ) : (
              <ul>
                {run.result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            )}
          </div>
        </section>
      ) : null}

      {run.error !== null ? (
        <section className="oasis-run-failure" role="alert" aria-labelledby={`oasis-failure-${run.id}`}>
          <span>运行失败</span>
          <h4 id={`oasis-failure-${run.id}`}>{run.error.code}</h4>
          <p>{run.error.message}</p>
        </section>
      ) : null}

      <details className="oasis-api-diagnostics">
        <summary>原始 API 诊断</summary>
        <dl>
          <div><dt>endpoint</dt><dd>/api/v2/simulation-runs/platform-smoke/{run.id}</dd></div>
          <div><dt>run_id</dt><dd>{run.id}</dd></div>
          <div><dt>scenario_id</dt><dd>{run.scenario.id}</dd></div>
          <div><dt>variant_id</dt><dd>{run.scenario.variant_id}</dd></div>
          <div><dt>world_snapshot_id</dt><dd>{run.scenario.world_snapshot_id}</dd></div>
          <div><dt>status</dt><dd>{run.status}</dd></div>
          <div><dt>error</dt><dd>{run.error === null ? "null" : `${run.error.code}: ${run.error.message}`}</dd></div>
        </dl>
      </details>
    </div>
  );
}

function RunDetailPanel({
  selectedRunId,
  state,
  onReload,
}: {
  readonly selectedRunId: string | null;
  readonly state: PlatformSmokeRunDetailLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  const loadedRun = state.status === "idle" ? null : state.data;
  const run = selectedRunId !== null && loadedRun?.id === selectedRunId
    ? loadedRun
    : null;

  if (selectedRunId === null) {
    return (
      <section className="oasis-run-detail oasis-run-detail-empty" aria-labelledby="oasis-run-detail-empty-title">
        <div>
          <h3 id="oasis-run-detail-empty-title">选择运行核对真实平台产物</h3>
          <p>这里会显示生命周期、冻结输入、内容哈希、SQLite 产物计数、限制和原始诊断。</p>
        </div>
      </section>
    );
  }

  return (
    <section
      className="oasis-run-detail"
      aria-label="OASIS 平台烟雾测试详情"
      aria-busy={state.status === "loading"}
    >
      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取运行详情"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && state.isPolling ? (
        <div className="oasis-polling-status" role="status" aria-live="polite">
          正在轮询 {run === null ? "运行状态" : runStatusLabels[run.status]}…
        </div>
      ) : null}

      {state.status === "loading" && run === null ? (
        <div className="oasis-run-detail-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取 OASIS 运行详情</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {run !== null ? <RunDetailView run={run} /> : null}
    </section>
  );
}

function PlatformSmokeWorkspace(): JSX.Element {
  const {
    state: readinessState,
    reload: reloadReadiness,
  } = useOasisReadiness();
  const {
    state: runsState,
    reload: reloadRuns,
  } = usePlatformSmokeRuns();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const {
    state: runDetailState,
    reload: reloadRunDetail,
  } = usePlatformSmokeRunDetail(selectedRunId);
  const terminalRefreshKey = useRef<string | null>(null);

  useEffect(() => {
    if (selectedRunId !== null || runsState.data === null) {
      return;
    }

    const firstRun = runsState.data.items[0];

    if (firstRun !== undefined) {
      setSelectedRunId(firstRun.id);
    }
  }, [runsState.data, selectedRunId]);

  useEffect(() => {
    if (runDetailState.status !== "success") {
      return;
    }

    const run = runDetailState.data;

    if (run.status !== "succeeded" && run.status !== "failed") {
      return;
    }

    const refreshKey = `${run.id}:${run.status}`;

    if (terminalRefreshKey.current === refreshKey) {
      return;
    }

    terminalRefreshKey.current = refreshKey;
    reloadRuns();
  }, [reloadRuns, runDetailState]);

  const runCreated = (run: PlatformSmokeRunDetail): void => {
    terminalRefreshKey.current = null;
    setSelectedRunId(run.id);
    reloadRuns();
  };

  return (
    <div className="oasis-page run-studio-page">
      <header className="oasis-page-intro run-studio-header" aria-labelledby="oasis-page-title">
        <div className="run-studio-title">
          <div className="run-studio-boundary-label">
            <span>HISTORICAL OASIS / READ ONLY</span>
            <code>legacy platform archive</code>
          </div>
          <h1 id="oasis-page-title">旧平台烟雾测试运行档案</h1>
          <p>
            这里保留 OASIS 0.2.5 Reddit 平台、SQLite 存储和手工初始帖动作的历史记录。
            新工作请返回原生模拟运行；本页不会创建任务，也不会把旧产物包装成现实预测。
          </p>
        </div>
        <ReadinessPanel state={readinessState} onReload={reloadReadiness} />
      </header>

      <div className="run-studio-cockpit">
        <RunLauncher
          readinessState={readinessState}
          onReloadReadiness={reloadReadiness}
          onRunCreated={runCreated}
          runDirectory={(
            <RunList
              state={runsState}
              selectedRunId={selectedRunId}
              onSelect={(run) => {
                terminalRefreshKey.current = null;
                setSelectedRunId(run.id);
              }}
              onReload={reloadRuns}
            />
          )}
        />

        <aside className="run-studio-inspector" aria-labelledby="run-studio-inspector-title">
          <div className="run-studio-inspector-heading">
            <div>
              <span>INSPECTOR / 03</span>
              <h2 id="run-studio-inspector-title">运行证据</h2>
              <p>生命周期、哈希、真实产物与限制。</p>
            </div>
            <code>GET /platform-smoke/&#123;id&#125;</code>
          </div>
          <RunDetailPanel
            selectedRunId={selectedRunId}
            state={runDetailState}
            onReload={reloadRunDetail}
          />
        </aside>
      </div>
    </div>
  );
}

interface OasisPlatformSmokePageProps {
  readonly route: LegacyRunStudioRoute;
  readonly onRouteChange: (route: LegacyRunStudioRoute) => void;
}

export function OasisPlatformSmokePage({
  route,
  onRouteChange,
}: OasisPlatformSmokePageProps): JSX.Element {
  return (
    <>
      <nav className="run-studio-mode-switch" aria-label="Run Studio 运行模式">
        <span>RUN STUDIO / MODE</span>
        <button
          type="button"
          aria-pressed={route.mode === "platform"}
          onClick={() => onRouteChange({
            mode: "platform",
            cohortId: null,
            scenarioId: null,
            experimentId: null,
            trialId: null,
            panel: null,
          })}
        >
          历史平台测试
        </button>
        <button
          type="button"
          aria-pressed={route.mode === "semantic"}
          onClick={() => onRouteChange({
            mode: "semantic",
            cohortId: null,
            scenarioId: null,
            experimentId: null,
            trialId: null,
            panel: null,
          })}
        >
          历史方案实验
        </button>
      </nav>
      {route.mode === "platform"
        ? <PlatformSmokeWorkspace />
        : <SemanticExperimentPage route={route} onRouteChange={onRouteChange} />}
    </>
  );
}
