import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import {
  ApiRequestError,
  isAmbiguousPostResultError,
} from "./apiClient";
import {
  fetchMediaArticle,
  type MediaArticle,
  type MediaArticlesQuery,
  type MediaArticlesResponse,
} from "./mediaContracts";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import type { PolicyDocumentSummary } from "./policyEvidenceContracts";
import { usePolicyDocuments } from "./usePolicyEvidence";
import {
  useMediaArticles,
  type MediaArticlesLoadState,
} from "./useMediaArticles";
import {
  useWorldModelDetail,
  useWorldModels,
  useWorldSnapshotDetail,
  type WorldModelDetailLoadState,
  type WorldModelsLoadState,
  type WorldSnapshotDetailLoadState,
} from "./useWorldModels";
import {
  appendWorldSnapshot,
  buildWorldModelCreateRequest,
  buildWorldSnapshotCreateRequest,
  createWorldModel,
  type SnapshotEvidence,
  type SnapshotDetail,
  type SnapshotPolicyEvidence,
  type WorldModelCreateRequest,
  type WorldModelDetail,
  type WorldModelSummary,
  type WorldSnapshotCreateRequest,
} from "./worldModelContracts";
import { EvidenceWorldGraph } from "./EvidenceWorldGraph";
import { SemanticWorldGraph } from "./SemanticWorldGraph";
import { EvidenceBundleLibrary } from "./EvidenceBundleLibrary";
import type { WorldRoute } from "./worldRoute";
import "./decisionWorkspace.css";

const articlesPerPage = 20;
const maximumEvidenceCount = 50;
type PolicyDirectoryState = ReturnType<typeof usePolicyDocuments>["state"];

type WorldModelCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly worldModel: WorldModelDetail }
  | { readonly status: "error"; readonly error: Error };

type WorldSnapshotAppendState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly snapshot: SnapshotDetail }
  | { readonly status: "error"; readonly error: Error };

interface WorldModelBuilderProps {
  readonly appliedQuery: string | null;
  readonly draftQuery: string;
  readonly mediaState: MediaArticlesLoadState;
  readonly page: number;
  readonly selectedArticles: readonly MediaArticle[];
  readonly selectedPolicies: readonly PolicyDocumentSummary[];
  readonly isHumanConfirmed: boolean;
  readonly onChangeDraftQuery: (query: string) => void;
  readonly onChangePage: (page: number) => void;
  readonly onChangeSelectedArticles: (articles: readonly MediaArticle[]) => void;
  readonly onChangeSelectedPolicies: (policies: readonly PolicyDocumentSummary[]) => void;
  readonly onChangeHumanConfirmed: (isConfirmed: boolean) => void;
  readonly onClearSearch: () => void;
  readonly onReloadMedia: () => void;
  readonly onSearch: (event: FormEvent<HTMLFormElement>) => void;
  readonly onCreated: (worldModel: WorldModelDetail) => void;
}

