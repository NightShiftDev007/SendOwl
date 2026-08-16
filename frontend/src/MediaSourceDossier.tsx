import { ApiErrorPanel } from "./ApiErrorPanel";
import { MediaArticleRow } from "./MediaArticleRow";
import { formatCountryName, formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import { useMediaSourceEvidence } from "./useMediaSourceEvidence";

export function MediaSourceDossier({
  sourceId,
  page,
  onPageChange,
}: {
  readonly sourceId: string | null;
  readonly page: number;
  readonly onPageChange: (page: number) => void;
}): JSX.Element {
  const { state, reload } = useMediaSourceEvidence(sourceId, page);

  if (sourceId === null) {
    return (
      <section className="media-source-dossier media-source-dossier--empty" aria-label="来源档案">
        <strong>选择一个媒体来源</strong>
        <p>从来源目录明确选择后，才会读取该来源的元数据与已采集报道证据。</p>
      </section>
    );
  }

  if (state.status === "loading") {
    return (
      <section className="media-source-dossier media-source-dossier--loading" role="status" aria-live="polite">
        <span className="sr-only">正在读取来源档案</span>
        <span className="skeleton-block" />
        <span className="skeleton-block" />
        <span className="skeleton-block" />
      </section>
    );
  }

  if (state.status === "error") {
    return <ApiErrorPanel title="无法读取来源档案" error={state.error} isRetrying={false} onRetry={reload} />;
  }

  if (state.status !== "success") {
    return <section className="media-source-dossier media-source-dossier--loading" aria-hidden="true" />;
  }
  const { data } = state;
  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <section className="media-source-dossier" aria-label={`${data.source.name} 来源档案`}>
      <header className="media-source-dossier__header">
        <div>
          <span>Source Evidence Dossier</span>
          <h3>{data.source.name}</h3>
          <p>{formatCountryName(data.source.country_code)} · {data.source.media_type} · {data.source.language}</p>
        </div>
        <a href={data.source.homepage_url} target="_blank" rel="noreferrer">访问官网 ↗</a>
      </header>
      <dl className="media-source-dossier__facts">
        <div><dt>有效文章</dt><dd>{formatMediaCount(data.article_total)}</dd></div>
        <div><dt>最早发表</dt><dd>{data.first_published_at === null ? "未记录" : formatMediaTimestamp(data.first_published_at)}</dd></div>
        <div><dt>最新发表</dt><dd>{data.latest_published_at === null ? "未记录" : formatMediaTimestamp(data.latest_published_at)}</dd></div>
        <div><dt>观测时间</dt><dd><time dateTime={data.observed_at}>{formatMediaTimestamp(data.observed_at)}</time></dd></div>
      </dl>
      <div className="media-source-dossier__evidence-heading">
        <div><span>已采集证据</span><strong>按发表时间归档的报道</strong></div>
        <small>第 {data.page} / {totalPages} 页</small>
      </div>
      {data.items.length === 0 ? (
        <div className="media-source-dossier__no-evidence" role="status">该来源已登记，但当前没有已采集报道。</div>
      ) : (
        <div className="article-list">{data.items.map((article) => <MediaArticleRow article={article} key={article.id} />)}</div>
      )}
      <nav className="pagination" aria-label="来源报道分页">
        <button className="button button-secondary" type="button" disabled={data.page <= 1} onClick={() => onPageChange(data.page - 1)}>上一页</button>
        <span>第 {data.page} / {totalPages} 页</span>
        <button className="button button-secondary" type="button" disabled={data.page >= totalPages} onClick={() => onPageChange(data.page + 1)}>下一页</button>
      </nav>
    </section>
  );
}
