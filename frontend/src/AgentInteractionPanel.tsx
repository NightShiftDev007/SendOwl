import { useEffect, useState, type FormEvent } from "react";

import {
  createAgentInteraction,
  fetchAgentInteractions,
  type AgentInteraction,
  type AgentInteractionsResponse,
} from "./agentInteractionContracts";
import { CitationDetails } from "./CitationDetails";

export function AgentInteractionPanel({ draftId }: { readonly draftId: string }): JSX.Element {
  const [data, setData] = useState<AgentInteractionsResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [parent, setParent] = useState<AgentInteraction | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | null = null;
    const load = (): void => {
      void fetchAgentInteractions(draftId, controller.signal)
        .then((response) => {
          setData(response);
          setError(null);
          if (response.items.some((item) => item.status === "queued" || item.status === "running")) {
            timer = window.setTimeout(load, 1_500);
          }
        })
        .catch((caught: unknown) => {
          if (!(caught instanceof DOMException && caught.name === "AbortError")) {
            setError(caught instanceof Error ? caught : new Error("读取报告追问失败。"));
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [draftId, reloadVersion]);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const normalized = question.trim();
    if (normalized.length < 2 || submitting) return;
    const controller = new AbortController();
    setSubmitting(true);
    setError(null);
    try {
      await createAgentInteraction(draftId, normalized, parent?.id ?? null, controller.signal);
      setQuestion("");
      setParent(null);
      setReloadVersion((current) => current + 1);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught : new Error("提交报告追问失败。"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="agent-interaction" aria-labelledby="agent-interaction-title">
      <header>
        <div><span>报告追问 / 单次运行</span><h4 id="agent-interaction-title">继续询问这次模拟</h4></div>
        <strong>每次提交会调用模型</strong>
      </header>
      <p>回答只绑定上方这份引用报告及其冻结运行记录，不比较其他方案，也不把合成结果当作现实预测。</p>
      <form onSubmit={(event) => { void submit(event); }}>
        {parent !== null ? <div className="agent-interaction-parent"><span>继续追问第 {parent.conversation_depth + 2} 轮</span><p>{parent.question}</p><button type="button" onClick={() => setParent(null)}>取消追问</button></div> : null}
        <label htmlFor={`agent-interaction-${draftId}`}>你的问题</label>
        <textarea id={`agent-interaction-${draftId}`} rows={3} minLength={2} maxLength={1000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这次模拟中哪些动作支持报告的这项分析？它没有证明什么？" />
        <div><small>{question.trim().length}/1000</small><button className="button button-primary" type="submit" disabled={question.trim().length < 2 || submitting}>{submitting ? "正在提交…" : "提交追问（调用模型）"}</button></div>
      </form>
      {error !== null ? <p className="research-run-failure" role="alert">{error.message}</p> : null}
      <div className="agent-interaction-history" aria-live="polite">
        {(data?.items ?? []).length === 0 ? <p>还没有互动。SandOwl 不会自动生成问题。</p> : (data?.items ?? []).map((item) => <article key={item.id}><header><span>第 {item.conversation_depth + 1} 轮</span><strong>{item.question}</strong></header>{item.status === "queued" || item.status === "running" ? <p role="status">报告 worker 正在核对冻结记录…</p> : null}{item.status === "failed" ? <p className="research-run-failure">{item.error_message}</p> : null}{item.status === "succeeded" ? <><p>{item.answer_markdown}</p><CitationDetails citations={item.citations} />{item.conversation_depth < 4 ? <button type="button" onClick={() => setParent(item)}>继续追问</button> : null}</> : null}</article>)}
      </div>
    </section>
  );
}
