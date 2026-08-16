import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type { SectionId } from "./domain";
import { MediaArticleRow } from "./MediaArticleRow";
import type { MediaCountryNode, MediaOverview } from "./mediaContracts";
import {
  formatCountryName,
  formatMediaCount,
  formatMediaTimestamp,
} from "./mediaPresentation";
import type { CapabilityDescriptor } from "./systemCapabilities";
import { useMediaOverview } from "./useMediaOverview";
import {
  useMediaPropagation,
  type MediaPropagationLoadState,
} from "./useMediaPropagation";
import {
  useSystemCapabilities,
  type SystemCapabilitiesLoadState,
} from "./useSystemCapabilities";
import "./situationHome.css";

export interface OverviewPageProps {
  readonly onNavigate: (sectionId: SectionId) => void;
  readonly onOpenMediaTopic: (topicId: string) => void;
}

interface DecisionPathStep {
  readonly code: string;
  readonly label: string;
  readonly title: string;
}

const MediaGlobe = lazy(async () => {
  const module = await import("./MediaGlobe");

  return { default: module.MediaGlobe };
});

const MediaWorldMap = lazy(async () => {
  const module = await import("./MediaWorldMap");

  return { default: module.MediaWorldMap };
});

type WorldLens = "globe" | "map" | "propagation";

const decisionPathSteps: readonly DecisionPathStep[] = [
  { code: "01", label: "Evidence", title: "媒体证据" },
  { code: "02", label: "World Snapshot", title: "冻结现实" },
  { code: "03", label: "Scenario", title: "决策实验" },
  { code: "04", label: "Run", title: "推演运行" },
];

const capabilityStateLabels: Readonly<
  Record<CapabilityDescriptor["state"], string>
> = {
  contract_ready: "仅契约就绪",
  runtime_ready: "运行链路就绪",
};

function CapabilityRow({
  capability,
}: {
  readonly capability: CapabilityDescriptor;
}): JSX.Element {
  return (
    <li className="capability-row">
      <div className="capability-system">
        <span className="capability-index" aria-hidden="true">
          {capability.name.slice(0, 2).toUpperCase()}
        </span>
        <span>
          <strong>{capability.name}</strong>
          <small>Source · {capability.source}</small>
        </span>
      </div>
      <p>{capability.contracts.join(" · ")}</p>
      <span className="status-badge" data-status={capability.state}>
        <span aria-hidden="true" />
        {capabilityStateLabels[capability.state]}
      </span>
    </li>
  );
}

function CapabilitySkeleton(): JSX.Element {
  return (
    <div
      className="capability-loading"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">正在从 V2 后端读取能力状态</span>
      {Array.from({ length: 4 }, (_, index) => (
        <div
          className="capability-row capability-skeleton-row"
          aria-hidden="true"
          key={index}
        >
          <span className="skeleton-block skeleton-system" />
          <span className="skeleton-block skeleton-contracts" />
          <span className="skeleton-block skeleton-status" />
        </div>
      ))}
    </div>
  );
}

function CapabilityContent({
  state,
  onReload,
}: {
  readonly state: SystemCapabilitiesLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  if (state.status === "loading") {
    return <CapabilitySkeleton />;
  }

  if (state.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取后端能力状态"
        error={state.error}
        isRetrying={state.isRetrying}
        onRetry={onReload}
      />
    );
  }

  return (
    <div className="capability-success" role="status" aria-live="polite">
      <div className="capability-contract-meta">
        <span>{state.data.product}</span>
        <code>API {state.data.api_version}</code>
      </div>
      <ul className="capability-list">
        {state.data.capabilities.map((capability) => (
          <CapabilityRow key={capability.name} capability={capability} />
        ))}
      </ul>
    </div>
  );
}

function OverviewSkeleton(): JSX.Element {
  return (
    <div
      className="situation-home__loading"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">正在读取媒体态势</span>
      <span className="skeleton-block situation-home__loading-globe" aria-hidden="true" />
      <span className="skeleton-block situation-home__loading-ledger" aria-hidden="true" />
      <span className="skeleton-block situation-home__loading-topics" aria-hidden="true" />
    </div>
  );
}

