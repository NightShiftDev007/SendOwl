import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { ApiRequestError } from "./apiClient";
import {
  type MediaArticle,
  type MediaArticlesQuery,
  type MediaArticlesResponse,
} from "./mediaContracts";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  useMediaArticles,
  type MediaArticlesLoadState,
} from "./useMediaArticles";
import {
  useWorldModelDetail,
  useWorldModels,
  type WorldModelDetailLoadState,
  type WorldModelsLoadState,
} from "./useWorldModels";
import {
  buildWorldModelCreateRequest,
  createWorldModel,
  type SnapshotEvidence,
  type WorldModelCreateRequest,
  type WorldModelDetail,
  type WorldModelSummary,
} from "./worldModelContracts";
import { EvidenceWorldGraph } from "./EvidenceWorldGraph";
import { SemanticWorldGraph } from "./SemanticWorldGraph";
import { EvidenceBundleLibrary } from "./EvidenceBundleLibrary";
import "./decisionWorkspace.css";

const articlesPerPage = 20;
const maximumEvidenceCount = 50;

type WorldModelCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly worldModel: WorldModelDetail }
  | { readonly status: "error"; readonly error: Error };

interface WorldModelBuilderProps {
  readonly appliedQuery: string | null;
  readonly draftQuery: string;
  readonly mediaState: MediaArticlesLoadState;
  readonly page: number;
  readonly selectedArticles: readonly MediaArticle[];
  readonly isHumanConfirmed: boolean;
  readonly onChangeDraftQuery: (query: string) => void;
  readonly onChangePage: (page: number) => void;
  readonly onChangeSelectedArticles: (articles: readonly MediaArticle[]) => void;
  readonly onChangeHumanConfirmed: (isConfirmed: boolean) => void;
  readonly onClearSearch: () => void;
  readonly onReloadMedia: () => void;
  readonly onSearch: (event: FormEvent<HTMLFormElement>) => void;
  readonly onCreated: (worldModel: WorldModelDetail) => void;
}

interface CandidateEvidenceSelectorProps {
  readonly response: MediaArticlesResponse;
  readonly selectedArticles: readonly MediaArticle[];
  readonly disabled: boolean;
  readonly onChange: (articles: readonly MediaArticle[]) => void;
  readonly onInvalidateConfirmation: () => void;
}

function normalizeWorldModelCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`世界模型输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("创建世界模型失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function isStaleEvidenceRevisionError(error: Error): boolean {
  return error instanceof ApiRequestError
    && error.kind === "http"
    && /(?:^|;) status=409(?:\s|;)/u.test(error.message);
}

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 12)}…${digest.slice(-8)}`;
}

function currentMediaData(state: MediaArticlesLoadState): MediaArticlesResponse | null {
  return state.data;
}

