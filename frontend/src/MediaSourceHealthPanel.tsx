import { useEffect, useId, useMemo, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type {
  MediaSourceSummary,
  MediaSourcesResponse,
} from "./mediaSourceContracts";
import {
  formatCountryName,
  formatMediaCount,
  formatMediaTimestamp,
} from "./mediaPresentation";
import { useMediaSources } from "./useMediaSources";
import "./mediaSourceHealth.css";

const sourcesPerPage = 25;

function MediaSourceHealthLoading(): JSX.Element {
  return (
    <section
      className="media-source-health media-source-health--loading"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">正在读取媒体源健康状态</span>
      <span className="skeleton-block media-source-health__loading-title" aria-hidden="true" />
      <span className="skeleton-block media-source-health__loading-ledger" aria-hidden="true" />
      {Array.from({ length: 6 }, (_, index) => (
        <span
          className="skeleton-block media-source-health__loading-row"
          aria-hidden="true"
          key={index}
        />
      ))}
    </section>
  );
}

function statusMatches(source: MediaSourceSummary, selectedStatus: string | null): boolean {
  return selectedStatus === null || source.status === selectedStatus;
}

function queryMatches(source: MediaSourceSummary, normalizedQuery: string): boolean {
  if (normalizedQuery.length === 0) {
    return true;
  }

  const searchableText = [
    source.name,
    source.country_code,
    formatCountryName(source.country_code),
    source.status,
    source.media_type,
    source.language,
  ]
    .join(" ")
    .toLocaleLowerCase();

  return searchableText.includes(normalizedQuery);
}

function visibleSources(
  sources: readonly MediaSourceSummary[],
  query: string,
  selectedStatus: string | null,
): readonly MediaSourceSummary[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();

  return sources.filter(
    (source) => statusMatches(source, selectedStatus) && queryMatches(source, normalizedQuery),
  );
}

function StatusMarker({ status }: { readonly status: string }): JSX.Element {
  return (
    <span className="media-source-health__status" data-status={status}>
      <span className="media-source-health__status-symbol" aria-hidden="true" />
      <span>{status}</span>
    </span>
  );
}

function SourceRow({
  source,
  selectedSourceId,
  onSelectSource,
}: {
  readonly source: MediaSourceSummary;
  readonly selectedSourceId: string | null;
  readonly onSelectSource: (source: MediaSourceSummary) => void;
}): JSX.Element {
  const isSelected = selectedSourceId === source.id;

  return (
    <li className="media-source-health__row" data-selected={isSelected}>
      <div className="media-source-health__source">
        <button
          type="button"
          aria-pressed={isSelected}
          onClick={() => onSelectSource(source)}
        >
          {source.name}
        </button>
        <span>{source.media_type} · {source.language}</span>
      </div>
      <div className="media-source-health__country" aria-label="国家或地区">
        <strong>{source.country_code}</strong>
        <span>{formatCountryName(source.country_code)}</span>
      </div>
      <StatusMarker status={source.status} />
      <div className="media-source-health__success">
        {source.last_success_at === null ? (
          <span>从未记录成功</span>
        ) : (
          <time dateTime={source.last_success_at}>
            {formatMediaTimestamp(source.last_success_at)}
          </time>
        )}
      </div>
      <a
        className="media-source-health__homepage"
        href={source.homepage_url}
        target="_blank"
        rel="noreferrer"
        aria-label={`打开 ${source.name} 官网（新窗口）`}
      >
        官网
      </a>
    </li>
  );
}

function StatusFilters({
  response,
  selectedStatus,
  onStatusChange,
}: {
  readonly response: MediaSourcesResponse;
  readonly selectedStatus: string | null;
  readonly onStatusChange: (status: string | null) => void;
}): JSX.Element {
  return (
    <div className="media-source-health__status-filters" aria-label="按接口状态筛选">
      <button
        type="button"
        aria-pressed={selectedStatus === null}
        onClick={() => onStatusChange(null)}
      >
        <span>全部</span>
        <strong>{formatMediaCount(response.total)}</strong>
      </button>
      {Object.entries(response.status_counts).map(([status, count]) => (
        <button
          type="button"
          data-status={status}
          aria-pressed={selectedStatus === status}
          onClick={() => onStatusChange(status)}
          key={status}
        >
          <span>{status}</span>
          <strong>{formatMediaCount(count)}</strong>
        </button>
      ))}
    </div>
  );
}

function MediaSourceHealthContent({
  response,
  onReload,
  selectedSourceId,
  onSelectSource,
}: {
  readonly response: MediaSourcesResponse;
  readonly onReload: () => void;
  readonly selectedSourceId: string | null;
  readonly onSelectSource: (source: MediaSourceSummary) => void;
}): JSX.Element {
  const [query, setQuery] = useState<string>("");
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null);
  const [page, setPage] = useState<number>(1);
  const titleId = useId();
  const queryId = useId();
  const sources = useMemo(
    () => visibleSources(response.items, query, selectedStatus),
    [query, response.items, selectedStatus],
  );
  const pageCount = Math.max(1, Math.ceil(sources.length / sourcesPerPage));
  const visiblePage = Math.min(page, pageCount);
  const pageSources = sources.slice(
    (visiblePage - 1) * sourcesPerPage,
    visiblePage * sourcesPerPage,
  );

  useEffect(() => {
    const selectedIndex = selectedSourceId === null
      ? -1
      : sources.findIndex((source) => source.id === selectedSourceId);
    setPage(selectedIndex < 0 ? 1 : Math.floor(selectedIndex / sourcesPerPage) + 1);
  }, [selectedSourceId, sources]);

  return (
    <section className="media-source-health" aria-labelledby={titleId}>
      <header className="media-source-health__header">
        <div>
          <h3 id={titleId}>媒体源健康</h3>
          <p>直接读取采集源目录；状态和值按接口原样呈现，不推算综合健康分。</p>
        </div>
        <button className="button button-secondary" type="button" onClick={onReload}>
          刷新目录
        </button>
      </header>

      <StatusFilters
        response={response}
        selectedStatus={selectedStatus}
        onStatusChange={setSelectedStatus}
      />

      <div className="media-source-health__toolbar">
        <label htmlFor={queryId}>
          <span>查找来源</span>
          <input
            id={queryId}
            type="search"
            value={query}
            placeholder="名称、国家、状态、类型或语言"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <p role="status" aria-live="polite">
          找到 {formatMediaCount(sources.length)} / {formatMediaCount(response.total)} 个来源
          {sources.length === 0 ? null : ` · 第 ${visiblePage} / ${pageCount} 页`}
        </p>
      </div>

      {response.items.length === 0 ? (
        <div className="media-source-health__empty" role="status">
          <strong>接口还没有媒体源记录</strong>
          <p>当前目录为空；这里不会生成示例来源或虚构状态。</p>
        </div>
      ) : sources.length === 0 ? (
        <div className="media-source-health__empty" role="status">
          <strong>没有符合当前筛选的来源</strong>
          <p>清除关键词或切换状态后可继续查看接口返回的目录。</p>
        </div>
      ) : (
        <div className="media-source-health__directory">
          <div className="media-source-health__columns" aria-hidden="true">
            <span>来源</span>
            <span>国家 / 地区</span>
            <span>接口状态</span>
            <span>最近成功采集</span>
            <span>原站</span>
          </div>
          <ul aria-label="媒体源健康目录">
            {pageSources.map((source) => (
              <SourceRow
                key={source.id}
                source={source}
                selectedSourceId={selectedSourceId}
                onSelectSource={onSelectSource}
              />
            ))}
          </ul>
          {pageCount <= 1 ? null : (
            <nav className="media-source-health__pagination" aria-label="媒体源目录分页">
              <button
                type="button"
                disabled={visiblePage === 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                上一页
              </button>
              <span aria-current="page">第 {visiblePage} / {pageCount} 页</span>
              <button
                type="button"
                disabled={visiblePage === pageCount}
                onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
              >
                下一页
              </button>
            </nav>
          )}
        </div>
      )}
    </section>
  );
}

export function MediaSourceHealthPanel({
  selectedSourceId,
  onSelectSource,
}: {
  readonly selectedSourceId: string | null;
  readonly onSelectSource: (source: MediaSourceSummary) => void;
}): JSX.Element {
  const { state, reload } = useMediaSources();

  if (state.status === "loading") {
    return <MediaSourceHealthLoading />;
  }

  if (state.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取媒体源健康状态"
        error={state.error}
        isRetrying={state.isRetrying}
        onRetry={reload}
      />
    );
  }

  return (
    <MediaSourceHealthContent
      response={state.data}
      selectedSourceId={selectedSourceId}
      onReload={reload}
      onSelectSource={onSelectSource}
    />
  );
}
