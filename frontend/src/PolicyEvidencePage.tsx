import { useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { formatMediaTimestamp } from "./mediaPresentation";
import {
  capturePolicyDocument,
  policyDocumentCaptureRequestSchema,
} from "./policyEvidenceContracts";
import { usePolicyDocument, usePolicyDocuments, usePolicyVersionContent } from "./usePolicyEvidence";
import "./policyEvidence.css";

type CaptureState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "error"; readonly error: Error };

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function normalizedError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("捕获政策证据失败：请求抛出了非标准错误。");
}

export function PolicyEvidencePage(): JSX.Element {
  const [page, setPage] = useState<number>(1);
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [authorityName, setAuthorityName] = useState<string>("");
  const [jurisdictionCode, setJurisdictionCode] = useState<string>("");
  const [homepageUrl, setHomepageUrl] = useState<string>("");
  const [canonicalIdentifier, setCanonicalIdentifier] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [originalUrl, setOriginalUrl] = useState<string>("");
  const [language, setLanguage] = useState<string>("zh-CN");
  const [publicationDate, setPublicationDate] = useState<string>("");
  const [effectiveFrom, setEffectiveFrom] = useState<string>("");
  const [effectiveUntil, setEffectiveUntil] = useState<string>("");
  const [capturedText, setCapturedText] = useState<string>("");
  const [confirmed, setConfirmed] = useState<boolean>(false);
  const [capture, setCapture] = useState<CaptureState>({ status: "idle" });
  const activeCapture = useRef<AbortController | null>(null);
  const directory = usePolicyDocuments(page);
  const detail = usePolicyDocument(selectedDocumentId);
  const selectedDetail = detail.state.data;
  const activeVersionId = selectedVersionId ?? selectedDetail?.latest_version.id ?? null;
  const content = usePolicyVersionContent(selectedDocumentId, activeVersionId);
  const pageCount = Math.max(1, Math.ceil((directory.state.data?.total ?? 0) / 20));

  const submit = async (): Promise<void> => {
    if (!confirmed || capture.status === "submitting") return;
    const controller = new AbortController();
    activeCapture.current?.abort();
    activeCapture.current = controller;
    setCapture({ status: "submitting" });
    try {
      const request = policyDocumentCaptureRequestSchema.parse({
        source: {
          authority_name: authorityName,
          jurisdiction_code: jurisdictionCode,
          homepage_url: homepageUrl,
        },
        canonical_identifier: canonicalIdentifier,
        title,
        original_url: originalUrl,
        language,
        publication_date: publicationDate,
        effective_from: effectiveFrom === "" ? null : effectiveFrom,
        effective_until: effectiveUntil === "" ? null : effectiveUntil,
        captured_text: capturedText,
        verification: "human_confirmed",
      });
      const created = await capturePolicyDocument(request, controller.signal);
      setCapture({ status: "idle" });
      setConfirmed(false);
      directory.reload();
      setSelectedDocumentId(created.id);
      setSelectedVersionId(created.latest_version.id);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setCapture({ status: "error", error: normalizedError(error) });
    } finally {
      if (activeCapture.current === controller) activeCapture.current = null;
    }
  };

  return (
    <div className="policy-page">
      <header className="policy-hero">
        <div><span>REALITY / POLICY</span><h1>政策证据库</h1></div>
        <p>人工确认外部政策原文，保存稳定文档身份、不可变版本、效力日期和内容哈希。政策证据不是 Agent 叙事或执行结果。</p>
      </header>
      <div className="policy-layout">
        <aside className="policy-capture">
          <header><span>CAPTURE / HUMAN CONFIRMED</span><h3>捕获政策版本</h3></header>
          <label>发布机构<input value={authorityName} maxLength={300} onChange={(event) => setAuthorityName(event.target.value)} /></label>
          <label>辖区代码<input value={jurisdictionCode} maxLength={16} placeholder="CN / CN-BJ / EU" onChange={(event) => setJurisdictionCode(event.target.value.toUpperCase())} /></label>
          <label>机构主页<input type="url" value={homepageUrl} maxLength={1_000} onChange={(event) => setHomepageUrl(event.target.value)} /></label>
          <label>规范文号<input value={canonicalIdentifier} maxLength={256} onChange={(event) => setCanonicalIdentifier(event.target.value)} /></label>
          <label>政策标题<input value={title} maxLength={500} onChange={(event) => setTitle(event.target.value)} /></label>
          <label>原文地址<input type="url" value={originalUrl} maxLength={1_000} onChange={(event) => setOriginalUrl(event.target.value)} /></label>
          <div className="policy-capture-row">
            <label>语言<input value={language} maxLength={16} onChange={(event) => setLanguage(event.target.value)} /></label>
            <label>发布日期<input type="date" value={publicationDate} onChange={(event) => setPublicationDate(event.target.value)} /></label>
          </div>
          <div className="policy-capture-row">
            <label>施行日期<input type="date" value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /></label>
            <label>失效日期<input type="date" value={effectiveUntil} onChange={(event) => setEffectiveUntil(event.target.value)} /></label>
          </div>
          <label>完整政策正文<textarea value={capturedText} maxLength={2_000_000} rows={10} onChange={(event) => setCapturedText(event.target.value)} /></label>
          <label className="policy-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>我已核对发布机构、原文地址、日期和正文；本次捕获将成为不可修改的外部现实证据。</span></label>
          <button type="button" disabled={!confirmed || capture.status === "submitting"} onClick={() => { void submit(); }}>{capture.status === "submitting" ? "正在封存…" : "封存政策证据"}</button>
          {capture.status === "error" ? <div role="alert"><strong>捕获失败</strong><p>{capture.error.message}</p></div> : null}
        </aside>

        <section className="policy-detail">
          <header><div><span>DOCUMENT / VERSIONS</span><h3>不可变政策版本</h3></div>{selectedDetail !== null ? <code>{shortHash(selectedDetail.document_sha256)}</code> : null}</header>
          {selectedDocumentId === null ? <div className="policy-empty"><strong>选择一份政策文档</strong><p>目录不会自动打开历史证据，避免把旧上下文带入当前判断。</p></div> : null}
          {detail.state.status === "error" ? <ApiErrorPanel title="无法读取政策文档" error={detail.state.error} isRetrying={false} onRetry={detail.reload} /> : null}
          {selectedDetail !== null ? <>
            <section className="policy-identity"><div><span>Authority</span><strong>{selectedDetail.source.authority_name}</strong></div><div><span>Jurisdiction</span><strong>{selectedDetail.source.jurisdiction_code}</strong></div><div><span>Identifier</span><strong>{selectedDetail.canonical_identifier}</strong></div><div><span>Versions</span><strong>{selectedDetail.version_count}</strong></div></section>
            <nav className="policy-versions" aria-label="政策版本">{[...selectedDetail.versions].reverse().map((version) => <button key={version.id} type="button" aria-pressed={version.id === activeVersionId} onClick={() => setSelectedVersionId(version.id)}><span>VERSION {version.version}</span><strong>{version.title}</strong><small>发布 {version.publication_date} · 施行 {version.effective_from ?? "未标明"} · 失效 {version.effective_until ?? "未标明"}</small><code>{shortHash(version.version_sha256)}</code></button>)}</nav>
            {content.status === "loading" ? <div className="policy-empty"><strong>正在核验正文…</strong></div> : null}
            {content.status === "error" ? <div className="policy-empty" role="alert"><strong>正文读取失败</strong><p>{content.error.message}</p></div> : null}
            {content.data !== null ? <article className="policy-content"><header><span>CAPTURED TEXT</span><code>{shortHash(content.data.content_sha256)}</code></header><pre>{content.data.captured_text}</pre></article> : null}
          </> : null}
        </section>

        <aside className="policy-directory">
          <header><div><span>INDEX / POLICY</span><h3>政策目录</h3></div><button type="button" onClick={directory.reload}>刷新</button></header>
          {directory.state.status === "error" ? <ApiErrorPanel title="无法读取政策目录" error={directory.state.error} isRetrying={false} onRetry={directory.reload} /> : null}
          {directory.state.data?.items.length === 0 ? <div className="policy-empty"><strong>尚无政策证据</strong><p>使用左侧表单捕获经过人工核对的真实政策原文。</p></div> : null}
          <ol>{directory.state.data?.items.map((document) => <li key={document.id}><button type="button" data-selected={document.id === selectedDocumentId} onClick={() => { setSelectedDocumentId(document.id); setSelectedVersionId(null); }}><strong>{document.latest_version.title}</strong><span>{document.source.authority_name} · {document.canonical_identifier}</span><small>{document.version_count} 个版本 · 发布 {document.latest_version.publication_date}</small><time dateTime={document.latest_version.captured_at}>{formatMediaTimestamp(document.latest_version.captured_at)}</time></button></li>)}</ol>
          <nav aria-label="政策目录分页"><button type="button" disabled={page <= 1} onClick={() => { setPage((current) => current - 1); setSelectedDocumentId(null); }}>上一页</button><span>{page} / {pageCount}</span><button type="button" disabled={page >= pageCount} onClick={() => { setPage((current) => current + 1); setSelectedDocumentId(null); }}>下一页</button></nav>
        </aside>
      </div>
    </div>
  );
}
