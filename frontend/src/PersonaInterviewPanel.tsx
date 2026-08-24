import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import type { DecisionReport } from "./decisionReportContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import {
  createPersonaInterview,
  createPersonaInterviewSession,
  type PersonaInterview,
  type PersonaInterviewSession,
} from "./personaInterviewContracts";
import { fetchSemanticReadiness } from "./semanticExperimentContracts";
import { useCohortDetail } from "./usePopulations";
import { usePersonaInterviews, usePersonaInterviewSessions } from "./usePersonaInterviews";
import "./personaInterview.css";

function InterviewResult({ item, report }: { readonly item: PersonaInterview; readonly report: DecisionReport }): JSX.Element {
  return (
    <article className="persona-interview-result" data-status={item.status}>
      <header>
        <div><strong>{item.persona.display_name}</strong><span>合成 Persona 视角</span></div>
        <time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time>
      </header>
      <h4>{item.question}</h4>
      {item.status === "queued" || item.status === "running" ? <p role="status">千问正在 Persona 档案与封存报告范围内生成回答…</p> : null}
      {item.status === "failed" ? <div className="persona-interview-error" role="alert"><strong>{item.error_code}</strong><p>{item.error_message}</p></div> : null}
      {item.status === "succeeded" && item.answer_markdown !== null ? (
        <>
          <p className="persona-interview-answer">{item.answer_markdown}</p>
          <ul className="persona-interview-sections" aria-label="回答引用的报告章节">
            {item.cited_section_positions.map((position) => (
              <li key={position}><span>SECTION {position + 1}</span><strong>{report.sections[position]?.title}</strong></li>
            ))}
          </ul>
          <details><summary>访谈完整性</summary><dl><div><dt>Persona profile</dt><dd><code>{item.persona.profile_sha256}</code></dd></div><div><dt>Interview</dt><dd><code>{item.interview_sha256}</code></dd></div><div><dt>Answer</dt><dd><code>{item.answer_sha256}</code></dd></div></dl></details>
        </>
      ) : null}
    </article>
  );
}

function InterviewSessionResult({ item, report }: { readonly item: PersonaInterviewSession; readonly report: DecisionReport }): JSX.Element {
  const completed = item.interviews.filter((interview) => interview.status === "succeeded" || interview.status === "failed").length;
  return (
    <article className="persona-interview-session" data-status={item.status}>
      <header>
        <div><strong>{item.persona_count} 人证据访谈</strong><span>{completed}/{item.persona_count} 已完成</span></div>
        <time dateTime={item.created_at}>{formatMediaTimestamp(item.created_at)}</time>
      </header>
      <h4>{item.question}</h4>
      <div className="persona-interview-progress" aria-label={`访谈进度 ${completed}/${item.persona_count}`}><span style={{ transform: `scaleX(${completed / item.persona_count})` }} /></div>
      <div className="persona-interview-session-grid">
        {item.interviews.map((interview) => <InterviewResult key={interview.id} item={interview} report={report} />)}
      </div>
      <details><summary>会话完整性</summary><code>{item.session_sha256}</code></details>
    </article>
  );
}

