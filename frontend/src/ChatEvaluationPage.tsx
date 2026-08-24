import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import {
  chatEvaluationCreateRequestSchema,
  createChatEvaluation,
  fetchChatReadiness,
  retryChatEvaluation,
  type ChatEvaluationDetail,
  type ChatEvaluationSummary,
  type ChatTrial,
  type MatraixChatTask,
} from "./chatEvaluationContracts";
import { resolveChatTrialSelection } from "./chatEvaluationSelection";
import { formatMediaTimestamp } from "./mediaPresentation";
import { useCohorts } from "./usePopulations";
import {
  useChatEvaluation,
  useChatEvaluations,
  useChatReadiness,
  useChatTasks,
  useChatTrialTrajectory,
} from "./useChatEvaluations";
import "./chatEvaluation.css";

type SubmissionState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly error: Error; readonly ambiguous: boolean };

const statusLabels: Readonly<Record<ChatEvaluationSummary["status"], string>> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
};

const satisfactionLabels = {
  yes: "满足",
  partially: "部分满足",
  no: "未满足",
} as const;

const outcomeLabels = {
  resolved: "已解决",
  partially_resolved: "部分解决",
  unresolved: "未解决",
} as const;

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function selectedTask(
  tasks: readonly MatraixChatTask[],
  taskId: string | null,
): MatraixChatTask | null {
  return tasks.find((task) => task.task_id === taskId) ?? null;
}

function detailData(
  state: ReturnType<typeof useChatEvaluation>["state"],
): ChatEvaluationDetail | null {
  return state.status === "idle" ? null : state.data;
}

function normalizeSubmissionError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("创建 Chat Evaluation 失败：请求抛出了非标准错误。请检查后端日志。");
}

function Transcript({ trial }: { readonly trial: ChatTrial }): JSX.Element {
  if (trial.transcript.length === 0) {
    return (
      <div className="chat-eval-empty chat-eval-transcript-empty" role="status">
        <strong>对话尚未开始</strong>
        <p>worker 领取该 Persona trial 后，这里会逐轮显示实际 customer / support 消息。</p>
      </div>
    );
  }

  return (
    <ol className="chat-eval-transcript" aria-label="真实对话 transcript">
      {trial.transcript.map((message) => (
        <li key={message.position} data-role={message.role}>
          <header>
            <span>{message.role === "customer" ? trial.persona.display_name : "Acme Support sample"}</span>
            <time dateTime={message.recorded_at}>{formatMediaTimestamp(message.recorded_at)}</time>
          </header>
          <p>{message.content}</p>
        </li>
      ))}
    </ol>
  );
}

