import type {
  MediaSyncRun,
  MediaSyncStatusResponse,
  MediaSyncTableCount,
  MediaSyncWatermarks,
} from "./mediaSyncContracts";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  useMediaSyncStatus,
  type MediaSyncStatusLoadState,
} from "./useMediaSyncStatus";
import "./mediaSyncFreshness.css";

interface FreshnessPresentation {
  readonly state: "verifying" | "healthy" | "running" | "warning" | "failed" | "empty";
  readonly headline: string;
}

const watermarkPresentation: readonly {
  readonly key: keyof MediaSyncWatermarks;
  readonly label: string;
}[] = [
  { key: "latest_source_updated_at", label: "来源配置更新" },
  { key: "latest_article_crawled_at", label: "文章采集" },
  { key: "latest_topic_updated_at", label: "议题更新" },
  { key: "latest_topic_article_assigned_at", label: "文章议题归属" },
  { key: "latest_snapshot_created_at", label: "议题快照写入" },
  { key: "latest_snapshot_window_end", label: "议题观测窗口" },
  { key: "latest_propagation_updated_at", label: "传播链更新" },
];

const tablePresentation: Readonly<Record<MediaSyncTableCount["table_name"], string>> = {
  sources: "来源",
  articles: "文章",
  topics: "议题",
  topic_articles: "文章议题关系",
  topic_snapshots: "议题快照",
  propagation_events: "传播事件",
  propagation_edges: "传播边",
  first_utterances: "首发证据",
};

const limitationTranslations: Readonly<Record<string, string>> = {
  "Each refresh scans all supported AgendaScope source rows and only writes changed target rows.":
    "每轮执行 full-scan，读取 AgendaScope 所有受支持行；目标端只 upsert 有变化的行。",
  "Articles absent from a complete source scan are hidden in SendOwl without deleting frozen evidence; other source deletions are not reconciled.":
    "完整源快照中不再出现的文章会在 SendOwl 当前视图中隐藏，但已冻结证据不会删除；其他源对象暂不做删除对账。",
  "Business-time watermarks do not prove semantic completeness or real-time coverage.":
    "业务时间水位只能说明已观测数据的新鲜度，不能证明语义完整或实时全量覆盖。",
};

function translatedLimitation(limitation: string): string {
  return limitationTranslations[limitation] ?? limitation;
}

function hasTargetData(watermarks: MediaSyncWatermarks): boolean {
  return watermarkPresentation.some(({ key }) => watermarks[key] !== null);
}

function latestWatermark(watermarks: MediaSyncWatermarks): string | null {
  const timestamps = watermarkPresentation
    .map(({ key }) => watermarks[key])
    .filter((timestamp): timestamp is string => timestamp !== null);

  if (timestamps.length === 0) {
    return null;
  }

  return timestamps.reduce((latest, timestamp) =>
    Date.parse(timestamp) > Date.parse(latest) ? timestamp : latest,
  );
}

function runStatusLabel(status: MediaSyncRun["status"]): string {
  if (status === "running") return "运行中";
  if (status === "succeeded") return "成功";
  if (status === "failed") return "失败";
  return "并发任务已跳过";
}

function triggerLabel(trigger: MediaSyncRun["trigger"]): string {
  return trigger === "scheduled" ? "定时" : "手动";
}

function freshnessPresentation(
  state: MediaSyncStatusLoadState,
  response: MediaSyncStatusResponse | null,
): FreshnessPresentation {
  if (
    state.status === "loading"
    || (state.status === "error" && state.isRetrying)
  ) {
    return { state: "verifying", headline: "同步新鲜度核验中" };
  }

  if (state.status === "error") {
    return { state: "failed", headline: "同步状态读取失败" };
  }

  if (response === null) {
    throw new Error("Media sync success state requires a validated response.");
  }

  if (response.latest_run === null) {
    return hasTargetData(response.target_watermarks)
      ? { state: "warning", headline: "已有导入数据 · 尚无运行档案" }
      : { state: "empty", headline: "尚无同步运行档案" };
  }

  if (response.latest_run.status === "running") {
    return { state: "running", headline: "同步进行中" };
  }

  if (response.latest_run.status === "succeeded") {
    return { state: "healthy", headline: "最近同步成功" };
  }

  if (response.latest_run.status === "failed") {
    return { state: "failed", headline: "最近同步失败" };
  }

  return { state: "warning", headline: "并发同步已跳过" };
}

