import { useEffect, useRef, useState, type FormEvent } from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { PopulationContextPanel } from "./PopulationContextPanel";
import { RunInteractionGraph } from "./RunInteractionGraph";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaTimestamp } from "./mediaPresentation";
import type { RunStudioRoute } from "./runStudioRoute";
import type { ScenarioDetail } from "./scenarioContracts";
import {
  createSemanticExperiment,
  fetchSemanticReadiness,
  semanticExperimentCreateRequestSchema,
  type SemanticExperimentCreateRequest,
  type SemanticExperimentDetail,
  type SemanticExperimentSummary,
  type SemanticTrial,
  type SemanticTrialEvent,
} from "./semanticExperimentContracts";
import {
  useSemanticComparison,
  useSemanticExperimentDetail,
  useSemanticExperiments,
  useSemanticReadiness,
  useSemanticTrialEvents,
  type SemanticExperimentsLoadState,
  type SemanticReadinessLoadState,
} from "./useSemanticExperiments";
import { useCohortDetail } from "./usePopulations";
import { useScenarioDetail, useScenarios } from "./useScenarios";
import "./semanticExperiment.css";

interface SemanticExperimentPageProps {
  readonly route: RunStudioRoute;
  readonly onRouteChange: (route: RunStudioRoute) => void;
}

type CreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly experiment: SemanticExperimentDetail }
  | { readonly status: "error"; readonly error: Error };

const statusLabels: Readonly<Record<SemanticTrial["status"], string>> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
};

const actionLabels: Readonly<Record<SemanticTrialEvent["action_type"], string>> = {
  create_post: "发布内容",
  create_comment: "发表评论",
  like_post: "赞同帖子",
  dislike_post: "反对帖子",
  do_nothing: "未采取动作",
};

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 10)}…${digest.slice(-8)}`;
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

function normalizeCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    return new Error(`语义实验输入无效：${error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ")}`);
  }

  return error instanceof Error
    ? error
    : new Error("创建语义实验失败：请求抛出了非标准错误。请检查后端日志。");
}

function parseSeed(value: string): number | null {
  if (!/^\d+$/u.test(value)) {
    return null;
  }

  const seed = Number(value);
  return Number.isSafeInteger(seed) && seed >= 0 && seed <= 4_294_967_295
    ? seed
    : null;
}

function parsedSeeds(firstSeed: string, secondSeed: string): readonly number[] | null {
  const first = parseSeed(firstSeed);
  const second = secondSeed === "" ? null : parseSeed(secondSeed);

  if (first === null || (secondSeed !== "" && second === null)) {
    return null;
  }

  const values = second === null ? [first] : [first, second];
  return new Set(values).size === values.length ? values : null;
}

function selectedScenario(
  scenarioId: string | null,
  detail: ScenarioDetail | null,
): ScenarioDetail | null {
  return scenarioId !== null && detail?.id === scenarioId ? detail : null;
}

function findTrial(
  experiment: SemanticExperimentDetail | null,
  trialId: string | null,
): SemanticTrial | null {
  if (experiment === null || trialId === null) {
    return null;
  }

  return experiment.variants
    .flatMap((variant) => variant.trials)
    .find((trial) => trial.id === trialId) ?? null;
}

function experimentIsTerminal(experiment: SemanticExperimentDetail | null): boolean {
  return experiment?.status === "succeeded" || experiment?.status === "failed";
}