function AtifTrajectoryPanel({ trial }: { readonly trial: ChatTrial }): JSX.Element | null {
  const { state, reload } = useChatTrialTrajectory(trial);
  if (state.status === "idle") return null;
  if (state.status === "loading") {
    return (
      <section className="chat-eval-atif chat-eval-atif-loading" aria-busy="true">
        <strong>正在核验 ATIF-v1.7 trajectory…</strong>
        <span>读取该 Trial 已记录的 customer / support 步骤，不生成缺失遥测。</span>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className="chat-eval-atif">
        <ApiErrorPanel
          title="无法读取 ATIF trajectory"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={reload}
        />
      </section>
    );
  }
  const projection = state.data;
  return (
    <details className="chat-eval-atif">
      <summary>
        <span>
          <strong>ATIF-v1.7 trajectory</strong>
          <small>{projection.trajectory.steps.length} 个已记录步骤 · {projection.completeness === "complete" ? "完整" : "部分"}</small>
        </span>
        <code>{shortHash(projection.projection_sha256)}</code>
      </summary>
      <div className="chat-eval-atif-meta">
        <span>Agent</span><strong>{projection.trajectory.agent.name}</strong>
        <span>Session</span><code>{projection.trajectory.session_id}</code>
        <span>Projection</span><code>{projection.projection_schema_version}</code>
      </div>
      <ol aria-label="ATIF trajectory steps">
        {projection.trajectory.steps.map((step) => (
          <li key={step.step_id} data-source={step.source}>
            <header>
              <span>STEP {step.step_id} · {step.source === "user" ? "PERSONA / USER" : "ACME SUPPORT / AGENT"}</span>
              <time dateTime={step.timestamp}>{formatMediaTimestamp(step.timestamp)}</time>
            </header>
            <p>{step.message}</p>
            {step.source === "agent" ? <small>确定性 source-sample 响应 · LLM calls 0</small> : null}
          </li>
        ))}
      </ol>
      <p>{projection.trajectory.notes}</p>
      <ul>
        {projection.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
      </ul>
    </details>
  );
}

function TrialEvidence({ trial }: { readonly trial: ChatTrial }): JSX.Element {
  return (
    <>
      <Transcript trial={trial} />
      <AtifTrajectoryPanel trial={trial} />

      {trial.error !== null ? (
        <section className="chat-eval-trial-error" role="alert">
          <strong>{trial.error.code}</strong>
          <p>{trial.error.message}</p>
          {trial.transcript.length > 0 ? (
            <small>上方仅保留失败前已记录的真实 transcript 前缀；本页没有补写后续消息或结果。</small>
          ) : null}
        </section>
      ) : null}

      {trial.feedback !== null ? (
        <section className="chat-eval-feedback" aria-labelledby="chat-eval-feedback-title">
          <header>
            <div>
              <span>PERSONA SELF-REPORT</span>
              <h4 id="chat-eval-feedback-title">合成 Persona 反馈</h4>
            </div>
            <strong>{trial.feedback.overall_experience_rating} / 10</strong>
          </header>
          <dl>
            <div>
              <dt>需求满足</dt>
              <dd>{satisfactionLabels[trial.feedback.need_constraint_satisfaction]}</dd>
            </div>
            <div>
              <dt>偏好匹配</dt>
              <dd>{satisfactionLabels[trial.feedback.personal_preference_satisfaction]}</dd>
            </div>
            <div>
              <dt>澄清问题</dt>
              <dd>{trial.feedback.asked_useful_clarification_questions ? "有帮助" : "没有帮助"}</dd>
            </div>
          </dl>
          <blockquote>{trial.feedback.reason}</blockquote>
          <p>{trial.feedback.clarifying_notes}</p>
          <small>评分是该合成 Persona 的运行后自述，不是真人满意度、总体样本得分或生产服务质量结论。</small>
        </section>
      ) : null}

      {trial.result !== null ? (
        <section className="chat-eval-result" aria-labelledby="chat-eval-result-title">
          <header>
            <div>
              <span>VERIFIER / RECORDED</span>
              <h4 id="chat-eval-result-title">可复核运行结果</h4>
            </div>
            <strong>{outcomeLabels[trial.result.outcome_status]}</strong>
          </header>
          <dl>
            <div><dt>消息</dt><dd>{trial.result.message_count}</dd></div>
            <div><dt>Customer</dt><dd>{trial.result.customer_turn_count}</dd></div>
            <div><dt>Support</dt><dd>{trial.result.support_turn_count}</dd></div>
            <div><dt>澄清问题</dt><dd>{trial.result.clarification_question_count}</dd></div>
            <div><dt>路径</dt><dd>{trial.result.conversation_path}</dd></div>
            <div><dt>推进</dt><dd>{trial.result.resolution_progression}</dd></div>
            <div><dt>下一步</dt><dd>{trial.result.next_step_owner}</dd></div>
          </dl>
          <p>这里只呈现后端 verifier 已记录的枚举和可复算计数；接口没有 reward 或统一分数，本页也不推断。</p>
        </section>
      ) : null}
    </>
  );
}

function EvaluationStage({
  evaluation,
  selectedTrialId,
  onSelectTrial,
}: {
  readonly evaluation: ChatEvaluationDetail;
  readonly selectedTrialId: string | null;
  readonly onSelectTrial: (trialId: string) => void;
}): JSX.Element {
  const selection = resolveChatTrialSelection(evaluation.trials, selectedTrialId);
  const trial = selection.status === "selected" ? selection.trial : null;

  return (
    <>
      <section className="chat-eval-evaluation-ledger" aria-label="Evaluation 冻结上下文">
        <div><span>Task</span><strong>{evaluation.task.title}</strong></div>
        <div><span>Cohort</span><strong>{evaluation.cohort.title} · {evaluation.trial_count} Persona</strong></div>
        <div><span>状态</span><strong data-status={evaluation.status}>{statusLabels[evaluation.status]}</strong></div>
        <div><span>完成</span><strong>{evaluation.succeeded_trial_count} 成功 / {evaluation.failed_trial_count} 失败</strong></div>
      </section>

      <nav className="chat-eval-trial-switcher" aria-label="选择 Persona trial">
        {evaluation.trials.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={item.id === selectedTrialId}
            data-status={item.status}
            onClick={() => onSelectTrial(item.id)}
          >
            <span>{item.persona.position + 1}</span>
            <span><strong>{item.persona.display_name}</strong><small>{statusLabels[item.status]}</small></span>
          </button>
        ))}
      </nav>

      {trial === null ? (
        <div
          className="chat-eval-empty chat-eval-stage-empty"
          role={selection.status === "idle" ? "status" : "alert"}
        >
          <strong>{selection.status === "idle" ? "明确选择一个 Persona trial" : "这个 trial 不属于当前 Evaluation"}</strong>
          <p>{selection.status === "idle"
            ? "每个 Persona 的 transcript、self-report 与 verifier 结果彼此独立；系统不会替你默认打开第一条。"
            : "系统没有回退到第一条或相似记录。请从上方当前 Evaluation 的 Persona trial 中重新选择。"}</p>
        </div>
      ) : (
        <div className="chat-eval-trial-evidence">
          <header>
            <div>
              <span>TRANSCRIPT / PERSONA {trial.persona.position + 1}</span>
              <h4>{trial.persona.display_name}</h4>
              <p>{trial.persona.persona_id}</p>
            </div>
            <strong data-status={trial.status}>{statusLabels[trial.status]}</strong>
          </header>
          <TrialEvidence trial={trial} />
          <details className="chat-eval-provenance">
            <summary>Trial provenance 与内容哈希</summary>
            <dl>
              <div><dt>trial_sha256</dt><dd><code>{trial.trial_sha256}</code></dd></div>
              <div><dt>profile_sha256</dt><dd><code>{trial.persona.profile_sha256}</code></dd></div>
              {trial.result !== null ? (
                <>
                  <div><dt>transcript_sha256</dt><dd><code>{trial.result.transcript_sha256}</code></dd></div>
                  <div><dt>feedback_sha256</dt><dd><code>{trial.result.feedback_sha256}</code></dd></div>
                  <div><dt>result_sha256</dt><dd><code>{trial.result.result_sha256}</code></dd></div>
                </>
              ) : null}
            </dl>
          </details>
        </div>
      )}
    </>
  );
}