interface CandidateEvidenceSelectorProps {
  readonly response: MediaArticlesResponse;
  readonly selectedArticles: readonly MediaArticle[];
  readonly selectionLimit: number;
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

function normalizeWorldSnapshotAppendError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`追加版本输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("追加世界快照失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function isStaleEvidenceRevisionError(error: Error): boolean {
  return error instanceof ApiRequestError
    && error.kind === "http"
    && /(?:^|;) status=409(?:\s|;)/u.test(error.message);
}

function evidenceSelectionKey(
  worldModelId: string,
  selectedArticles: readonly MediaArticle[],
  selectedPolicies: readonly PolicyDocumentSummary[],
): string {
  return [
    worldModelId,
    ...selectedArticles.map(
      (article) => `${article.id}:${article.evidence_revision_sha256}`,
    ),
    ...selectedPolicies.map(
      (document) => (
        `${document.latest_version.id}:${document.latest_version.version_sha256}`
      ),
    ),
  ].join("|");
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
  selectionLimit,
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
      if (selectedIds.has(article.id) || selectedArticles.length >= selectionLimit) {
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

    const availableSlots = selectionLimit - selectedArticles.length;
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
          <strong>{selectedArticles.length} / {selectionLimit} 可选媒体位</strong>
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
            const selectionLimitReached = selectedArticles.length >= selectionLimit
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

function WorldPolicyEvidenceSelector({
  state,
  page,
  selectedPolicies,
  mediaEvidenceCount,
  disabled,
  onChangePage,
  onChange,
  onReload,
  onInvalidateConfirmation,
}: {
  readonly state: PolicyDirectoryState;
  readonly page: number;
  readonly selectedPolicies: readonly PolicyDocumentSummary[];
  readonly mediaEvidenceCount: number;
  readonly disabled: boolean;
  readonly onChangePage: (page: number) => void;
  readonly onChange: (policies: readonly PolicyDocumentSummary[]) => void;
  readonly onReload: () => void;
  readonly onInvalidateConfirmation: () => void;
}): JSX.Element {
  const selectedVersionIds = new Set(
    selectedPolicies.map((document) => document.latest_version.id),
  );
  const total = state.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / 20));
  const policyLimit = maximumEvidenceCount - mediaEvidenceCount;

  const togglePolicy = (document: PolicyDocumentSummary, checked: boolean): void => {
    if (disabled) return;
    const versionId = document.latest_version.id;
    const next = checked
      ? selectedVersionIds.has(versionId) || selectedPolicies.length >= policyLimit
        ? selectedPolicies
        : [...selectedPolicies, document]
      : selectedPolicies.filter((item) => item.latest_version.id !== versionId);
    if (next !== selectedPolicies) {
      onChange(next);
      onInvalidateConfirmation();
    }
  };

  return (
    <section className="world-policy-selector" aria-labelledby="world-policy-selector-title">
      <header>
        <div>
          <span>POLICY / IMMUTABLE VERSIONS</span>
          <h3 id="world-policy-selector-title">选择要共同冻结的政策版本</h3>
          <p>目录展示每份政策当前最新版本；已选项保留精确版本 ID 和哈希，不随目录更新漂移。</p>
        </div>
        <strong>{selectedPolicies.length} / {policyLimit} 可选政策位</strong>
      </header>

      {selectedPolicies.length === 0 ? null : (
        <ol className="world-selected-policy-list" aria-label="待冻结政策版本">
          {selectedPolicies.map((document) => (
            <li key={document.latest_version.id}>
              <div>
                <strong>{document.latest_version.title}</strong>
                <span>
                  {document.source.authority_name} · {document.canonical_identifier} · v
                  {document.latest_version.version}
                </span>
                <code title={document.latest_version.version_sha256}>
                  {abbreviatedDigest(document.latest_version.version_sha256)}
                </code>
              </div>
              <button
                type="button"
                disabled={disabled}
                onClick={() => togglePolicy(document, false)}
              >
                移除
              </button>
            </li>
          ))}
        </ol>
      )}

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取政策证据目录"
          error={state.error}
          isRetrying={false}
          onRetry={onReload}
        />
      ) : null}
      {state.status === "loading" && state.data === null ? (
        <div className="world-policy-loading" role="status">正在读取政策版本…</div>
      ) : null}
      {state.data?.items.length === 0 ? (
        <div className="world-policy-loading" role="status">
          尚无可选政策证据；先在“政策证据”工作区人工捕获真实版本。
        </div>
      ) : null}
      <ul className="world-policy-candidates">
        {state.data?.items.map((document) => {
          const version = document.latest_version;
          const checked = selectedVersionIds.has(version.id);
          const limitReached = selectedPolicies.length >= policyLimit && !checked;
          return (
            <li key={version.id} data-selected={checked}>
              <input
                id={`world-policy-${version.id}`}
                type="checkbox"
                checked={checked}
                disabled={disabled || limitReached}
                onChange={(event) => togglePolicy(document, event.target.checked)}
              />
              <label htmlFor={`world-policy-${version.id}`}>
                <strong>{version.title}</strong>
                <span>
                  {document.source.authority_name} · {document.canonical_identifier} · v
                  {version.version}
                </span>
                <small>
                  发布 {version.publication_date} · 施行 {version.effective_from ?? "未标明"}
                </small>
              </label>
              <a href={version.original_url} target="_blank" rel="noopener noreferrer">
                原文 ↗
              </a>
            </li>
          );
        })}
      </ul>
      <nav aria-label="政策证据分页">
        <button
          type="button"
          disabled={disabled || page <= 1}
          onClick={() => onChangePage(page - 1)}
        >
          上一页
        </button>
        <span>{page} / {pageCount}</span>
        <button
          type="button"
          disabled={disabled || page >= pageCount}
          onClick={() => onChangePage(page + 1)}
        >
          下一页
        </button>
      </nav>
    </section>
  );
}

function WorldModelBuilder({
  appliedQuery,
  draftQuery,
  mediaState,
  page,
  selectedArticles,
  selectedPolicies,
  isHumanConfirmed,
  onChangeDraftQuery,
  onChangePage,
  onChangeSelectedArticles,
  onChangeSelectedPolicies,
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
    && selectedArticles.length + selectedPolicies.length <= maximumEvidenceCount
    && isHumanConfirmed
    && !isSubmitting;

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (activeController.current === null) {
      setCreationState({ status: "idle" });
    }
  }, [selectedPolicies]);

  const submitWorldModel = async (): Promise<void> => {
    if (!canSubmit || activeController.current !== null) {
      return;
    }

    let request: WorldModelCreateRequest;

    try {
      request = buildWorldModelCreateRequest(title, selectedArticles, selectedPolicies);
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
      onChangeSelectedPolicies([]);
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
                  selectionLimit={maximumEvidenceCount - selectedPolicies.length}
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
              <p>保存所选报道修订与政策版本的来源、日期和正文哈希；后续采集不会改写这一版本。</p>
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
                  <strong>我已核验所选媒体与政策来源，并确认冻结这些精确版本</strong>
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
              {isSubmitting
                ? "正在冻结证据…"
                : `确认并创建 v1 · ${selectedArticles.length} 篇媒体 · ${selectedPolicies.length} 份政策`}
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
                  disabled={state.status === "loading"}
                  onClick={() => onSelect(worldModel)}
                >
                  <span className="world-version-marker" aria-hidden="true">
                    v{worldModel.latest_snapshot.version}
                  </span>
                  <span className="world-model-list-copy">
                    <strong>{worldModel.title}</strong>
                    <small>
                      {worldModel.latest_snapshot.evidence_count} 篇媒体 ·
                      {` ${worldModel.latest_snapshot.policy_evidence_count} 份政策`}
                    </small>
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

function SnapshotPolicyEvidenceArticle({
  evidence,
}: {
  readonly evidence: SnapshotPolicyEvidence;
}): JSX.Element {
  return (
    <article className="world-snapshot-evidence world-snapshot-policy-evidence">
      <div className="world-snapshot-source">
        <span>
          <strong>{evidence.authority_name}</strong>
          <small>{evidence.jurisdiction_code}</small>
          <small>{evidence.canonical_identifier}</small>
        </span>
        <a href={evidence.original_url} target="_blank" rel="noopener noreferrer">
          回查政策原文 ↗
        </a>
      </div>
      <h5>{evidence.title}</h5>
      <p>
        v{evidence.version} · 发布 {evidence.publication_date} · 施行
        {` ${evidence.effective_from ?? "未标明"}`} · 失效
        {` ${evidence.effective_until ?? "未标明"}`}
      </p>
      <footer>
        <span>正文捕获于 {formatMediaTimestamp(evidence.captured_at)}</span>
        <code title={evidence.version_sha256}>
          version_sha256 {evidence.version_sha256}
        </code>
      </footer>
    </article>
  );
}

function WorldSnapshotAppender({
  worldModel,
  selectedArticles,
  selectedPolicies,
  onAppended,
  onResetStaleEvidence,
  onVerifyAmbiguousResult,
}: {
  readonly worldModel: WorldModelDetail;
  readonly selectedArticles: readonly MediaArticle[];
  readonly selectedPolicies: readonly PolicyDocumentSummary[];
  readonly onAppended: (snapshot: SnapshotDetail) => void;
  readonly onResetStaleEvidence: () => void;
  readonly onVerifyAmbiguousResult: () => void;
}): JSX.Element {
  const [confirmedSelectionKey, setConfirmedSelectionKey] = useState<string | null>(null);
  const [appendState, setAppendState] = useState<WorldSnapshotAppendState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const selectionKey = evidenceSelectionKey(worldModel.id, selectedArticles, selectedPolicies);
  const isHumanConfirmed = selectedArticles.length > 0
    && confirmedSelectionKey === selectionKey;
  const isSubmitting = appendState.status === "submitting";
  const isRevisionConflict = appendState.status === "error"
    && isStaleEvidenceRevisionError(appendState.error);
  const isAmbiguousResult = appendState.status === "error"
    && isAmbiguousPostResultError(appendState.error);
  const canAppend = selectedArticles.length > 0
    && selectedArticles.length + selectedPolicies.length <= maximumEvidenceCount
    && isHumanConfirmed
    && !isSubmitting
    && !isRevisionConflict
    && !isAmbiguousResult;

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  useEffect(() => {
    setConfirmedSelectionKey(null);
    if (activeController.current === null) {
      setAppendState({ status: "idle" });
    }
  }, [selectionKey]);

  const submitSnapshot = async (): Promise<void> => {
    if (!canAppend || activeController.current !== null) {
      return;
    }

    let request: WorldSnapshotCreateRequest;

    try {
      request = buildWorldSnapshotCreateRequest(selectedArticles, selectedPolicies);
    } catch (error: unknown) {
      setAppendState({ status: "error", error: normalizeWorldSnapshotAppendError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setAppendState({ status: "submitting" });

    try {
      const snapshot = await appendWorldSnapshot(worldModel.id, request, controller.signal);

      if (activeController.current !== controller || controller.signal.aborted) {
        return;
      }

      setConfirmedSelectionKey(null);
      setAppendState({ status: "success", snapshot });
      onAppended(snapshot);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      if (activeController.current !== controller) {
        return;
      }

      setAppendState({ status: "error", error: normalizeWorldSnapshotAppendError(error) });
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  };

  const resetStaleEvidence = (): void => {
    if (activeController.current !== null) {
      return;
    }

    setConfirmedSelectionKey(null);
    setAppendState({ status: "idle" });
    onResetStaleEvidence();
  };

  const verifyAmbiguousResult = (): void => {
    if (activeController.current !== null) {
      return;
    }

    setConfirmedSelectionKey(null);
    setAppendState({ status: "idle" });
    onVerifyAmbiguousResult();
  };

  return (
    <section className="world-snapshot-appender" aria-labelledby="world-snapshot-appender-title">
      <div className="world-snapshot-appender-heading">
        <div>
          <span>追加版本</span>
          <h4 id="world-snapshot-appender-title">把当前媒体与政策选择冻结为下一版</h4>
          <p>沿用上方精确媒体修订和政策版本；旧版本保持不变，提交不会自动重试。</p>
        </div>
        <strong>
          {selectedArticles.length} 篇媒体 · {selectedPolicies.length} 份政策
        </strong>
      </div>

      {selectedArticles.length === 0 ? (
        <div className="world-snapshot-append-empty" role="status">
          先在上方媒体流明确选择证据，再为“{worldModel.title}”追加版本。
        </div>
      ) : (
        <label className="world-human-confirmation world-snapshot-append-confirmation">
          <input
            type="checkbox"
            checked={isHumanConfirmed}
            disabled={isSubmitting}
            onChange={(event) => {
              setConfirmedSelectionKey(event.target.checked ? selectionKey : null);
              setAppendState({ status: "idle" });
            }}
          />
          <span>
            <strong>
              我已重新核验 {selectedArticles.length} 篇媒体和 {selectedPolicies.length}
              份政策版本，并确认追加到此模型
            </strong>
            <small>证据选择、顺序或目标模型变化后，本次确认立即失效。</small>
          </span>
        </label>
      )}

      {appendState.status === "error" ? (
        <div className="world-create-message world-create-error world-snapshot-append-message" role="alert">
          <strong>
            {isRevisionConflict
              ? "证据修订冲突，未创建新版本"
              : isAmbiguousResult
                ? "提交结果不确定，请先刷新档案核对"
                : "新版本未创建"}
          </strong>
          <p>{appendState.error.message}</p>
          <small>
            {isRevisionConflict
              ? "服务器返回 409：媒体内容已变化，必须清空选择、刷新并重新人工确认。"
              : "追加请求不会自动重试，避免一次人工确认生成多个版本。"}
          </small>
          {isRevisionConflict ? (
            <button
              className="button button-secondary button-compact"
              type="button"
              onClick={resetStaleEvidence}
            >
              清空选择并刷新媒体
            </button>
          ) : null}
          {isAmbiguousResult ? (
            <button
              className="button button-secondary button-compact"
              type="button"
              onClick={verifyAmbiguousResult}
            >
              刷新档案并核对版本
            </button>
          ) : null}
        </div>
      ) : null}

      {appendState.status === "success" ? (
        <div className="world-create-message world-create-success world-snapshot-append-message" role="status">
          已追加 v{appendState.snapshot.version}，档案正在刷新并已显式切换到新版本。
        </div>
      ) : null}

      <button
        className="button button-primary world-snapshot-append-action"
        type="button"
        data-testid="append-world-snapshot"
        disabled={!canAppend}
        aria-busy={isSubmitting}
        onClick={() => void submitSnapshot()}
      >
        {isSubmitting
          ? "正在追加不可变快照…"
          : `人工确认并追加 v${worldModel.latest_snapshot.version + 1}`}
      </button>
    </section>
  );
}

function WorldModelDetailView({
  worldModel,
  snapshot,
  selectedArticles,
  selectedPolicies,
  onSelectSnapshot,
  onSnapshotAppended,
  onResetStaleEvidence,
  onVerifyAmbiguousResult,
}: {
  readonly worldModel: WorldModelDetail;
  readonly snapshot: SnapshotDetail;
  readonly selectedArticles: readonly MediaArticle[];
  readonly selectedPolicies: readonly PolicyDocumentSummary[];
  readonly onSelectSnapshot: (snapshotId: string | null) => void;
  readonly onSnapshotAppended: (snapshot: SnapshotDetail) => void;
  readonly onResetStaleEvidence: () => void;
  readonly onVerifyAmbiguousResult: () => void;
}): JSX.Element {
  const history = [...worldModel.snapshots].reverse();

  return (
    <div className="world-model-detail-content">
      <div className="world-detail-heading">
        <div>
          <span className="world-human-verified">人工冻结声明</span>
          <h3>{worldModel.title}</h3>
          <p>
            模型创建于 {formatMediaTimestamp(worldModel.created_at)} · 正在核验 v{snapshot.version}
          </p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>GET /api/v2/world-models/&#123;id&#125;</code>
          <code>GET /api/v2/world-models/&#123;id&#125;/snapshots/&#123;snapshot_id&#125;</code>
          <code>POST /api/v2/world-models/&#123;id&#125;/snapshots</code>
        </details>
      </div>

      <dl className="world-snapshot-ledger" aria-label="当前选定不可变快照摘要">
        <div><dt>选定版本</dt><dd>v{snapshot.version}</dd></div>
        <div>
          <dt>冻结证据</dt>
          <dd>
            {formatMediaCount(snapshot.evidence.length)} · {snapshot.policy_evidence.length} 份政策
          </dd>
        </div>
        <div><dt>确认方式</dt><dd>人工确认</dd></div>
        <div><dt>冻结时间</dt><dd>{formatMediaTimestamp(snapshot.created_at)}</dd></div>
      </dl>

      <div className="world-snapshot-hash">
        <span>snapshot_sha256 · 冻结内容地址</span>
        <code>{snapshot.snapshot_sha256}</code>
      </div>

      <section className="world-version-history" aria-labelledby="world-version-history-title">
        <div>
          <h4 id="world-version-history-title">版本记录</h4>
          <p>每个版本都是独立快照；新版本不会覆盖旧版本。</p>
        </div>
        <ol>
          {history.map((version) => (
            <li key={version.id} data-current={version.id === snapshot.id}>
              <button
                type="button"
                data-testid={`world-snapshot-version-${version.version}`}
                data-current={version.id === snapshot.id}
                aria-pressed={version.id === snapshot.id}
                onClick={() => onSelectSnapshot(
                  version.id === worldModel.latest_snapshot.id ? null : version.id,
                )}
              >
                <strong>v{version.version}</strong>
                <span>
                  {version.evidence_count} 篇 · {version.policy_evidence_count} 份政策
                </span>
                <time dateTime={version.created_at}>{formatMediaTimestamp(version.created_at)}</time>
                <code title={version.snapshot_sha256}>{abbreviatedDigest(version.snapshot_sha256)}</code>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <WorldSnapshotAppender
        key={worldModel.id}
        worldModel={worldModel}
        selectedArticles={selectedArticles}
        selectedPolicies={selectedPolicies}
        onAppended={onSnapshotAppended}
        onResetStaleEvidence={onResetStaleEvidence}
        onVerifyAmbiguousResult={onVerifyAmbiguousResult}
      />

      <EvidenceWorldGraph
        key={`evidence-graph:${snapshot.id}`}
        worldModelId={worldModel.id}
        snapshotId={snapshot.id}
      />

      <SemanticWorldGraph
        key={`semantic-graph:${snapshot.id}`}
        worldModelId={worldModel.id}
        snapshotId={snapshot.id}
      />

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

      {snapshot.policy_evidence.length === 0 ? null : (
        <section
          className="world-frozen-evidence world-frozen-policy-evidence"
          aria-labelledby="world-frozen-policy-evidence-title"
        >
          <div className="world-frozen-evidence-heading">
            <div>
              <h4 id="world-frozen-policy-evidence-title">冻结政策证据</h4>
              <p>政策来源、具体版本、效力日期和正文哈希均已复制进此快照。</p>
            </div>
            <span>{snapshot.policy_evidence.length} 份</span>
          </div>
          <div className="world-snapshot-evidence-list">
            {snapshot.policy_evidence.map((evidence) => (
              <SnapshotPolicyEvidenceArticle
                evidence={evidence}
                key={evidence.policy_version_id}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function WorldModelDetailPanel({
  selectedWorldModelId,
  selectedSnapshotId,
  selectedArticles,
  selectedPolicies,
  worldModelState,
  snapshotState,
  onReloadWorldModel,
  onReloadSnapshot,
  onSelectSnapshot,
  onSnapshotAppended,
  onResetStaleEvidence,
  onVerifyAmbiguousResult,
}: {
  readonly selectedWorldModelId: string | null;
  readonly selectedSnapshotId: string | null;
  readonly selectedArticles: readonly MediaArticle[];
  readonly selectedPolicies: readonly PolicyDocumentSummary[];
  readonly worldModelState: WorldModelDetailLoadState;
  readonly snapshotState: WorldSnapshotDetailLoadState;
  readonly onReloadWorldModel: () => void;
  readonly onReloadSnapshot: () => void;
  readonly onSelectSnapshot: (snapshotId: string | null) => void;
  readonly onSnapshotAppended: (snapshot: SnapshotDetail) => void;
  readonly onResetStaleEvidence: () => void;
  readonly onVerifyAmbiguousResult: () => void;
}): JSX.Element {
  const loadedWorldModel = worldModelState.status === "idle" ? null : worldModelState.data;
  const worldModel = selectedWorldModelId !== null && loadedWorldModel?.id === selectedWorldModelId
    ? loadedWorldModel
    : null;
  const loadedSnapshot = snapshotState.status === "idle" ? null : snapshotState.data;
  const historicalSnapshot = selectedSnapshotId !== null
    && loadedSnapshot?.world_model_id === selectedWorldModelId
    && loadedSnapshot.id === selectedSnapshotId
    ? loadedSnapshot
    : null;
  const snapshot = selectedSnapshotId === null
    ? worldModel?.latest_snapshot ?? null
    : historicalSnapshot;
  const isLoading = worldModelState.status === "loading"
    || (selectedSnapshotId !== null && snapshotState.status === "loading");

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
      aria-busy={isLoading}
    >
      {worldModelState.status === "error" ? (
        <ApiErrorPanel
          title="无法读取不可变快照"
          error={worldModelState.error}
          isRetrying={worldModelState.isRetrying}
          onRetry={onReloadWorldModel}
        />
      ) : null}

      {snapshotState.status === "error" && selectedSnapshotId !== null ? (
        <ApiErrorPanel
          title="无法读取选定的历史快照"
          error={snapshotState.error}
          isRetrying={snapshotState.isRetrying}
          onRetry={onReloadSnapshot}
        />
      ) : null}

      {isLoading && snapshot === null ? (
        <div className="world-detail-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取选定的不可变快照</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {worldModel !== null && snapshot !== null ? (
        <WorldModelDetailView
          worldModel={worldModel}
          snapshot={snapshot}
          selectedArticles={selectedArticles}
          selectedPolicies={selectedPolicies}
          onSelectSnapshot={onSelectSnapshot}
          onSnapshotAppended={onSnapshotAppended}
          onResetStaleEvidence={onResetStaleEvidence}
          onVerifyAmbiguousResult={onVerifyAmbiguousResult}
        />
      ) : null}
    </section>
  );
}

export function WorldModelPage({
  route,
  onRouteChange,
}: {
  readonly route: WorldRoute;
  readonly onRouteChange: (route: WorldRoute) => void;
}): JSX.Element {
  const [draftQuery, setDraftQuery] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [page, setPage] = useState<number>(1);
  const [policyPage, setPolicyPage] = useState<number>(1);
  const [selectedArticles, setSelectedArticles] = useState<readonly MediaArticle[]>([]);
  const [selectedPolicies, setSelectedPolicies] = useState<readonly PolicyDocumentSummary[]>([]);
  const [isHumanConfirmed, setIsHumanConfirmed] = useState<boolean>(false);
  const [handoffError, setHandoffError] = useState<Error | null>(null);
  const hydratedEvidenceId = useRef<string | null>(null);
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
  const policyDirectory = usePolicyDocuments(policyPage);
  const { state: worldModelsState, reload: reloadWorldModels } = useWorldModels();
  const selectedWorldModelId = route.worldModelId;
  const selectedSnapshotId = route.snapshotId;
  const {
    state: worldModelDetailState,
    reload: reloadWorldModelDetail,
  } = useWorldModelDetail(selectedWorldModelId);
  const {
    state: worldSnapshotDetailState,
    reload: reloadWorldSnapshotDetail,
  } = useWorldSnapshotDetail(selectedWorldModelId, selectedSnapshotId);
  const selectedWorldModel = selectedWorldModelId === null
    ? null
    : worldModelsState.data?.items.find((worldModel) => worldModel.id === selectedWorldModelId) ?? null;
  const loadedWorldModel = worldModelDetailState.status === "idle"
    ? null
    : worldModelDetailState.data;
  const activeWorldModelDetail = loadedWorldModel?.id === selectedWorldModelId
    ? loadedWorldModel
    : null;
  const loadedSelectedSnapshot = worldSnapshotDetailState.status === "idle"
    ? null
    : worldSnapshotDetailState.data;
  const selectedSnapshot = selectedSnapshotId === null
    ? activeWorldModelDetail?.latest_snapshot ?? null
    : loadedSelectedSnapshot?.id === selectedSnapshotId
      && loadedSelectedSnapshot.world_model_id === selectedWorldModelId
      ? loadedSelectedSnapshot
      : null;

  useEffect(() => {
    if (route.evidenceId === null) {
      hydratedEvidenceId.current = null;
      setHandoffError(null);
      return undefined;
    }
    if (hydratedEvidenceId.current === route.evidenceId) return undefined;
    const controller = new AbortController();
    setHandoffError(null);
    void fetchMediaArticle(route.evidenceId, controller.signal)
      .then((article) => {
        setSelectedArticles((current) => current.some((item) => item.id === article.id)
          ? current
          : current.length >= maximumEvidenceCount
            ? current
            : [...current, article]);
        setIsHumanConfirmed(false);
        hydratedEvidenceId.current = article.id;
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setHandoffError(error instanceof Error
          ? error
          : new Error("读取移交报道时收到非标准错误。"));
      });
    return () => controller.abort();
  }, [route.evidenceId]);

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
    onRouteChange({ ...route, worldModelId: worldModel.id, snapshotId: null });
  };

  const worldModelCreated = (worldModel: WorldModelDetail): void => {
    onRouteChange({ ...route, worldModelId: worldModel.id, snapshotId: null });
    reloadWorldModels();
  };

  const snapshotAppended = (snapshot: SnapshotDetail): void => {
    onRouteChange({ ...route, worldModelId: snapshot.world_model_id, snapshotId: snapshot.id });
    reloadWorldModelDetail();
    reloadWorldModels();
  };

  const resetStaleEvidence = (): void => {
    setSelectedArticles([]);
    setIsHumanConfirmed(false);
    reloadMedia();
  };

  const verifyAmbiguousAppendResult = (): void => {
    onRouteChange({ worldModelId: null, snapshotId: null, evidenceId: null });
    reloadWorldModels();
  };

  const selectSnapshot = (snapshotId: string | null): void => {
    if (selectedWorldModelId === null) {
      throw new Error("Cannot select a World snapshot without a selected WorldModel.");
    }
    onRouteChange({ ...route, worldModelId: selectedWorldModelId, snapshotId });
  };

  return (
    <div className="world-model-page decision-surface decision-world-surface">
      <header className="decision-surface-header" aria-labelledby="world-model-page-title">
        <div className="decision-surface-heading">
          <span className="decision-stage-index">02 · 现实版本室</span>
          <div>
            <h2 id="world-model-page-title">把核验过的证据冻结成共同现实</h2>
            <p>研究员明确选择媒体修订与政策版本，让后续实验始终回到同一个可复核现实。</p>
          </div>
        </div>
        <div className="decision-context-bar">
          <div className="decision-context-current" data-active={selectedArticles.length > 0}>
            <span>待冻结证据</span>
            <strong>
              {selectedArticles.length === 0 && selectedPolicies.length === 0
                ? "尚未选择证据"
                : `${selectedArticles.length} 篇媒体 · ${selectedPolicies.length} 份政策`}
            </strong>
            <small>{isHumanConfirmed ? "人工冻结声明已确认" : "选择变化后需要重新确认"}</small>
          </div>
          <div className="decision-context-current" data-active={selectedWorldModel !== null}>
            <span>档案核验对象</span>
            <strong>{selectedWorldModel?.title ?? "尚未选择历史快照"}</strong>
            <small>
              {selectedWorldModel === null
                ? "从下方档案明确打开一个版本。"
                : selectedSnapshot === null
                  ? "正在读取明确选定的快照…"
                  : `v${selectedSnapshot.version} · ${selectedSnapshot.evidence.length} 篇媒体 · ${selectedSnapshot.policy_evidence.length} 份政策`}
            </small>
          </div>
          <ul className="decision-boundary-legend" aria-label="世界模型边界">
            <li data-boundary="candidate"><span />媒体修订</li>
            <li data-boundary="human"><span />人工确认</li>
            <li data-boundary="immutable"><span />不可变快照</li>
          </ul>
        </div>
      </header>

      <WorldPolicyEvidenceSelector
        state={policyDirectory.state}
        page={policyPage}
        selectedPolicies={selectedPolicies}
        mediaEvidenceCount={selectedArticles.length}
        disabled={false}
        onChangePage={setPolicyPage}
        onChange={setSelectedPolicies}
        onReload={policyDirectory.reload}
        onInvalidateConfirmation={() => setIsHumanConfirmed(false)}
      />

      <WorldModelBuilder
        appliedQuery={appliedQuery}
        draftQuery={draftQuery}
        mediaState={mediaState}
        page={page}
        selectedArticles={selectedArticles}
        selectedPolicies={selectedPolicies}
        isHumanConfirmed={isHumanConfirmed}
        onChangeDraftQuery={setDraftQuery}
        onChangePage={setPage}
        onChangeSelectedArticles={setSelectedArticles}
        onChangeSelectedPolicies={setSelectedPolicies}
        onChangeHumanConfirmed={setIsHumanConfirmed}
        onClearSearch={clearSearch}
        onReloadMedia={reloadMedia}
        onSearch={submitSearch}
        onCreated={worldModelCreated}
      />

      {route.evidenceId === null ? null : (
        <section className="world-evidence-handoff" aria-live="polite">
          <div>
            <span>Media → World</span>
            <strong>
              {handoffError === null
                ? hydratedEvidenceId.current === route.evidenceId
                  ? "报道已加入待冻结证据"
                  : "正在核验移交报道…"
                : "移交报道读取失败"}
            </strong>
            <p>系统只带入文章身份和当前证据修订；人工冻结声明仍需你在本页明确确认。</p>
          </div>
          {handoffError === null ? null : <p role="alert">{handoffError.message}</p>}
          <button
            type="button"
            className="button button-secondary button-compact"
            onClick={() => onRouteChange({ ...route, evidenceId: null })}
          >
            结束移交上下文
          </button>
        </section>
      )}

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
            selectedSnapshotId={selectedSnapshotId}
            selectedArticles={selectedArticles}
            selectedPolicies={selectedPolicies}
            worldModelState={worldModelDetailState}
            snapshotState={worldSnapshotDetailState}
            onReloadWorldModel={reloadWorldModelDetail}
            onReloadSnapshot={reloadWorldSnapshotDetail}
            onSelectSnapshot={selectSnapshot}
            onSnapshotAppended={snapshotAppended}
            onResetStaleEvidence={resetStaleEvidence}
            onVerifyAmbiguousResult={verifyAmbiguousAppendResult}
          />
        </div>
      </section>
    </div>
  );
}