export function PersonaInterviewPanel({
  report,
  runtimeReady,
}: {
  readonly report: DecisionReport;
  readonly runtimeReady: boolean;
}): JSX.Element {
  const [personaId, setPersonaId] = useState<string>("");
  const [question, setQuestion] = useState<string>("");
  const [submissionError, setSubmissionError] = useState<Error | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [sessionPersonaIds, setSessionPersonaIds] = useState<readonly string[]>([]);
  const [sessionQuestion, setSessionQuestion] = useState<string>("");
  const [sessionSubmissionError, setSessionSubmissionError] = useState<Error | null>(null);
  const [isSessionSubmitting, setIsSessionSubmitting] = useState<boolean>(false);
  const activeController = useRef<AbortController | null>(null);
  const activeSessionController = useRef<AbortController | null>(null);
  const { state: cohortState, reload: reloadCohort } = useCohortDetail(report.cohort_id);
  const { state: interviewsState, reload } = usePersonaInterviews(report.id);
  const { state: sessionsState, reload: reloadSessions } = usePersonaInterviewSessions(report.id);
  const normalizedQuestion = question.trim();
  const cohort = cohortState.status === "success" ? cohortState.data : null;
  const normalizedSessionQuestion = sessionQuestion.trim();

  useEffect(() => {
    setPersonaId("");
    setQuestion("");
    setSubmissionError(null);
    setSessionPersonaIds([]);
    setSessionQuestion("");
    setSessionSubmissionError(null);
  }, [report.id]);
  useEffect(() => () => {
    activeController.current?.abort();
    activeSessionController.current?.abort();
  }, []);

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (personaId === "" || normalizedQuestion.length < 2 || normalizedQuestion.length > 1000 || activeController.current !== null) return;
    const controller = new AbortController();
    activeController.current = controller;
    setIsSubmitting(true);
    setSubmissionError(null);
    void fetchSemanticReadiness(controller.signal)
      .then((readiness) => {
        if (!readiness.semantic_runtime_ready) {
          throw new Error("语义 Worker 尚未通过模型启动探测；Persona 访谈 POST 尚未发送。");
        }
        return createPersonaInterview(
          report.id,
          personaId,
          normalizedQuestion,
          controller.signal,
        );
      })
      .then(() => { setQuestion(""); reload(); })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          const normalized = error instanceof Error ? error : new Error("Persona 访谈返回了非标准错误。");
          setSubmissionError(new Error(isAmbiguousPostResultError(normalized) ? `访谈提交结果未知，请刷新记录核对。${normalized.message}` : normalized.message));
        }
      })
      .finally(() => {
        if (activeController.current === controller) {
          activeController.current = null;
          setIsSubmitting(false);
        }
      });
  };

  const toggleSessionPersona = (selectedId: string): void => {
    setSessionPersonaIds((current) => current.includes(selectedId)
      ? current.filter((item) => item !== selectedId)
      : current.length < 8 ? [...current, selectedId] : current);
  };

  const submitSession = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (sessionPersonaIds.length < 2 || normalizedSessionQuestion.length < 2
      || normalizedSessionQuestion.length > 1000 || activeSessionController.current !== null) return;
    const controller = new AbortController();
    activeSessionController.current = controller;
    setIsSessionSubmitting(true);
    setSessionSubmissionError(null);
    void fetchSemanticReadiness(controller.signal)
      .then((readiness) => {
        if (!readiness.semantic_runtime_ready) {
          throw new Error("语义 Worker 尚未通过模型启动探测；多人访谈 POST 尚未发送。");
        }
        return createPersonaInterviewSession(
          report.id,
          sessionPersonaIds,
          normalizedSessionQuestion,
          controller.signal,
        );
      })
      .then(() => {
        setSessionQuestion("");
        setSessionPersonaIds([]);
        reloadSessions();
        reload();
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          const normalized = error instanceof Error ? error : new Error("多人访谈返回了非标准错误。");
          setSessionSubmissionError(new Error(isAmbiguousPostResultError(normalized) ? `多人访谈提交结果未知，请刷新会话核对。${normalized.message}` : normalized.message));
        }
      })
      .finally(() => {
        if (activeSessionController.current === controller) {
          activeSessionController.current = null;
          setIsSessionSubmitting(false);
        }
      });
  };

  const sessionInterviewIds = new Set((sessionsState.data?.items ?? []).flatMap((item) => item.interviews.map((interview) => interview.id)));
  const standaloneInterviews = (interviewsState.data?.items ?? []).filter((item) => !sessionInterviewIds.has(item.id));

  return (
    <section className="persona-interview-panel" aria-labelledby="persona-interview-title">
      <header><span>MIROFISH / PERSONA INTERVIEW</span><h3 id="persona-interview-title">从一个 Persona 视角追问</h3><p>这是模型基于冻结 Persona 档案生成的合成视角，不代表真实个人；回答只能引用当前封存报告章节。</p><strong data-ready={runtimeReady}>{runtimeReady ? "Qwen Worker 可提交" : "Qwen Worker 配置阻塞"}</strong></header>
      {cohortState.status === "error" ? <ApiErrorPanel title="无法读取报告 Cohort" error={cohortState.error} isRetrying={cohortState.isRetrying} onRetry={reloadCohort} /> : null}
      <form onSubmit={submit}>
        <label htmlFor="persona-interview-persona">Persona</label>
        <select id="persona-interview-persona" name="persona_id" value={personaId} disabled={isSubmitting || cohort === null || !runtimeReady} onChange={(event) => setPersonaId(event.target.value)}>
          <option value="">选择一个 Persona</option>
          {(cohort?.members ?? []).map((member) => <option key={member.persona.id} value={member.persona.id}>{member.persona.display_name}</option>)}
        </select>
        <label htmlFor="persona-interview-question">访谈问题</label>
        <textarea id="persona-interview-question" name="persona_interview_question" rows={4} minLength={2} maxLength={1000} value={question} disabled={isSubmitting || !runtimeReady} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：从你的背景看，这个方案最需要进一步核验什么？" />
        <div><small>{normalizedQuestion.length}/1000</small><button type="submit" className="button button-primary" disabled={personaId === "" || normalizedQuestion.length < 2 || isSubmitting || !runtimeReady}>{isSubmitting ? "正在入队…" : "开始证据访谈"}</button></div>
      </form>
      {submissionError !== null ? <div className="persona-interview-error" role="alert">{submissionError.message}</div> : null}
      <section className="persona-interview-session-builder" aria-labelledby="persona-interview-session-title">
        <header><h4 id="persona-interview-session-title">多人访谈会话</h4><p>向 2–8 个冻结 Persona 提出同一个问题。服务端会一次性封存整组访谈，不会出现只创建一部分的情况。</p></header>
        <form onSubmit={submitSession}>
          <fieldset disabled={isSessionSubmitting || cohort === null || !runtimeReady}>
            <legend>选择 Persona <span>{sessionPersonaIds.length}/8</span></legend>
            <div className="persona-interview-persona-grid">
              {(cohort?.members ?? []).map((member) => {
                const checked = sessionPersonaIds.includes(member.persona.id);
                return <label key={member.persona.id}><input type="checkbox" name="session_persona_ids" value={member.persona.id} checked={checked} disabled={!checked && sessionPersonaIds.length >= 8} onChange={() => toggleSessionPersona(member.persona.id)} /><span><strong>{member.persona.display_name}</strong><small>{member.persona.persona_id}</small></span></label>;
              })}
            </div>
          </fieldset>
          <label htmlFor="persona-interview-session-question">共同问题</label>
          <textarea id="persona-interview-session-question" name="persona_interview_session_question" rows={4} minLength={2} maxLength={1000} value={sessionQuestion} disabled={isSessionSubmitting || !runtimeReady} onChange={(event) => setSessionQuestion(event.target.value)} placeholder="例如：从各自背景看，报告中哪项限制最值得优先验证？" />
          <div><small>{normalizedSessionQuestion.length}/1000 · 至少选择 2 人</small><button type="submit" className="button button-primary" disabled={sessionPersonaIds.length < 2 || normalizedSessionQuestion.length < 2 || isSessionSubmitting || !runtimeReady}>{isSessionSubmitting ? "正在封存会话…" : "开始多人访谈"}</button></div>
        </form>
        {sessionSubmissionError !== null ? <div className="persona-interview-error" role="alert">{sessionSubmissionError.message}</div> : null}
      </section>
      {sessionsState.status === "error" ? <ApiErrorPanel title="无法读取多人访谈会话" error={sessionsState.error} isRetrying={false} onRetry={reloadSessions} /> : null}
      <div className="persona-interview-sessions" aria-live="polite">
        {(sessionsState.data?.items ?? []).map((item) => <InterviewSessionResult key={item.id} item={item} report={report} />)}
      </div>
      {interviewsState.status === "error" ? <ApiErrorPanel title="无法读取 Persona 访谈" error={interviewsState.error} isRetrying={false} onRetry={reload} /> : null}
      <div className="persona-interview-history" aria-live="polite">
        {standaloneInterviews.length === 0 && (sessionsState.data?.items ?? []).length === 0 ? <p>还没有 Persona 访谈。系统不会自动选择 Persona 或自动生成问题。</p> : standaloneInterviews.map((item) => <InterviewResult key={item.id} item={item} report={report} />)}
      </div>
    </section>
  );
}
