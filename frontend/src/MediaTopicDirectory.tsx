import { useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type { MediaTopicSummary } from "./mediaContracts";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import { useMediaTopics } from "./useMediaTopics";

const topicsPerPage = 10;

export interface MediaTopicDirectoryProps {
  readonly selectedTopicId: string | null;
  readonly onSelect: (topic: MediaTopicSummary | null) => void;
}

function DirectorySkeleton(): JSX.Element {
  return (
    <div className="media-topic-directory__skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取完整议题目录</span>
      {Array.from({ length: 5 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

export function MediaTopicDirectory({
  selectedTopicId,
  onSelect,
}: MediaTopicDirectoryProps): JSX.Element {
  const [page, setPage] = useState<number>(1);
  const { state, reload } = useMediaTopics(page, topicsPerPage);
  const response = state.data;
  const totalPages = response === null
    ? 1
    : Math.max(1, Math.ceil(response.total / response.page_size));

  return (
    <section
      id="media-topic-directory"
      className="media-topic-directory"
      tabIndex={-1}
      aria-labelledby="media-topic-directory-title"
    >
      <header className="media-topic-directory__heading">
        <div>
          <h3 id="media-topic-directory-title">完整议题目录</h3>
          <span>{response === null ? "读取中" : `${formatMediaCount(response.total)} 项真实议题`}</span>
        </div>
        <button type="button" disabled={state.status === "loading"} onClick={reload}>
          {state.status === "loading" ? "读取中…" : "刷新"}
        </button>
      </header>

      <p className="media-topic-directory__intro">
        按最近活跃时间排序。明确选择后，文章证据流与议题演化会共享同一稳定 ID。
      </p>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取完整议题目录"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={reload}
        />
      ) : null}
      {state.status === "loading" && response === null ? <DirectorySkeleton /> : null}
      {response !== null && response.items.length === 0 ? (
        <div className="media-topic-directory__empty" role="status">
          <strong>当前目录为空</strong>
          <p>接口没有返回可选择的活跃议题。</p>
        </div>
      ) : null}
      {response !== null && response.items.length > 0 ? (
        <ol className="media-topic-directory__list" aria-busy={state.status === "loading"}>
          {response.items.map((topic) => {
            const selected = selectedTopicId === topic.id;

            return (
              <li key={topic.id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  data-topic-id={topic.id}
                  onClick={() => onSelect(selected ? null : topic)}
                >
                  <span className="media-topic-directory__title">
                    <strong>{topic.topic}</strong>
                    <small>{topic.category ?? "未分类"} · {topic.status}</small>
                  </span>
                  <span className="media-topic-directory__activity">
                    <strong>{formatMediaCount(topic.article_count)}</strong>
                    <time dateTime={topic.last_seen_at}>{formatMediaTimestamp(topic.last_seen_at)}</time>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : null}

      {response !== null && response.total > 0 ? (
        <nav className="media-topic-directory__pagination" aria-label="完整议题目录分页">
          <button
            type="button"
            disabled={page <= 1 || state.status === "loading"}
            onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))}
          >
            上一页
          </button>
          <span aria-live="polite">{page} / {totalPages}</span>
          <button
            type="button"
            disabled={page >= totalPages || state.status === "loading"}
            onClick={() => setPage((currentPage) => currentPage + 1)}
          >
            下一页
          </button>
        </nav>
      ) : null}
    </section>
  );
}
