import { useState } from "react";

import {
  createResearchEvaluationTarget,
  createResearchEvaluationJob,
  retryResearchEvaluationJob,
  type ResearchEvaluationJob,
  type ResearchEvaluationTarget,
  type ResearchEvaluationTargetKind,
} from "./researchEvaluationContracts";

const kindLabel = { chat: "Chat", web: "Web", app: "App" } as const;

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function TargetDefinitionForm({
  kind,
  projectId,
  runId,
  onCreated,
}: {
  readonly kind: ResearchEvaluationTargetKind;
  readonly projectId: string;
  readonly runId: string;
  readonly onCreated: () => Promise<void>;
}): JSX.Element {
  const [title, setTitle] = useState("");
  const [targetUrl, setTargetUrl] = useState("");
  const [taskPackage, setTaskPackage] = useState("");
  const [transport, setTransport] = useState<"rest_chat" | "mcp_streamable_http">(
    "rest_chat",
  );
  const [goal, setGoal] = useState("");
  const [criteria, setCriteria] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const parsedCriteria = criteria.split("\n").map((item) => item.trim()).filter(Boolean);
  const canSubmit = title.trim() !== ""
    && (kind === "app" ? taskPackage.trim() !== "" : targetUrl.trim() !== "")
    && goal.trim() !== ""
    && parsedCriteria.length >= 1
    && parsedCriteria.length <= 8
    && !submitting;

  const submit = async (): Promise<void> => {
    if (!canSubmit) return;
    const controller = new AbortController();
    setSubmitting(true);
    setError(null);
    try {
      await createResearchEvaluationTarget({
        research_project_id: projectId,
        research_simulation_run_id: runId,
        kind,
        title,
        target_url: kind === "app" ? null : targetUrl,
        task_package: kind === "app" ? taskPackage : null,
        transport: kind === "app" ? "harbor_task" : kind === "web" ? "playwright_browser" : transport,
        task_goal: goal,
        success_criteria: parsedCriteria,
      }, controller.signal);
      await onCreated();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("封存研究被测对象失败"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <details className="research-evaluation-target-form">
      <summary>定义 {kindLabel[kind]} 被测对象</summary>
      <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <p>这里只封存定义，不会访问地址、发送 Persona 数据或启动评测。</p>
        <label>名称<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder={kind === "chat" ? "例如：研究报告问答服务" : "例如：研究专题页面"} /></label>
        {kind === "app" ? <label>Harbor Task Package<input required maxLength={300} value={taskPackage} onChange={(event) => setTaskPackage(event.target.value)} placeholder="application/tasks/example-computer-use-linux_note-to-csv" /></label> : <label>目标地址<input required type="url" maxLength={500} value={targetUrl} onChange={(event) => setTargetUrl(event.target.value)} placeholder={kind === "chat" ? "https://example.com/chat" : "https://example.com/research"} /></label>}
        {kind === "chat" ? <label>传输方式<select value={transport} onChange={(event) => setTransport(event.target.value as "rest_chat" | "mcp_streamable_http")}><option value="rest_chat">REST 文本对话</option><option value="mcp_streamable_http">MCP Streamable HTTP</option></select></label> : <p className="research-evaluation-target-fixed">浏览方式：隔离 Playwright（尚未授权执行）</p>}
        <label>任务目标<textarea required maxLength={2000} rows={3} value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="说明合成 Persona 要完成什么任务。" /></label>
        <label>成功标准<textarea required maxLength={2400} rows={3} value={criteria} onChange={(event) => setCriteria(event.target.value)} placeholder="每行一条，最多 8 条。" /><small>{parsedCriteria.length} / 8 条</small></label>
        {error !== null ? <p className="research-evaluation-target-error" role="alert">{error.message}</p> : null}
        <button type="submit" disabled={!canSubmit}>{submitting ? "正在封存…" : `封存 ${kindLabel[kind]} 被测对象`}</button>
      </form>
    </details>
  );
}

export function ResearchEvaluationTargetsPanel({
  projectId,
  runId,
  targets,
  jobs,
  onChanged,
}: {
  readonly projectId: string;
  readonly runId: string;
  readonly targets: readonly ResearchEvaluationTarget[];
  readonly jobs: readonly ResearchEvaluationJob[];
  readonly onChanged: () => Promise<void>;
}): JSX.Element {
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState<Error | null>(null);
  const launch = async (targetId: string): Promise<void> => {
    if (submittingId !== null) return;
    const controller = new AbortController();
    setSubmittingId(targetId);
    setLaunchError(null);
    try {
      await createResearchEvaluationJob(projectId, runId, targetId, controller.signal);
      await onChanged();
    } catch (reason: unknown) {
      setLaunchError(reason instanceof Error ? reason : new Error("提交 Harbor Job 失败"));
    } finally {
      setSubmittingId(null);
    }
  };
  const retry = async (job: ResearchEvaluationJob): Promise<void> => {
    if (submittingId !== null || job.status !== "failed" || job.attempt_number >= 5) return;
    const controller = new AbortController();
    setSubmittingId(job.id);
    setLaunchError(null);
    try {
      await retryResearchEvaluationJob(job.id, controller.signal);
      await onChanged();
    } catch (reason: unknown) {
      setLaunchError(reason instanceof Error ? reason : new Error("重试 Harbor Job 失败"));
    } finally {
      setSubmittingId(null);
    }
  };
  return (
    <section className="research-evaluation-targets" aria-label="当前研究被测对象">
      <header><h3>Chat / Web / App 被测对象</h3><p>先定义 SUT 或 Harbor Task、任务目标和成功标准，再进入隔离执行。</p></header>
      <div>
        {(["chat", "web", "app"] as const).map((kind) => {
          const target = targets.find((item) => item.payload.kind === kind) ?? null;
          const targetJobs = [...jobs.filter((job) => job.target_id === target?.id)]
            .sort((left, right) => right.attempt_number - left.attempt_number);
          const latestJob = targetJobs.at(0) ?? null;
          return <article key={kind}>
            <h4>{kindLabel[kind]}</h4>
            {target === null ? <TargetDefinitionForm kind={kind} projectId={projectId} runId={runId} onCreated={onChanged} /> : <div className="research-evaluation-target-sealed">
              <strong>{target.payload.title}</strong>
              {target.payload.target_url !== null ? <a href={target.payload.target_url} target="_blank" rel="noreferrer">查看定义地址</a> : <code>{target.payload.task_package}</code>}
              <p>{target.payload.task_goal}</p>
              {latestJob === null ? <button type="button" disabled={submittingId !== null} onClick={() => { void launch(target.id); }}>{submittingId === target.id ? "正在提交…" : "提交 Harbor Job"}</button> : <>
                <span>Harbor Job：{latestJob.status} · attempt {latestJob.attempt_number}/5</span>
                {latestJob.status === "failed" ? <div className="research-evaluation-job-error" role="alert"><strong>{latestJob.error_code ?? "执行失败"}</strong><p>{latestJob.error_message ?? "Harbor Job 未返回错误详情。"}</p><button type="button" disabled={submittingId !== null || latestJob.attempt_number >= 5} onClick={() => { void retry(latestJob); }}>{submittingId === latestJob.id ? "正在创建重试…" : latestJob.attempt_number >= 5 ? "已达到重试上限" : "保留失败并重试"}</button></div> : null}
                {latestJob.status === "succeeded" ? <dl className="research-evaluation-job-result"><div><dt>Reward</dt><dd>{latestJob.reward_value ?? "—"}</dd></div><div><dt>Trajectory</dt><dd><code>{latestJob.trajectory_sha256 === null ? "—" : shortHash(latestJob.trajectory_sha256)}</code></dd></div><div><dt>Artifact</dt><dd><code>{latestJob.artifact_sha256 === null ? "—" : shortHash(latestJob.artifact_sha256)}</code></dd></div><div><dt>Verifier</dt><dd><code>{latestJob.verifier_sha256 === null ? "—" : shortHash(latestJob.verifier_sha256)}</code></dd></div></dl> : null}
                <details><summary>查看 {targetJobs.length} 次尝试谱系</summary><ol>{targetJobs.map((job) => <li key={job.id}><span>attempt {job.attempt_number} · {job.status}</span><code>{shortHash(job.job_sha256)}</code>{job.retry_of_job_sha256 === null ? <small>根任务</small> : <small>重试自 {shortHash(job.retry_of_job_sha256)}</small>}</li>)}</ol></details>
              </>}
            </div>}
          </article>;
        })}
      </div>
      {launchError !== null ? <p className="research-evaluation-target-error" role="alert">{launchError.message}</p> : null}
    </section>
  );
}
