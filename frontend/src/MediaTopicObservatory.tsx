import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { init, use, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type {
  MediaFirstUtteranceObservation,
  MediaTopicLatestCountry,
  MediaTopicTimelineQuery,
  MediaTopicTimelineResponse,
} from "./mediaContracts";
import { formatCountryName, formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  buildMediaTopicTimelineChartData,
  type MediaTopicTimelineChartData,
} from "./mediaTopicTimelineChart";
import { useMediaTopicTimeline } from "./useMediaTopicTimeline";
import { useMediaFirstUtterances } from "./useMediaFirstUtterances";
import "./mediaTopicObservatory.css";

use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const timelinePointLimit = 168;
const firstUtteranceLimit = 20;
const axisTimestampFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export interface MediaTopicObservatoryProps {
  readonly topicId: string;
  readonly topicName: string;
  readonly country: string | null;
}

interface TimelineTooltipParameter {
  readonly dataIndex: number;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatScore(score: number): string {
  return score.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatAxisTimestamp(timestamp: string): string {
  return axisTimestampFormatter.format(new Date(timestamp));
}

function timelineTooltip(
  parameters: TimelineTooltipParameter | readonly TimelineTooltipParameter[],
  data: MediaTopicTimelineChartData,
): string {
  const parameter = Array.isArray(parameters) ? parameters[0] : parameters;
  if (parameter === undefined) {
    throw new Error("议题演化图提示框缺少数据索引。");
  }

  const timestamp = data.timestamps[parameter.dataIndex];
  const articleCount = data.articleCounts[parameter.dataIndex];
  const salienceScore = data.salienceScores[parameter.dataIndex];
  const salienceRank = data.salienceRanks[parameter.dataIndex];
  if (
    timestamp === undefined
    || articleCount === undefined
    || salienceScore === undefined
    || salienceRank === undefined
  ) {
    throw new Error(`议题演化图提示框索引越界。dataIndex=${parameter.dataIndex}`);
  }

  return [
    formatMediaTimestamp(timestamp),
    `报道索引 ${formatMediaCount(articleCount)}`,
    `显著度 ${formatScore(salienceScore)}`,
    salienceRank === null ? "显著度排名 跨国家聚合不适用" : `显著度排名 #${salienceRank}`,
  ].join("\n");
}

function TimelineChart({ response }: { readonly response: MediaTopicTimelineResponse }): JSX.Element {
  const chartElement = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<EChartsType | null>(null);
  const data = useMemo(
    () => buildMediaTopicTimelineChartData(response.points),
    [response.points],
  );

  useEffect(() => {
    const element = chartElement.current;
    if (element === null) {
      throw new Error("TimelineChart requires a mounted chart container.");
    }

    const chart = init(element, undefined, { renderer: "canvas" });
    chartInstance.current = chart;
    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(element);

    return () => {
      resizeObserver.disconnect();
      chart.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartInstance.current;
    if (chart === null) {
      throw new Error("TimelineChart cannot render before ECharts initialization.");
    }

    chart.setOption(
      {
        animation: !prefersReducedMotion(),
        backgroundColor: "transparent",
        grid: { top: 30, right: 52, bottom: 52, left: 46, containLabel: false },
        tooltip: {
          trigger: "axis",
          renderMode: "richText",
          borderWidth: 0,
          backgroundColor: "#10212b",
          textStyle: { color: "#e8f5f7", fontSize: 12, lineHeight: 19 },
          formatter: (
            parameters: TimelineTooltipParameter | readonly TimelineTooltipParameter[],
          ): string => timelineTooltip(parameters, data),
        },
        xAxis: {
          type: "category",
          boundaryGap: true,
          data: data.timestamps,
          axisLine: { lineStyle: { color: "rgba(167, 208, 221, 0.22)" } },
          axisTick: { show: false },
          axisLabel: {
            color: "#76939a",
            fontSize: 10,
            hideOverlap: true,
            formatter: (timestamp: string): string => formatAxisTimestamp(timestamp),
          },
        },
        yAxis: [
          {
            type: "value",
            name: "报道索引",
            min: 0,
            max: data.maximumArticleCount === 0 ? 1 : undefined,
            minInterval: 1,
            nameTextStyle: { color: "#76939a", fontSize: 10 },
            axisLabel: { color: "#76939a", fontSize: 10 },
            splitLine: { lineStyle: { color: "rgba(167, 208, 221, 0.08)" } },
          },
          {
            type: "value",
            name: "显著度",
            min: 0,
            max: data.maximumSalienceScore === 0 ? 1 : undefined,
            nameTextStyle: { color: "#76939a", fontSize: 10 },
            axisLabel: { color: "#76939a", fontSize: 10 },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: "article_count",
            type: "bar",
            yAxisIndex: 0,
            data: data.articleCounts,
            barMaxWidth: 11,
            large: data.articleCounts.length > 100,
            itemStyle: { color: "rgba(91, 213, 212, 0.34)", borderColor: "#5bd5d4" },
            emphasis: { itemStyle: { color: "rgba(91, 213, 212, 0.66)" } },
          },
          {
            name: "salience_score",
            type: "line",
            yAxisIndex: 1,
            data: data.salienceScores,
            showSymbol: data.salienceScores.length <= 36,
            symbolSize: 5,
            lineStyle: { color: "#e5a55a", width: 1.8 },
            itemStyle: { color: "#e5a55a" },
          },
        ],
      } as never,
      true,
    );
  }, [data]);

  return (
    <div
      ref={chartElement}
      className="topic-observatory__chart"
      role="img"
      aria-label={`${response.topic}的报道索引与媒体显著度时间线，共 ${response.points.length} 个真实观测窗口`}
    />
  );
}

function TopicTimelineLoading({ topicName }: { readonly topicName: string }): JSX.Element {
  return (
    <div className="topic-observatory__loading" role="status" aria-live="polite">
      <span className="sr-only">正在读取{topicName}的真实议题时间线</span>
      <span className="skeleton-block topic-observatory__loading-title" aria-hidden="true" />
      <span className="skeleton-block topic-observatory__loading-metrics" aria-hidden="true" />
      <span className="skeleton-block topic-observatory__loading-chart" aria-hidden="true" />
    </div>
  );
}

function LatestCountryRow({
  country,
  position,
}: {
  readonly country: MediaTopicLatestCountry;
  readonly position: number;
}): JSX.Element {
  return (
    <li className="topic-observatory__country-row">
      <span className="topic-observatory__country-position" aria-label={`序号 ${position}`}>
        {String(position).padStart(2, "0")}
      </span>
      <div className="topic-observatory__country-name">
        <strong>{formatCountryName(country.country_code)}</strong>
        <span>{country.country_code} · {country.granularity}</span>
      </div>
      <dl>
        <div>
          <dt>报道索引</dt>
          <dd>{formatMediaCount(country.article_count)}</dd>
        </div>
        <div>
          <dt>显著度</dt>
          <dd>{formatScore(country.salience_score)}</dd>
        </div>
        <div>
          <dt>议题排名</dt>
          <dd>#{country.salience_rank}</dd>
        </div>
      </dl>
      <time dateTime={country.window_end}>{formatMediaTimestamp(country.window_end)}</time>
    </li>
  );
}

function FirstUtteranceRow({
  observation,
}: {
  readonly observation: MediaFirstUtteranceObservation;
}): JSX.Element {
  const observedAt = observation.occurred_at ?? observation.article.published_at;
  return (
    <li className="topic-observatory__utterance-row">
      <div className="topic-observatory__utterance-meta">
        <strong>{observation.entity_name}</strong>
        <span>{observation.entity_type} · {observation.country_code} · high confidence</span>
        <time dateTime={observedAt}>
          {formatMediaTimestamp(observedAt)}
          {observation.occurred_at === null ? " · 文章发布时间" : " · 判定发生时间"}
        </time>
      </div>
      <blockquote>{observation.evidence_quote}</blockquote>
      <div className="topic-observatory__utterance-source">
        <a href={observation.article.original_url} target="_blank" rel="noreferrer">
          {observation.article.title}
        </a>
        <span>{observation.article.source_name}</span>
        <code>{observation.model_name} · {observation.prompt_version}</code>
      </div>
    </li>
  );
}

function FirstUtteranceEvidence({ topicId }: { readonly topicId: string }): JSX.Element {
  const { state, reload } = useMediaFirstUtterances(topicId, firstUtteranceLimit);
  if (state.status === "loading") {
    return <div className="topic-observatory__utterance-loading" role="status">正在核验首发证据…</div>;
  }
  if (state.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取首发证据"
        error={state.error}
        isRetrying={state.isRetrying}
        onRetry={reload}
      />
    );
  }
  return (
    <section className="topic-observatory__utterances" aria-labelledby="first-utterances-title">
      <div className="topic-observatory__section-heading">
        <div>
          <span>First-utterance evidence</span>
          <h4 id="first-utterances-title">首发证据观察</h4>
        </div>
        <p>显示 {state.data.items.length} / {state.data.total} 条</p>
      </div>
      {state.data.items.length === 0 ? (
        <div className="topic-observatory__empty compact" role="status">
          <strong>这个议题尚无可核验的首发观察</strong>
          <p>系统不会用模型推理或缺少原文引用的记录补齐。</p>
        </div>
      ) : (
        <ol className="topic-observatory__utterance-list">
          {state.data.items.map((observation) => (
            <FirstUtteranceRow key={observation.id} observation={observation} />
          ))}
        </ol>
      )}
      <div className="topic-observatory__utterance-boundary">
        {state.data.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
      </div>
    </section>
  );
}

function TopicTimelineContent({
  response,
}: {
  readonly response: MediaTopicTimelineResponse;
}): JSX.Element {
  const latestPoint = response.points.at(-1) ?? null;
  const contextLabel = response.selected_country === null
    ? "跨国家聚合"
    : `${formatCountryName(response.selected_country)}切片`;

  return (
    <article className="topic-observatory" aria-labelledby="topic-observatory-title">
      <header className="topic-observatory__header">
        <div>
          <span>{contextLabel} · {response.points.length} 个观测窗口</span>
          <h3 id="topic-observatory-title">{response.topic}</h3>
        </div>
        <p>
          生成于 <time dateTime={response.generated_at}>{formatMediaTimestamp(response.generated_at)}</time>
        </p>
      </header>

      <dl className="topic-observatory__metrics">
        <div>
          <dt>最新报道索引</dt>
          <dd>{latestPoint === null ? "—" : formatMediaCount(latestPoint.article_count)}</dd>
          <small>article_count</small>
        </div>
        <div>
          <dt>最新显著度</dt>
          <dd>{latestPoint === null ? "—" : formatScore(latestPoint.salience_score)}</dd>
          <small>salience_score</small>
        </div>
        <div>
          <dt>最新议题排名</dt>
          <dd>
            {latestPoint?.salience_rank === null || latestPoint === null
              ? "不适用"
              : `#${latestPoint.salience_rank}`}
          </dd>
          <small>{response.selected_country === null ? "聚合不生成排名" : "国家切片排名"}</small>
        </div>
        <div>
          <dt>可见国家覆盖</dt>
          <dd>{response.latest_countries.length} 个</dd>
          <small>最新切片，最多 12 个</small>
        </div>
      </dl>

      <section className="topic-observatory__timeline" aria-labelledby="topic-timeline-title">
        <div className="topic-observatory__section-heading">
          <div>
            <span>Observed timeline</span>
            <h4 id="topic-timeline-title">报道量与显著度</h4>
          </div>
          <div className="topic-observatory__legend" aria-label="图例">
            <span data-series="articles">article_count</span>
            <span data-series="salience">salience_score</span>
          </div>
        </div>
        {response.points.length === 0 ? (
          <div className="topic-observatory__empty" role="status">
            <strong>这个切面还没有时间线观测点</strong>
            <p>接口返回了空 points；系统不会用估算值补齐缺失窗口。</p>
          </div>
        ) : (
          <TimelineChart response={response} />
        )}
      </section>

      <section className="topic-observatory__countries" aria-labelledby="latest-countries-title">
        <div className="topic-observatory__section-heading">
          <div>
            <span>Country coverage</span>
            <h4 id="latest-countries-title">最新国家切片</h4>
          </div>
          <p>按接口显著度顺序 · 最多 12 个</p>
        </div>
        {response.latest_countries.length === 0 ? (
          <div className="topic-observatory__empty compact" role="status">
            <strong>暂无国家切片</strong>
            <p>接口没有返回可验证的 latest_countries。</p>
          </div>
        ) : (
          <ol className="topic-observatory__country-list">
            {response.latest_countries.map((country, index) => (
              <LatestCountryRow
                key={country.country_code}
                country={country}
                position={index + 1}
              />
            ))}
          </ol>
        )}
      </section>

      <FirstUtteranceEvidence topicId={response.topic_id} />

      <section className="topic-observatory__boundary" aria-labelledby="timeline-boundary-title">
        <span>Interpretation boundary</span>
        <h4 id="timeline-boundary-title">解释边界</h4>
        <strong>
          {response.selected_country === null
            ? "跨国家视角是 country-indexed sum，不等于全网唯一报道量；同一篇报道可能在多个国家切片中重复计入。"
            : `当前只显示${formatCountryName(response.selected_country)}的国家索引快照，不代表该国完整媒体覆盖。`}
        </strong>
        <ul>
          {response.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
        <p>图中只呈现已观测的报道覆盖与媒体显著度变化，不据此推断因果、事实真伪或未来走势。</p>
      </section>
    </article>
  );
}

export function MediaTopicObservatory({
  topicId,
  topicName,
  country,
}: MediaTopicObservatoryProps): JSX.Element {
  const query = useMemo<MediaTopicTimelineQuery>(
    () => ({ topicId, country, limit: timelinePointLimit }),
    [country, topicId],
  );
  const { state, reload } = useMediaTopicTimeline(query);

  if (state.status === "loading") {
    return <TopicTimelineLoading topicName={topicName} />;
  }

  if (state.status === "error") {
    return (
      <ApiErrorPanel
        title="无法读取议题时间线"
        error={state.error}
        isRetrying={state.isRetrying}
        onRetry={reload}
      />
    );
  }

  return <TopicTimelineContent response={state.data} />;
}
