import { useCallback, useEffect, useState } from "react";

import { MediaSyncFreshness } from "./MediaSyncFreshness";
import {
  createNativeMediaSource,
  fetchNativeMediaCollectionStatus,
  type NativeMediaCollectionStatus,
} from "./nativeMediaCollectionContracts";
import { formatMediaTimestamp } from "./mediaPresentation";
import "./nativeMediaCollection.css";

export function NativeMediaCollectionPanel(): JSX.Element {
  const [status, setStatus] = useState<NativeMediaCollectionStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [name, setName] = useState("");
  const [country, setCountry] = useState("CN");
  const [homepage, setHomepage] = useState("");
  const [mode, setMode] = useState<"rss" | "web">("rss");
  const [feedUrl, setFeedUrl] = useState("");
  const [language, setLanguage] = useState("zh");
  const [interval, setIntervalValue] = useState(900);

  const load = useCallback(async (signal: AbortSignal): Promise<void> => {
    try {
      setStatus(await fetchNativeMediaCollectionStatus(signal));
      setError(null);
    } catch (reason: unknown) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(reason instanceof Error ? reason : new Error("读取原生采集状态失败"));
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const canSubmit = name.trim() !== ""
    && country.length === 2
    && homepage.trim() !== ""
    && language.trim().length >= 2
    && (mode === "web" || feedUrl.trim() !== "")
    && !submitting;

  const submit = async (): Promise<void> => {
    if (!canSubmit) return;
    const controller = new AbortController();
    setSubmitting(true);
    setError(null);
    try {
      await createNativeMediaSource({
        name,
        country_code: country.toUpperCase(),
        homepage_url: homepage,
        media_type: "online",
        language,
        collection_mode: mode,
        feed_url: mode === "rss" ? feedUrl : null,
        poll_interval_seconds: interval,
      }, controller.signal);
      setName("");
      setHomepage("");
      setFeedUrl("");
      setShowForm(false);
      await load(controller.signal);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason : new Error("新增媒体来源失败"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="native-media-collection" aria-label="SandOwl 原生媒体采集">
      <header>
        <div><strong>SandOwl 原生采集</strong><p>来源发现、抓取、正文提取和去重都在当前产品内运行。</p></div>
        <span data-online={status?.worker_online ?? false}>{status === null ? "核验中" : status.worker_online ? "采集器在线" : "采集器离线"}</span>
      </header>
      {error !== null ? <div className="native-media-collection__error" role="alert"><p>{error.message}</p><button type="button" onClick={() => { const controller = new AbortController(); void load(controller.signal); }}>重新读取</button></div> : null}
      {status !== null ? <dl><div><dt>自动采集来源</dt><dd>{status.enabled_source_count}</dd></div><div><dt>等待采集</dt><dd>{status.due_source_count}</dd></div><div><dt>活动告警</dt><dd>{status.active_alerts.length}</dd></div><div><dt>最近运行</dt><dd>{status.latest_runs[0]?.completed_at ? formatMediaTimestamp(status.latest_runs[0].completed_at) : "尚无"}</dd></div></dl> : null}
      <button type="button" className="native-media-collection__add" aria-expanded={showForm} onClick={() => setShowForm((current) => !current)}>{showForm ? "收起来源配置" : "新增自动采集来源"}</button>
      {showForm ? <form onSubmit={(event) => { event.preventDefault(); void submit(); }}><p>保存后即进入自动调度。SandOwl 只访问公开 HTTP(S) 地址，并阻止私网目标。</p><label>来源名称<input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></label><label>国家代码<input required pattern="[A-Za-z]{2}" maxLength={2} value={country} onChange={(event) => setCountry(event.target.value)} /></label><label>主页地址<input required type="url" maxLength={500} value={homepage} onChange={(event) => setHomepage(event.target.value)} placeholder="https://example.com/" /></label><label>采集方式<select value={mode} onChange={(event) => setMode(event.target.value as "rss" | "web")}><option value="rss">RSS / Atom</option><option value="web">网页列表发现</option></select></label>{mode === "rss" ? <label>Feed 地址<input required type="url" maxLength={500} value={feedUrl} onChange={(event) => setFeedUrl(event.target.value)} placeholder="https://example.com/feed.xml" /></label> : null}<label>语言<input required minLength={2} maxLength={10} value={language} onChange={(event) => setLanguage(event.target.value)} /></label><label>采集间隔<select value={interval} onChange={(event) => setIntervalValue(Number(event.target.value))}><option value={300}>5 分钟</option><option value={900}>15 分钟</option><option value={3600}>1 小时</option><option value={21600}>6 小时</option></select></label><button type="submit" disabled={!canSubmit}>{submitting ? "正在保存…" : "保存并启用自动采集"}</button></form> : null}
      <details className="native-media-collection__legacy"><summary>历史 AgendaScope 数据迁移状态</summary><MediaSyncFreshness /></details>
    </section>
  );
}
