import { lazy, Suspense, useMemo, useState, type FormEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { MediaArticleRow } from "./MediaArticleRow";
import { MediaSourceDossier } from "./MediaSourceDossier";
import { MediaSyncFreshness } from "./MediaSyncFreshness";
import { MediaTopicDirectory } from "./MediaTopicDirectory";
import type {
  MediaArticle,
  MediaArticlesQuery,
  MediaArticlesResponse,
  MediaCountryFacet,
  MediaTopicFacet,
  MediaTopicSummary,
} from "./mediaContracts";
import { createWorldHash } from "./worldRoute";
import type { MediaSourceSummary } from "./mediaSourceContracts";
import { formatCountryName, formatMediaCount } from "./mediaPresentation";
import type { MediaLens, MediaRoute } from "./mediaRoute";
import {
  useMediaArticles,
  type MediaArticlesLoadState,
} from "./useMediaArticles";
import "./mediaEvidence.css";
import "./mediaSourceDossier.css";

const articlesPerPage = 20;

const MediaTopicObservatory = lazy(async () => {
  const module = await import("./MediaTopicObservatory");

  return { default: module.MediaTopicObservatory };
});

const MediaSourceHealthPanel = lazy(async () => {
  const module = await import("./MediaSourceHealthPanel");

  return { default: module.MediaSourceHealthPanel };
});

const lensPresentation: Readonly<
  Record<MediaLens, { readonly eyebrow: string; readonly title: string; readonly status: string }>
> = {
  articles: {
    eyebrow: "按发布时间读取",
    title: "报道证据流",
    status: "报道目录",
  },
  topic: {
    eyebrow: "按观测窗口读取",
    title: "议题演化",
    status: "议题时间线",
  },
  sources: {
    eyebrow: "按采集来源读取",
    title: "来源证据档案",
    status: "来源目录、采集状态与报道证据",
  },
};

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
  readonly onDirectoryTopicSelect: (topic: MediaTopicSummary | null) => void;
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

function TopicEvolutionPrompt({
  onOpenDirectory,
}: {
  readonly onOpenDirectory: () => void;
}): JSX.Element {
  return (
    <div className="topic-evolution-prompt" role="region" aria-label="议题演化引导">
      <span>Topic Observatory</span>
      <strong>先选择一个有稳定 ID 的议题</strong>
      <p>
        从右侧完整议题目录明确选择后，这里会读取真实时间线，并用同一个 ID 筛选报道证据。未选择议题时不会请求或生成趋势数据。
      </p>
      <button className="button button-secondary" type="button" onClick={onOpenDirectory}>
        浏览完整议题目录
      </button>
    </div>
  );
}

function TopicObservatoryFallback(): JSX.Element {
  return (
    <div className="topic-observatory-lazy-loading" role="status" aria-live="polite">
      <span className="sr-only">正在加载议题演化视图</span>
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
    </div>
  );
}

function SourceHealthFallback(): JSX.Element {
  return (
    <div className="topic-observatory-lazy-loading" role="status" aria-live="polite">
      <span className="sr-only">正在加载媒体源健康目录</span>
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
    </div>
  );
}

function ArticleResults({
  response,
  isUpdating,
  onSendToWorld,
}: {
  readonly response: MediaArticlesResponse;
  readonly isUpdating: boolean;
  readonly onSendToWorld: (article: MediaArticle) => void;
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
          <MediaArticleRow key={article.id} article={article} onSendToWorld={onSendToWorld} />
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
              placeholder="事件、人物或议题"
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
  onDirectoryTopicSelect,
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

      <MediaTopicDirectory
        selectedTopicId={selectedTopic?.id ?? null}
        onSelect={onDirectoryTopicSelect}
      />

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

function unresolvedTopicName(topicId: string): string {
  return `议题 ${topicId.slice(0, 8)}…（待核验）`;
}

export function MediaPage({
  route,
  onRouteChange,
}: {
  readonly route: MediaRoute;
  readonly onRouteChange: (route: MediaRoute) => void;
}): JSX.Element {
  const [draftQuery, setDraftQuery] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [knownTopicNames, setKnownTopicNames] = useState<Readonly<Record<string, string>>>({});
  const [page, setPage] = useState<number>(1);
  const [sourceEvidencePage, setSourceEvidencePage] = useState<number>(1);
  const [filtersExpanded, setFiltersExpanded] = useState<boolean>(false);
  const query = useMemo<MediaArticlesQuery>(
    () => ({
      q: appliedQuery,
      country: route.country,
      topicId: route.topicId,
      page,
      pageSize: articlesPerPage,
    }),
    [appliedQuery, page, route.country, route.topicId],
  );
  const { state, reload } = useMediaArticles(query);
  const response = currentData(state);
  const countryFacets = response?.facets.countries ?? [];
  const topicFacets = response?.facets.topics ?? [];
  const selectedTopicFacet = route.topicId === null
    ? null
    : topicFacets.find((facet) => facet.topic_id === route.topicId) ?? null;
  const selectedTopic = route.topicId === null
    ? null
    : {
        id: route.topicId,
        name: selectedTopicFacet?.topic
          ?? knownTopicNames[route.topicId]
          ?? unresolvedTopicName(route.topicId),
      };
  const selectedCountryIsMissing =
    route.country !== null
    && !countryFacets.some((facet) => facet.country_code === route.country);
  const selectedTopicIsMissing =
    selectedTopic !== null &&
    !topicFacets.some((facet) => facet.topic_id === selectedTopic.id);
  const totalPages = response === null
    ? 1
    : Math.max(1, Math.ceil(response.total / response.page_size));
  const isUpdating = state.status === "loading" && response !== null;
  const activeFilterCount = Number(appliedQuery !== null)
    + Number(route.country !== null)
    + Number(selectedTopic !== null);
  const activeLens = lensPresentation[route.lens];

  const rememberTopicName = (topicId: string, topicName: string): void => {
    setKnownTopicNames((currentNames) => currentNames[topicId] === topicName
      ? currentNames
      : { ...currentNames, [topicId]: topicName });
  };

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
    onRouteChange({ ...route, topicId: null, country: null });
    setPage(1);
  };

  const changeCountry = (nextCountry: string | null): void => {
    onRouteChange({ ...route, country: nextCountry });
    setPage(1);
  };

  const selectCountryFacet = (nextCountry: string): void => {
    onRouteChange({
      ...route,
      country: route.country === nextCountry ? null : nextCountry,
    });
    setPage(1);
  };

  const changeTopic = (topicId: string): void => {
    if (topicId === "") {
      onRouteChange({ ...route, topicId: null });
      setPage(1);
      return;
    }

    const facet = topicFacets.find((candidate) => candidate.topic_id === topicId);
    if (facet === undefined) {
      throw new Error(`Selected topic_id ${topicId} is absent from validated facets`);
    }

    rememberTopicName(topicId, facet.topic);
    onRouteChange({ ...route, topicId });
    setPage(1);
  };

  const selectTopicFacet = (facet: MediaTopicFacet): void => {
    if (facet.topic_id === null) {
      throw new Error(`Topic facet ${facet.topic} cannot be selected because it has no stable topic_id`);
    }

    rememberTopicName(facet.topic_id, facet.topic);
    onRouteChange({
      ...route,
      topicId: selectedTopic?.id === facet.topic_id ? null : facet.topic_id,
    });
    setPage(1);
  };

  const selectDirectoryTopic = (topic: MediaTopicSummary | null): void => {
    if (topic === null) {
      onRouteChange({ ...route, topicId: null, sourceId: null, lens: "topic" });
    } else {
      rememberTopicName(topic.id, topic.topic);
      onRouteChange({
        topicId: topic.id,
        sourceId: null,
        lens: "topic",
        country: route.country,
      });
    }
    setPage(1);
  };

  const openTopicDirectory = (): void => {
    const directory = document.getElementById("media-topic-directory");
    if (!(directory instanceof HTMLElement)) {
      throw new Error("Media topic directory is not mounted.");
    }
    directory.focus({ preventScroll: true });
    directory.scrollIntoView({ block: "start" });
  };

  const selectSource = (source: MediaSourceSummary): void => {
    onRouteChange({ topicId: null, sourceId: source.id, lens: "sources", country: null });
    setSourceEvidencePage(1);
  };

  const sendArticleToWorld = (article: MediaArticle): void => {
    window.location.hash = createWorldHash({
      worldModelId: null,
      snapshotId: null,
      evidenceId: article.id,
    });
  };

  return (
    <div className="media-page evidence-lens">
      <header
        className="evidence-lens-header evidence-lens-header--with-sync"
        aria-labelledby="media-page-title"
      >
        <div className="evidence-lens-stage">
          <span>Decision Workspace · 媒体证据</span>
          <strong>现实证据</strong>
        </div>
        <div className="evidence-lens-title">
          <h2 id="media-page-title">Evidence Lens</h2>
          <p>从已采集的媒体报道中定位事件与政策线索。先读来源，再把可核验事实带入世界快照。</p>
        </div>
        <div className="evidence-lens-boundary">
          <strong>边界</strong>
          <p>这里是报道索引与原文入口，不是对事件真伪、现实影响或未来走势的自动结论。</p>
        </div>
        <MediaSyncFreshness />
      </header>

      <div className="evidence-lens-workbench">
        <EvidenceQueryRail
          activeFilterCount={activeFilterCount}
          country={route.country}
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

        <section className="evidence-stream" aria-labelledby="evidence-stream-title">
          <div className="evidence-stream-heading">
            <div>
              <span>{activeLens.eyebrow}</span>
              <h2 id="evidence-stream-title">{activeLens.title}</h2>
            </div>
            <div className="evidence-stream-controls">
              <div className="evidence-center-lenses" role="group" aria-label="中心观察镜头">
                <button
                  type="button"
                  aria-pressed={route.lens === "articles"}
                  onClick={() => onRouteChange({ ...route, sourceId: null, lens: "articles" })}
                >
                  报道证据流
                </button>
                <button
                  type="button"
                  aria-pressed={route.lens === "topic"}
                  onClick={() => onRouteChange({ ...route, sourceId: null, lens: "topic" })}
                >
                  议题演化
                </button>
                <button
                  type="button"
                  aria-pressed={route.lens === "sources"}
                  onClick={() => onRouteChange({
                    topicId: null,
                    sourceId: route.lens === "sources" ? route.sourceId : null,
                    lens: "sources",
                    country: null,
                  })}
                >
                  来源档案
                </button>
              </div>
              <p aria-live="polite">
                {route.lens === "articles"
                  ? response === null
                    ? "等待接口返回"
                    : `${formatMediaCount(response.total)} 篇 · 第 ${response.page} / ${totalPages} 页`
                  : route.lens === "topic" && selectedTopic === null
                    ? "需要稳定议题 ID"
                    : route.lens === "topic" && selectedTopic !== null
                      ? `${selectedTopic.name} · ${route.country === null ? "跨国家聚合" : formatCountryName(route.country)}`
                      : activeLens.status}
              </p>
            </div>
          </div>

          {route.lens === "articles" ? (
            <div id="article-evidence-view">
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
                <ArticleResults
                  response={response}
                  isUpdating={isUpdating}
                  onSendToWorld={sendArticleToWorld}
                />
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
            </div>
          ) : route.lens === "topic" ? (
            <div id="topic-evolution-view">
              {selectedTopic === null ? (
                <TopicEvolutionPrompt onOpenDirectory={openTopicDirectory} />
              ) : (
                <Suspense fallback={<TopicObservatoryFallback />}>
                  <MediaTopicObservatory
                    topicId={selectedTopic.id}
                    topicName={selectedTopic.name}
                    country={route.country}
                  />
                </Suspense>
              )}
            </div>
          ) : (
            <div id="media-source-health-view">
              <Suspense fallback={<SourceHealthFallback />}>
                <MediaSourceDossier
                  sourceId={route.sourceId}
                  page={sourceEvidencePage}
                  onPageChange={setSourceEvidencePage}
                />
                <MediaSourceHealthPanel
                  selectedSourceId={route.sourceId}
                  onSelectSource={selectSource}
                />
              </Suspense>
            </div>
          )}
        </section>

        <EvidenceInspector
          appliedQuery={appliedQuery}
          country={route.country}
          countryFacets={countryFacets}
          response={response}
          selectedTopic={selectedTopic}
          topicFacets={topicFacets}
          onCountrySelect={selectCountryFacet}
          onDirectoryTopicSelect={selectDirectoryTopic}
          onTopicSelect={selectTopicFacet}
        />
      </div>
    </div>
  );
}