function EvaluationDirectory({
  items,
  status,
  selectedEvaluationId,
  page,
  total,
  pageSize,
  onSelect,
  onPageChange,
  onReload,
}: {
  readonly items: readonly ChatEvaluationSummary[];
  readonly status: "loading" | "success" | "error";
  readonly selectedEvaluationId: string | null;
  readonly page: number;
  readonly total: number;
  readonly pageSize: number;
  readonly onSelect: (evaluationId: string) => void;
  readonly onPageChange: (page: number) => void;
  readonly onReload: () => void;
}): JSX.Element {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <aside className="chat-eval-directory" aria-labelledby="chat-eval-directory-title">
      <header>
        <div><span>TRIAL ARCHIVE</span><h3 id="chat-eval-directory-title">Evaluation 目录</h3></div>
        <button type="button" disabled={status === "loading"} onClick={onReload}>
          {status === "loading" ? "刷新中…" : "刷新"}
        </button>
      </header>
      {status === "success" && items.length === 0 ? (
        <div className="chat-eval-empty">
          <strong>尚无 Chat Evaluation</strong>
          <p>完成一组明确输入后，真实运行会持久显示在这里。</p>
        </div>
      ) : null}
      <ol>
        {items.map((evaluation) => (
          <li key={evaluation.id}>
            <button
              type="button"
              data-selected={evaluation.id === selectedEvaluationId}
              onClick={() => onSelect(evaluation.id)}
            >
              <span><strong>{evaluation.cohort.title}</strong><small>attempt {evaluation.attempt_number} · {evaluation.trial_count} Persona · {formatMediaTimestamp(evaluation.created_at)}</small></span>
              <em data-status={evaluation.status}>{statusLabels[evaluation.status]}</em>
              <code>{shortHash(evaluation.evaluation_sha256)}</code>
            </button>
          </li>
        ))}
      </ol>
      <nav aria-label="Chat Evaluation 分页">
        <button type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>上一页</button>
        <span>{page} / {totalPages}</span>
        <button type="button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}>下一页</button>
      </nav>
    </aside>
  );
}

