import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { createLinuxEvaluation, fetchLinuxReadiness, retryLinuxEvaluation } from "./linuxArtifactContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import { PopulationContextPanel } from "./PopulationContextPanel";
import { useLinuxEvaluation, useLinuxEvaluations, useLinuxReadiness, useLinuxTasks, useLinuxTrial } from "./useLinuxArtifacts";
import { useCohortDetail } from "./usePopulations";
import "./linuxArtifact.css";

interface LinuxArtifactPageProps {
  readonly page: number;
  readonly initialEvaluationId: string | null;
  readonly initialTrialId: string | null;
  readonly onBack: () => void;
  readonly onSelectionChange: (
    page: number,
    evaluationId: string | null,
    trialId: string | null,
  ) => void;
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

export function LinuxArtifactPage({
  page,
  initialEvaluationId,
  initialTrialId,
  onBack,
  onSelectionChange,
}: LinuxArtifactPageProps): JSX.Element {
  const [cohortId, setCohortId] = useState<string | null>(null);
  const [personaId, setPersonaId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [submissionError, setSubmissionError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const activeRequest = useRef<AbortController | null>(null);
  const readiness = useLinuxReadiness();
  const tasks = useLinuxTasks();
  const directory = useLinuxEvaluations(page);
  const detail = useLinuxTrial(initialTrialId);
  const evaluation = useLinuxEvaluation(initialEvaluationId);
  const cohort = useCohortDetail(cohortId);
  const ready = readiness.state.status === "success" && readiness.state.data.linux_runtime_ready;
  const selectedCohort = cohort.state.status === "success" ? cohort.state.data : null;
  const selectedTrial = evaluation.state.data?.trial ?? detail.state.data;
  const totalPages = Math.max(1, Math.ceil((directory.state.data?.total ?? 0) / 20));

  useEffect(() => () => activeRequest.current?.abort(), []);

  const submit = async (): Promise<void> => {
    if (!ready || cohortId === null || personaId === null || !confirmed || submitting) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setSubmitting(true);
    setSubmissionError(null);
    try {
      const fresh = await fetchLinuxReadiness(controller.signal);
      if (!fresh.linux_runtime_ready) throw new Error("Linux readiness preflight is no longer ready.");
      const created = await createLinuxEvaluation(cohortId, personaId, controller.signal);
      setConfirmed(false);
      directory.reload();
      onSelectionChange(1, created.id, null);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const normalized = error instanceof Error ? error : new Error("创建 Linux Trial 失败。");
      setSubmissionError(normalized);
      if (isAmbiguousPostResultError(normalized)) onSelectionChange(1, null, null);
      directory.reload();
    } finally {
      setSubmitting(false);
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  };

  const retry = async (): Promise<void> => {
    const selectedEvaluation = evaluation.state.data;
    if (!ready || selectedEvaluation === null || selectedEvaluation.status !== "failed" || selectedEvaluation.trial.attempt_number >= 5 || submitting) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    setSubmitting(true);
    setSubmissionError(null);
    try {
      const created = await retryLinuxEvaluation(selectedEvaluation.id, controller.signal);
      directory.reload();
      onSelectionChange(1, created.id, null);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const normalized = error instanceof Error ? error : new Error("创建 Linux 重试 attempt 失败。");
      setSubmissionError(normalized);
      if (isAmbiguousPostResultError(normalized)) onSelectionChange(1, null, null);
      directory.reload();
    } finally {
      setSubmitting(false);
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  };

  return (
    <div className="linux-artifact-page">
      <header className="linux-artifact-hero">
        <div><button type="button" onClick={onBack}>← 返回评测中心</button><span>隔离运行器 / 固定产物</span><h1>Note → CSV 固定产物任务</h1><p>模型只生成受约束的解释和合成反馈；隔离运行器写入并校验 4 个固定文件。这里不提供任意命令、任意路径或桌面操作能力。</p></div>
        <dl><div><dt>执行器</dt><dd>linux_artifact_runner</dd></div><div><dt>桌面操作</dt><dd>不支持</dd></div><div><dt>运行状态</dt><dd data-ready={ready}>{ready ? "可运行" : "已阻止"}</dd></div></dl>
      </header>
      <div className="linux-artifact-layout">
        <aside className="linux-artifact-composer">
          <PopulationContextPanel selectedCohortId={cohortId} onSelectedCohortIdChange={(value) => { setCohortId(value); setPersonaId(null); setConfirmed(false); }} />
          <section><span>输入 / 合成人物</span><h3>明确选择一名合成人物</h3><label htmlFor="linux-persona">选择合成人物</label><select id="linux-persona" name="linux-persona" value={personaId ?? ""} disabled={selectedCohort === null} onChange={(event) => { setPersonaId(event.target.value || null); setConfirmed(false); }}><option value="">请选择人群成员</option>{selectedCohort?.members.map((member) => <option key={member.persona.id} value={member.persona.id}>{member.position + 1}. {member.persona.display_name}</option>)}</select><label><input type="checkbox" checked={confirmed} disabled={personaId === null} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认这是固定来源样例与合成人物输出，不代表真人操作或通用 Linux 代理。</span></label><button type="button" disabled={!ready || personaId === null || !confirmed || submitting} onClick={() => { void submit(); }}>{submitting ? "正在原子入队并封存…" : "创建 Linux 评测"}</button>{!ready ? <p>隔离运行器可用不等于模型已就绪；必须先通过模型与 worker 探测。</p> : null}{submissionError !== null ? <div role="alert"><strong>创建失败</strong><p>{submissionError.message}</p></div> : null}</section>
        </aside>
        <section className="linux-artifact-stage">
          <header><div><span>产物 / 已核验</span><h3>封存产物与合成人物自述</h3></div>{evaluation.state.data !== null ? <div><code>attempt {evaluation.state.data.trial.attempt_number} · {shortHash(evaluation.state.data.evaluation_sha256)}</code>{evaluation.state.data.status === "failed" ? <button type="button" disabled={!ready || evaluation.state.data.trial.attempt_number >= 5 || submitting} onClick={() => { void retry(); }}>{submitting ? "正在创建…" : "保留失败并重试"}</button> : null}</div> : selectedTrial !== null ? <code>attempt {selectedTrial.attempt_number} · {shortHash(selectedTrial.trial_sha256)}</code> : null}</header>
          {initialTrialId === null && initialEvaluationId === null ? <div className="linux-artifact-empty"><strong>显式选择或创建 Linux 评测</strong><p>目录不会自动打开历史记录；试验与产物由所选父资源继续深链。</p></div> : null}
          {evaluation.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux 评测" error={evaluation.state.error} isRetrying={false} onRetry={evaluation.reload} /> : null}
          {detail.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux 试验" error={detail.state.error} isRetrying={false} onRetry={detail.reload} /> : null}
          {selectedTrial !== null ? <article className="linux-artifact-result"><dl><div><dt>Persona</dt><dd>{selectedTrial.persona.display_name}</dd></div><div><dt>Status</dt><dd data-status={selectedTrial.status}>{selectedTrial.status}</dd></div><div><dt>Task</dt><dd>{selectedTrial.task.title}</dd></div><div><dt>Created</dt><dd>{formatMediaTimestamp(selectedTrial.created_at)}</dd></div></dl>{selectedTrial.error !== null ? <div role="alert"><strong>{selectedTrial.error.code}</strong><p>{selectedTrial.error.message}</p></div> : null}{selectedTrial.result !== null ? <><section><header><h4>cleaned_list.csv</h4><strong>3 rows · verifier passed</strong></header><pre>item,quantity,priority{"\n"}oat milk,2,urgent{"\n"}batteries,4,normal{"\n"}trash bags,1,low</pre></section><p>{selectedTrial.result.reason}</p><dl><div><dt>Need</dt><dd>{selectedTrial.result.need_constraint_satisfaction}</dd></div><div><dt>Preference</dt><dd>{selectedTrial.result.personal_preference_satisfaction}</dd></div><div><dt>Rating</dt><dd>{selectedTrial.result.overall_experience_rating} / 10</dd></div><div><dt>Artifact</dt><dd><code>{shortHash(selectedTrial.result.artifact_sha256)}</code></dd></div></dl><nav aria-label="Linux artifacts">{Object.keys(selectedTrial.result.file_sha256).map((name) => <a key={name} href={`/api/v2/matraix/linux-trials/${selectedTrial.id}/artifacts/${name === "cleaned_list_csv" ? "cleaned_list.csv" : name === "submission_json" ? "submission.json" : name === "user_feedback_json" ? "user_feedback.json" : "verifier.json"}`}>{name}</a>)}</nav><small>协议封存成功不等于 benchmark reward；反馈为合成 Persona 自述。</small></> : null}</article> : null}
        </section>
        <aside className="linux-artifact-directory">
          <header><div><span>档案 / 已封存</span><h3>Linux 评测目录</h3></div><button type="button" onClick={directory.reload}>刷新</button></header>
          {directory.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux 评测目录" error={directory.state.error} isRetrying={false} onRetry={directory.reload} /> : null}
          <ol>{directory.state.data?.items.map((item) => <li key={item.id}><button type="button" data-selected={item.id === initialEvaluationId} onClick={() => onSelectionChange(page, item.id, null)}><strong>{item.trial.persona.display_name}</strong><span>attempt {item.trial.attempt_number} · {item.status} · {item.trial.cohort.title}</span><time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time><code>{shortHash(item.evaluation_sha256)}</code></button></li>)}</ol>
          {directory.state.data?.items.length === 0 ? <div className="linux-artifact-empty"><strong>尚无 Linux 评测</strong></div> : null}
          <nav><button type="button" disabled={page <= 1} onClick={() => onSelectionChange(page - 1, null, null)}>上一页</button><span>{page} / {totalPages}</span><button type="button" disabled={page >= totalPages} onClick={() => onSelectionChange(page + 1, null, null)}>下一页</button></nav>
          <details><summary>任务与边界</summary><p>{tasks.state.data?.[0]?.instruction ?? "正在核验固定任务…"}</p><ul>{readiness.state.data?.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>
        </aside>
      </div>
    </div>
  );
}