function selectedNode(
  overview: MediaOverview,
  selectedCountry: string | null,
): MediaCountryNode | null {
  if (selectedCountry === null) {
    return null;
  }

  return overview.country_nodes.find((node) => node.country_code === selectedCountry) ?? null;
}

function CoverageLedger({ overview }: { readonly overview: MediaOverview }): JSX.Element {
  return (
    <dl className="situation-home__ledger" aria-label="媒体采集概况">
      <div>
        <dt>媒体来源</dt>
        <dd>{formatMediaCount(overview.source_count)}</dd>
      </div>
      <div>
        <dt>24 小时报道</dt>
        <dd>{formatMediaCount(overview.article_count)}</dd>
      </div>
      <div>
        <dt>识别议题</dt>
        <dd>{formatMediaCount(overview.topic_count)}</dd>
      </div>
      <div className="situation-home__ledger-time">
        <dt>统计更新时间</dt>
        <dd>
          <time dateTime={overview.generated_at}>
            {formatMediaTimestamp(overview.generated_at)}
          </time>
        </dd>
      </div>
    </dl>
  );
}

function HotTopics({
  overview,
  onOpenTopic,
}: {
  readonly overview: MediaOverview;
  readonly onOpenTopic: (topicId: string) => void;
}): JSX.Element {
  const maximumCount = Math.max(
    1,
    overview.hot_topics.reduce(
      (maximum, topic) => Math.max(maximum, topic.article_count),
      0,
    ),
  );

  if (overview.hot_topics.length === 0) {
    return (
      <div className="situation-home__empty compact" role="status">
        <strong>尚无热点议题</strong>
        <p>接口未返回当前统计窗口的议题聚合。</p>
      </div>
    );
  }

  return (
    <ol className="situation-home__topics-list">
      {overview.hot_topics.map((topic, index) => {
        const topicId = topic.topic_id;

        return (
          <li key={topicId ?? "unclassified"}>
            <span className="situation-home__topic-rank">
              {String(index + 1).padStart(2, "0")}
            </span>
            {topicId === null ? (
              <div className="situation-home__topic-copy">
                <strong>{topic.topic}</strong>
                <progress max={maximumCount} value={topic.article_count}>
                  {topic.article_count} / {maximumCount}
                </progress>
              </div>
            ) : (
              <button
                className="situation-home__topic-copy situation-home__topic-link"
                type="button"
                aria-label={`打开议题演化：${topic.topic}`}
                onClick={() => onOpenTopic(topicId)}
              >
                <strong>{topic.topic}</strong>
                <progress max={maximumCount} value={topic.article_count}>
                  {topic.article_count} / {maximumCount}
                </progress>
              </button>
            )}
            <span>{formatMediaCount(topic.article_count)}</span>
          </li>
        );
      })}
    </ol>
  );
}

function SituationIntro({
  onNavigate,
}: {
  readonly onNavigate: (sectionId: SectionId) => void;
}): JSX.Element {
  return (
    <header className="situation-home__intro">
      <div className="situation-home__signal">
        <span aria-hidden="true" />
        媒体证据场
      </div>
      <h1 id="situation-home-title">从正在发生的事实，进入下一步决策</h1>
      <p>
        先看真实报道正在聚焦哪里，再将可追溯证据冻结为世界快照并带入决策实验。
      </p>
      <div className="situation-home__actions">
        <button
          className="button situation-home__button-primary"
          type="button"
          onClick={() => onNavigate("world")}
        >
          进入 Decision Workspace
          <span aria-hidden="true">→</span>
        </button>
        <button
          className="button situation-home__button-secondary"
          type="button"
          onClick={() => onNavigate("media")}
        >
          检索媒体证据
        </button>
      </div>
    </header>
  );
}