export function ChatEvaluationPage({
  page,
  initialEvaluationId,
  initialTrialId,
  onBack,
  onSelectionChange,
}: {
  readonly page: number;
  readonly initialEvaluationId: string | null;
  readonly initialTrialId: string | null;
  readonly onBack: () => void;
  readonly onSelectionChange: (
    page: number,
    evaluationId: string | null,
    trialId: string | null,
  ) => void;
}): JSX.Element {
  const { state: readiness, reload: reloadReadiness } = useChatReadiness();
  const { state: tasks, reload: reloadTasks } = useChatTasks();
  const { state: cohorts, reload: reloadCohorts } = useCohorts();
  const { state: directory, reload: reloadDirectory } = useChatEvaluations(page);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [cohortId, setCohortId] = useState<string | null>(null);
  const selectedEvaluationId = initialEvaluationId;
  const selectedTrialId = initialTrialId;
  const [confirmed, setConfirmed] = useState<boolean>(false);
  const [submission, setSubmission] = useState<SubmissionState>({ status: "idle" });
  const [retrySubmission, setRetrySubmission] = useState<SubmissionState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const { state: evaluationState, reload: reloadEvaluation } = useChatEvaluation(selectedEvaluationId);
  const task = selectedTask(tasks.items, taskId);
  const cohort = cohorts.data?.items.find((item) => item.id === cohortId) ?? null;
  const readinessData = readiness.status === "success" ? readiness.data : null;
  const taskMatchesReadiness = task !== null
    && readinessData !== null
    && readinessData.tasks.some((item) => (
      item.task_id === task.task_id && item.version === task.version
    ));
  const runtimeReady = readinessData !== null
    && readinessData.worker_online
    && readinessData.chat_runtime_ready
    && !readinessData.configuration_conflict;
  const isSubmitting = submission.status === "submitting";
  const canSubmit = runtimeReady
    && taskMatchesReadiness
    && cohort !== null
    && cohort.persona_count <= 8
    && confirmed
    && !isSubmitting;
  const evaluation = detailData(evaluationState);

  useEffect(() => () => activeController.current?.abort(), []);

  useEffect(() => {
    setConfirmed(false);
    setSubmission({ status: "idle" });
  }, [cohortId, taskId]);

  const selectEvaluation = (evaluationId: string): void => {
    if (activeController.current !== null) return;
    onSelectionChange(page, evaluationId, null);
  };

  const submit = (): void => {
    if (
      !canSubmit
      || activeController.current !== null
      || task === null
      || cohort === null
    ) return;

    const request = chatEvaluationCreateRequestSchema.parse({
      cohort_id: cohort.id,
      task_id: task.task_id,
      task_version: task.version,
    });
    const controller = new AbortController();
    activeController.current = controller;
    setSubmission({ status: "submitting" });

    void fetchChatReadiness(controller.signal)
      .then((currentReadiness) => {
        const sameTask = currentReadiness.tasks.some((item) => (
          item.task_id === request.task_id && item.version === request.task_version
        ));
        if (
          !currentReadiness.worker_online
          || !currentReadiness.chat_runtime_ready
          || currentReadiness.configuration_conflict
          || !sameTask
        ) {
          setConfirmed(false);
          reloadReadiness();
          throw new Error(
            "Chat runtime 或任务规格在提交前核验时已变化，POST 尚未发送。请等待 readiness 恢复后重新确认。",
          );
        }
        return createChatEvaluation(request, controller.signal);
      })
      .then((created) => {
        if (activeController.current !== controller || controller.signal.aborted) return;
        onSelectionChange(1, created.id, null);
        setConfirmed(false);
        setSubmission({ status: "idle" });
        reloadDirectory();
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (activeController.current !== controller) return;
        const normalized = normalizeSubmissionError(error);
        const ambiguous = isAmbiguousPostResultError(normalized);
        if (ambiguous) {
          onSelectionChange(1, null, null);
          reloadDirectory();
        }
        setConfirmed(false);
        setSubmission({ status: "error", error: normalized, ambiguous });
      })
      .finally(() => {
        if (activeController.current === controller) activeController.current = null;
      });
  };

  const retryEvaluation = (): void => {
    if (
      evaluation === null
      || evaluation.status !== "failed"
      || evaluation.attempt_number >= 5
      || !runtimeReady
      || activeController.current !== null
    ) return;
    const controller = new AbortController();
    activeController.current = controller;
    setRetrySubmission({ status: "submitting" });
    void fetchChatReadiness(controller.signal)
      .then((currentReadiness) => {
        if (!currentReadiness.chat_runtime_ready || currentReadiness.configuration_conflict) {
          throw new Error("Chat runtime 在重试前核验时已不可用，POST 尚未发送。");
        }
        return retryChatEvaluation(evaluation.id, controller.signal);
      })
      .then((created) => {
        if (activeController.current !== controller || controller.signal.aborted) return;
        onSelectionChange(1, created.id, null);
        setRetrySubmission({ status: "idle" });
        reloadDirectory();
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (activeController.current !== controller) return;
        const normalized = normalizeSubmissionError(error);
        const ambiguous = isAmbiguousPostResultError(normalized);
        if (ambiguous) {
          onSelectionChange(1, null, null);
          reloadDirectory();
        }
        setRetrySubmission({ status: "error", error: normalized, ambiguous });
      })
      .finally(() => {
        if (activeController.current === controller) activeController.current = null;
      });
  };

  const blockers = [
    runtimeReady ? null : "Chat worker 与一致模型配置尚未同时就绪",
    task === null ? "明确选择一个 Chat task" : null,
    taskMatchesReadiness ? null : "所选任务尚未通过实时 readiness 核验",
    cohort === null ? "明确选择一个冻结 Cohort" : null,
    cohort !== null && cohort.persona_count > 8 ? "首个切片只接受 1–8 Persona Cohort" : null,
    confirmed ? null : "确认固定样例与合成人物边界",
  ].filter((item): item is string => item !== null);

  return (
    <div className="chat-eval-page">
      <header className="chat-eval-header">
        <button type="button" onClick={onBack}>← 返回评测中心</button>
        <div>
          <span>对话系统评测</span>
          <h1>固定客服样例多通道评测</h1>
          <p>显式选择 REST 或 MCP 固定样例，冻结 1–8 人合成人群，让每个人物完成真实多轮对话，再查看逐条记录、自述反馈和可复核运行结果。</p>
        </div>
        <div data-ready={runtimeReady}>
          <strong>{runtimeReady ? "CHAT READY" : "RUNTIME LOCKED"}</strong>
          <small>{readinessData?.model_name ?? "等待一致模型配置"}</small>
          <span>固定样例 · 非生产系统</span>
        </div>
      </header>

      {readiness.status === "error" ? (
        <ApiErrorPanel title="无法核验 Chat runtime" error={readiness.error} isRetrying={readiness.isRetrying} onRetry={reloadReadiness} />
      ) : null}

      <div className="chat-eval-cockpit">
        <aside className="chat-eval-composer" aria-labelledby="chat-eval-composer-title">
          <header><span>INPUT / FROZEN</span><h3 id="chat-eval-composer-title">Evaluation 输入</h3></header>

          {tasks.status === "error" ? (
            <ApiErrorPanel title="无法读取 Chat task" error={tasks.error} isRetrying={tasks.isRetrying} onRetry={reloadTasks} />
          ) : null}
          {cohorts.status === "error" ? (
            <ApiErrorPanel title="无法读取冻结 Cohort" error={cohorts.error} isRetrying={cohorts.isRetrying} onRetry={reloadCohorts} />
          ) : null}

          <label htmlFor="chat-eval-task">
            <span>Chat task</span>
            <select
              id="chat-eval-task"
              name="chat_evaluation_task"
              value={taskId ?? ""}
              disabled={isSubmitting}
              onChange={(event) => setTaskId(event.target.value || null)}
            >
              <option value="">明确选择固定样例</option>
              {tasks.items.map((item) => (
                <option key={`${item.task_id}@${item.version}`} value={item.task_id}>
                  {item.title} · {item.transport === "mcp_streamable_http" ? "MCP" : "REST"} · v{item.version}
                </option>
              ))}
            </select>
          </label>

          <label htmlFor="chat-eval-cohort">
            <span>冻结人群</span>
            <select
              id="chat-eval-cohort"
              name="chat_evaluation_cohort"
              value={cohortId ?? ""}
              disabled={isSubmitting}
              onChange={(event) => setCohortId(event.target.value || null)}
            >
              <option value="">明确选择 1–8 个合成人物</option>
              {cohorts.data?.items.map((item) => (
                <option key={item.id} value={item.id} disabled={item.persona_count > 8}>
                  {item.title} · {item.persona_count} 人
                </option>
              ))}
            </select>
          </label>

          {task !== null ? (
            <section className="chat-eval-task-spec" aria-label="所选固定样例规格">
              <header><span>固定评测样例</span><strong>{task.title}</strong></header>
              <p>{task.instruction}</p>
              <dl>
                <div><dt>固定样例</dt><dd>{task.source.canonical_path}</dd></div>
                <div><dt>SUT</dt><dd>{task.source.production_sut ? "生产" : "非生产 sidecar sample"}</dd></div>
                <div><dt>Transport</dt><dd>{task.transport}</dd></div>
                <div><dt>最低轮次</dt><dd>{task.minimum_customer_turns} customer / {task.minimum_total_messages} messages</dd></div>
                <div><dt>task_spec</dt><dd><code>{shortHash(task.task_spec_sha256)}</code></dd></div>
              </dl>
            </section>
          ) : null}

          <label className="chat-eval-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={!runtimeReady || !taskMatchesReadiness || cohort === null || isSubmitting}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>我确认这是固定非生产样例与合成人物的评测，不代表生产客服、真人用户或总体服务质量。</span>
          </label>

          <button className="chat-eval-launch" type="button" disabled={!canSubmit} onClick={submit}>
            {isSubmitting ? "正在冻结 Evaluation…" : "启动 Chat Evaluation"}
          </button>

          {!canSubmit && !isSubmitting ? (
            <ul className="chat-eval-blockers" aria-label="提交前置条件">
              {blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
            </ul>
          ) : null}

          {submission.status === "error" ? (
            <div className="chat-eval-submit-error" role="alert">
              <strong>{submission.ambiguous ? "提交结果未知" : "未能创建 Evaluation"}</strong>
              <p>{submission.error.message}</p>
              {submission.ambiguous ? <small>目录已刷新；请先在右侧按时间和 Cohort 核对，不要立即重复提交。</small> : null}
            </div>
          ) : null}

          {readinessData !== null ? (
            <details className="chat-eval-limitations">
              <summary>运行边界与 limitations</summary>
              <dl>
                <div><dt>Worker</dt><dd>{readinessData.live_worker_count}</dd></div>
                <div><dt>Model</dt><dd>{readinessData.model_name ?? "—"}</dd></div>
                <div><dt>Config</dt><dd><code>{readinessData.chat_config_sha256 ?? "—"}</code></dd></div>
                <div><dt>Prompt</dt><dd>{readinessData.prompt_schema_version ?? "—"}</dd></div>
              </dl>
              <ul>{readinessData.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}
        </aside>

        <section className="chat-eval-stage" aria-labelledby="chat-eval-stage-title">
          <header>
            <div><span>TRANSCRIPT / EVIDENCE</span><h3 id="chat-eval-stage-title">逐 Persona 对话与反馈</h3></div>
            {evaluation !== null ? (
              <div className="chat-eval-stage-actions">
                <code>attempt {evaluation.attempt_number} · {shortHash(evaluation.evaluation_sha256)}</code>
                {evaluation.status === "failed" ? (
                  <button
                    type="button"
                    disabled={!runtimeReady || evaluation.attempt_number >= 5 || activeController.current !== null}
                    onClick={retryEvaluation}
                  >
                    {retrySubmission.status === "submitting" ? "正在创建下一次…" : "保留失败并重试"}
                  </button>
                ) : null}
              </div>
            ) : null}
          </header>
          {retrySubmission.status === "error" ? (
            <div className="chat-eval-submit-error" role="alert">
              <strong>{retrySubmission.ambiguous ? "重试创建结果未知" : "未能创建重试 attempt"}</strong>
              <p>{retrySubmission.error.message}</p>
            </div>
          ) : null}

          {selectedEvaluationId === null ? (
            <div className="chat-eval-empty chat-eval-stage-empty">
              <strong>选择已有 Evaluation，或冻结一组新输入</strong>
              <p>中心舞台只展示后端持久化的真实 transcript、Persona self-report 和可复算运行结果。</p>
            </div>
          ) : null}
          {evaluationState.status === "loading" && evaluation === null ? (
            <div className="chat-eval-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div>
          ) : null}
          {evaluationState.status === "error" ? (
            <ApiErrorPanel title="无法读取 Chat Evaluation" error={evaluationState.error} isRetrying={evaluationState.isRetrying} onRetry={reloadEvaluation} />
          ) : null}
          {evaluation !== null ? (
            <EvaluationStage
              evaluation={evaluation}
              selectedTrialId={selectedTrialId}
              onSelectTrial={(trialId) => onSelectionChange(page, evaluation.id, trialId)}
            />
          ) : null}
        </section>

        <div className="chat-eval-directory-slot">
          {directory.status === "error" ? (
            <ApiErrorPanel title="无法读取 Evaluation 目录" error={directory.error} isRetrying={directory.isRetrying} onRetry={reloadDirectory} />
          ) : null}
          <EvaluationDirectory
            items={directory.items}
            status={directory.status}
            selectedEvaluationId={selectedEvaluationId}
            page={page}
            total={directory.total}
            pageSize={directory.pageSize}
            onSelect={selectEvaluation}
            onPageChange={(nextPage) => onSelectionChange(nextPage, null, null)}
            onReload={reloadDirectory}
          />
        </div>
      </div>
    </div>
  );
}
