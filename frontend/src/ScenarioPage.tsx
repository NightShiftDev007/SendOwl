import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  createScenario,
  scenarioCreateRequestSchema,
  type AlternativeVariant,
  type ScenarioCreateRequest,
  type ScenarioDetail,
  type ScenarioIntervention,
  type ScenarioSummary,
} from "./scenarioContracts";
import {
  useScenarioDetail,
  useScenarios,
  type ScenarioDetailLoadState,
  type ScenariosLoadState,
} from "./useScenarios";
import {
  useWorldModelDetail,
  useWorldModels,
  type WorldModelDetailLoadState,
  type WorldModelsLoadState,
} from "./useWorldModels";
import type {
  SnapshotSummary,
  WorldModelDetail,
  WorldModelSummary,
} from "./worldModelContracts";
import "./decisionWorkspace.css";

type ScenarioCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly scenario: ScenarioDetail }
  | { readonly status: "error"; readonly error: Error };

interface InterventionDraft {
  readonly clientId: string;
  readonly content: string;
  readonly offsetMinutes: string;
}

interface AlternativeDraft {
  readonly clientId: string;
  readonly name: string;
  readonly hypothesis: string;
  readonly interventions: readonly InterventionDraft[];
}

interface ScenarioBuilderProps {
  readonly onCreated: (scenario: ScenarioDetail) => void;
}

function createInterventionDraft(clientId: string): InterventionDraft {
  return {
    clientId,
    content: "",
    offsetMinutes: "0",
  };
}

function createAlternativeDraft(
  clientId: string,
  interventionClientId: string,
): AlternativeDraft {
  return {
    clientId,
    name: "",
    hypothesis: "",
    interventions: [createInterventionDraft(interventionClientId)],
  };
}

function updateAlternativeName(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  name: string,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId ? { ...alternative, name } : alternative,
  );
}

function updateAlternativeHypothesis(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  hypothesis: string,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId
      ? { ...alternative, hypothesis }
      : alternative,
  );
}

function addAlternativeIntervention(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  intervention: InterventionDraft,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId
      ? {
          ...alternative,
          interventions: [...alternative.interventions, intervention],
        }
      : alternative,
  );
}

function removeAlternativeIntervention(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  interventionId: string,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId
      ? {
          ...alternative,
          interventions: alternative.interventions.filter(
            (intervention) => intervention.clientId !== interventionId,
          ),
        }
      : alternative,
  );
}

function updateInterventionContent(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  interventionId: string,
  content: string,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId
      ? {
          ...alternative,
          interventions: alternative.interventions.map((intervention) =>
            intervention.clientId === interventionId
              ? { ...intervention, content }
              : intervention,
          ),
        }
      : alternative,
  );
}

function updateInterventionOffset(
  alternatives: readonly AlternativeDraft[],
  alternativeId: string,
  interventionId: string,
  offsetMinutes: string,
): readonly AlternativeDraft[] {
  return alternatives.map((alternative) =>
    alternative.clientId === alternativeId
      ? {
          ...alternative,
          interventions: alternative.interventions.map((intervention) =>
            intervention.clientId === interventionId
              ? { ...intervention, offsetMinutes }
              : intervention,
          ),
        }
      : alternative,
  );
}

function isValidOffset(offsetMinutes: string): boolean {
  const parsedOffset = Number(offsetMinutes);

  return offsetMinutes.trim() !== ""
    && Number.isInteger(parsedOffset)
    && parsedOffset >= 0
    && parsedOffset <= 1_440;
}

function isAlternativeComplete(alternative: AlternativeDraft): boolean {
  return alternative.name.trim() !== ""
    && alternative.hypothesis.trim() !== ""
    && alternative.interventions.length >= 1
    && alternative.interventions.length <= 20
    && alternative.interventions.every(
      (intervention) =>
        intervention.content.trim() !== ""
        && isValidOffset(intervention.offsetMinutes),
    );
}

function normalizeScenarioCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`决策实验输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("创建决策实验失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function isAmbiguousScenarioCreationError(error: Error): boolean {
  return isAmbiguousPostResultError(error);
}

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 12)}…${digest.slice(-8)}`;
}

function selectedWorldModelSummary(
  state: WorldModelsLoadState,
  worldModelId: string | null,
): WorldModelSummary | null {
  if (worldModelId === null || state.data === null) {
    return null;
  }

  return state.data.items.find((worldModel) => worldModel.id === worldModelId) ?? null;
}

