import { useEffect, useRef, useState } from "react";

import type { EvidenceBundleDetail } from "./evidenceBundleContracts";
import {
  createReportAgentRun,
  enqueueReportAgentDraft,
  fetchReportAgentDraft,
  listReportAgentEvidence,
  readReportAgentMedia,
  readReportAgentPolicy,
  retryReportAgentDraft,
  type ReportAgentCitedDraft,
  type ReportAgentRun,
} from "./reportAgentContracts";

type ActionState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly label: string }
  | { readonly status: "success"; readonly message: string }
  | { readonly status: "error"; readonly error: Error };

interface LastRead {
  readonly label: string;
  readonly content: string;
  readonly digest: string;
}

function shortDigest(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function normalizeError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("ReportAgent evidence tool failed with a non-standard error.");
}

function toolLabel(toolName: ReportAgentRun["tool_calls"][number]["tool_name"]): string {
  if (toolName === "list_evidence") return "列出证据";
  if (toolName === "read_media") return "读取媒体";
  if (toolName === "read_policy") return "读取政策";
  return "读取单次模拟记录";
}

export function ReportAgentEvidencePanel({
  bundle,
}: {
  readonly bundle: EvidenceBundleDetail;
}): JSX.Element {
  const [objective, setObjective] = useState<string>("整理当前快照能够支持的观察与限制。");
  const [observationFocus, setObservationFocus] = useState<string>(
    "读取媒体与政策中可逐字核验的事实陈述。",
  );
  const [limitationFocus, setLimitationFocus] = useState<string>(
    "明确当前证据尚不能证明的因果、预测与建议。",
  );
  const [maxToolCalls, setMaxToolCalls] = useState<number>(8);
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  const [run, setRun] = useState<ReportAgentRun | null>(null);
  const [draft, setDraft] = useState<ReportAgentCitedDraft | null>(null);
  const [lastRead, setLastRead] = useState<LastRead | null>(null);
  const [action, setAction] = useState<ActionState>({ status: "idle" });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    controller.current?.abort();
    setRun(null);
    setDraft(null);
    setSelectedTarget("");
    setLastRead(null);
    setAction({ status: "idle" });
    return () => controller.current?.abort();
  }, [bundle.id]);

  useEffect(() => {
    if (draft === null || (draft.status !== "queued" && draft.status !== "running")) return;
    const pollingController = new AbortController();
    const timer = window.setTimeout(() => {
      void fetchReportAgentDraft(draft.id, pollingController.signal)
        .then(setDraft)
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setAction({ status: "error", error: normalizeError(error) });
        });
    }, 1500);
    return () => {
      window.clearTimeout(timer);
      pollingController.abort();
    };
  }, [draft]);

  const beginAction = (label: string): AbortController => {
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setAction({ status: "loading", label });
    return nextController;
  };

  const createRun = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const nextController = beginAction("正在冻结运行边界…");
    void createReportAgentRun(
      {
        world_model_id: bundle.world_model_id,
        world_snapshot_id: bundle.world_snapshot_id,
        snapshot_sha256: bundle.snapshot_sha256,
        objective,
        outline: [
          { position: 0, title: "证据观察", focus: observationFocus },
          { position: 1, title: "证据限制", focus: limitationFocus },
        ],
        max_tool_calls: maxToolCalls,
      },
      nextController.signal,
    )
      .then((created) => {
        if (controller.current !== nextController) return;
        setRun(created);
        setAction({ status: "success", message: "运行边界已冻结，尚未执行证据工具。" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setAction({ status: "error", error: normalizeError(error) });
        }
      });
  };

  const auditDirectory = (): void => {
    if (run === null) return;
    const nextController = beginAction("正在核验冻结证据目录…");
    void listReportAgentEvidence(run.id, nextController.signal)
      .then((result) => {
        if (controller.current !== nextController) return;
        setRun(result.run);
        setAction({
          status: "success",
          message: `已核验 ${result.bundle.item_count} 篇媒体与 ${result.bundle.policy_item_count} 份政策。`,
        });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setAction({ status: "error", error: normalizeError(error) });
        }
      });
  };

  const readSelected = (): void => {
    if (run === null || selectedTarget === "") return;
    const separator = selectedTarget.indexOf(":");
    const kind = selectedTarget.slice(0, separator);
    const targetId = selectedTarget.slice(separator + 1);
    const nextController = beginAction("正在执行受限正文读取…");
    const request = kind === "media"
      ? readReportAgentMedia(run.id, targetId, nextController.signal)
      : readReportAgentPolicy(run.id, targetId, nextController.signal);
    void request
      .then((result) => {
        if (controller.current !== nextController) return;
        setRun(result.run);
        setLastRead({
          label: kind === "media" ? "媒体冻结正文" : "政策冻结正文",
          content: result.content.captured_text,
          digest: "captured_text_sha256" in result.content
            ? result.content.captured_text_sha256
            : result.content.content_sha256,
        });
        setAction({ status: "success", message: "正文读取已记录为不可变工具调用。" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setAction({ status: "error", error: normalizeError(error) });
        }
      });
  };

  const generateDraft = (): void => {
    if (run === null) return;
    const nextController = beginAction("正在冻结证据前缀并排队生成草稿…");
    void enqueueReportAgentDraft(run.id, nextController.signal)
      .then((created) => {
        if (controller.current !== nextController) return;
        setDraft(created);
        setAction({ status: "success", message: "引用草稿已进入受控生成队列。" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setAction({ status: "error", error: normalizeError(error) });
        }
      });
  };

  const retryDraft = (): void => {
    if (draft === null || draft.status !== "failed" || draft.attempt_number >= 5) return;
    const nextController = beginAction("正在保留失败记录并创建下一次尝试…");
    void retryReportAgentDraft(draft.id, nextController.signal)
      .then((created) => {
        if (controller.current !== nextController) return;
        setDraft(created);
        setAction({ status: "success", message: "新的引用草稿尝试已进入受控生成队列。" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setAction({ status: "error", error: normalizeError(error) });
        }
      });
  };

  const isLoading = action.status === "loading";
  const canCall = run !== null && run.remaining_tool_calls > 0 && !isLoading;
  const evidenceReadCount = run?.tool_calls.filter(
    (call) => call.tool_name === "read_media" || call.tool_name === "read_policy",
  ).length ?? 0;

  return (
    <section className="report-agent-evidence" aria-labelledby="report-agent-evidence-title">
      <header>
        <div>
          <span>REPORTAGENT / BOUNDED EVIDENCE</span>
          <h4 id="report-agent-evidence-title">封存一次只读证据运行</h4>
          <p>运行只能访问当前快照；工具调用有显式预算并逐次追加哈希。此处不自动生成结论。</p>
        </div>
        {run === null ? null : (
          <strong>{run.remaining_tool_calls} / {run.max_tool_calls} 次剩余</strong>
        )}
      </header>

      {run === null ? (
        <form onSubmit={createRun}>
          <label htmlFor="report-agent-objective">分析目标</label>
          <textarea
            id="report-agent-objective"
            minLength={2}
            maxLength={1000}
            required
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
          />
          <div className="report-agent-outline-grid">
            <label htmlFor="report-agent-observation-focus">
              章节 1 · 证据观察
              <textarea
                id="report-agent-observation-focus"
                minLength={2}
                maxLength={500}
                required
                value={observationFocus}
                onChange={(event) => setObservationFocus(event.target.value)}
              />
            </label>
            <label htmlFor="report-agent-limitation-focus">
              章节 2 · 证据限制
              <textarea
                id="report-agent-limitation-focus"
                minLength={2}
                maxLength={500}
                required
                value={limitationFocus}
                onChange={(event) => setLimitationFocus(event.target.value)}
              />
            </label>
          </div>
          <label htmlFor="report-agent-tool-budget">只读工具预算</label>
          <input
            id="report-agent-tool-budget"
            type="number"
            min={1}
            max={20}
            required
            value={maxToolCalls}
            onChange={(event) => setMaxToolCalls(Number(event.target.value))}
          />
          <button type="submit" disabled={isLoading}>
            {isLoading ? "正在冻结…" : "冻结受控运行"}
          </button>
        </form>
      ) : (
        <div className="report-agent-runtime">
          <dl>
            <div><dt>Run</dt><dd><code title={run.run_sha256}>{shortDigest(run.run_sha256)}</code></dd></div>
            <div><dt>Snapshot</dt><dd><code title={run.snapshot_sha256}>{shortDigest(run.snapshot_sha256)}</code></dd></div>
          </dl>
          <div className="report-agent-tool-controls">
            <button type="button" disabled={!canCall} onClick={auditDirectory}>
              执行 list_evidence
            </button>
            <select
              aria-label="选择受控正文工具目标"
              value={selectedTarget}
              disabled={!canCall}
              onChange={(event) => setSelectedTarget(event.target.value)}
            >
              <option value="">明确选择正文目标</option>
              {bundle.items.map((item) => (
                <option key={item.article_id} value={`media:${item.article_id}`}>
                  媒体 · {item.title}
                </option>
              ))}
              {bundle.policy_items.map((item) => (
                <option key={item.policy_version_id} value={`policy:${item.policy_version_id}`}>
                  政策 · {item.title}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={!canCall || selectedTarget === ""}
              onClick={readSelected}
            >
              执行正文读取
            </button>
          </div>
          <ol className="report-agent-audit" aria-label="ReportAgent 工具审计记录">
            {run.tool_calls.map((call) => (
              <li key={call.id}>
                <span>{call.position + 1}</span>
                <strong>{toolLabel(call.tool_name)}</strong>
                <code title={call.call_sha256}>{shortDigest(call.call_sha256)}</code>
              </li>
            ))}
          </ol>
          {lastRead === null ? null : (
            <details className="report-agent-last-read" open>
              <summary>{lastRead.label}</summary>
              <pre>{lastRead.content}</pre>
              <code title={lastRead.digest}>{lastRead.digest}</code>
            </details>
          )}
          <div className="report-agent-draft-controls">
            <button
              type="button"
              disabled={evidenceReadCount === 0 || isLoading || draft?.status === "running"
                || draft?.status === "queued"}
              onClick={generateDraft}
            >
              生成逐条引用草稿
            </button>
            <p>只使用当前已审计的 {evidenceReadCount} 次正文读取；章节标题保持冻结大纲不变。</p>
          </div>
          {draft === null ? null : (
            <article className="report-agent-draft" aria-live="polite">
              <header>
                <strong>草稿状态 · attempt {draft.attempt_number} · {draft.status}</strong>
                <code title={draft.input_sha256}>{shortDigest(draft.input_sha256)}</code>
              </header>
              {draft.status === "failed" ? (
                <div>
                  <p role="alert">{draft.error_message}</p>
                  <button type="button" disabled={isLoading || draft.attempt_number >= 5} onClick={retryDraft}>保留失败并重试</button>
                </div>
              ) : null}
              {draft.status === "succeeded" ? (
                <>
                  <h5>{draft.title}</h5>
                  {draft.sections.map((section) => (
                    <section key={section.position}>
                      <h6>{section.title}</h6>
                      <p>{section.body_markdown}</p>
                      <ol>
                        {section.citations.map((citation) => (
                          <li key={`${section.position}-${citation.position}`}>
                            <q>{citation.quote}</q>
                            <small>{citation.source_label}</small>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                  <code title={draft.draft_sha256 ?? undefined}>{draft.draft_sha256}</code>
                </>
              ) : <p>工作进程正在生成并核验逐字引用。</p>}
            </article>
          )}
        </div>
      )}

      {action.status === "loading" ? <p role="status">{action.label}</p> : null}
      {action.status === "success" ? <p role="status">{action.message}</p> : null}
      {action.status === "error" ? <p role="alert">{action.error.message}</p> : null}
    </section>
  );
}
