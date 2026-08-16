import type { MediaArticle } from "./mediaContracts";
import {
  formatCountryName,
  formatMediaTimestamp,
} from "./mediaPresentation";

export interface MediaArticleRowProps {
  readonly article: MediaArticle;
  readonly onSendToWorld?: (article: MediaArticle) => void;
}

export function MediaArticleSummaryContent({ article }: MediaArticleRowProps): JSX.Element {
  return (
    <>
      <div className="article-meta">
        <strong>{article.source_name}</strong>
        <time dateTime={article.published_at}>
          {formatMediaTimestamp(article.published_at)}
        </time>
        {article.country_code === null ? null : (
          <span>{formatCountryName(article.country_code)}</span>
        )}
        <span>{article.topic}</span>
      </div>
      <div className="article-content">
        <h3>{article.title}</h3>
        <p>{article.excerpt}</p>
      </div>
      <a
        className="article-source-link"
        href={article.original_url}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`查看原文：${article.title}`}
      >
        查看原文
        <span aria-hidden="true">↗</span>
      </a>
    </>
  );
}

export function MediaArticleRow({ article, onSendToWorld }: MediaArticleRowProps): JSX.Element {
  return (
    <article className="media-article-row">
      <MediaArticleSummaryContent article={article} />
      {onSendToWorld === undefined ? null : (
        <button
          className="article-world-handoff"
          type="button"
          onClick={() => onSendToWorld(article)}
        >
          带入 World 版本室
        </button>
      )}
    </article>
  );
}