function selectedWorldModelDetail(
  state: WorldModelDetailLoadState,
  worldModelId: string | null,
): WorldModelDetail | null {
  if (worldModelId === null || state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === worldModelId ? state.data : null;
}

function selectedSnapshotSummary(
  worldModel: WorldModelDetail | null,
  snapshotId: string | null,
): SnapshotSummary | null {
  if (worldModel === null || snapshotId === null) {
    return null;
  }

  return worldModel.snapshots.find((snapshot) => snapshot.id === snapshotId) ?? null;
}

function ScenarioBuilderSkeleton(): JSX.Element {
  return (
    <div className="scenario-builder-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取已封存世界模型</span>
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
    </div>
  );
}

function SnapshotContext({
  snapshot,
}: {
  readonly snapshot: SnapshotSummary;
}): JSX.Element {
  return (
    <div className="scenario-snapshot-context" aria-label="实验使用的冻结现实版本">
      <div>
        <span className="scenario-version-marker" aria-hidden="true">v{snapshot.version}</span>
        <p>
          <strong>{snapshot.company_name}</strong>
          <small>{snapshot.evidence_count} 篇冻结证据 · 只读版本</small>
        </p>
      </div>
      <code title={snapshot.snapshot_sha256}>{snapshot.snapshot_sha256}</code>
    </div>
  );
}

function AlternativeEditor({
  alternative,
  alternativeIndex,
  alternativeCount,
  createClientId,
  onChange,
  onRemove,
  onInvalidateAcknowledgement,
}: {
  readonly alternative: AlternativeDraft;
  readonly alternativeIndex: number;
  readonly alternativeCount: number;
  readonly createClientId: () => string;
  readonly onChange: (alternatives: readonly AlternativeDraft[]) => void;
  readonly onRemove: (alternativeId: string) => void;
  readonly onInvalidateAcknowledgement: () => void;
}): JSX.Element {
  const nameId = `scenario-alternative-name-${alternative.clientId}`;
  const hypothesisId = `scenario-alternative-hypothesis-${alternative.clientId}`;

  const applyChange = (alternatives: readonly AlternativeDraft[]): void => {
    onChange(alternatives);
    onInvalidateAcknowledgement();
  };

  return (
    <section
      className="scenario-alternative-editor"
      aria-labelledby={`scenario-alternative-title-${alternative.clientId}`}
    >
      <div className="scenario-alternative-heading">
        <div>
          <span>备选方案 {alternativeIndex + 1}</span>
          <h4 id={`scenario-alternative-title-${alternative.clientId}`}>
            {alternative.name.trim() === "" ? "尚未命名" : alternative.name}
          </h4>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={alternativeCount <= 1}
          aria-label={`删除方案：备选方案 ${alternativeIndex + 1}`}
          onClick={() => onRemove(alternative.clientId)}
        >
          删除方案
        </button>
      </div>

      <div className="scenario-variant-fields">
        <label htmlFor={nameId}>
          <span>方案名称</span>
          <input
            id={nameId}
            type="text"
            value={alternative.name}
            maxLength={200}
            placeholder="例如：主动公开供应链进展"
            required
            onChange={(event) =>
              applyChange(
                updateAlternativeName(
                  [alternative],
                  alternative.clientId,
                  event.target.value,
                ),
              )
            }
          />
        </label>
        <label htmlFor={hypothesisId}>
          <span>实验假设</span>
          <textarea
            id={hypothesisId}
            value={alternative.hypothesis}
            maxLength={2_000}
            rows={3}
            placeholder="说明这一方案预计改变什么，以及为什么。"
            required
            onChange={(event) =>
              applyChange(
                updateAlternativeHypothesis(
                  [alternative],
                  alternative.clientId,
                  event.target.value,
                ),
              )
            }
          />
        </label>
      </div>

      <div className="scenario-intervention-heading">
        <div>
          <h5>初始帖子</h5>
          <p>固定由快照企业在 Reddit 发布；时间相对实验开始计算。</p>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={alternative.interventions.length >= 20}
          onClick={() =>
            applyChange(
              addAlternativeIntervention(
                [alternative],
                alternative.clientId,
                createInterventionDraft(createClientId()),
              ),
            )
          }
        >
          添加帖子
        </button>
      </div>

      <ol className="scenario-intervention-editors">
        {alternative.interventions.map((intervention, interventionIndex) => {
          const contentId = `scenario-intervention-content-${intervention.clientId}`;
          const offsetId = `scenario-intervention-offset-${intervention.clientId}`;

          return (
            <li key={intervention.clientId}>
              <div className="scenario-intervention-meta">
                <strong>帖子 {interventionIndex + 1}</strong>
                <span>冻结企业</span>
                <span>Reddit</span>
                <button
                  type="button"
                  disabled={alternative.interventions.length <= 1}
                  aria-label={`删除备选方案 ${alternativeIndex + 1} 的帖子 ${interventionIndex + 1}`}
                  onClick={() =>
                    applyChange(
                      removeAlternativeIntervention(
                        [alternative],
                        alternative.clientId,
                        intervention.clientId,
                      ),
                    )
                  }
                >
                  删除
                </button>
              </div>
              <div className="scenario-intervention-fields">
                <label htmlFor={contentId}>
                  <span>帖子内容</span>
                  <textarea
                    id={contentId}
                    value={intervention.content}
                    maxLength={4_000}
                    rows={3}
                    placeholder="输入希望投放到模拟环境中的初始内容。"
                    required
                    onChange={(event) =>
                      applyChange(
                        updateInterventionContent(
                          [alternative],
                          alternative.clientId,
                          intervention.clientId,
                          event.target.value,
                        ),
                      )
                    }
                  />
                </label>
                <label htmlFor={offsetId}>
                  <span>开始后分钟</span>
                  <input
                    id={offsetId}
                    type="number"
                    value={intervention.offsetMinutes}
                    min={0}
                    max={1_440}
                    step={1}
                    inputMode="numeric"
                    required
                    onChange={(event) =>
                      applyChange(
                        updateInterventionOffset(
                          [alternative],
                          alternative.clientId,
                          intervention.clientId,
                          event.target.value,
                        ),
                      )
                    }
                  />
                </label>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ScenarioBuilder({ onCreated }: ScenarioBuilderProps): JSX.Element {
  const { state: worldModelsState, reload: reloadWorldModels } = useWorldModels();
  const [selectedWorldModelId, setSelectedWorldModelId] = useState<string | null>(null);
  const {
    state: worldModelDetailState,
    reload: reloadWorldModelDetail,
  } = useWorldModelDetail(selectedWorldModelId);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [title, setTitle] = useState<string>("");
  const [decisionQuestion, setDecisionQuestion] = useState<string>("");
  const [baselineName, setBaselineName] = useState<string>("保持当前状态");
  const [baselineHypothesis, setBaselineHypothesis] = useState<string>("");
  const [alternatives, setAlternatives] = useState<readonly AlternativeDraft[]>(() => [
    createAlternativeDraft("alternative-1", "intervention-1"),
  ]);
  const [isHypothesisAcknowledged, setIsHypothesisAcknowledged] = useState<boolean>(false);
  const [creationState, setCreationState] = useState<ScenarioCreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const nextClientId = useRef<number>(2);
  const selectedModelSummary = selectedWorldModelSummary(
    worldModelsState,
    selectedWorldModelId,
  );
  const selectedModelDetail = selectedWorldModelDetail(
    worldModelDetailState,
    selectedWorldModelId,
  );
  const selectedSnapshot = selectedSnapshotSummary(
    selectedModelDetail,
    selectedSnapshotId,
  );
  const isSubmitting = creationState.status === "submitting";
  const hasAmbiguousCreationResult = creationState.status === "error"
    && isAmbiguousScenarioCreationError(creationState.error);
  const canSubmit = selectedWorldModelId !== null
    && selectedSnapshot !== null
    && worldModelsState.status === "success"
    && worldModelDetailState.status === "success"
    && title.trim() !== ""
    && decisionQuestion.trim() !== ""
    && baselineName.trim() !== ""
    && baselineHypothesis.trim() !== ""
    && alternatives.length >= 1
    && alternatives.length <= 5
    && alternatives.every(isAlternativeComplete)
    && isHypothesisAcknowledged
    && !isSubmitting;

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  const createClientId = (): string => {
    const clientId = `draft-${nextClientId.current}`;
    nextClientId.current += 1;

    return clientId;
  };

  const invalidateAcknowledgement = (): void => {
    setIsHypothesisAcknowledged(false);
    setCreationState({ status: "idle" });
  };

  const changeWorldModel = (worldModelId: string): void => {
    if (activeController.current !== null) {
      return;
    }

    setSelectedWorldModelId(worldModelId);
    setSelectedSnapshotId(null);
    invalidateAcknowledgement();
  };

  const changeSnapshot = (snapshotId: string): void => {
    if (activeController.current !== null) {
      return;
    }

    setSelectedSnapshotId(snapshotId);
    invalidateAcknowledgement();
  };

  const removeAlternative = (alternativeId: string): void => {
    if (activeController.current !== null || alternatives.length <= 1) {
      return;
    }

    setAlternatives((currentAlternatives) =>
      currentAlternatives.filter((alternative) => alternative.clientId !== alternativeId),
    );
    invalidateAcknowledgement();
  };

  const addAlternative = (): void => {
    if (activeController.current !== null || alternatives.length >= 5) {
      return;
    }

    setAlternatives((currentAlternatives) => [
      ...currentAlternatives,
      createAlternativeDraft(createClientId(), createClientId()),
    ]);
    invalidateAcknowledgement();
  };

  const resetDraft = (): void => {
    setTitle("");
    setDecisionQuestion("");
    setBaselineName("保持当前状态");
    setBaselineHypothesis("");
    setAlternatives([
      createAlternativeDraft(createClientId(), createClientId()),
    ]);
    setIsHypothesisAcknowledged(false);
  };

  const submitScenario = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (
      !canSubmit
      || activeController.current !== null
      || selectedWorldModelId === null
      || selectedSnapshot === null
    ) {
      return;
    }

    let request: ScenarioCreateRequest;

    try {
      request = scenarioCreateRequestSchema.parse({
        title,
        decision_question: decisionQuestion,
        world_model_id: selectedWorldModelId,
        world_snapshot_id: selectedSnapshot.id,
        baseline: {
          name: baselineName,
          hypothesis: baselineHypothesis,
        },
        alternatives: alternatives.map((alternative) => ({
          name: alternative.name,
          hypothesis: alternative.hypothesis,
          interventions: alternative.interventions.map((intervention) => ({
            kind: "initial_post",
            actor: "snapshot_company",
            channel: "reddit",
            content: intervention.content,
            offset_minutes: Number(intervention.offsetMinutes),
          })),
        })),
      });
    } catch (error: unknown) {
      setCreationState({ status: "error", error: normalizeScenarioCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setCreationState({ status: "submitting" });

    try {
      const scenario = await createScenario(request, controller.signal);

      if (activeController.current !== controller || controller.signal.aborted) {
        return;
      }

      resetDraft();
      setCreationState({ status: "success", scenario });
      onCreated(scenario);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      if (activeController.current !== controller) {
        return;
      }

      setCreationState({ status: "error", error: normalizeScenarioCreationError(error) });
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  };

  const worldModels = worldModelsState.data?.items ?? [];
  const snapshots = selectedModelDetail?.snapshots ?? [];

  return (
    <section className="scenario-builder" aria-labelledby="scenario-builder-title">
      <div className="scenario-section-heading">
        <div>
          <span>实验编排</span>
          <h3 id="scenario-builder-title">在同一现实版本上并排设计对照</h3>
          <p>先明确选择世界版本，再把自然演化基线与每个行动方案放进同一比较面。</p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>POST /api/v2/scenarios</code>
        </details>
      </div>

      <form onSubmit={(event) => void submitScenario(event)}>
        <fieldset className="scenario-builder-fieldset" disabled={isSubmitting}>
          <legend className="sr-only">决策实验规格</legend>

          {worldModelsState.status === "error" ? (
            <ApiErrorPanel
              title="无法读取冻结世界模型"
              error={worldModelsState.error}
              isRetrying={worldModelsState.isRetrying}
              onRetry={reloadWorldModels}
            />
          ) : null}

          {worldModelsState.status === "loading" && worldModelsState.data === null ? (
            <ScenarioBuilderSkeleton />
          ) : null}

          {worldModelsState.data !== null && worldModels.length === 0 ? (
            <div className="scenario-builder-empty" role="status">
              <strong>还没有可用于实验的现实快照</strong>
              <p>先到“世界模型”完成企业证据的人工确认与冻结，再回来设计决策实验。</p>
            </div>
          ) : null}

          {worldModels.length > 0 ? (
            <div className="scenario-form-content scenario-builder-cockpit">
              <aside className="scenario-context-rail decision-context-rail" aria-label="实验现实上下文">
                <div className="decision-rail-heading">
                  <span>现实上下文</span>
                  <strong>{selectedModelSummary?.title ?? "尚未选择世界模型"}</strong>
                  <small>实验不会自动沿用上次查看的模型或快照。</small>
                </div>
                <div className="scenario-context-fields">
                <label htmlFor="scenario-world-model">
                  <span>世界模型</span>
                  <select
                    id="scenario-world-model"
                    value={selectedWorldModelId ?? ""}
                    required
                    onChange={(event) => changeWorldModel(event.target.value)}
                  >
                    <option value="" disabled>请选择世界模型</option>
                    {worldModels.map((worldModel) => (
                      <option value={worldModel.id} key={worldModel.id}>
                        {worldModel.title} · {worldModel.company_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="scenario-world-snapshot">
                  <span>冻结快照版本</span>
                  <select
                    id="scenario-world-snapshot"
                    value={selectedSnapshotId ?? ""}
                    disabled={selectedModelDetail === null}
                    required
                    onChange={(event) => changeSnapshot(event.target.value)}
                  >
                    <option value="" disabled>请选择冻结版本</option>
                    {snapshots.map((snapshot) => (
                      <option value={snapshot.id} key={snapshot.id}>
                        v{snapshot.version} · {snapshot.evidence_count} 篇证据 · {abbreviatedDigest(snapshot.snapshot_sha256)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="button button-secondary button-compact scenario-context-refresh"
                  type="button"
                  disabled={selectedWorldModelId === null || worldModelDetailState.status === "loading"}
                  aria-busy={worldModelDetailState.status === "loading"}
                  onClick={reloadWorldModelDetail}
                >
                  {worldModelDetailState.status === "loading" ? "核验中…" : "重新核验版本"}
                </button>
                </div>

                {worldModelDetailState.status === "error" ? (
                  <ApiErrorPanel
                    title="无法读取冻结快照版本"
                    error={worldModelDetailState.error}
                    isRetrying={worldModelDetailState.isRetrying}
                    onRetry={reloadWorldModelDetail}
                  />
                ) : null}

                {selectedModelDetail !== null && selectedSnapshot === null ? (
                  <div className="decision-inspector-empty" role="status">
                    <strong>请选择一个冻结版本</strong>
                    <p>读取模型不会替你选择最新版本，避免把变化后的现实当作原实验上下文。</p>
                  </div>
                ) : null}

                {selectedModelSummary !== null && selectedSnapshot !== null ? (
                  <SnapshotContext snapshot={selectedSnapshot} />
                ) : null}
              </aside>

              <main className="scenario-experiment-stage decision-main-stage">
                <div className="decision-stage-heading">
                  <span>比较画布</span>
                  <strong>一个决策问题 · 一条自然基线 · {alternatives.length} 个行动方案</strong>
                </div>
                <div className="scenario-core-fields">
                <label htmlFor="scenario-title">
                  <span>实验名称</span>
                  <input
                    id="scenario-title"
                    type="text"
                    value={title}
                    maxLength={300}
                    placeholder="例如：华为全球舆情回应策略实验"
                    required
                    onChange={(event) => {
                      setTitle(event.target.value);
                      invalidateAcknowledgement();
                    }}
                  />
                </label>
                <label htmlFor="scenario-decision-question">
                  <span>要回答的决策问题</span>
                  <textarea
                    id="scenario-decision-question"
                    value={decisionQuestion}
                    maxLength={2_000}
                    rows={3}
                    placeholder="明确比较对象、目标受众和判断范围。"
                    required
                    onChange={(event) => {
                      setDecisionQuestion(event.target.value);
                      invalidateAcknowledgement();
                    }}
                  />
                </label>
                </div>

                <div className="scenario-comparison-canvas">
                  <section className="scenario-baseline-editor" aria-labelledby="scenario-baseline-title">
                    <div className="scenario-baseline-heading">
                      <div>
                        <span>对照基线</span>
                        <h4 id="scenario-baseline-title">不施加任何干预</h4>
                      </div>
                      <strong>0 个动作</strong>
                    </div>
                    <div className="scenario-variant-fields">
                      <label htmlFor="scenario-baseline-name">
                        <span>基线名称</span>
                        <input
                          id="scenario-baseline-name"
                          type="text"
                          value={baselineName}
                          maxLength={200}
                          required
                          onChange={(event) => {
                            setBaselineName(event.target.value);
                            invalidateAcknowledgement();
                          }}
                        />
                      </label>
                      <label htmlFor="scenario-baseline-hypothesis">
                        <span>基线假设</span>
                        <textarea
                          id="scenario-baseline-hypothesis"
                          value={baselineHypothesis}
                          maxLength={2_000}
                          rows={3}
                          placeholder="说明若不采取新动作，预计环境会如何演化。"
                          required
                          onChange={(event) => {
                            setBaselineHypothesis(event.target.value);
                            invalidateAcknowledgement();
                          }}
                        />
                      </label>
                    </div>
                    <p className="scenario-baseline-rule">
                      基线固定为空干预组，用来区分环境自然变化与方案动作造成的变化。
                    </p>
                  </section>

                  <section className="scenario-alternatives-lane" aria-labelledby="scenario-alternatives-title">
                    <div className="scenario-alternatives-heading">
                      <div>
                        <h4 id="scenario-alternatives-title">备选方案</h4>
                        <p>最多 5 个方案；每个方案包含 1–20 条初始帖子。</p>
                      </div>
                      <button
                        className="button button-secondary"
                        type="button"
                        disabled={alternatives.length >= 5}
                        onClick={addAlternative}
                      >
                        添加备选方案
                      </button>
                    </div>

                    <div className="scenario-alternative-list">
                      {alternatives.map((alternative, alternativeIndex) => (
                        <AlternativeEditor
                          key={alternative.clientId}
                          alternative={alternative}
                          alternativeIndex={alternativeIndex}
                          alternativeCount={alternatives.length}
                          createClientId={createClientId}
                          onChange={(updatedAlternative) => {
                            setAlternatives((currentAlternatives) =>
                              currentAlternatives.map((currentAlternative) =>
                                currentAlternative.clientId === alternative.clientId
                                  ? updatedAlternative[0] ?? currentAlternative
                                  : currentAlternative,
                              ),
                            );
                          }}
                          onRemove={removeAlternative}
                          onInvalidateAcknowledgement={invalidateAcknowledgement}
                        />
                      ))}
                    </div>
                  </section>
                </div>
              </main>

              <aside className="scenario-submit-bar decision-inspector scenario-action-inspector">
                <div className="decision-inspector-heading">
                  <span>冻结规格</span>
                  <h4>提交前边界确认</h4>
                </div>
                <dl className="decision-context-ledger">
                  <div><dt>现实版本</dt><dd>{selectedSnapshot === null ? "未选择" : `v${selectedSnapshot.version}`}</dd></div>
                  <div><dt>对照基线</dt><dd>0 个干预动作</dd></div>
                  <div><dt>备选方案</dt><dd>{alternatives.length} 个</dd></div>
                </dl>
                <label className="scenario-hypothesis-confirmation">
                  <input
                    type="checkbox"
                    checked={isHypothesisAcknowledged}
                    onChange={(event) => {
                      setIsHypothesisAcknowledged(event.target.checked);
                      setCreationState({ status: "idle" });
                    }}
                  />
                  <span>
                    <strong>这是实验假设，不是现实事实</strong>
                    <small>方案和帖子将作为模拟输入；它们不会写回冻结证据或被当作真实报道。</small>
                  </span>
                </label>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={!canSubmit}
                  aria-busy={isSubmitting}
                >
                  {isSubmitting ? "正在冻结实验规格…" : "创建决策实验"}
                </button>

                {creationState.status === "error" ? (
                  <div className="scenario-create-message scenario-create-error" role="alert">
                    <strong>
                      {hasAmbiguousCreationResult
                        ? "创建结果未知，请先刷新实验目录核对"
                        : "实验没有创建"}
                    </strong>
                    <p>{creationState.error.message}</p>
                    <small>
                      {hasAmbiguousCreationResult
                        ? "网络、服务端或响应契约异常可能发生在完成封存之后；相同规格会按内容哈希去重，但仍应先核对实验目录。"
                        : "POST 请求不会自动重试；核对输入后请再次主动提交。"}
                    </small>
                  </div>
                ) : null}

                {creationState.status === "success" ? (
                  <div className="scenario-create-message scenario-create-success" role="status">
                    <strong>实验规格已冻结</strong>
                    <p>
                      {creationState.scenario.title} · {abbreviatedDigest(creationState.scenario.scenario_sha256)}
                    </p>
                  </div>
                ) : null}
              </aside>
            </div>
          ) : null}
        </fieldset>
      </form>
    </section>
  );
}

function ScenarioListSkeleton(): JSX.Element {
  return (
    <div className="scenario-list-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取决策实验</span>
      {Array.from({ length: 3 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function ScenarioList({
  state,
  selectedScenarioId,
  onSelect,
  onReload,
}: {
  readonly state: ScenariosLoadState;
  readonly selectedScenarioId: string | null;
  readonly onSelect: (scenario: ScenarioSummary) => void;
  readonly onReload: () => void;
}): JSX.Element {
  const response = state.data;

  return (
    <aside className="scenario-directory" aria-labelledby="scenario-directory-title">
      <div className="scenario-directory-heading">
        <div>
          <h3 id="scenario-directory-title">实验目录</h3>
          <p>{response === null ? "等待接口返回" : `${formatMediaCount(response.total)} 个实验`}</p>
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
          title="无法读取实验目录"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && response === null ? <ScenarioListSkeleton /> : null}

      {response !== null && response.items.length === 0 ? (
        <div className="scenario-directory-empty" role="status">
          <strong>还没有决策实验</strong>
          <p>在上方选择冻结世界版本，建立第一组基线与备选方案。</p>
        </div>
      ) : null}

      {response !== null && response.items.length > 0 ? (
        <ul className="scenario-list" aria-busy={state.status === "loading"}>
          {response.items.map((scenario) => {
            const isSelected = selectedScenarioId === scenario.id;

            return (
              <li key={scenario.id}>
                <button
                  type="button"
                  data-selected={isSelected}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(scenario)}
                >
                  <span className="scenario-version-marker" aria-hidden="true">
                    v{scenario.snapshot.version}
                  </span>
                  <span className="scenario-list-copy">
                    <strong>{scenario.title}</strong>
                    <small>{scenario.decision_question}</small>
                    <span>{scenario.snapshot.company_name} · {scenario.snapshot.evidence_count} 篇证据</span>
                    <code title={scenario.scenario_sha256}>
                      {abbreviatedDigest(scenario.scenario_sha256)}
                    </code>
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

function InterventionDetail({
  intervention,
}: {
  readonly intervention: ScenarioIntervention;
}): JSX.Element {
  return (
    <li>
      <header>
        <strong>帖子 #{intervention.position + 1}</strong>
        <span>冻结企业</span>
        <span>Reddit</span>
        <time>+{intervention.offset_minutes} 分钟</time>
      </header>
      <p>{intervention.content}</p>
      <code title={intervention.id}>{intervention.id}</code>
    </li>
  );
}

function AlternativeDetail({
  alternative,
}: {
  readonly alternative: AlternativeVariant;
}): JSX.Element {
  return (
    <section
      className="scenario-variant-detail"
      aria-labelledby={`scenario-variant-detail-${alternative.id}`}
    >
      <div className="scenario-variant-detail-heading">
        <div>
          <span>备选 #{alternative.position}</span>
          <h4 id={`scenario-variant-detail-${alternative.id}`}>{alternative.name}</h4>
        </div>
        <code title={alternative.id}>{alternative.id}</code>
      </div>
      <p className="scenario-variant-hypothesis">{alternative.hypothesis}</p>
      <ol className="scenario-intervention-detail-list">
        {alternative.interventions.map((intervention) => (
          <InterventionDetail intervention={intervention} key={intervention.id} />
        ))}
      </ol>
    </section>
  );
}

function ScenarioDetailView({ scenario }: { readonly scenario: ScenarioDetail }): JSX.Element {
  const interventionCount = scenario.alternatives.reduce(
    (count, alternative) => count + alternative.interventions.length,
    0,
  );

  return (
    <div className="scenario-detail-content">
      <div className="scenario-detail-heading">
        <div>
          <span className="scenario-spec-badge">实验规格 · 非现实事实</span>
          <h3>{scenario.title}</h3>
          <p>{scenario.decision_question}</p>
          <time dateTime={scenario.created_at}>创建于 {formatMediaTimestamp(scenario.created_at)}</time>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>GET /api/v2/scenarios/&#123;id&#125;</code>
        </details>
      </div>

      <dl className="scenario-detail-ledger" aria-label="实验摘要">
        <div>
          <dt>现实版本</dt>
          <dd>v{scenario.snapshot.version}</dd>
        </div>
        <div>
          <dt>冻结企业</dt>
          <dd>{scenario.snapshot.company_name}</dd>
        </div>
        <div>
          <dt>备选方案</dt>
          <dd>{scenario.alternatives.length}</dd>
        </div>
        <div>
          <dt>干预动作</dt>
          <dd>{interventionCount}</dd>
        </div>
      </dl>

      <div className="scenario-hash-ledger">
        <div>
          <span>scenario_sha256 · 实验规格内容地址</span>
          <code>{scenario.scenario_sha256}</code>
        </div>
        <div>
          <span>snapshot_sha256 · 冻结现实内容地址</span>
          <code>{scenario.snapshot.snapshot_sha256}</code>
        </div>
      </div>

      <section
        className="scenario-baseline-detail"
        aria-labelledby={`scenario-baseline-detail-${scenario.baseline.id}`}
      >
        <div className="scenario-variant-detail-heading">
          <div>
            <span>对照基线 · #{scenario.baseline.position}</span>
            <h4 id={`scenario-baseline-detail-${scenario.baseline.id}`}>
              {scenario.baseline.name}
            </h4>
          </div>
          <strong>无干预</strong>
        </div>
        <p className="scenario-variant-hypothesis">{scenario.baseline.hypothesis}</p>
        <code title={scenario.baseline.id}>{scenario.baseline.id}</code>
      </section>

      <div className="scenario-alternative-details-heading">
        <h4>备选方案与初始帖子</h4>
        <p>以下均为实验输入；固定 actor=snapshot_company、channel=reddit。</p>
      </div>
      <div className="scenario-alternative-details">
        {scenario.alternatives.map((alternative) => (
          <AlternativeDetail alternative={alternative} key={alternative.id} />
        ))}
      </div>
    </div>
  );
}

function ScenarioDetailPanel({
  selectedScenarioId,
  state,
  onReload,
}: {
  readonly selectedScenarioId: string | null;
  readonly state: ScenarioDetailLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  const loadedScenario = state.status === "idle" ? null : state.data;
  const scenario = selectedScenarioId !== null && loadedScenario?.id === selectedScenarioId
    ? loadedScenario
    : null;

  if (selectedScenarioId === null) {
    return (
      <section className="scenario-detail scenario-detail-empty" aria-labelledby="scenario-detail-empty-title">
        <div>
          <h3 id="scenario-detail-empty-title">选择实验核对完整规格</h3>
          <p>这里会并列显示现实快照、基线、备选方案、初始帖子与两个内容哈希。</p>
        </div>
      </section>
    );
  }

  return (
    <section
      className="scenario-detail"
      aria-label="决策实验规格详情"
      aria-busy={state.status === "loading"}
    >
      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取实验规格"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && scenario === null ? (
        <div className="scenario-detail-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取实验规格</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {scenario !== null ? <ScenarioDetailView scenario={scenario} /> : null}
    </section>
  );
}

export function ScenarioPage(): JSX.Element {
  const { state: scenariosState, reload: reloadScenarios } = useScenarios();
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const {
    state: scenarioDetailState,
    reload: reloadScenarioDetail,
  } = useScenarioDetail(selectedScenarioId);

  const selectedScenario = selectedScenarioId === null
    ? null
    : scenariosState.data?.items.find((scenario) => scenario.id === selectedScenarioId) ?? null;

  const scenarioCreated = (scenario: ScenarioDetail): void => {
    setSelectedScenarioId(scenario.id);
    reloadScenarios();
  };

  return (
    <div className="scenario-page decision-surface decision-scenario-surface">
      <header className="decision-surface-header" aria-labelledby="scenario-page-title">
        <div className="decision-surface-heading">
          <span className="decision-stage-index">03 · 决策实验室</span>
          <div>
            <h2 id="scenario-page-title">让基线与行动方案站在同一个现实上</h2>
            <p>现实证据保持只读；这里冻结的是比较问题、假设与可复现干预，不把模拟输入伪装成事实。</p>
          </div>
        </div>
        <div className="decision-context-bar">
          <div className="decision-context-current" data-active={selectedScenario !== null}>
            <span>档案核验对象</span>
            <strong>{selectedScenario?.title ?? "尚未选择历史实验"}</strong>
            <small>
              {selectedScenario === null
                ? "下方档案等待明确选择，不会自动打开第一条。"
                : `现实 v${selectedScenario.snapshot.version} · ${selectedScenario.snapshot.company_name}`}
            </small>
          </div>
          <ul className="decision-boundary-legend" aria-label="实验边界">
            <li data-boundary="immutable"><span />冻结现实</li>
            <li data-boundary="observed"><span />无干预基线</li>
            <li data-boundary="candidate"><span />行动假设</li>
          </ul>
        </div>
      </header>

      <ScenarioBuilder onCreated={scenarioCreated} />

      <section className="scenario-registry decision-archive-stage" aria-labelledby="scenario-registry-title">
        <div className="scenario-registry-heading">
          <div>
            <span>实验档案</span>
            <h2 id="scenario-registry-title">回查现实版本与完整对照规格</h2>
            <p>只有明确选择后才会打开历史实验；基线、方案动作与两个内容地址保持只读。</p>
          </div>
        </div>
        <div className="scenario-registry-workbench">
          <ScenarioList
            state={scenariosState}
            selectedScenarioId={selectedScenarioId}
            onSelect={(scenario) => setSelectedScenarioId(scenario.id)}
            onReload={reloadScenarios}
          />
          <ScenarioDetailPanel
            selectedScenarioId={selectedScenarioId}
            state={scenarioDetailState}
            onReload={reloadScenarioDetail}
          />
        </div>
      </section>
    </div>
  );
}