function SemanticReadinessStrip({
  state,
  onReload,
}: {
  readonly state: SemanticReadinessLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  const readiness = state.data;

  return (
    <section className="semantic-readiness" aria-labelledby="semantic-readiness-title">
      <header>
        <div>
          <span>RUNTIME / SEMANTIC</span>
          <h3 id="semantic-readiness-title">语义运行边界</h3>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={state.status === "loading"}
          onClick={onReload}
        >
          {state.status === "loading" ? "核验中…" : "重新核验"}
        </button>
      </header>
      {state.status === "error" ? (
        <ApiErrorPanel title="无法核验语义运行状态" error={state.error} onRetry={onReload} isRetrying={false} />
      ) : null}
      {state.status === "loading" && readiness === null ? (
        <div className="semantic-skeleton" role="status"><span className="skeleton-block" /></div>
      ) : readiness !== null ? (
        <div className="semantic-readiness-body">
          <dl>
            <div><dt>工作进程</dt><dd data-ready={readiness.worker_online}>{readiness.live_worker_count} 个在线</dd></div>
            <div><dt>语义运行时</dt><dd data-ready={readiness.semantic_runtime_ready}>{readiness.semantic_runtime_ready ? "可提交" : "未就绪"}</dd></div>
            <div><dt>模型</dt><dd>{readiness.model_name ?? "未配置"}</dd></div>
            <div><dt>配置冲突</dt><dd data-ready={!readiness.configuration_conflict}>{readiness.configuration_conflict ? "存在" : "无"}</dd></div>
            <div><dt>配置哈希</dt><dd>{readiness.semantic_config_sha256 === null ? "—" : <code title={readiness.semantic_config_sha256}>{abbreviatedDigest(readiness.semantic_config_sha256)}</code>}</dd></div>
            <div><dt>Persona profile</dt><dd>{readiness.prompt_schema_version ?? "—"}</dd></div>
          </dl>
          <div className="semantic-limitations">
            <strong>能力限制</strong>
            {readiness.limitations.length === 0
              ? <p>接口未声明附加限制。</p>
              : <ul>{readiness.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function ExperimentDirectory({
  state,
  selectedExperimentId,
  onSelect,
  onReload,
}: {
  readonly state: SemanticExperimentsLoadState;
  readonly selectedExperimentId: string | null;
  readonly onSelect: (experiment: SemanticExperimentSummary) => void;
  readonly onReload: () => void;
}): JSX.Element {
  const response = state.data;

  return (
    <section className="semantic-directory" aria-labelledby="semantic-directory-title">
      <header>
        <div>
          <h3 id="semantic-directory-title">实验目录</h3>
          <p>{response === null ? "等待接口" : `${response.total} 个真实实验`}</p>
        </div>
        <button className="button button-secondary button-compact" type="button" onClick={onReload}>刷新</button>
      </header>
      {state.status === "error" ? (
        <ApiErrorPanel title="无法读取语义实验目录" error={state.error} onRetry={onReload} isRetrying={false} />
      ) : null}
      {response !== null && response.items.length === 0 ? (
        <div className="semantic-empty"><strong>还没有语义实验</strong><p>成功提交的真实实验会出现在这里。</p></div>
      ) : null}
      {response !== null && response.items.length > 0 ? (
        <ul>
          {response.items.map((experiment) => (
            <li key={experiment.id}>
              <button
                type="button"
                data-selected={experiment.id === selectedExperimentId}
                aria-pressed={experiment.id === selectedExperimentId}
                onClick={() => onSelect(experiment)}
              >
                <span className="semantic-status" data-status={experiment.status}>{statusLabels[experiment.status]}</span>
                <span><strong>{experiment.scenario.title}</strong><small>{experiment.cohort.title} · {experiment.trial_count} trials</small></span>
                <code>{abbreviatedDigest(experiment.experiment_sha256)}</code>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function SemanticComposer({
  readinessState,
  cohortId,
  scenarioId,
  onCohortIdChange,
  onScenarioIdChange,
  onReloadReadiness,
  onCreated,
}: {
  readonly readinessState: SemanticReadinessLoadState;
  readonly cohortId: string | null;
  readonly scenarioId: string | null;
  readonly onCohortIdChange: (cohortId: string | null) => void;
  readonly onScenarioIdChange: (scenarioId: string | null) => void;
  readonly onReloadReadiness: () => void;
  readonly onCreated: (experiment: SemanticExperimentDetail) => void;
}): JSX.Element {
  const { state: scenariosState, reload: reloadScenarios } = useScenarios();
  const { state: scenarioState, reload: reloadScenario } = useScenarioDetail(scenarioId);
  const { state: cohortState, reload: reloadCohort } = useCohortDetail(cohortId);
  const [alternativeIds, setAlternativeIds] = useState<readonly string[]>([]);
  const [firstSeed, setFirstSeed] = useState<string>("");
  const [secondSeed, setSecondSeed] = useState<string>("");
  const [rounds, setRounds] = useState<string>("1");
  const [minutesPerRound, setMinutesPerRound] = useState<string>("60");
  const [creationState, setCreationState] = useState<CreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const scenarios = scenariosState.data?.items ?? [];
  const scenario = selectedScenario(
    scenarioId,
    scenarioState.status === "idle" ? null : scenarioState.data,
  );
  const cohort = cohortState.status === "success" && cohortState.data.id === cohortId
    ? cohortState.data
    : null;
  const seeds = parsedSeeds(firstSeed, secondSeed);
  const parsedRounds = Number(rounds);
  const parsedMinutes = Number(minutesPerRound);
  const hasValidRounds = Number.isInteger(parsedRounds)
    && parsedRounds >= 1
    && parsedRounds <= 3;
  const hasValidMinutes = Number.isInteger(parsedMinutes)
    && parsedMinutes >= 15
    && parsedMinutes <= 240;
  const budget = cohort === null || seeds === null || !hasValidRounds
    ? null
    : (1 + alternativeIds.length) * seeds.length * parsedRounds * cohort.persona_count;
  const readiness = readinessState.status === "success" ? readinessState.data : null;
  const blockers: string[] = [];

  if (readiness === null) blockers.push("等待语义 readiness 核验");
  else {
    if (!readiness.worker_online) blockers.push("没有在线工作进程");
    if (!readiness.semantic_runtime_ready) blockers.push("语义运行时未就绪");
    if (readiness.configuration_conflict) blockers.push("存在模型配置冲突");
  }
  if (scenario === null) blockers.push("请选择并载入已封存决策实验");
  if (cohort === null) blockers.push("请选择已封存 Cohort");
  else if (cohort.persona_count > 8) blockers.push(`Cohort 含 ${cohort.persona_count} 人，语义实验最多 8 人`);
  if (alternativeIds.length < 1 || alternativeIds.length > 2) blockers.push("请选择 1–2 个备选方案");
  if (seeds === null) blockers.push("种子需为 1–2 个不重复 uint32");
  if (!hasValidRounds) blockers.push("轮次需为 1–3");
  if (!hasValidMinutes) blockers.push("每轮时长需为 15–240 分钟");
  if (budget !== null && budget > 96) blockers.push(`当前预算 ${budget}，上限为 96`);

  useEffect(() => () => activeController.current?.abort(), []);

  const resetCreation = (): void => setCreationState({ status: "idle" });

  const toggleAlternative = (alternativeId: string, checked: boolean): void => {
    if (checked) {
      if (alternativeIds.length < 2 && !alternativeIds.includes(alternativeId)) {
        setAlternativeIds([...alternativeIds, alternativeId]);
      }
    } else {
      setAlternativeIds(alternativeIds.filter((id) => id !== alternativeId));
    }
    resetCreation();
  };

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (blockers.length > 0 || scenario === null || cohort === null || seeds === null || activeController.current !== null) {
      return;
    }

    let request: SemanticExperimentCreateRequest;
    try {
      request = semanticExperimentCreateRequestSchema.parse({
        scenario_id: scenario.id,
        cohort_id: cohort.id,
        alternative_ids: alternativeIds,
        seeds,
        rounds: parsedRounds,
        minutes_per_round: parsedMinutes,
      });
    } catch (error: unknown) {
      setCreationState({ status: "error", error: normalizeCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setCreationState({ status: "submitting" });
    try {
      const currentReadiness = await fetchSemanticReadiness(controller.signal);
      if (!currentReadiness.worker_online
        || !currentReadiness.semantic_runtime_ready
        || currentReadiness.configuration_conflict) {
        onReloadReadiness();
        throw new Error(
          `提交前 readiness 已失效：worker_online=${String(currentReadiness.worker_online)}; `
          + `semantic_runtime_ready=${String(currentReadiness.semantic_runtime_ready)}; `
          + `configuration_conflict=${String(currentReadiness.configuration_conflict)}。POST 尚未发送。`,
        );
      }

      if (readiness === null
        || currentReadiness.model_name !== readiness.model_name
        || currentReadiness.semantic_config_sha256 !== readiness.semantic_config_sha256
        || currentReadiness.prompt_schema_version !== readiness.prompt_schema_version) {
        onReloadReadiness();
        throw new Error(
          "提交前模型配置与页面已核验配置不一致；POST 尚未发送。"
          + "已刷新 readiness，请核对模型和配置哈希后重新提交。",
        );
      }

      const experiment = await createSemanticExperiment(request, controller.signal);
      if (!controller.signal.aborted && activeController.current === controller) {
        setCreationState({ status: "success", experiment });
        onCreated(experiment);
      }
    } catch (error: unknown) {
      if (!(error instanceof DOMException && error.name === "AbortError")
        && activeController.current === controller) {
        setCreationState({ status: "error", error: normalizeCreationError(error) });
      }
    } finally {
      if (activeController.current === controller) activeController.current = null;
    }
  };

  return (
    <aside className="semantic-composer" aria-labelledby="semantic-composer-title">
      <header><span>COMPOSER / INPUT</span><h3 id="semantic-composer-title">冻结实验矩阵</h3><p>基线固定加入；只选择真实场景、Cohort 和备选方案。</p></header>
      <form onSubmit={(event) => void submit(event)}>
        <fieldset disabled={creationState.status === "submitting"}>
          {scenariosState.status === "error" ? <ApiErrorPanel title="无法读取决策实验" error={scenariosState.error} onRetry={reloadScenarios} isRetrying={false} /> : null}
          <div className="semantic-fields">
            <label htmlFor="semantic-scenario"><span>已封存决策实验</span><select id="semantic-scenario" name="scenario_id" value={scenarioId ?? ""} onChange={(event) => { onScenarioIdChange(event.target.value || null); setAlternativeIds([]); resetCreation(); }}><option value="">请选择</option>{scenarios.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
            {scenarioState.status === "error" ? <ApiErrorPanel title="无法载入决策实验规格" error={scenarioState.error} onRetry={reloadScenario} isRetrying={false} /> : null}
            <div className="semantic-baseline"><span>固定基线</span><strong>{scenario?.baseline.name ?? "选择场景后载入"}</strong><small>无干预 · 不可移除</small></div>
            {scenario !== null ? (
              <fieldset className="semantic-alternatives"><legend>备选方案 · 选择 1–2 项</legend>{scenario.alternatives.map((alternative) => <label key={alternative.id}><input type="checkbox" checked={alternativeIds.includes(alternative.id)} disabled={!alternativeIds.includes(alternative.id) && alternativeIds.length >= 2} onChange={(event) => toggleAlternative(alternative.id, event.target.checked)} /><span><strong>{alternative.name}</strong><small>{alternative.interventions.length} 条初始动作</small></span></label>)}</fieldset>
            ) : null}
            <div className="semantic-cohort-selection"><span>已选 Cohort</span><strong>{cohort?.title ?? (cohortState.status === "loading" ? "正在核验…" : "尚未选择")}</strong><small>{cohort === null ? "在下方目录中明确选择" : `${cohort.persona_count} 人 · ${abbreviatedDigest(cohort.cohort_sha256)}`}</small>{cohortId !== null ? <button type="button" onClick={() => { onCohortIdChange(null); resetCreation(); }}>清除选择</button> : null}</div>
            {cohortState.status === "error" ? <ApiErrorPanel title="无法核验所选 Cohort" error={cohortState.error} onRetry={reloadCohort} isRetrying={false} /> : null}
            <div className="semantic-seeds"><label htmlFor="semantic-seed-primary"><span>随机种子 1 · uint32</span><input id="semantic-seed-primary" name="seed_primary" value={firstSeed} inputMode="numeric" placeholder="必填" onChange={(event) => { setFirstSeed(event.target.value); resetCreation(); }} /></label><label htmlFor="semantic-seed-secondary"><span>随机种子 2 · uint32</span><input id="semantic-seed-secondary" name="seed_secondary" value={secondSeed} inputMode="numeric" placeholder="可选" onChange={(event) => { setSecondSeed(event.target.value); resetCreation(); }} /></label></div>
            <div className="semantic-horizon"><label htmlFor="semantic-rounds"><span>轮次</span><input id="semantic-rounds" name="rounds" type="number" min="1" max="3" value={rounds} onChange={(event) => { setRounds(event.target.value); resetCreation(); }} /></label><label htmlFor="semantic-minutes-per-round"><span>每轮分钟</span><input id="semantic-minutes-per-round" name="minutes_per_round" type="number" min="15" max="240" value={minutesPerRound} onChange={(event) => { setMinutesPerRound(event.target.value); resetCreation(); }} /></label></div>
            <div className="semantic-budget" data-valid={budget !== null && budget <= 96}><span>计算预算</span><strong>{budget === null ? "待输入" : `${budget} / 96`}</strong><small>(1 + 备选) × 种子 × 轮次 × 人数</small></div>
          </div>
          <PopulationContextPanel selectedCohortId={cohortId} onSelectedCohortIdChange={(id) => { onCohortIdChange(id); resetCreation(); }} />
          <div className="semantic-submit">
            {blockers.length > 0 ? <div role="status"><strong>当前不能提交</strong><ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul></div> : <p>输入和实时 readiness 均已通过前端核验；后端仍会执行最终校验。</p>}
            <button className="button button-primary" type="submit" disabled={blockers.length > 0 || creationState.status === "submitting"}>{creationState.status === "submitting" ? "正在入队…" : "启动语义实验"}</button>
            {creationState.status === "error" ? <div className="semantic-message" data-status="error" role="alert"><strong>{isAmbiguousPostResultError(creationState.error) ? "提交结果未知，请刷新目录核对" : "实验没有入队"}</strong><p>{creationState.error.message}</p><small>POST 不会自动重试。</small></div> : null}
            {creationState.status === "success" ? <div className="semantic-message" data-status="success" role="status"><strong>实验已入队；系统没有自动打开它</strong><p>experiment_id={creationState.experiment.id}</p></div> : null}
          </div>
        </fieldset>
      </form>
    </aside>
  );
}

function ExperimentMatrix({
  experiment,
  selectedTrialId,
  onSelectTrial,
}: {
  readonly experiment: SemanticExperimentDetail | null;
  readonly selectedTrialId: string | null;
  readonly onSelectTrial: (trial: SemanticTrial) => void;
}): JSX.Element {
  if (experiment === null) {
    return <div className="semantic-stage-empty"><strong>选择一个真实实验</strong><p>矩阵不会自动打开第一条记录，也不会生成占位 Trial。</p></div>;
  }

  return (
    <section className="semantic-matrix" aria-labelledby="semantic-matrix-title">
      <header><div><span>MATRIX / LIVE</span><h3 id="semantic-matrix-title">{experiment.scenario.title}</h3><p>{experiment.cohort.title} · {experiment.cohort.persona_count} 人 · {experiment.rounds} 轮</p></div><span className="semantic-status" data-status={experiment.status}>{statusLabels[experiment.status]}</span></header>
      <div className="semantic-table-wrap">
        <table>
          <thead><tr><th scope="col">方案</th>{experiment.seeds.map((seed) => <th scope="col" key={seed}>Seed {seed}</th>)}</tr></thead>
          <tbody>{experiment.variants.map((variant) => <tr key={variant.id}><th scope="row"><span>{variant.role === "baseline" ? "固定基线" : `备选 ${variant.position}`}</span><strong>{variant.name}</strong><small>{variant.intervention_count} 条初始动作</small></th>{variant.trials.map((trial) => <td key={trial.id}><button type="button" data-selected={trial.id === selectedTrialId} aria-pressed={trial.id === selectedTrialId} onClick={() => onSelectTrial(trial)}><span className="semantic-status" data-status={trial.status}>{statusLabels[trial.status]}</span><strong>{trial.current_round} / {experiment.rounds} 轮</strong><code>{abbreviatedDigest(trial.trial_sha256)}</code></button></td>)}</tr>)}</tbody>
        </table>
      </div>
      <p className="semantic-matrix-note">点击单元格读取该 Trial 的真实事件；系统不会自动选择任一单元格。</p>
    </section>
  );
}

function Timeline({ trial }: { readonly trial: SemanticTrial | null }): JSX.Element {
  const { state, reload } = useSemanticTrialEvents(trial?.id ?? null, trial?.status ?? null);
  if (trial === null) return <div className="semantic-panel-empty"><strong>尚未选择 Trial</strong><p>点击矩阵单元格后读取真实事件时间线。</p></div>;
  return (
    <section className="semantic-timeline" aria-labelledby="semantic-timeline-title">
      <header><h4 id="semantic-timeline-title">事件时间线</h4><button className="button button-secondary button-compact" type="button" onClick={reload}>刷新</button></header>
      {state.status === "error" ? <ApiErrorPanel title="无法读取 Trial 事件" error={state.error} onRetry={reload} isRetrying={false} /> : null}
      {state.status !== "idle" && state.items.length === 0 ? <div className="semantic-panel-empty"><strong>{state.status === "loading" ? "正在读取事件" : "尚无已记录事件"}</strong><p>运行中的 Trial 会按游标继续读取。</p></div> : null}
      {state.status !== "idle" && state.items.length > 0 ? <ol>{state.items.map((event) => {
        const objectReferences = [
          event.post_id === null ? null : `post ${event.post_id}`,
          event.comment_id === null ? null : `comment ${event.comment_id}`,
          event.target_post_id === null ? null : `target ${event.target_post_id}`,
        ].filter((reference): reference is string => reference !== null);

        return <li key={event.sequence}><span>#{event.sequence} · R{event.round}</span><div><strong>{actionLabels[event.action_type]}</strong><small>{event.actor_kind === "persona" ? `Persona ${event.agent_position}` : "场景动作"} · {event.phase}</small>{event.content !== null ? <p>{event.content}</p> : null}{objectReferences.length > 0 ? <code>{objectReferences.join(" · ")}</code> : null}<small>observed {event.observed_at_raw}</small><time dateTime={event.recorded_at}>recorded {formatMediaTimestamp(event.recorded_at)}</time></div></li>;
      })}</ol> : null}
    </section>
  );
}

function TrialLedger({ trial }: { readonly trial: SemanticTrial | null }): JSX.Element | null {
  if (trial === null) return null;
  return (
    <section className="semantic-trial-ledger" aria-labelledby={`trial-${trial.id}`}>
      <header><span className="semantic-status" data-status={trial.status}>{statusLabels[trial.status]}</span><h4 id={`trial-${trial.id}`}>Trial 真实产物</h4><code>{trial.id}</code></header>
      <dl><div><dt>Seed</dt><dd>{trial.seed}</dd></div><div><dt>当前轮次</dt><dd>{trial.current_round}</dd></div><div><dt>开始</dt><dd>{trial.started_at === null ? "—" : formatMediaTimestamp(trial.started_at)}</dd></div><div><dt>完成</dt><dd>{trial.completed_at === null ? "—" : formatMediaTimestamp(trial.completed_at)}</dd></div><div><dt>trial_sha256</dt><dd><code>{trial.trial_sha256}</code></dd></div></dl>
      {trial.result !== null ? <><dl className="semantic-counts"><div><dt>平台用户</dt><dd>{trial.result.user_count}</dd></div><div><dt>完成轮次</dt><dd>{trial.result.rounds_completed}</dd></div><div><dt>初始帖子</dt><dd>{trial.result.initial_post_count}</dd></div><div><dt>生成帖子</dt><dd>{trial.result.generated_post_count}</dd></div><div><dt>评论</dt><dd>{trial.result.comment_count}</dd></div><div><dt>反应</dt><dd>{trial.result.reaction_count}</dd></div><div><dt>未动作</dt><dd>{trial.result.do_nothing_count}</dd></div><div><dt>创作内容</dt><dd>{trial.result.authored_content_count}</dd></div><div><dt>观察动作</dt><dd>{trial.result.observed_action_count}</dd></div></dl><dl><div><dt>artifact</dt><dd>{formatArtifactSize(trial.result.artifact_size_bytes)} · <code>{trial.result.artifact_sha256}</code></dd></div><div><dt>engine</dt><dd>OASIS {trial.result.engine_version} · CAMEL {trial.result.camel_version}</dd></div></dl><div className="semantic-limitations"><strong>产物限制</strong>{trial.result.limitations.length === 0 ? <p>接口未声明附加限制。</p> : <ul>{trial.result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}</div></> : null}
      {trial.error !== null ? <div className="semantic-message" data-status="error" role="alert"><strong>{trial.error.code}</strong><p>{trial.error.message}</p></div> : null}
    </section>
  );
}

function Provenance({ experiment }: { readonly experiment: SemanticExperimentDetail | null }): JSX.Element {
  if (experiment === null) return <div className="semantic-panel-empty"><strong>尚未选择实验</strong><p>选择后核对场景、人群、模型与内容哈希。</p></div>;
  return <section className="semantic-provenance"><dl><div><dt>experiment</dt><dd><code>{experiment.experiment_sha256}</code></dd></div><div><dt>scenario</dt><dd>{experiment.scenario.title}<code>{experiment.scenario.scenario_sha256}</code></dd></div><div><dt>cohort</dt><dd>{experiment.cohort.title} · {experiment.cohort.persona_count} 人<code>{experiment.cohort.cohort_sha256}</code></dd></div><div><dt>dataset</dt><dd><code>{experiment.cohort.dataset_sha256}</code></dd></div><div><dt>model</dt><dd>{experiment.model_name}<code>{experiment.semantic_config_sha256}</code></dd></div><div><dt>engine contract</dt><dd>camel-oasis 0.2.5 · CAMEL 0.2.78</dd></div><div><dt>prompt schema</dt><dd>{experiment.prompt_schema_version}</dd></div></dl></section>;
}

function Metrics({ experiment }: { readonly experiment: SemanticExperimentDetail | null }): JSX.Element {
  const terminalId = experimentIsTerminal(experiment) ? experiment?.id ?? null : null;
  const { state, reload } = useSemanticComparison(terminalId);
  if (experiment === null) return <div className="semantic-panel-empty"><strong>尚未选择实验</strong><p>选择终态实验后读取计数比较。</p></div>;
  if (!experimentIsTerminal(experiment)) return <div className="semantic-panel-empty"><strong>实验尚未终止</strong><p>计数比较只在全部 Trial 进入终态后展示。</p></div>;
  if (state.status === "error") return <ApiErrorPanel title="无法读取实验计数比较" error={state.error} onRetry={reload} isRetrying={false} />;
  if (state.status !== "success") return <div className="semantic-panel-empty"><strong>正在读取计数比较</strong></div>;
  const labels = { observed_action_count: "观察动作", authored_content_count: "创作内容", reaction_count: "反应", do_nothing_count: "未动作" } as const;
  return <section className="semantic-metrics"><header><h4>已观察计数比较</h4><span>{state.data.state}</span></header>{state.data.metrics.map((metric) => <section key={metric.metric}><h5>{labels[metric.metric]}</h5>{metric.variants.length === 0 ? <p className="semantic-no-samples">无成功样本，无法计算该项计数比较。</p> : <ul>{metric.variants.map((variant) => <li key={variant.id}><span>{variant.name}</span><code>mean {variant.mean.toFixed(2)} · std {variant.stddev.toFixed(2)} · n {variant.n}</code></li>)}</ul>}{metric.paired_deltas.length > 0 ? <dl>{metric.paired_deltas.map((delta) => <div key={delta.alternative_id}><dt>{delta.alternative_name} − 基线</dt><dd>mean Δ {delta.mean_delta.toFixed(2)} · std Δ {delta.stddev_delta.toFixed(2)} · n {delta.n}</dd></div>)}</dl> : null}</section>)}<div className="semantic-limitations"><strong>比较限制</strong>{state.data.limitations.length === 0 ? <p>接口未声明附加限制。</p> : <ul>{state.data.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}</div></section>;
}

function Inspector({
  route,
  experiment,
  trial,
  onRouteChange,
}: {
  readonly route: RunStudioRoute;
  readonly experiment: SemanticExperimentDetail | null;
  readonly trial: SemanticTrial | null;
  readonly onRouteChange: (route: RunStudioRoute) => void;
}): JSX.Element {
  const panel = route.panel ?? "provenance";
  const selectPanel = (nextPanel: "timeline" | "metrics" | "provenance"): void => onRouteChange({ ...route, panel: nextPanel });
  return <aside className="semantic-inspector" aria-labelledby="semantic-inspector-title"><header><span>INSPECTOR / REAL OUTPUT</span><h3 id="semantic-inspector-title">实验核验</h3><nav aria-label="实验核验面板"><button type="button" aria-pressed={panel === "timeline"} onClick={() => selectPanel("timeline")}>事件</button><button type="button" aria-pressed={panel === "metrics"} onClick={() => selectPanel("metrics")}>计数</button><button type="button" aria-pressed={panel === "provenance"} onClick={() => selectPanel("provenance")}>来源</button></nav></header>{panel === "timeline" ? <Timeline trial={trial} /> : null}{panel === "metrics" ? <Metrics experiment={experiment} /> : null}{panel === "provenance" ? <Provenance experiment={experiment} /> : null}<TrialLedger trial={trial} /></aside>;
}

export function SemanticExperimentPage({ route, onRouteChange }: SemanticExperimentPageProps): JSX.Element {
  const { state: readinessState, reload: reloadReadiness } = useSemanticReadiness();
  const { state: experimentsState, reload: reloadExperiments } = useSemanticExperiments();
  const experiments = experimentsState.data?.items ?? [];
  const routeExperimentExists = route.experimentId !== null
    && experiments.some((experiment) => experiment.id === route.experimentId);
  const validatedExperimentId = experimentsState.data !== null && routeExperimentExists
    ? route.experimentId
    : null;
  const { state: detailState, reload: reloadDetail } = useSemanticExperimentDetail(validatedExperimentId);
  const experiment = detailState.status === "idle" || detailState.data?.id !== validatedExperimentId
    ? null
    : detailState.data;
  const trial = findTrial(experiment, route.trialId);
  const experimentLinkError = route.experimentId !== null
    && experimentsState.status === "success"
    && !routeExperimentExists;
  const trialLinkError = route.trialId !== null && experiment !== null && trial === null;

  useEffect(() => {
    if (detailState.status === "success"
      && (detailState.data.status === "succeeded" || detailState.data.status === "failed")) {
      reloadExperiments();
    }
  }, [detailState, reloadExperiments]);

  return (
    <div className="semantic-page run-studio-page">
      <header className="semantic-hero"><div><span>OASIS / SEMANTIC EXPERIMENT</span><h2>用固定人群运行基线与备选方案</h2><p>同一种子成对运行，只展示真实事件、可复核计数和运行限制。实验结果不等于现实因果结论。</p></div><SemanticReadinessStrip state={readinessState} onReload={reloadReadiness} /></header>
      {route.experimentId !== null && experimentsState.status === "error" ? <ApiErrorPanel title="无法验证实验深链归属" error={experimentsState.error} onRetry={reloadExperiments} isRetrying={false} /> : null}
      {experimentLinkError ? <div className="semantic-route-error" role="alert"><strong>experiment_id 不属于当前实验目录</strong><p>{route.experimentId}</p></div> : null}
      {trialLinkError ? <div className="semantic-route-error" role="alert"><strong>trial_id 不属于当前实验</strong><p>{route.trialId}</p></div> : null}
      <div className="semantic-cockpit">
        <div className="semantic-left"><SemanticComposer readinessState={readinessState} cohortId={route.cohortId} scenarioId={route.scenarioId} onCohortIdChange={(cohortId) => onRouteChange({ ...route, cohortId })} onScenarioIdChange={(scenarioId) => onRouteChange({ ...route, scenarioId })} onReloadReadiness={reloadReadiness} onCreated={() => reloadExperiments()} /><ExperimentDirectory state={experimentsState} selectedExperimentId={route.experimentId} onSelect={(item) => onRouteChange({ mode: "semantic", cohortId: item.cohort.id, scenarioId: item.scenario.id, experimentId: item.id, trialId: null, panel: "provenance" })} onReload={reloadExperiments} /></div>
        <section className="semantic-center" aria-label="语义实验矩阵" aria-busy={detailState.status === "loading"}>
          {detailState.status === "error" ? <ApiErrorPanel title="无法读取语义实验详情" error={detailState.error} onRetry={reloadDetail} isRetrying={false} /> : null}
          {detailState.status === "loading" && experiment === null ? <div className="semantic-skeleton" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
          <ExperimentMatrix experiment={experiment} selectedTrialId={route.trialId} onSelectTrial={(item) => onRouteChange({ mode: "semantic", cohortId: route.cohortId, scenarioId: route.scenarioId, experimentId: experiment?.id ?? null, trialId: item.id, panel: "timeline" })} />
          <RunInteractionGraph trial={trial} cohortId={experiment?.cohort.id ?? null} />
        </section>
        <Inspector route={route} experiment={experiment} trial={trial} onRouteChange={onRouteChange} />
      </div>
    </div>
  );
}
