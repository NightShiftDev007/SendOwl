import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { createLinuxEvaluation, fetchLinuxReadiness } from "./linuxArtifactContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import { PopulationContextPanel } from "./PopulationContextPanel";
import { useLinuxEvaluation, useLinuxReadiness, useLinuxTasks, useLinuxTrial, useLinuxTrials } from "./useLinuxArtifacts";
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
  const directory = useLinuxTrials(page);
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
      onSelectionChange(1, created.id, created.trial.id);
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

  return (
    <div className="linux-artifact-page">
      <header className="linux-artifact-hero">
        <div><button type="button" onClick={onBack}>← Task Gallery</button><span>MATRAIX / LINUX SOURCE SAMPLE</span><h2>Note → CSV 固定产物任务</h2><p>千问只生成受约束的解释和合成反馈；隔离 Runner 写入并校验 4 个固定文件。这里没有 shell、任意路径、桌面 Computer Use 或 Harbor。</p></div>
        <dl><div><dt>Execution</dt><dd>linux_artifact_runner</dd></div><div><dt>Computer Use</dt><dd>false</dd></div><div><dt>Runtime</dt><dd data-ready={ready}>{ready ? "ready" : "blocked"}</dd></div></dl>
      </header>
      <div className="linux-artifact-layout">
        <aside className="linux-artifact-composer">
          <PopulationContextPanel selectedCohortId={cohortId} onSelectedCohortIdChange={(value) => { setCohortId(value); setPersonaId(null); setConfirmed(false); }} />
          <section><span>INPUT / PERSONA</span><h3>明确选择一名 Persona</h3><select id="linux-persona" name="linux-persona" value={personaId ?? ""} disabled={selectedCohort === null} onChange={(event) => { setPersonaId(event.target.value || null); setConfirmed(false); }}><option value="">请选择 Cohort 成员</option>{selectedCohort?.members.map((member) => <option key={member.persona.id} value={member.persona.id}>{member.position + 1}. {member.persona.display_name}</option>)}</select><label><input type="checkbox" checked={confirmed} disabled={personaId === null} onChange={(event) => setConfirmed(event.target.checked)} /><span>我确认这是固定来源样例与合成 Persona 输出，不代表真人操作或通用 Linux Agent。</span></label><button type="button" disabled={!ready || personaId === null || !confirmed || submitting} onClick={() => { void submit(); }}>{submitting ? "正在原子入队并封存…" : "创建 Linux Evaluation"}</button>{!ready ? <p>Runner 可用不等于模型已就绪；必须先通过千问与 Worker 探测。</p> : null}{submissionError !== null ? <div role="alert"><strong>创建失败</strong><p>{submissionError.message}</p></div> : null}</section>
        </aside>
        <main className="linux-artifact-stage">
          <header><div><span>ARTIFACT / VERIFIED</span><h3>封存产物与 Persona 自述</h3></div>{evaluation.state.data !== null ? <code>{shortHash(evaluation.state.data.evaluation_sha256)}</code> : selectedTrial !== null ? <code>{shortHash(selectedTrial.trial_sha256)}</code> : null}</header>
          {initialTrialId === null && initialEvaluationId === null ? <div className="linux-artifact-empty"><strong>显式选择或创建 Trial</strong><p>目录不会自动打开历史记录。</p></div> : null}
          {evaluation.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux Evaluation" error={evaluation.state.error} isRetrying={false} onRetry={evaluation.reload} /> : null}
          {detail.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux Trial" error={detail.state.error} isRetrying={false} onRetry={detail.reload} /> : null}
          {selectedTrial !== null ? <article className="linux-artifact-result"><dl><div><dt>Persona</dt><dd>{selectedTrial.persona.display_name}</dd></div><div><dt>Status</dt><dd data-status={selectedTrial.status}>{selectedTrial.status}</dd></div><div><dt>Task</dt><dd>{selectedTrial.task.title}</dd></div><div><dt>Created</dt><dd>{formatMediaTimestamp(selectedTrial.created_at)}</dd></div></dl>{selectedTrial.error !== null ? <div role="alert"><strong>{selectedTrial.error.code}</strong><p>{selectedTrial.error.message}</p></div> : null}{selectedTrial.result !== null ? <><section><header><h4>cleaned_list.csv</h4><strong>3 rows · verifier passed</strong></header><pre>item,quantity,priority{"\n"}oat milk,2,urgent{"\n"}batteries,4,normal{"\n"}trash bags,1,low</pre></section><p>{selectedTrial.result.reason}</p><dl><div><dt>Need</dt><dd>{selectedTrial.result.need_constraint_satisfaction}</dd></div><div><dt>Preference</dt><dd>{selectedTrial.result.personal_preference_satisfaction}</dd></div><div><dt>Rating</dt><dd>{selectedTrial.result.overall_experience_rating} / 10</dd></div><div><dt>Artifact</dt><dd><code>{shortHash(selectedTrial.result.artifact_sha256)}</code></dd></div></dl><nav aria-label="Linux artifacts">{Object.keys(selectedTrial.result.file_sha256).map((name) => <a key={name} href={`/api/v2/matraix/linux-trials/${selectedTrial.id}/artifacts/${name === "cleaned_list_csv" ? "cleaned_list.csv" : name === "submission_json" ? "submission.json" : name === "user_feedback_json" ? "user_feedback.json" : "verifier.json"}`}>{name}</a>)}</nav><small>协议封存成功不等于 benchmark reward；反馈为合成 Persona 自述。</small></> : null}</article> : null}
        </main>
        <aside className="linux-artifact-directory"><header><div><span>ARCHIVE / SEALED</span><h3>Linux Trial 目录</h3></div><button type="button" onClick={directory.reload}>刷新</button></header>{directory.state.status === "error" ? <ApiErrorPanel title="无法读取 Linux Trial 目录" error={directory.state.error} isRetrying={false} onRetry={directory.reload} /> : null}<ol>{directory.state.data?.items.map((item) => <li key={item.id}><button type="button" data-selected={item.id === initialTrialId} onClick={() => onSelectionChange(page, null, item.id)}><strong>{item.persona.display_name}</strong><span>{item.status} · {item.cohort.title}</span><time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time><code>{shortHash(item.trial_sha256)}</code></button></li>)}</ol>{directory.state.data?.items.length === 0 ? <div className="linux-artifact-empty"><strong>尚无 Linux Trial</strong></div> : null}<nav><button type="button" disabled={page <= 1} onClick={() => onSelectionChange(page - 1, null, null)}>上一页</button><span>{page} / {totalPages}</span><button type="button" disabled={page >= totalPages} onClick={() => onSelectionChange(page + 1, null, null)}>下一页</button></nav><details><summary>任务与边界</summary><p>{tasks.state.data?.[0]?.instruction ?? "正在核验固定任务…"}</p><ul>{readiness.state.data?.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details></aside>
      </div>
    </div>
  );
}
