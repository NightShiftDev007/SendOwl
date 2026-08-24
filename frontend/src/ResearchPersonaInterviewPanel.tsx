import { useEffect, useState, type FormEvent } from "react";

import { CitationDetails } from "./CitationDetails";
import {
  createResearchPersonaInterview,
  createResearchPersonaInterviewSession,
  fetchResearchPersonaInterviews,
  type ResearchPersonaInterviewsResponse,
} from "./researchInterviewContracts";
import { useCohortDetail } from "./usePopulations";

export function ResearchPersonaInterviewPanel({
  projectId,
  runId,
  cohortId,
}: {
  readonly projectId: string;
  readonly runId: string;
  readonly cohortId: string;
}): JSX.Element {
  const cohort = useCohortDetail(cohortId);
  const [data, setData] = useState<ResearchPersonaInterviewsResponse | null>(null);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | null = null;
    const load = (): void => {
      void fetchResearchPersonaInterviews(projectId, runId, controller.signal)
        .then((response) => {
          setData(response);
          setError(null);
          if (response.items.some((item) => item.status === "queued" || item.status === "running")) {
            timer = window.setTimeout(load, 1_500);
          }
        })
        .catch((caught: unknown) => {
          if (!(caught instanceof DOMException && caught.name === "AbortError")) {
            setError(caught instanceof Error ? caught : new Error("读取运行世界访谈失败。"));
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [projectId, runId, reloadVersion]);

  const togglePersona = (personaId: string): void => {
    setSelected((current) => current.includes(personaId)
      ? current.filter((item) => item !== personaId)
      : [...current, personaId]);
  };

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const normalized = question.trim();
    if (normalized.length < 2 || selected.length === 0 || submitting) return;
    const controller = new AbortController();
    setSubmitting(true);
    setError(null);
    try {
      if (selected.length === 1) {
        await createResearchPersonaInterview(
          projectId,
          runId,
          selected[0] ?? "",
          normalized,
          controller.signal,
        );
      } else {
        await createResearchPersonaInterviewSession(
          projectId,
          runId,
          selected,
          normalized,
          controller.signal,
        );
      }
      setQuestion("");
      setSelected([]);
      setReloadVersion((current) => current + 1);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("提交运行世界访谈失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  const members = cohort.state.status === "idle" ? [] : cohort.state.data?.members.slice(0, 8) ?? [];

  return (
    <section className="research-persona-interviews" aria-labelledby={`run-interviews-${runId}`}>
      <header>
        <div>
          <span>运行世界访谈</span>
          <h4 id={`run-interviews-${runId}`}>向合成 Persona 追加提问</h4>
        </div>
        <strong>每名 Persona 各调用一次模型</strong>
      </header>
      <p>这是读取已冻结运行状态后生成的新合成观察，不是仍在线 Agent 的实时对话，也不是现实用户访谈。</p>
      <form onSubmit={(event) => { void submit(event); }}>
        <fieldset>
          <legend>选择 1–8 名 Persona</legend>
          {cohort.state.status === "loading" ? <p role="status">正在读取运行人群…</p> : null}
          {members.map((member) => (
            <label key={member.persona.id}>
              <input
                type="checkbox"
                checked={selected.includes(member.persona.id)}
                onChange={() => togglePersona(member.persona.id)}
              />
              <span>{member.persona.display_name}</span>
            </label>
          ))}
        </fieldset>
        <label htmlFor={`run-interview-question-${runId}`}>访谈问题</label>
        <textarea
          id={`run-interview-question-${runId}`}
          rows={3}
          minLength={2}
          maxLength={1000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：看到这轮公开说明和评论后，你为什么采取了这个动作？哪些信息仍不足？"
        />
        <div>
          <small>{selected.length} 人 · {question.trim().length}/1000</small>
          <button
            className="button button-primary"
            type="submit"
            disabled={selected.length === 0 || question.trim().length < 2 || submitting}
          >
            {submitting ? "正在提交…" : selected.length > 1 ? `提交 ${selected.length} 人访谈` : "提交单人访谈"}
          </button>
        </div>
      </form>
      {error !== null ? <p className="research-run-failure" role="alert">{error.message}</p> : null}
      <div className="research-persona-interview-history" aria-live="polite">
        {(data?.items ?? []).length === 0 ? <p>还没有追加访谈；系统不会自动调用模型。</p> : (data?.items ?? []).map((item) => (
          <article key={item.id}>
            <header><strong>{item.persona.display_name}</strong><span>{item.question}</span></header>
            {item.status === "queued" || item.status === "running" ? <p role="status">正在读取冻结运行世界并生成合成回答…</p> : null}
            {item.status === "failed" ? <p className="research-run-failure">{item.error_message}</p> : null}
            {item.status === "succeeded" ? <><p>{item.answer_markdown}</p><CitationDetails citations={item.citations} /></> : null}
          </article>
        ))}
      </div>
    </section>
  );
}