function SituationScene({
  overview,
  selectedCountry,
  onSelectCountry,
  propagationState,
  onOpenTopic,
}: {
  readonly overview: MediaOverview;
  readonly selectedCountry: string | null;
  readonly onSelectCountry: (countryCode: string | null) => void;
  readonly propagationState: MediaPropagationLoadState;
  readonly onOpenTopic: (topicId: string) => void;
}): JSX.Element {
  const [worldLens, setWorldLens] = useState<WorldLens>("globe");
  const activeNode = selectedNode(overview, selectedCountry);
  const overviewIsEmpty =
    overview.source_count === 0 &&
    overview.article_count === 0 &&
    overview.topic_count === 0 &&
    overview.country_nodes.length === 0 &&
    overview.hot_topics.length === 0 &&
    overview.latest_articles.length === 0;

  return (
    <div className="situation-home__scene">
      <div className="situation-home__world-lens" aria-label="全球报道分布">
        <div className="situation-home__lens-switch" role="group" aria-label="世界视图">
          <button
            type="button"
            aria-pressed={worldLens === "globe"}
            onClick={() => setWorldLens("globe")}
          >
            3D 地球
          </button>
          <button
            type="button"
            aria-pressed={worldLens === "map"}
            onClick={() => setWorldLens("map")}
          >
            平面热力
          </button>
          <button
            type="button"
            aria-pressed={worldLens === "propagation"}
            onClick={() => setWorldLens("propagation")}
          >
            传播链
          </button>
        </div>
        <div className="situation-home__world-viewport">
          <Suspense
            fallback={
              <div className="media-globe-loading" role="status">
                正在加载世界视图…
              </div>
            }
          >
            {worldLens === "globe" ? (
              <MediaGlobe
                nodes={overview.country_nodes}
                selectedCountry={selectedCountry}
                onSelect={onSelectCountry}
              />
            ) : worldLens === "map" ? (
              <MediaWorldMap
                nodes={overview.country_nodes}
                mode="heat"
                propagationEvents={[]}
                selectedCountry={selectedCountry}
                onSelect={onSelectCountry}
              />
            ) : propagationState.status === "success" ? (
              <MediaWorldMap
                nodes={overview.country_nodes}
                mode="propagation"
                propagationEvents={propagationState.data.items}
                selectedCountry={selectedCountry}
                onSelect={onSelectCountry}
              />
            ) : (
              <div className="media-globe-loading" role="status">
                {propagationState.status === "loading"
                  ? "正在读取真实传播链…"
                  : `传播链读取失败：${propagationState.error.message}`}
              </div>
            )}
          </Suspense>
        </div>
      </div>

      <CoverageLedger overview={overview} />

      <aside className="situation-home__topics" aria-labelledby="situation-topics-title">
        <div className="situation-home__topics-heading">
          <div>
            <span>Topic Pulse</span>
            <h2 id="situation-topics-title">热点议题</h2>
          </div>
          <strong>{overview.hot_topics.length}</strong>
        </div>
        <HotTopics overview={overview} onOpenTopic={onOpenTopic} />
      </aside>

      <div className="situation-home__country-focus" aria-live="polite">
        {activeNode === null ? (
          <>
            <span className="situation-home__focus-code" aria-hidden="true">—</span>
            <div>
              <strong>选择国家热点</strong>
              <p>点击地球节点或使用国家列表，核对该地区的报道规模与主导议题。</p>
            </div>
          </>
        ) : (
          <>
            <span className="situation-home__focus-code">{activeNode.country_code}</span>
            <div>
              <strong>{formatCountryName(activeNode.country_code)}</strong>
              <p>
                {formatMediaCount(activeNode.article_count)} 篇报道 · {activeNode.topic}
              </p>
            </div>
          </>
        )}
      </div>

      {overviewIsEmpty ? (
        <div className="situation-home__zero-data" role="status">
          <strong>当前统计窗口没有媒体数据</strong>
          <p>概览接口已成功返回，但来源、报道、议题和国家热点均为空。</p>
        </div>
      ) : null}
    </div>
  );
}

