import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { ApiRequestError } from "./apiClient";
import {
  type Company,
  type CompanyCoverageItem,
  type CompanyCoverageResponse,
} from "./companyContracts";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import { useCompanies, type CompaniesLoadState } from "./useCompanies";
import {
  useCompanyCoverage,
  type CompanyCoverageLoadState,
} from "./useCompanyCoverage";
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
import "./decisionWorkspace.css";

const coveragePageSize = 50;

type WorldModelCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly worldModel: WorldModelDetail }
  | { readonly status: "error"; readonly error: Error };

interface WorldModelBuilderProps {
  readonly companiesState: CompaniesLoadState;
  readonly selectedCompany: Company | null;
  readonly coverageState: CompanyCoverageLoadState;
  readonly selectedArticleIds: readonly string[];
  readonly isHumanConfirmed: boolean;
  readonly onSelectCompany: (company: Company) => void;
  readonly onChangeSelectedArticleIds: (articleIds: readonly string[]) => void;
  readonly onChangeHumanConfirmed: (isConfirmed: boolean) => void;
  readonly onReloadCompanies: () => void;
  readonly onReloadCoverage: () => void;
  readonly onCreated: (worldModel: WorldModelDetail) => void;
}

interface CandidateEvidenceSelectorProps {
  readonly response: CompanyCoverageResponse;
  readonly selectedArticleIds: readonly string[];
  readonly disabled: boolean;
  readonly isRequestActive: () => boolean;
  readonly onChange: (articleIds: readonly string[]) => void;
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

function BuilderSkeleton(): JSX.Element {
  return (
    <div className="world-builder-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取企业名称命中候选</span>
      {Array.from({ length: 3 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function CandidateContext({ item }: { readonly item: CompanyCoverageItem }): JSX.Element {
  return (
    <div className="world-candidate-context">
      <div className="world-candidate-aliases">
        <span>命中</span>
        {item.matched_aliases.map((alias) => (
          <mark key={alias}>{alias}</mark>
        ))}
      </div>
      <ul>
        {item.evidence_contexts.map((context, index) => (
          <li key={`${context.alias}-${context.start_offset}-${context.end_offset}-${index}`}>
            <q>{context.context}</q>
            <small>
              “{context.alias}” · 原文字符 {context.start_offset}–{context.end_offset}
            </small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CandidateEvidenceSelector({
  response,
  selectedArticleIds,
  disabled,
  isRequestActive,
  onChange,
  onInvalidateConfirmation,
}: CandidateEvidenceSelectorProps): JSX.Element {
  const selectedIds = new Set(selectedArticleIds);
  const allArticleIds = response.items.map((item) => item.article.id);
  const allSelected = allArticleIds.length > 0
    && allArticleIds.every((articleId) => selectedIds.has(articleId));

  const toggleArticle = (articleId: string, isSelected: boolean): void => {
    if (disabled || isRequestActive()) {
      return;
    }

    const nextArticleIds = isSelected
      ? [...selectedArticleIds, articleId]
      : selectedArticleIds.filter((selectedId) => selectedId !== articleId);

    onChange(nextArticleIds);
    onInvalidateConfirmation();
  };

  const selectAll = (): void => {
    if (disabled || isRequestActive()) {
      return;
    }

    onChange(allSelected ? [] : allArticleIds);
    onInvalidateConfirmation();
  };

  return (
    <fieldset className="world-evidence-fieldset" disabled={disabled}>
      <legend>选择要冻结的报道证据</legend>
      <div className="world-evidence-toolbar">
        <p>
          仅显示前 {coveragePageSize} 条真实名称候选；逐条阅读上下文后再勾选。
          <strong>{selectedArticleIds.length} / {response.items.length} 已选</strong>
        </p>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={response.items.length === 0}
          onClick={selectAll}
        >
          {allSelected ? "清空选择" : "全选当前候选"}
        </button>
      </div>
      {response.items.length === 0 ? (
        <div className="world-builder-empty" role="status">
          <strong>该企业没有名称命中候选</strong>
          <p>先在“企业证据”工作区补充规范名称或别名，再回到这里进行人工语义确认。</p>
        </div>
      ) : (
        <ul className="world-candidate-list">
          {response.items.map((item) => {
            const inputId = `world-evidence-${item.article.id}`;
            const descriptionId = `world-evidence-description-${item.article.id}`;
            const isSelected = selectedIds.has(item.article.id);

            return (
              <li key={item.article.id} data-selected={isSelected}>
                <div className="world-candidate-heading">
                  <input
                    id={inputId}
                    type="checkbox"
                    checked={isSelected}
                    aria-describedby={descriptionId}
                    onChange={(event) => toggleArticle(item.article.id, event.target.checked)}
                  />
                  <label htmlFor={inputId}>
                    <strong>{item.article.title}</strong>
                    <span>
                      {item.article.source_name} · {formatMediaTimestamp(item.article.published_at)}
                      {item.article.country_code === null ? "" : ` · ${item.article.country_code}`}
                    </span>
                  </label>
                  <a
                    href={item.article.original_url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`打开原文：${item.article.title}`}
                  >
                    原文 ↗
                  </a>
                </div>
                <p id={descriptionId} className="world-candidate-excerpt">
                  {item.article.excerpt}
                </p>
                <CandidateContext item={item} />
              </li>
            );
          })}
        </ul>
      )}
    </fieldset>
  );
}

function WorldModelBuilder({
  companiesState,
  selectedCompany,
  coverageState,
  selectedArticleIds,
  isHumanConfirmed,
  onSelectCompany,
  onChangeSelectedArticleIds,
  onChangeHumanConfirmed,
  onReloadCompanies,
  onReloadCoverage,
  onCreated,
}: WorldModelBuilderProps): JSX.Element {
  const [title, setTitle] = useState<string>("");
  const [creationState, setCreationState] = useState<WorldModelCreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const companies = companiesState.data?.items ?? [];
  const loadedCoverage = coverageState.status === "idle" ? null : coverageState.data;
  const coverage = selectedCompany !== null && loadedCoverage?.company.id === selectedCompany.id
    ? loadedCoverage
    : null;
  const isSubmitting = creationState.status === "submitting";
  const hasStaleEvidenceRevision = creationState.status === "error"
    && isStaleEvidenceRevisionError(creationState.error);
  const isCoverageReady = coverage !== null && coverageState.status === "success";
  const canSubmit = selectedCompany !== null
    && title.trim() !== ""
    && selectedArticleIds.length > 0
    && isHumanConfirmed
    && isCoverageReady
    && !isSubmitting;

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  const submitWorldModel = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (!canSubmit || activeController.current !== null || selectedCompany === null) {
      return;
    }

    if (coverage === null) {
      setCreationState({
        status: "error",
        error: new Error("无法冻结世界模型：当前企业证据尚未完整加载。请刷新候选并重新阅读确认。"),
      });
      return;
    }

    let request: WorldModelCreateRequest;

    try {
      request = buildWorldModelCreateRequest(
        title,
        selectedCompany.id,
        selectedArticleIds,
        coverage.items,
      );
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
      onChangeSelectedArticleIds([]);
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

    onChangeSelectedArticleIds([]);
    onChangeHumanConfirmed(false);
    setCreationState({ status: "idle" });
    onReloadCoverage();
  };

  return (
    <section className="world-model-builder" aria-labelledby="world-builder-title">
      <div className="world-section-heading">
        <div>
          <span>当前任务</span>
          <h3 id="world-builder-title">核验候选并冻结现实版本</h3>
          <p>在中间逐篇阅读原文上下文；右侧动作只会冻结明确勾选且经人确认的证据。</p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>POST /api/v2/world-models</code>
        </details>
      </div>

      <form onSubmit={(event) => void submitWorldModel(event)}>
        <div className="world-builder-cockpit">
          <aside className="world-builder-controls decision-context-rail" aria-label="世界模型上下文">
            <div className="decision-rail-heading">
              <span>现实对象</span>
              <strong>{selectedCompany?.canonical_name ?? "未选择企业"}</strong>
              <small>企业选择必须由本次任务明确指定。</small>
            </div>
            <label>
              <span>企业档案</span>
              <select
                id="world-model-company"
                name="company_id"
                value={selectedCompany?.id ?? ""}
                required
                disabled={companies.length === 0 || isSubmitting}
                onChange={(event) => {
                  if (isSubmitting || activeController.current !== null) {
                    return;
                  }

                  const company = companies.find((candidate) => candidate.id === event.target.value);

                  if (company === undefined) {
                    throw new Error(
                      `Company selection is missing from the loaded directory: ${event.target.value}`,
                    );
                  }

                  setCreationState({ status: "idle" });
                  onSelectCompany(company);
                }}
              >
                <option value="" disabled>
                  {companies.length === 0 ? "暂无企业档案" : "请选择企业档案"}
                </option>
                {companies.map((company) => (
                  <option value={company.id} key={company.id}>
                    {company.canonical_name}
                  </option>
                ))}
              </select>
            </label>
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
                placeholder="例如：华为全球媒体环境 · 2026 Q3"
                onChange={(event) => {
                  if (isSubmitting || activeController.current !== null) {
                    return;
                  }

                  setTitle(event.target.value);
                  setCreationState({ status: "idle" });
                }}
              />
            </label>

            {companiesState.status === "error" ? (
              <ApiErrorPanel
                title="无法读取企业档案"
                error={companiesState.error}
                isRetrying={companiesState.isRetrying}
                onRetry={onReloadCompanies}
              />
            ) : null}

            {companiesState.status === "loading" && companiesState.data === null ? (
              <BuilderSkeleton />
            ) : null}

            {companiesState.data !== null && companies.length === 0 ? (
              <div className="world-builder-empty" role="status">
                <strong>还没有可建模的企业</strong>
                <p>先在“企业证据”建立企业档案；世界模型不接受没有企业身份的孤立报道。</p>
              </div>
            ) : null}
          </aside>

          <div className="world-evidence-stage decision-main-stage">
            <div className="decision-stage-heading">
              <span>候选证据</span>
              <strong>
                {coverage === null
                  ? "等待企业上下文"
                  : `${coverage.items.length} 条可见名称候选`}
              </strong>
            </div>

            {selectedCompany === null ? (
              <div className="decision-stage-empty" role="status">
                <strong>先明确本次冻结的企业</strong>
                <p>选择后才会载入报道候选；不会自动打开目录中的第一家企业。</p>
              </div>
            ) : null}

            {selectedCompany !== null && coverageState.status === "error" ? (
              <ApiErrorPanel
                title={`无法读取“${selectedCompany.canonical_name}”的报道候选`}
                error={coverageState.error}
                isRetrying={coverageState.isRetrying}
                onRetry={onReloadCoverage}
              />
            ) : null}

            {selectedCompany !== null && coverageState.status === "loading" && coverage === null ? (
              <BuilderSkeleton />
            ) : null}

            {coverage !== null ? (
              <CandidateEvidenceSelector
                response={coverage}
                selectedArticleIds={selectedArticleIds}
                disabled={isSubmitting || coverageState.status === "loading"}
                isRequestActive={() => activeController.current !== null}
                onChange={onChangeSelectedArticleIds}
                onInvalidateConfirmation={() => onChangeHumanConfirmed(false)}
              />
            ) : null}
          </div>

          <aside className="world-freeze-inspector decision-inspector" aria-label="冻结动作与边界">
            <div className="decision-inspector-heading">
              <span>冻结动作</span>
              <h4>建立 v1 现实版本</h4>
            </div>
            <div className="world-freeze-note">
              <strong>不可变边界</strong>
              <p>保存企业身份、来源、正文哈希与命中字符位置；之后导入的新报道不会改写它。</p>
            </div>
            <dl className="decision-context-ledger">
              <div><dt>当前企业</dt><dd>{selectedCompany?.canonical_name ?? "未选择"}</dd></div>
              <div><dt>冻结证据</dt><dd>{selectedArticleIds.length} 篇</dd></div>
              <div><dt>人工声明</dt><dd>{isHumanConfirmed ? "已确认" : "未确认"}</dd></div>
            </dl>

            {coverage !== null && coverage.items.length > 0 ? (
              <label className="world-human-confirmation">
                <input
                  type="checkbox"
                  checked={isHumanConfirmed}
                  disabled={!isCoverageReady || selectedArticleIds.length === 0 || isSubmitting}
                  onChange={(event) => {
                    if (isSubmitting || activeController.current !== null) {
                      return;
                    }

                    onChangeHumanConfirmed(event.target.checked);
                    setCreationState({ status: "idle" });
                  }}
                />
                <span>
                  <strong>我已阅读上下文，确认所选报道指向该企业</strong>
                  <small>这是人工语义声明，不是名称匹配自动得出的结论。</small>
                </span>
              </label>
            ) : null}

            {creationState.status === "error" ? (
              <div className="world-create-message world-create-error" role="alert">
                <strong>
                  {hasStaleEvidenceRevision
                    ? "报道已更新，请重新阅读确认"
                    : "世界模型未创建"}
                </strong>
                <p>{creationState.error.message}</p>
                {hasStaleEvidenceRevision ? (
                  <button
                    className="button button-secondary button-compact"
                    type="button"
                    onClick={reloadStaleEvidence}
                  >
                    刷新候选并重新核验
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
              type="submit"
              disabled={!canSubmit}
              aria-busy={isSubmitting}
            >
              {isSubmitting ? "正在冻结证据…" : `确认并创建 v1 · ${selectedArticleIds.length} 篇`}
            </button>
          </aside>
        </div>
      </form>
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
          <p>完成上方人工语义确认后，第一个世界模型和版本 1 会出现在这里。</p>
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
                    <small>
                      {worldModel.company_name} · {worldModel.latest_snapshot.evidence_count} 篇证据
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
        <a href={evidence.original_url} target="_blank" rel="noreferrer">
          回查原文 ↗
        </a>
      </div>
      <h5>{evidence.title}</h5>
      <p>{evidence.excerpt}</p>
      <div className="world-snapshot-aliases" aria-label="人工确认时的命中别名">
        <strong>冻结命中</strong>
        <span>
          {evidence.matched_aliases.map((alias) => (
            <mark key={alias}>{alias}</mark>
          ))}
        </span>
      </div>
      <ul className="world-snapshot-contexts">
        {evidence.evidence_contexts.map((context, index) => (
          <li key={`${context.alias}-${context.start_offset}-${context.end_offset}-${index}`}>
            <q>{context.context}</q>
            <small>
              “{context.alias}” · 冻结字符 {context.start_offset}–{context.end_offset}
            </small>
          </li>
        ))}
      </ul>
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
          <span className="world-human-verified">人工确认声明</span>
          <h3>{worldModel.title}</h3>
          <p>创建于 {formatMediaTimestamp(worldModel.created_at)}</p>
        </div>
        <details className="decision-diagnostics">
          <summary>接口诊断</summary>
          <code>GET /api/v2/world-models/&#123;id&#125;</code>
        </details>
      </div>

      <dl className="world-snapshot-ledger" aria-label="最新不可变快照摘要">
        <div>
          <dt>当前版本</dt>
          <dd>v{snapshot.version}</dd>
        </div>
        <div>
          <dt>冻结证据</dt>
          <dd>{formatMediaCount(snapshot.evidence.length)}</dd>
        </div>
        <div>
          <dt>确认方式</dt>
          <dd>人工声明</dd>
        </div>
        <div>
          <dt>冻结时间</dt>
          <dd>{formatMediaTimestamp(snapshot.created_at)}</dd>
        </div>
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

      <section className="world-frozen-company" aria-labelledby="world-frozen-company-title">
        <div>
          <h4 id="world-frozen-company-title">冻结企业身份</h4>
          <p>这里展示的是建模时的企业名称与别名，不随档案后续修改。</p>
        </div>
        <div className="world-frozen-company-identity">
          <span aria-hidden="true">{snapshot.company.canonical_name.slice(0, 1)}</span>
          <div>
            <strong>{snapshot.company.canonical_name}</strong>
            <small>
              {snapshot.company.aliases.length === 0
                ? "快照中没有额外别名"
                : snapshot.company.aliases.join(" · ")}
            </small>
          </div>
        </div>
      </section>

      <section className="world-frozen-evidence" aria-labelledby="world-frozen-evidence-title">
        <div className="world-frozen-evidence-heading">
          <div>
            <h4 id="world-frozen-evidence-title">冻结证据</h4>
            <p>上下文、字符位置和正文哈希均来自创建时刻，可通过原文链接再次核验。</p>
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
          <p>模型创建后，这里会显示完整版本哈希、冻结企业身份和逐篇证据上下文。</p>
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
  const { state: companiesState, reload: reloadCompanies } = useCompanies();
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [selectedArticleIds, setSelectedArticleIds] = useState<readonly string[]>([]);
  const [isHumanConfirmed, setIsHumanConfirmed] = useState<boolean>(false);
  const companyId = selectedCompany?.id ?? null;
  const { state: coverageState, reload: reloadCoverage } = useCompanyCoverage(
    companyId,
    1,
    coveragePageSize,
  );
  const { state: worldModelsState, reload: reloadWorldModels } = useWorldModels();
  const [selectedWorldModelId, setSelectedWorldModelId] = useState<string | null>(null);
  const {
    state: worldModelDetailState,
    reload: reloadWorldModelDetail,
  } = useWorldModelDetail(selectedWorldModelId);
  const loadedCoverage = coverageState.status === "idle" ? null : coverageState.data;
  const selectedCoverage = selectedCompany !== null && loadedCoverage?.company.id === selectedCompany.id
    ? loadedCoverage
    : null;
  const selectedWorldModel = selectedWorldModelId === null
    ? null
    : worldModelsState.data?.items.find((worldModel) => worldModel.id === selectedWorldModelId) ?? null;

  useEffect(() => {
    if (selectedCoverage === null) {
      return;
    }

    const availableArticleIds = new Set(
      selectedCoverage.items.map((item) => item.article.id),
    );

    setSelectedArticleIds((currentIds) =>
      currentIds.filter((articleId) => availableArticleIds.has(articleId)),
    );
    setIsHumanConfirmed(false);
  }, [selectedCoverage]);

  const selectCompany = (company: Company): void => {
    setSelectedCompany(company);
    setSelectedArticleIds([]);
    setIsHumanConfirmed(false);
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
            <p>研究员明确选择企业与报道，保留内容地址，让后续实验始终回到同一个可复核版本。</p>
          </div>
        </div>
        <div className="decision-context-bar">
          <div className="decision-context-current" data-active={selectedCompany !== null}>
            <span>待冻结对象</span>
            <strong>{selectedCompany?.canonical_name ?? "尚未选择企业"}</strong>
            <small>
              {selectedCompany === null
                ? "选择企业后才载入候选，不会沿用上次查看。"
                : `${selectedArticleIds.length} 篇已选 · ${isHumanConfirmed ? "人工声明已勾选" : "等待人工声明"}`}
            </small>
          </div>
          <div className="decision-context-current" data-active={selectedWorldModel !== null}>
            <span>档案核验对象</span>
            <strong>{selectedWorldModel?.title ?? "尚未选择历史快照"}</strong>
            <small>
              {selectedWorldModel === null
                ? "从下方档案明确打开一个版本。"
                : `v${selectedWorldModel.latest_snapshot.version} · ${selectedWorldModel.company_name}`}
            </small>
          </div>
          <ul className="decision-boundary-legend" aria-label="世界模型边界">
            <li data-boundary="candidate"><span />名称候选</li>
            <li data-boundary="human"><span />人工声明</li>
            <li data-boundary="immutable"><span />不可变快照</li>
          </ul>
        </div>
      </header>

      <WorldModelBuilder
        companiesState={companiesState}
        selectedCompany={selectedCompany}
        coverageState={coverageState}
        selectedArticleIds={selectedArticleIds}
        isHumanConfirmed={isHumanConfirmed}
        onSelectCompany={selectCompany}
        onChangeSelectedArticleIds={setSelectedArticleIds}
        onChangeHumanConfirmed={setIsHumanConfirmed}
        onReloadCompanies={reloadCompanies}
        onReloadCoverage={reloadCoverage}
        onCreated={worldModelCreated}
      />

      <section className="world-model-registry decision-archive-stage" aria-labelledby="world-registry-title">
        <div className="world-registry-heading">
          <div>
            <span>版本档案</span>
            <h2 id="world-registry-title">回查冻结时刻的完整证据链</h2>
            <p>这里只在你明确选择后打开模型；版本、企业身份和文章内容地址均保持只读。</p>
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
