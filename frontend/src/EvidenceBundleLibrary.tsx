import { useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import {
  fetchEvidenceBundleContent,
  type EvidenceBundleContent,
  type EvidenceBundleDetail,
  type EvidenceBundleSummary,
} from "./evidenceBundleContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import { useEvidenceBundle, useEvidenceBundles } from "./useEvidenceBundles";
import "./evidenceBundles.css";

function shortDigest(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

function BundleDirectoryItem({
  bundle,
  isSelected,
  onSelect,
}: {
  readonly bundle: EvidenceBundleSummary;
  readonly isSelected: boolean;
  readonly onSelect: (bundleId: string) => void;
}): JSX.Element {
  return (
    <li>
      <button type="button" data-selected={isSelected} onClick={() => onSelect(bundle.id)}>
        <span><strong>{bundle.title}</strong><small>v{bundle.version} · {bundle.item_count} 篇</small></span>
        <time dateTime={bundle.created_at}>{formatMediaTimestamp(bundle.created_at)}</time>
        <code title={bundle.bundle_sha256}>{shortDigest(bundle.bundle_sha256)}</code>
      </button>
    </li>
  );
}

function FrozenContent({
  bundle,
  articleId,
}: {
  readonly bundle: EvidenceBundleDetail;
  readonly articleId: string;
}): JSX.Element {
  const [state, setState] = useState<
    | { readonly status: "idle" }
    | { readonly status: "loading" }
    | { readonly status: "success"; readonly data: EvidenceBundleContent }
    | { readonly status: "error"; readonly error: Error }
  >({ status: "idle" });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const load = (): void => {
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setState({ status: "loading" });
    void fetchEvidenceBundleContent(bundle.id, articleId, nextController.signal)
      .then((data) => {
        if (controller.current === nextController) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (controller.current === nextController) {
          setState({
            status: "error",
            error: error instanceof Error ? error : new Error("读取冻结正文失败。"),
          });
        }
      });
  };

  if (state.status === "success") {
    return (
      <div className="evidence-bundle-content">
        <pre>{state.data.captured_text}</pre>
        <code title={state.data.captured_text_sha256}>{state.data.captured_text_sha256}</code>
      </div>
    );
  }

  return (
    <div className="evidence-bundle-content-action">
      <button type="button" disabled={state.status === "loading"} onClick={load}>
        {state.status === "loading" ? "正在核验正文…" : "读取冻结正文"}
      </button>
      {state.status === "error" ? <p role="alert">{state.error.message}</p> : null}
    </div>
  );
}

function BundleDetail({ bundle }: { readonly bundle: EvidenceBundleDetail }): JSX.Element {
  return (
    <article className="evidence-bundle-detail">
      <header>
        <div><span>SEALED / HUMAN CONFIRMED</span><h3>{bundle.title}</h3></div>
        <strong>v{bundle.version}</strong>
      </header>
      <dl>
        <div><dt>Bundle</dt><dd><code>{bundle.bundle_sha256}</code></dd></div>
        <div><dt>Snapshot</dt><dd><code>{bundle.snapshot_sha256}</code></dd></div>
        <div><dt>冻结证据</dt><dd>{bundle.item_count} 篇</dd></div>
        <div><dt>创建时间</dt><dd>{formatMediaTimestamp(bundle.created_at)}</dd></div>
      </dl>
      <ol>
        {bundle.items.map((item) => (
          <li key={item.article_id}>
            <header>
              <span>{item.position + 1}</span>
              <div><strong>{item.title}</strong><small>{item.source_name} · {formatMediaTimestamp(item.published_at)}</small></div>
              <a href={item.original_url} target="_blank" rel="noopener noreferrer">原文 ↗</a>
            </header>
            <p>{item.excerpt}</p>
            <details>
              <summary>冻结正文与内容地址</summary>
              <FrozenContent bundle={bundle} articleId={item.article_id} />
            </details>
          </li>
        ))}
      </ol>
    </article>
  );
}

export function EvidenceBundleLibrary(): JSX.Element {
  const { state: directoryState, reload: reloadDirectory } = useEvidenceBundles();
  const [selectedBundleId, setSelectedBundleId] = useState<string | null>(null);
  const { state: detailState, reload: reloadDetail } = useEvidenceBundle(selectedBundleId);

  return (
    <section className="evidence-bundle-library" aria-labelledby="evidence-bundle-library-title">
      <header>
        <div>
          <span>EVIDENCE / SEALED BUNDLES</span>
          <h2 id="evidence-bundle-library-title">可复用证据包</h2>
          <p>每个已封存世界版本同时是一份独立证据包。两者共享同一正文与哈希，不复制数据、不产生双真相。</p>
        </div>
        <details className="decision-diagnostics"><summary>接口诊断</summary><code>GET /api/v2/evidence-bundles</code></details>
      </header>

      <div className="evidence-bundle-workbench">
        <div className="evidence-bundle-focus" aria-live="polite">
          {selectedBundleId === null ? <div className="evidence-bundle-empty"><strong>明确选择一份证据包</strong><p>这里不会自动打开第一项，避免把历史版本误认为当前决策上下文。</p></div> : null}
          {detailState.status === "loading" ? <div className="evidence-bundle-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
          {detailState.status === "error" ? <ApiErrorPanel title="无法读取证据包" error={detailState.error} isRetrying={detailState.isRetrying} onRetry={reloadDetail} /> : null}
          {detailState.status === "success" ? <BundleDetail bundle={detailState.data} /> : null}
        </div>

        <aside className="evidence-bundle-directory" aria-label="Evidence Bundle 目录">
          <header><div><strong>封存目录</strong><small>{directoryState.status === "success" ? `${directoryState.data.total} 份` : "核验中"}</small></div><button type="button" disabled={directoryState.status === "loading"} onClick={reloadDirectory}>刷新</button></header>
          {directoryState.status === "error" ? <ApiErrorPanel title="无法读取证据包目录" error={directoryState.error} isRetrying={directoryState.isRetrying} onRetry={reloadDirectory} /> : null}
          {directoryState.status === "loading" ? <div className="evidence-bundle-loading" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div> : null}
          {directoryState.status === "success" && directoryState.data.items.length === 0 ? <div className="evidence-bundle-empty"><strong>还没有证据包</strong><p>在上方人工确认并冻结媒体证据后，这里会出现可复用版本。</p></div> : null}
          {directoryState.status === "success" && directoryState.data.items.length > 0 ? <ol>{directoryState.data.items.map((bundle) => <BundleDirectoryItem key={bundle.id} bundle={bundle} isSelected={bundle.id === selectedBundleId} onSelect={setSelectedBundleId} />)}</ol> : null}
        </aside>
      </div>
    </section>
  );
}