function BuilderSkeleton(): JSX.Element {
  return (
    <div className="world-builder-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取媒体报道</span>
      {Array.from({ length: 4 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function CandidateEvidenceSelector({
  response,
  selectedArticles,
  disabled,
  onChange,
  onInvalidateConfirmation,
}: CandidateEvidenceSelectorProps): JSX.Element {
  const selectedIds = new Set(selectedArticles.map((article) => article.id));
  const pageArticleIds = response.items.map((article) => article.id);
  const allPageArticlesSelected = pageArticleIds.length > 0
    && pageArticleIds.every((articleId) => selectedIds.has(articleId));

  const applySelection = (articles: readonly MediaArticle[]): void => {
    onChange(articles);
    onInvalidateConfirmation();
  };

  const toggleArticle = (article: MediaArticle, isSelected: boolean): void => {
    if (disabled) {
      return;
    }

    if (isSelected) {
      if (selectedIds.has(article.id) || selectedArticles.length >= maximumEvidenceCount) {
        return;
      }

      applySelection([...selectedArticles, article]);
      return;
    }

    applySelection(selectedArticles.filter((selectedArticle) => selectedArticle.id !== article.id));
  };

  const toggleCurrentPage = (): void => {
    if (disabled) {
      return;
    }

    if (allPageArticlesSelected) {
      const pageIds = new Set(pageArticleIds);
      applySelection(selectedArticles.filter((article) => !pageIds.has(article.id)));
      return;
    }

    const availableSlots = maximumEvidenceCount - selectedArticles.length;
    const additions = response.items
      .filter((article) => !selectedIds.has(article.id))
      .slice(0, availableSlots);
    applySelection([...selectedArticles, ...additions]);
  };

  return (
    <fieldset className="world-evidence-fieldset" disabled={disabled}>
      <legend>选择要冻结的报道证据</legend>
      <div className="world-evidence-toolbar">
        <p>
          选择会跨搜索与分页保留；打开原文核验后再确认冻结。
          <strong>{selectedArticles.length} / {maximumEvidenceCount} 已选</strong>
        </p>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={response.items.length === 0}
          onClick={toggleCurrentPage}
        >
          {allPageArticlesSelected ? "取消本页" : "选择本页"}
        </button>
      </div>

      {response.items.length === 0 ? (
        <div className="world-builder-empty" role="status">
          <strong>当前检索没有可选报道</strong>
          <p>调整关键词或清除检索条件；已从其他页面选择的证据不会丢失。</p>
        </div>
      ) : (
        <ul className="world-candidate-list">
          {response.items.map((article) => {
            const inputId = `world-evidence-${article.id}`;
            const descriptionId = `world-evidence-description-${article.id}`;
            const isSelected = selectedIds.has(article.id);
            const selectionLimitReached = selectedArticles.length >= maximumEvidenceCount
              && !isSelected;

            return (
              <li key={article.id} data-selected={isSelected}>
                <div className="world-candidate-heading">
                  <input
                    id={inputId}
                    type="checkbox"
                    checked={isSelected}
                    disabled={selectionLimitReached}
                    aria-describedby={descriptionId}
                    onChange={(event) => toggleArticle(article, event.target.checked)}
                  />
                  <label htmlFor={inputId}>
                    <strong>{article.title}</strong>
                    <span>
                      {article.source_name} · {formatMediaTimestamp(article.published_at)}
                      {article.country_code === null ? "" : ` · ${article.country_code}`}
                    </span>
                  </label>
                  <a
                    href={article.original_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`打开原文：${article.title}`}
                  >
                    原文 ↗
                  </a>
                </div>
                <p id={descriptionId} className="world-candidate-excerpt">
                  {article.excerpt}
                </p>
                <div className="world-candidate-revision">
                  <span>证据修订</span>
                  <code title={article.evidence_revision_sha256}>
                    {abbreviatedDigest(article.evidence_revision_sha256)}
                  </code>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}

function SelectedEvidenceList({
  selectedArticles,
  disabled,
  onRemove,
}: {
  readonly selectedArticles: readonly MediaArticle[];
  readonly disabled: boolean;
  readonly onRemove: (articleId: string) => void;
}): JSX.Element {
  if (selectedArticles.length === 0) {
    return (
      <div className="world-selected-empty" role="status">
        <strong>尚未选择证据</strong>
        <p>从中间的报道流选择一篇或多篇记录。</p>
      </div>
    );
  }

  return (
    <ol className="world-selected-evidence-list" aria-label="待冻结证据">
      {selectedArticles.map((article, index) => (
        <li key={article.id}>
          <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <div>
            <strong>{article.title}</strong>
            <small>{article.source_name}</small>
            <code title={article.evidence_revision_sha256}>
              {abbreviatedDigest(article.evidence_revision_sha256)}
            </code>
          </div>
          <button
            type="button"
            disabled={disabled}
            aria-label={`移除证据：${article.title}`}
            onClick={() => onRemove(article.id)}
          >
            移除
          </button>
        </li>
      ))}
    </ol>
  );
}

function WorldModelBuilder({
  appliedQuery,
  draftQuery,
  mediaState,
  page,
  selectedArticles,
  isHumanConfirmed,
  onChangeDraftQuery,
  onChangePage,
  onChangeSelectedArticles,
  onChangeHumanConfirmed,
  onClearSearch,
  onReloadMedia,
  onSearch,
  onCreated,
}: WorldModelBuilderProps): JSX.Element {
  const [title, setTitle] = useState<string>("");
  const [creationState, setCreationState] = useState<WorldModelCreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const response = currentMediaData(mediaState);
  const totalPages = response === null
    ? 1
    : Math.max(1, Math.ceil(response.total / response.page_size));
  const isSubmitting = creationState.status === "submitting";
  const hasStaleEvidenceRevision = creationState.status === "error"
    && isStaleEvidenceRevisionError(creationState.error);
  const canSubmit = title.trim() !== ""
    && selectedArticles.length > 0
    && selectedArticles.length <= maximumEvidenceCount
    && isHumanConfirmed
    && !isSubmitting;

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  const submitWorldModel = async (): Promise<void> => {
    if (!canSubmit || activeController.current !== null) {
      return;
    }

    let request: WorldModelCreateRequest;

    try {
      request = buildWorldModelCreateRequest(title, selectedArticles);
    } catch (error: unknown) {
      setCreationState({ status: "error", error: normalizeWorldModelCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setCreationState({ status: "submitting" });

    try {
      const worldModel = await createWorldModel(request, controller.signal);

      if (activeController.current !== controller || controller.signal.aborted) {
        return;
      }

      setTitle("");
      onChangeSelectedArticles([]);
      onChangeHumanConfirmed(false);
      setCreationState({ status: "success", worldModel });
      onCreated(worldModel);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      if (activeController.current !== controller) {
        return;
      }

      setCreationState({ status: "error", error: normalizeWorldModelCreationError(error) });
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  };

  const reloadStaleEvidence = (): void => {
    if (activeController.current !== null) {
      return;
    }

    onChangeSelectedArticles([]);
    onChangeHumanConfirmed(false);
    setCreationState({ status: "idle" });
    onReloadMedia();
  };

  const removeSelectedArticle = (articleId: string): void => {
    onChangeSelectedArticles(selectedArticles.filter((article) => article.id !== articleId));
    onChangeHumanConfirmed(false);
    setCreationState({ status: "idle" });
  };

  return (
    <section className="world-model-builder" aria-labelledby="world-builder-title">
      <div className="world-section-heading">
        <div>
          <span>当前任务</span>
          <h3 id="world-builder-title">检索证据并冻结现实版本</h3>
          <p>从通用媒体库跨页选取报道；右侧动作只冻结明确选择且经人工确认的修订。</p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>GET /api/v2/media/articles</code>
          <code>POST /api/v2/world-models</code>
        </details>
      </div>

      <div>
        <div className="world-builder-cockpit">
          <aside className="world-builder-controls decision-context-rail" aria-label="现实版本输入">
            <div className="decision-rail-heading">
              <span>现实版本</span>
              <strong>{title.trim() === "" ? "尚未命名" : title}</strong>
              <small>标题描述本次证据冻结的观察边界。</small>
            </div>

            <label>
              <span>现实版本标题</span>
              <input
                id="world-model-title"
                name="title"
                type="text"
                value={title}
                required
                maxLength={300}
                disabled={isSubmitting}
                placeholder="例如：全球供应链媒体基线 · 2026 Q3"
                onChange={(event) => {
                  setTitle(event.target.value);
                  setCreationState({ status: "idle" });
                }}
              />
            </label>

            <form className="world-evidence-search" role="search" onSubmit={onSearch}>
              <label htmlFor="world-evidence-query">
                <span>检索媒体证据</span>
                <input
                  id="world-evidence-query"
                  type="search"
                  value={draftQuery}
                  minLength={2}
                  maxLength={100}
                  placeholder="事件、人物或议题"
                  disabled={isSubmitting}
                  onChange={(event) => onChangeDraftQuery(event.target.value)}
                />
              </label>
              <div>
                <button
                  className="button button-primary button-compact"
                  type="submit"
                  disabled={draftQuery.trim().length === 1 || isSubmitting}
                >
                  检索
                </button>
                <button
                  className="button button-secondary button-compact"
                  type="button"
                  disabled={appliedQuery === null && draftQuery === ""}
                  onClick={onClearSearch}
                >
                  清除
                </button>
              </div>
            </form>

            <dl className="decision-context-ledger">
              <div><dt>当前关键词</dt><dd>{appliedQuery ?? "全部报道"}</dd></div>
              <div><dt>结果规模</dt><dd>{response === null ? "读取中" : `${response.total} 篇`}</dd></div>
              <div><dt>选择上限</dt><dd>{maximumEvidenceCount} 篇</dd></div>
            </dl>
          </aside>

          <div className="world-evidence-stage decision-main-stage">
            <div className="decision-stage-heading">
              <span>媒体证据库</span>
              <strong>
                {response === null
                  ? "等待报道索引"
                  : `${formatMediaCount(response.total)} 篇 · 第 ${response.page} / ${totalPages} 页`}
              </strong>
            </div>

            {mediaState.status === "error" ? (
              <ApiErrorPanel
                title="无法读取媒体证据"
                error={mediaState.error}
                isRetrying={mediaState.isRetrying}
                onRetry={onReloadMedia}
              />
            ) : null}

            {mediaState.status === "loading" && response === null ? <BuilderSkeleton /> : null}

            {response !== null ? (
              <div aria-busy={mediaState.status === "loading"}>
                <CandidateEvidenceSelector
                  response={response}
                  selectedArticles={selectedArticles}
                  disabled={isSubmitting || mediaState.status === "loading"}
                  onChange={onChangeSelectedArticles}
                  onInvalidateConfirmation={() => {
                    onChangeHumanConfirmed(false);
                    setCreationState({ status: "idle" });
                  }}
                />
                <nav className="pagination world-evidence-pagination" aria-label="待冻结媒体报道分页">
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={page <= 1 || mediaState.status === "loading"}
                    onClick={() => onChangePage(Math.max(1, page - 1))}
                  >
                    上一页
                  </button>
                  <span aria-live="polite">第 {response.page} / {totalPages} 页</span>
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={page >= totalPages || mediaState.status === "loading"}
                    onClick={() => onChangePage(page + 1)}
                  >
                    下一页
                  </button>
                </nav>
              </div>
            ) : null}
          </div>

          <aside className="world-freeze-inspector decision-inspector" aria-label="冻结动作与边界">
            <div className="decision-inspector-heading">
              <span>冻结动作</span>
              <h4>建立 v1 现实版本</h4>
            </div>
            <div className="world-freeze-note">
              <strong>不可变边界</strong>
              <p>保存所选报道的来源、正文哈希和修订地址；后续采集不会改写这一版本。</p>
            </div>

            <SelectedEvidenceList
              selectedArticles={selectedArticles}
              disabled={isSubmitting}
              onRemove={removeSelectedArticle}
            />

            {selectedArticles.length > 0 ? (
              <label className="world-human-confirmation">
                <input
                  type="checkbox"
                  checked={isHumanConfirmed}
                  disabled={isSubmitting}
                  onChange={(event) => {
                    onChangeHumanConfirmed(event.target.checked);
                    setCreationState({ status: "idle" });
                  }}
                />
                <span>
                  <strong>我已核验所选来源，并确认以这些修订冻结当前现实</strong>
                  <small>这是人工冻结声明，不代表系统已判断报道真伪或未来走势。</small>
                </span>
              </label>
            ) : null}

            {creationState.status === "error" ? (
              <div className="world-create-message world-create-error" role="alert">
                <strong>
                  {hasStaleEvidenceRevision ? "报道修订已变化，请重新核验" : "世界模型未创建"}
                </strong>
                <p>{creationState.error.message}</p>
                {hasStaleEvidenceRevision ? (
                  <button
                    className="button button-secondary button-compact"
                    type="button"
                    onClick={reloadStaleEvidence}
                  >
                    清空选择并刷新
                  </button>
                ) : null}
              </div>
            ) : null}

            {creationState.status === "success" ? (
              <div className="world-create-message world-create-success" role="status">
                已冻结“{creationState.worldModel.title}”版本 {creationState.worldModel.latest_snapshot.version}；
                完整快照已在档案中打开。
              </div>
            ) : null}

            <button
              className="button button-primary world-freeze-action"
              type="button"
              disabled={!canSubmit}
              aria-busy={isSubmitting}
              onClick={() => void submitWorldModel()}
            >
              {isSubmitting ? "正在冻结证据…" : `确认并创建 v1 · ${selectedArticles.length} 篇`}
            </button>
          </aside>
        </div>
      </div>
    </section>
  );
}

function WorldModelListSkeleton(): JSX.Element {
  return (
    <div className="world-model-list-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取世界模型</span>
      {Array.from({ length: 3 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function WorldModelList({
  state,
  selectedWorldModelId,
  onSelect,
  onReload,
}: {
  readonly state: WorldModelsLoadState;
  readonly selectedWorldModelId: string | null;
  readonly onSelect: (worldModel: WorldModelSummary) => void;
  readonly onReload: () => void;
}): JSX.Element {
  const response = state.data;

  return (
    <aside className="world-model-directory" aria-labelledby="world-model-directory-title">
      <div className="world-directory-heading">
        <div>
          <h3 id="world-model-directory-title">已冻结模型</h3>
          <p>{response === null ? "等待接口返回" : `${formatMediaCount(response.total)} 个模型`}</p>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={state.status === "loading"}
          aria-busy={state.status === "loading"}
          onClick={onReload}
        >
          {state.status === "loading" ? "读取中…" : "刷新"}
        </button>
      </div>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取世界模型"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && response === null ? <WorldModelListSkeleton /> : null}

      {response !== null && response.items.length === 0 ? (
        <div className="world-directory-empty" role="status">
          <strong>还没有不可变快照</strong>
          <p>在上方选择媒体证据并完成人工确认，第一个现实版本就会出现在这里。</p>
        </div>
      ) : null}

      {response !== null && response.items.length > 0 ? (
        <ul className="world-model-list" aria-busy={state.status === "loading"}>
          {response.items.map((worldModel) => {
            const isSelected = selectedWorldModelId === worldModel.id;

            return (
              <li key={worldModel.id}>
                <button
                  type="button"
                  data-selected={isSelected}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(worldModel)}
                >
                  <span className="world-version-marker" aria-hidden="true">
                    v{worldModel.latest_snapshot.version}
                  </span>
                  <span className="world-model-list-copy">
                    <strong>{worldModel.title}</strong>
                    <small>{worldModel.latest_snapshot.evidence_count} 篇冻结证据</small>
                    <code title={worldModel.latest_snapshot.snapshot_sha256}>
                      {abbreviatedDigest(worldModel.latest_snapshot.snapshot_sha256)}
                    </code>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </aside>
  );
}

function SnapshotEvidenceArticle({ evidence }: { readonly evidence: SnapshotEvidence }): JSX.Element {
  return (
    <article className="world-snapshot-evidence">
      <div className="world-snapshot-source">
        <span>
          <strong>{evidence.source_name}</strong>
          <time dateTime={evidence.published_at}>{formatMediaTimestamp(evidence.published_at)}</time>
          {evidence.country_code === null ? null : <small>{evidence.country_code}</small>}
        </span>
        <a href={evidence.original_url} target="_blank" rel="noopener noreferrer">
          回查原文 ↗
        </a>
      </div>
      <h5>{evidence.title}</h5>
      <p>{evidence.excerpt}</p>
      <footer>
        <span>正文捕获于 {formatMediaTimestamp(evidence.captured_at)}</span>
        <code title={evidence.captured_text_sha256}>
          content_sha256 {evidence.captured_text_sha256}
        </code>
      </footer>
    </article>
  );
}

function WorldModelDetailView({ worldModel }: { readonly worldModel: WorldModelDetail }): JSX.Element {
  const snapshot = worldModel.latest_snapshot;

  return (
    <div className="world-model-detail-content">
      <div className="world-detail-heading">
        <div>
          <span className="world-human-verified">人工冻结声明</span>
          <h3>{worldModel.title}</h3>
          <p>创建于 {formatMediaTimestamp(worldModel.created_at)}</p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>GET /api/v2/world-models/&#123;id&#125;</code>
        </details>
      </div>

      <dl className="world-snapshot-ledger" aria-label="最新不可变快照摘要">
        <div><dt>当前版本</dt><dd>v{snapshot.version}</dd></div>
        <div><dt>冻结证据</dt><dd>{formatMediaCount(snapshot.evidence.length)}</dd></div>
        <div><dt>确认方式</dt><dd>人工确认</dd></div>
        <div><dt>冻结时间</dt><dd>{formatMediaTimestamp(snapshot.created_at)}</dd></div>
      </dl>

      <div className="world-snapshot-hash">
        <span>snapshot_sha256 · 冻结内容地址</span>
        <code>{snapshot.snapshot_sha256}</code>
      </div>

      <EvidenceWorldGraph worldModelId={worldModel.id} snapshotId={snapshot.id} />

      <SemanticWorldGraph worldModelId={worldModel.id} snapshotId={snapshot.id} />

      <section className="world-version-history" aria-labelledby="world-version-history-title">
        <div>
          <h4 id="world-version-history-title">版本记录</h4>
          <p>每个版本都是独立快照；新版本不会覆盖旧版本。</p>
        </div>
        <ol>
          {worldModel.snapshots.map((version) => (
            <li key={version.id} data-current={version.id === snapshot.id}>
              <strong>v{version.version}</strong>
              <span>{version.evidence_count} 篇</span>
              <time dateTime={version.created_at}>{formatMediaTimestamp(version.created_at)}</time>
              <code title={version.snapshot_sha256}>{abbreviatedDigest(version.snapshot_sha256)}</code>
            </li>
          ))}
        </ol>
      </section>

      <section className="world-frozen-evidence" aria-labelledby="world-frozen-evidence-title">
        <div className="world-frozen-evidence-heading">
          <div>
            <h4 id="world-frozen-evidence-title">冻结证据</h4>
            <p>来源、采集时间和正文哈希来自创建时刻，可通过原文链接再次核验。</p>
          </div>
          <span>{snapshot.evidence.length} 篇</span>
        </div>
        <div className="world-snapshot-evidence-list">
          {snapshot.evidence.map((evidence) => (
            <SnapshotEvidenceArticle evidence={evidence} key={evidence.article_id} />
          ))}
        </div>
      </section>
    </div>
  );
}

function WorldModelDetailPanel({
  selectedWorldModelId,
  state,
  onReload,
}: {
  readonly selectedWorldModelId: string | null;
  readonly state: WorldModelDetailLoadState;
  readonly onReload: () => void;
}): JSX.Element {
  const loadedWorldModel = state.status === "idle" ? null : state.data;
  const worldModel = selectedWorldModelId !== null && loadedWorldModel?.id === selectedWorldModelId
    ? loadedWorldModel
    : null;

  if (selectedWorldModelId === null) {
    return (
      <section className="world-model-detail world-detail-empty" aria-labelledby="world-detail-title">
        <div>
          <h3 id="world-detail-title">选择模型核验不可变快照</h3>
          <p>模型创建后，这里会显示完整版本哈希和逐篇证据来源。</p>
        </div>
      </section>
    );
  }

  return (
    <section
      className="world-model-detail"
      aria-label="世界模型不可变快照详情"
      aria-busy={state.status === "loading"}
    >
      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取不可变快照"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && worldModel === null ? (
        <div className="world-detail-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取不可变快照</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {worldModel !== null ? <WorldModelDetailView worldModel={worldModel} /> : null}
    </section>
  );
}

export function WorldModelPage(): JSX.Element {
  const [draftQuery, setDraftQuery] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [page, setPage] = useState<number>(1);
  const [selectedArticles, setSelectedArticles] = useState<readonly MediaArticle[]>([]);
  const [isHumanConfirmed, setIsHumanConfirmed] = useState<boolean>(false);
  const query = useMemo<MediaArticlesQuery>(
    () => ({
      q: appliedQuery,
      country: null,
      topicId: null,
      page,
      pageSize: articlesPerPage,
    }),
    [appliedQuery, page],
  );
  const { state: mediaState, reload: reloadMedia } = useMediaArticles(query);
  const { state: worldModelsState, reload: reloadWorldModels } = useWorldModels();
  const [selectedWorldModelId, setSelectedWorldModelId] = useState<string | null>(null);
  const {
    state: worldModelDetailState,
    reload: reloadWorldModelDetail,
  } = useWorldModelDetail(selectedWorldModelId);
  const selectedWorldModel = selectedWorldModelId === null
    ? null
    : worldModelsState.data?.items.find((worldModel) => worldModel.id === selectedWorldModelId) ?? null;

  useEffect(() => {
    if (mediaState.data === null || selectedArticles.length === 0) {
      return;
    }

    const visibleArticles = new Map(
      mediaState.data.items.map((article) => [article.id, article]),
    );
    let revisionChanged = false;
    const nextSelectedArticles = selectedArticles.map((article) => {
      const currentArticle = visibleArticles.get(article.id);

      if (
        currentArticle === undefined
        || currentArticle.evidence_revision_sha256 === article.evidence_revision_sha256
      ) {
        return article;
      }

      revisionChanged = true;
      return currentArticle;
    });

    if (revisionChanged) {
      setSelectedArticles(nextSelectedArticles);
      setIsHumanConfirmed(false);
    }
  }, [mediaState.data, selectedArticles]);

  const submitSearch = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const normalizedQuery = draftQuery.trim();

    if (normalizedQuery.length === 1) {
      return;
    }

    setAppliedQuery(normalizedQuery === "" ? null : normalizedQuery);
    setPage(1);
  };

  const clearSearch = (): void => {
    setDraftQuery("");
    setAppliedQuery(null);
    setPage(1);
  };

  const selectWorldModel = (worldModel: WorldModelSummary): void => {
    setSelectedWorldModelId(worldModel.id);
  };

  const worldModelCreated = (worldModel: WorldModelDetail): void => {
    setSelectedWorldModelId(worldModel.id);
    reloadWorldModels();
  };

  return (
    <div className="world-model-page decision-surface decision-world-surface">
      <header className="decision-surface-header" aria-labelledby="world-model-page-title">
        <div className="decision-surface-heading">
          <span className="decision-stage-index">02 · 现实版本室</span>
          <div>
            <h2 id="world-model-page-title">把核验过的证据冻结成共同现实</h2>
            <p>研究员从媒体证据库明确选择报道与修订，让后续实验始终回到同一个可复核版本。</p>
          </div>
        </div>
        <div className="decision-context-bar">
          <div className="decision-context-current" data-active={selectedArticles.length > 0}>
            <span>待冻结证据</span>
            <strong>{selectedArticles.length === 0 ? "尚未选择报道" : `${selectedArticles.length} 篇已选`}</strong>
            <small>{isHumanConfirmed ? "人工冻结声明已确认" : "选择变化后需要重新确认"}</small>
          </div>
          <div className="decision-context-current" data-active={selectedWorldModel !== null}>
            <span>档案核验对象</span>
            <strong>{selectedWorldModel?.title ?? "尚未选择历史快照"}</strong>
            <small>
              {selectedWorldModel === null
                ? "从下方档案明确打开一个版本。"
                : `v${selectedWorldModel.latest_snapshot.version} · ${selectedWorldModel.latest_snapshot.evidence_count} 篇证据`}
            </small>
          </div>
          <ul className="decision-boundary-legend" aria-label="世界模型边界">
            <li data-boundary="candidate"><span />媒体修订</li>
            <li data-boundary="human"><span />人工确认</li>
            <li data-boundary="immutable"><span />不可变快照</li>
          </ul>
        </div>
      </header>

      <WorldModelBuilder
        appliedQuery={appliedQuery}
        draftQuery={draftQuery}
        mediaState={mediaState}
        page={page}
        selectedArticles={selectedArticles}
        isHumanConfirmed={isHumanConfirmed}
        onChangeDraftQuery={setDraftQuery}
        onChangePage={setPage}
        onChangeSelectedArticles={setSelectedArticles}
        onChangeHumanConfirmed={setIsHumanConfirmed}
        onClearSearch={clearSearch}
        onReloadMedia={reloadMedia}
        onSearch={submitSearch}
        onCreated={worldModelCreated}
      />

      <EvidenceBundleLibrary />

      <section className="world-model-registry decision-archive-stage" aria-labelledby="world-registry-title">
        <div className="world-registry-heading">
          <div>
            <span>版本档案</span>
            <h2 id="world-registry-title">回查冻结时刻的完整证据链</h2>
            <p>这里只在你明确选择后打开模型；版本、证据来源和内容地址均保持只读。</p>
          </div>
        </div>
        <div className="world-registry-workbench">
          <WorldModelList
            state={worldModelsState}
            selectedWorldModelId={selectedWorldModelId}
            onSelect={selectWorldModel}
            onReload={reloadWorldModels}
          />
          <WorldModelDetailPanel
            selectedWorldModelId={selectedWorldModelId}
            state={worldModelDetailState}
            onReload={reloadWorldModelDetail}
          />
        </div>
      </section>
    </div>
  );
}
