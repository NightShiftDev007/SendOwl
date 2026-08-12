import { useMemo, useState, type FormEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { MediaArticleRow } from "./MediaArticleRow";
import type {
  MediaArticlesQuery,
  MediaArticlesResponse,
  MediaCountryFacet,
  MediaTopicFacet,
} from "./mediaContracts";
import { formatCountryName, formatMediaCount } from "./mediaPresentation";
import {
  useMediaArticles,
  type MediaArticlesLoadState,
} from "./useMediaArticles";
import "./mediaEvidence.css";

const articlesPerPage = 20;

interface SelectedTopic {
  readonly id: string;
  readonly name: string;
}

interface EvidenceQueryRailProps {
  readonly activeFilterCount: number;
  readonly country: string | null;
  readonly countryFacets: readonly MediaCountryFacet[];
  readonly draftQuery: string;
  readonly filtersExpanded: boolean;
  readonly selectedCountryIsMissing: boolean;
  readonly selectedTopic: SelectedTopic | null;
  readonly selectedTopicIsMissing: boolean;
  readonly topicFacets: readonly MediaTopicFacet[];
  readonly onClear: () => void;
  readonly onCountryChange: (country: string | null) => void;
  readonly onDraftQueryChange: (query: string) => void;
  readonly onFiltersExpandedChange: (expanded: boolean) => void;
  readonly onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  readonly onTopicChange: (topicId: string) => void;
}

interface EvidenceInspectorProps {
  readonly appliedQuery: string | null;
  readonly country: string | null;
  readonly countryFacets: readonly MediaCountryFacet[];
  readonly response: MediaArticlesResponse | null;
  readonly selectedTopic: SelectedTopic | null;
  readonly topicFacets: readonly MediaTopicFacet[];
  readonly onCountrySelect: (country: string) => void;
  readonly onTopicSelect: (topic: MediaTopicFacet) => void;
}

function ArticlesSkeleton(): JSX.Element {
  return (
    <div className="article-list article-list-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取媒体报道</span>
      {Array.from({ length: 5 }, (_, index) => (
        <div className="article-skeleton-row" aria-hidden="true" key={index}>
          <span className="skeleton-block skeleton-article-meta" />
          <span className="skeleton-block skeleton-article-title" />
          <span className="skeleton-block skeleton-article-excerpt" />
        </div>
      ))}
    </div>
  );
}

function ArticlesEmpty(): JSX.Element {
  return (
    <div className="media-empty-state" role="status">
      <strong>这组条件没有返回报道</strong>
      <p>这是接口返回的空结果，不代表现实中没有相关事件。可以放宽关键词、国家或议题后继续检索。</p>
    </div>
  );
}

function ArticleResults({
  response,
  isUpdating,
}: {
  readonly response: MediaArticlesResponse;
  readonly isUpdating: boolean;
}): JSX.Element {
  if (response.items.length === 0) {
    return <ArticlesEmpty />;
  }

  return (
    <div className="article-results" aria-busy={isUpdating}>
      {isUpdating ? (
        <div className="results-updating" role="status">
          正在更新证据流…
        </div>
      ) : null}
      <div className="article-list">
        {response.items.map((article) => (
          <MediaArticleRow key={article.id} article={article} />
        ))}
      </div>
    </div>
  );
}

function currentData(state: MediaArticlesLoadState): MediaArticlesResponse | null {
  return state.data;
}

function EvidenceQueryRail({
  activeFilterCount,
  country,
  countryFacets,
  draftQuery,
  filtersExpanded,
  selectedCountryIsMissing,
  selectedTopic,
  selectedTopicIsMissing,
  topicFacets,
  onClear,
  onCountryChange,
  onDraftQueryChange,
  onFiltersExpandedChange,
  onSubmit,
  onTopicChange,
}: EvidenceQueryRailProps): JSX.Element {
  const hasInvalidQueryLength = draftQuery.trim().length === 1;

  return (
    <aside
      className="evidence-query-rail"
      data-expanded={filtersExpanded}
      aria-label="报道查询条件"
    >
      <button
        className="evidence-filter-toggle"
        type="button"
        aria-controls="evidence-filter-form"
        aria-expanded={filtersExpanded}
        onClick={() => onFiltersExpandedChange(!filtersExpanded)}
      >
        <span>
          <strong>查询与筛选</strong>
          <small>{activeFilterCount === 0 ? "当前未限制" : `${activeFilterCount} 项条件已生效`}</small>
        </span>
        <span aria-hidden="true">{filtersExpanded ? "收起" : "展开"}</span>
      </button>

      <div className="evidence-filter-body" id="evidence-filter-form">
        <div className="evidence-rail-heading">
          <strong>形成观察切面</strong>
          <p>先缩小已采集报道范围，再进入原文核验。筛选不会生成新证据。</p>
        </div>

        <form className="evidence-filter-form" role="search" onSubmit={onSubmit}>
          <label className="evidence-search-field" htmlFor="media-evidence-query">
            <span>关键词</span>
            <input
              id="media-evidence-query"
              name="q"
              type="search"
              value={draftQuery}
              placeholder="企业、人物或议题"
              minLength={2}
              maxLength={100}
              aria-invalid={hasInvalidQueryLength}
              aria-describedby="media-evidence-query-help"
              onChange={(event) => onDraftQueryChange(event.target.value)}
            />
          </label>
          <small className="evidence-field-help" id="media-evidence-query-help">
            {hasInvalidQueryLength ? "关键词至少需要 2 个字符。" : "留空表示不限制关键词。"}
          </small>

          <label htmlFor="media-evidence-country">
            <span>国家 / 地区</span>
            <select
              id="media-evidence-country"
              name="country"
              value={country ?? ""}
              onChange={(event) => onCountryChange(event.target.value === "" ? null : event.target.value)}
            >
              <option value="">{country === null ? "全部国家" : "清除国家筛选"}</option>
              {selectedCountryIsMissing ? (
                <option value={country ?? ""}>{formatCountryName(country ?? "")}</option>
              ) : null}
              {countryFacets.map((facet) => (
                <option key={facet.country_code} value={facet.country_code}>
                  {formatCountryName(facet.country_code)} · {formatMediaCount(facet.article_count)}
                </option>
              ))}
            </select>
          </label>

          <label htmlFor="media-evidence-topic">
            <span>议题分面</span>
            <select
              id="media-evidence-topic"
              name="topic_id"
              value={selectedTopic?.id ?? ""}
              onChange={(event) => onTopicChange(event.target.value)}
            >
              <option value="">
                {selectedTopic === null ? "全部议题" : "清除议题筛选"}
              </option>
              {selectedTopicIsMissing ? (
                <option value={selectedTopic?.id ?? ""}>{selectedTopic?.name}</option>
              ) : null}
              {topicFacets.map((facet) => (
                <option
                  key={facet.topic_id ?? "unclassified"}
                  value={facet.topic_id ?? ""}
                  disabled={facet.topic_id === null}
                >
                  {facet.topic} · {formatMediaCount(facet.article_count)}
                  {facet.topic_id === null ? "（无稳定议题 ID）" : ""}
                </option>
              ))}
            </select>
          </label>

          <div className="evidence-filter-actions">
            <button
              className="button button-primary"
              type="submit"
              disabled={hasInvalidQueryLength}
            >
              更新证据流
            </button>
            <button className="button button-secondary" type="button" onClick={onClear}>
              清除条件
            </button>
          </div>
        </form>

        <details className="evidence-diagnostics">
          <summary>接口与数据诊断</summary>
          <code>GET /api/v2/media/articles</code>
          <p>文章、分页和分面在进入界面前均通过运行时契约校验；请求失败时不会伪造结果。</p>
        </details>
      </div>
    </aside>
  );
}

function EvidenceInspector({
  appliedQuery,
  country,
  countryFacets,
  response,
  selectedTopic,
  topicFacets,
  onCountrySelect,
  onTopicSelect,
}: EvidenceInspectorProps): JSX.Element {
  const visibleCountries = countryFacets.slice(0, 6);
  const visibleTopics = topicFacets.slice(0, 8);

  return (
    <aside className="evidence-inspector" aria-labelledby="evidence-inspector-title">
      <div className="evidence-inspector-heading">
        <strong id="evidence-inspector-title">当前观察切面</strong>
        <span>{response === null ? "等待接口" : `${formatMediaCount(response.total)} 篇记录`}</span>
      </div>

      <dl className="evidence-active-filters">
        <div>
          <dt>关键词</dt>
          <dd>{appliedQuery ?? "不限"}</dd>
        </div>
        <div>
          <dt>国家</dt>
          <dd>{country === null ? "不限" : formatCountryName(country)}</dd>
        </div>
        <div>
          <dt>议题</dt>
          <dd>{selectedTopic?.name ?? "不限"}</dd>
        </div>
      </dl>

      <section className="evidence-facet-section" aria-labelledby="country-facets-title">
        <div className="evidence-facet-heading">
          <h3 id="country-facets-title">高频国家</h3>
          <span>当前查询</span>
        </div>
        {visibleCountries.length === 0 ? (
          <p className="evidence-inspector-empty">接口尚未返回可用国家分面。</p>
        ) : (
          <ul className="evidence-facet-list">
            {visibleCountries.map((facet) => (
              <li key={facet.country_code}>
                <button
                  type="button"
                  aria-pressed={country === facet.country_code}
                  onClick={() => onCountrySelect(facet.country_code)}
                >
                  <span>{formatCountryName(facet.country_code)}</span>
                  <small>{formatMediaCount(facet.article_count)}</small>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="evidence-facet-section" aria-labelledby="topic-facets-title">
        <div className="evidence-facet-heading">
          <h3 id="topic-facets-title">高频议题</h3>
          <span>当前查询</span>
        </div>
        {visibleTopics.length === 0 ? (
          <p className="evidence-inspector-empty">接口尚未返回可用议题分面。</p>
        ) : (
          <ul className="evidence-facet-list">
            {visibleTopics.map((facet) => (
              <li key={facet.topic_id ?? `unclassified-${facet.topic}`}>
                {facet.topic_id === null ? (
                  <div className="evidence-facet-unavailable">
                    <span>{facet.topic}</span>
                    <small>{formatMediaCount(facet.article_count)} · 无稳定 ID</small>
                  </div>
                ) : (
                  <button
                    type="button"
                    aria-pressed={selectedTopic?.id === facet.topic_id}
                    onClick={() => onTopicSelect(facet)}
                  >
                    <span>{facet.topic}</span>
                    <small>{formatMediaCount(facet.article_count)}</small>
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="evidence-boundary" aria-labelledby="evidence-boundary-title">
        <h3 id="evidence-boundary-title">如何读取这些证据</h3>
        <ul>
          <li>这里只呈现已采集文章，不代表全网或全国完整覆盖。</li>
          <li>国家和议题来自文章记录字段，不等同于事实结论。</li>
          <li>标题与摘要用于定位线索，判断前应打开来源原文核验。</li>
        </ul>
      </section>
    </aside>
  );
}

export function MediaPage(): JSX.Element {
  const [draftQuery, setDraftQuery] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [country, setCountry] = useState<string | null>(null);
  const [selectedTopic, setSelectedTopic] = useState<SelectedTopic | null>(null);
  const [page, setPage] = useState<number>(1);
  const [filtersExpanded, setFiltersExpanded] = useState<boolean>(false);
  const query = useMemo<MediaArticlesQuery>(
    () => ({
      q: appliedQuery,
      country,
      topicId: selectedTopic?.id ?? null,
      page,
      pageSize: articlesPerPage,
    }),
    [appliedQuery, country, page, selectedTopic],
  );
  const { state, reload } = useMediaArticles(query);
  const response = currentData(state);
  const countryFacets = response?.facets.countries ?? [];
  const topicFacets = response?.facets.topics ?? [];
  const selectedCountryIsMissing =
    country !== null && !countryFacets.some((facet) => facet.country_code === country);
  const selectedTopicIsMissing =
    selectedTopic !== null &&
    !topicFacets.some((facet) => facet.topic_id === selectedTopic.id);
  const totalPages = response === null
    ? 1
    : Math.max(1, Math.ceil(response.total / response.page_size));
  const isUpdating = state.status === "loading" && response !== null;
  const activeFilterCount = Number(appliedQuery !== null)
    + Number(country !== null)
    + Number(selectedTopic !== null);

  const submitSearch = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const normalizedQuery = draftQuery.trim();
    if (normalizedQuery.length === 1) {
      return;
    }
    setAppliedQuery(normalizedQuery === "" ? null : normalizedQuery);
    setPage(1);
    setFiltersExpanded(false);
  };

  const clearFilters = (): void => {
    setDraftQuery("");
    setAppliedQuery(null);
    setCountry(null);
    setSelectedTopic(null);
    setPage(1);
  };

  const changeCountry = (nextCountry: string | null): void => {
    setCountry(nextCountry);
    setPage(1);
  };

  const selectCountryFacet = (nextCountry: string): void => {
    setCountry(country === nextCountry ? null : nextCountry);
    setPage(1);
  };

  const changeTopic = (topicId: string): void => {
    if (topicId === "") {
      setSelectedTopic(null);
      setPage(1);
      return;
    }

    const facet = topicFacets.find((candidate) => candidate.topic_id === topicId);
    if (facet === undefined) {
      throw new Error(`Selected topic_id ${topicId} is absent from validated facets`);
    }

    setSelectedTopic({ id: topicId, name: facet.topic });
    setPage(1);
  };

  const selectTopicFacet = (facet: MediaTopicFacet): void => {
    if (facet.topic_id === null) {
      throw new Error(`Topic facet ${facet.topic} cannot be selected because it has no stable topic_id`);
    }

    setSelectedTopic(
      selectedTopic?.id === facet.topic_id
        ? null
        : { id: facet.topic_id, name: facet.topic },
    );
    setPage(1);
  };

  return (
    <div className="media-page evidence-lens">
      <header className="evidence-lens-header" aria-labelledby="media-page-title">
        <div className="evidence-lens-stage">
          <span>Decision Workspace · 媒体证据</span>
          <strong>现实证据</strong>
        </div>
        <div className="evidence-lens-title">
          <h2 id="media-page-title">Evidence Lens</h2>
          <p>从已采集的媒体报道中定位企业与政策线索。先读来源，再把可核验事实带入企业档案和世界模型。</p>
        </div>
        <div className="evidence-lens-boundary">
          <strong>边界</strong>
          <p>这里是报道索引与原文入口，不是对事件真伪、企业影响或未来走势的自动结论。</p>
        </div>
      </header>

      <div className="evidence-lens-workbench">
        <EvidenceQueryRail
          activeFilterCount={activeFilterCount}
          country={country}
          countryFacets={countryFacets}
          draftQuery={draftQuery}
          filtersExpanded={filtersExpanded}
          selectedCountryIsMissing={selectedCountryIsMissing}
          selectedTopic={selectedTopic}
          selectedTopicIsMissing={selectedTopicIsMissing}
          topicFacets={topicFacets}
          onClear={clearFilters}
          onCountryChange={changeCountry}
          onDraftQueryChange={setDraftQuery}
          onFiltersExpandedChange={setFiltersExpanded}
          onSubmit={submitSearch}
          onTopicChange={changeTopic}
        />

        <section className="evidence-stream" aria-labelledby="article-results-title">
          <div className="evidence-stream-heading">
            <div>
              <span>按发布时间读取</span>
              <h2 id="article-results-title">报道证据流</h2>
            </div>
            <p aria-live="polite">
              {response === null
                ? "等待接口返回"
                : `${formatMediaCount(response.total)} 篇 · 第 ${response.page} / ${totalPages} 页`}
            </p>
          </div>

          {state.status === "error" ? (
            <ApiErrorPanel
              title="无法读取媒体报道"
              error={state.error}
              isRetrying={state.isRetrying}
              onRetry={reload}
            />
          ) : null}

          {state.status === "loading" && response === null ? <ArticlesSkeleton /> : null}
          {response === null ? null : (
            <ArticleResults response={response} isUpdating={isUpdating} />
          )}

          <nav className="pagination" aria-label="媒体报道分页">
            <button
              className="button button-secondary"
              type="button"
              disabled={page <= 1 || state.status === "loading"}
              onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))}
            >
              上一页
            </button>
            <span aria-live="polite">
              第 {response?.page ?? page} / {totalPages} 页
            </span>
            <button
              className="button button-secondary"
              type="button"
              disabled={page >= totalPages || state.status === "loading" || response === null}
              onClick={() => setPage((currentPage) => currentPage + 1)}
            >
              下一页
            </button>
          </nav>
        </section>

        <EvidenceInspector
          appliedQuery={appliedQuery}
          country={country}
          countryFacets={countryFacets}
          response={response}
          selectedTopic={selectedTopic}
          topicFacets={topicFacets}
          onCountrySelect={selectCountryFacet}
          onTopicSelect={selectTopicFacet}
        />
      </div>
    </div>
  );
}