function DecisionPath(): JSX.Element {
  return (
    <section className="situation-home__path" aria-labelledby="decision-path-title">
      <header>
        <div>
          <h2 id="decision-path-title">一条从证据到运行的决策链路</h2>
          <p>阶段仅表示产品工作路径，不代表当前任务已经完成。</p>
        </div>
        <span>Evidence → Decision → Run</span>
      </header>
      <ol>
        {decisionPathSteps.map((step) => (
          <li key={step.code}>
            <span>{step.code}</span>
            <div>
              <strong>{step.title}</strong>
              <small>{step.label}</small>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function LatestEvidence({
  overview,
  onNavigate,
}: {
  readonly overview: MediaOverview;
  readonly onNavigate: (sectionId: SectionId) => void;
}): JSX.Element {
  return (
    <section className="situation-home__evidence" aria-labelledby="latest-evidence-title">
      <header>
        <div>
          <span>Latest Evidence</span>
          <h2 id="latest-evidence-title">最新可核验报道</h2>
          <p>保留来源、发布时间、摘录与原文入口。</p>
        </div>
        <button
          className="button situation-home__evidence-link"
          type="button"
          onClick={() => onNavigate("media")}
        >
          打开完整证据库
          <span aria-hidden="true">→</span>
        </button>
      </header>

      {overview.latest_articles.length === 0 ? (
        <div className="situation-home__evidence-empty" role="status">
          <strong>尚无最新报道</strong>
          <p>接口未返回当前统计窗口的文章。</p>
        </div>
      ) : (
        <div className="situation-home__evidence-list" tabIndex={0} aria-label="最新报道横向列表">
          {overview.latest_articles.map((article) => (
            <MediaArticleRow key={article.id} article={article} />
          ))}
        </div>
      )}
    </section>
  );
}

export function OverviewPage({ onNavigate, onOpenMediaTopic }: OverviewPageProps): JSX.Element {
  const { state: mediaState, reload: reloadMedia } = useMediaOverview();
  const propagationState = useMediaPropagation();
  const { state: capabilitiesState, reload: reloadCapabilities } = useSystemCapabilities();
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const capabilityTitle = useRef<HTMLHeadingElement>(null);
  const previousCapabilitiesStatus = useRef<SystemCapabilitiesLoadState["status"]>(
    capabilitiesState.status,
  );

  const handleSelectCountry = useCallback((countryCode: string | null): void => {
    setSelectedCountry(countryCode);
  }, []);

  useEffect(() => {
    if (
      previousCapabilitiesStatus.current === "error" &&
      capabilitiesState.status === "success"
    ) {
      capabilityTitle.current?.focus();
    }

    previousCapabilitiesStatus.current = capabilitiesState.status;
  }, [capabilitiesState.status]);

  useEffect(() => {
    if (
      mediaState.status === "success" &&
      selectedCountry !== null &&
      !mediaState.data.country_nodes.some((node) => node.country_code === selectedCountry)
    ) {
      setSelectedCountry(null);
    }
  }, [mediaState, selectedCountry]);

  return (
    <div className="overview-page situation-home">
      <section className="situation-home__stage" aria-labelledby="situation-home-title">
        <div className="situation-home__grid" aria-hidden="true" />
        <SituationIntro onNavigate={onNavigate} />

        {mediaState.status === "loading" ? <OverviewSkeleton /> : null}
        {mediaState.status === "error" ? (
          <div className="situation-home__error">
            <ApiErrorPanel
              title="无法读取媒体态势"
              error={mediaState.error}
              isRetrying={mediaState.isRetrying}
              onRetry={reloadMedia}
            />
          </div>
        ) : null}
        {mediaState.status === "success" ? (
          <SituationScene
            overview={mediaState.data}
            selectedCountry={selectedCountry}
            onSelectCountry={handleSelectCountry}
            propagationState={propagationState}
            onOpenTopic={onOpenMediaTopic}
          />
        ) : null}
      </section>

      <DecisionPath />

      {mediaState.status === "success" ? (
        <LatestEvidence overview={mediaState.data} onNavigate={onNavigate} />
      ) : null}

      <details className="engineering-details situation-home__diagnostics">
        <summary>
          <span>
            <strong>系统诊断与能力契约</strong>
            <small>工程状态不代表业务数据可用性</small>
          </span>
          <span aria-hidden="true">展开</span>
        </summary>
        <div className="engineering-details-content">
          <h2 id="capability-title" ref={capabilityTitle} tabIndex={-1}>
            V2 后端能力契约
          </h2>
          <CapabilityContent state={capabilitiesState} onReload={reloadCapabilities} />
        </div>
      </details>
    </div>
  );
}