function RunLedger({ run }: { readonly run: MediaSyncRun }): JSX.Element {
  return (
    <dl className="media-sync-freshness__run-ledger">
      <div>
        <dt>状态</dt>
        <dd>{runStatusLabel(run.status)}</dd>
      </div>
      <div>
        <dt>触发</dt>
        <dd>{triggerLabel(run.trigger)}</dd>
      </div>
      <div>
        <dt>开始</dt>
        <dd><time dateTime={run.started_at}>{formatMediaTimestamp(run.started_at)}</time></dd>
      </div>
      <div>
        <dt>完成</dt>
        <dd>
          {run.completed_at === null
            ? "尚未完成"
            : <time dateTime={run.completed_at}>{formatMediaTimestamp(run.completed_at)}</time>}
        </dd>
      </div>
      <div>
        <dt>下次计划</dt>
        <dd>
          {run.next_scheduled_at === null
            ? "无计划时间"
            : <time dateTime={run.next_scheduled_at}>{formatMediaTimestamp(run.next_scheduled_at)}</time>}
        </dd>
      </div>
      <div>
        <dt>Worker</dt>
        <dd><code>{run.worker_id}</code></dd>
      </div>
    </dl>
  );
}

function TargetWatermarks({ watermarks }: { readonly watermarks: MediaSyncWatermarks }): JSX.Element {
  return (
    <dl className="media-sync-freshness__watermarks">
      {watermarkPresentation.map(({ key, label }) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd>
            {watermarks[key] === null
              ? "无水位"
              : <time dateTime={watermarks[key]}>{formatMediaTimestamp(watermarks[key])}</time>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TableAccounting({ counts }: { readonly counts: readonly MediaSyncTableCount[] }): JSX.Element {
  return (
    <div className="media-sync-freshness__accounting">
      <div className="media-sync-freshness__accounting-labels" aria-hidden="true">
        <span>对象</span><span>读取</span><span>新增</span><span>更新</span><span>跳过</span>
      </div>
      <dl>
        {counts.map((count) => (
          <div key={count.table_name}>
            <dt>{tablePresentation[count.table_name]}</dt>
            <dd><span>读取</span>{formatMediaCount(count.read_count)}</dd>
            <dd><span>新增</span>{formatMediaCount(count.inserted_count)}</dd>
            <dd><span>更新</span>{formatMediaCount(count.updated_count)}</dd>
            <dd><span>跳过</span>{formatMediaCount(count.skipped_count)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function FailedRunNotice({ response }: { readonly response: MediaSyncStatusResponse }): JSX.Element | null {
  if (response.latest_run?.status !== "failed") {
    return null;
  }

  const failedRun = response.latest_run;
  const failedRunError = failedRun.error;
  if (failedRunError === null) {
    throw new Error("A validated failed media sync run must include a controlled error.");
  }
  let snapshotMessage = "当前没有可确认的成功同步档案；现有数据不会被这次失败自动清空。";
  if (response.latest_success !== null) {
    const completedAt = response.latest_success.completed_at;
    if (completedAt === null) {
      throw new Error("A validated successful media sync run must include completed_at.");
    }
    snapshotMessage = `仍展示上次成功快照（${formatMediaTimestamp(completedAt)}）。`;
  }

  return (
    <div className="media-sync-freshness__failure" role="alert">
      <strong>最近同步失败</strong>
      <p>{snapshotMessage}</p>
      <code>{failedRunError.code}</code>
      <span>{failedRunError.message}</span>
    </div>
  );
}

function FreshnessDetails({ response }: { readonly response: MediaSyncStatusResponse }): JSX.Element {
  const hasImportedData = hasTargetData(response.target_watermarks);

  return (
    <div className="media-sync-freshness__details-body">
      <FailedRunNotice response={response} />

      <div className="media-sync-freshness__sections">
        <section aria-labelledby="media-sync-latest-run-title">
          <h3 id="media-sync-latest-run-title">最新运行</h3>
          {response.latest_run === null ? (
            <p className="media-sync-freshness__empty-note">
              {hasImportedData
                ? "尚无同步运行档案，现有数据来自此前导入。"
                : "尚无同步运行档案，目标库也没有可用业务时间水位。"}
            </p>
          ) : (
            <RunLedger run={response.latest_run} />
          )}
        </section>

        <section aria-labelledby="media-sync-latest-success-title">
          <h3 id="media-sync-latest-success-title">最近成功快照</h3>
          {response.latest_success === null ? (
            <p className="media-sync-freshness__empty-note">尚未记录成功同步运行。</p>
          ) : (
            <LatestSuccessSnapshot run={response.latest_success} />
          )}
        </section>
      </div>

      <section className="media-sync-freshness__target" aria-labelledby="media-sync-target-title">
        <h3 id="media-sync-target-title">目标库业务时间水位</h3>
        <TargetWatermarks watermarks={response.target_watermarks} />
        <p className="media-sync-freshness__success-note">
          当前可见文章 {formatMediaCount(response.article_reconciliation.present_count)} 篇；
          源端缺席但为保护冻结证据而保留 {formatMediaCount(response.article_reconciliation.absent_count)} 篇。
          {response.article_reconciliation.latest_absent_at === null ? null : (
            <> 最近一次缺席确认于 <time dateTime={response.article_reconciliation.latest_absent_at}>{formatMediaTimestamp(response.article_reconciliation.latest_absent_at)}</time>。</>
          )}
        </p>
      </section>

      <section className="media-sync-freshness__boundary" aria-labelledby="media-sync-boundary-title">
        <h3 id="media-sync-boundary-title">同步边界</h3>
        <ul>
          {response.limitations.map((limitation) => (
            <li key={limitation}>{translatedLimitation(limitation)}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function LatestSuccessSnapshot({ run }: { readonly run: MediaSyncRun }): JSX.Element {
  if (run.status !== "succeeded" || run.source_observed_at === null) {
    throw new Error("LatestSuccessSnapshot requires a validated succeeded run.");
  }

  return (
    <>
      <p className="media-sync-freshness__success-note">
        源快照观测于{" "}
        <time dateTime={run.source_observed_at}>
          {formatMediaTimestamp(run.source_observed_at)}
        </time>
      </p>
      <TableAccounting counts={run.table_counts} />
    </>
  );
}

export function MediaSyncFreshness(): JSX.Element {
  const { state, reload } = useMediaSyncStatus();
  const response = state.data;
  const presentation = freshnessPresentation(state, response);
  const watermark = response === null ? null : latestWatermark(response.target_watermarks);
  const isVerifying = state.status === "loading"
    || (state.status === "error" && state.isRetrying);

  return (
    <section
      className="media-sync-freshness"
      data-state={presentation.state}
      aria-label="媒体同步新鲜度"
      aria-busy={isVerifying}
    >
      <details>
        <summary>
          <span className="media-sync-freshness__signal" aria-hidden="true" />
          <span className="media-sync-freshness__label">同步新鲜度</span>
          <strong>{presentation.headline}</strong>
          {watermark === null ? null : (
            <time dateTime={watermark}>{formatMediaTimestamp(watermark)}</time>
          )}
          <span className="media-sync-freshness__disclosure" aria-hidden="true">详情</span>
        </summary>

        {state.status === "error" ? (
          <div className="media-sync-freshness__request-error" role="alert">
            <strong>无法刷新同步状态</strong>
            <p>{state.error.message}</p>
            <button type="button" disabled={state.isRetrying} onClick={reload}>
              {state.isRetrying ? "正在重新读取…" : "重新读取状态"}
            </button>
          </div>
        ) : null}

        {response === null ? (
          <p className="media-sync-freshness__loading" role="status">
            正在核验同步运行档案和目标库业务时间水位…
          </p>
        ) : (
          <FreshnessDetails response={response} />
        )}
      </details>
    </section>
  );
}
