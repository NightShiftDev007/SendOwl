import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import {
  createCompany,
  parseCompanyCreateRequest,
  type Company,
  type CompanyCoverageItem,
  type CompanyCoverageResponse,
} from "./companyContracts";
import { MediaArticleSummaryContent } from "./MediaArticleRow";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import { useCompanies, type CompaniesLoadState } from "./useCompanies";
import {
  useCompanyCoverage,
  type CompanyCoverageLoadState,
} from "./useCompanyCoverage";
import "./decisionWorkspace.css";

const coveragePageSize = 20;

type CompanyCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly company: Company }
  | { readonly status: "error"; readonly error: Error };

interface CompanyCreateFormProps {
  readonly onCreated: (company: Company) => void;
}

interface CompanyDirectoryProps {
  readonly state: CompaniesLoadState;
  readonly selectedCompanyId: string | null;
  readonly onSelect: (company: Company) => void;
  readonly onReload: () => void;
  readonly onCreated: (company: Company) => void;
}

interface CompanyCoveragePanelProps {
  readonly company: Company | null;
  readonly state: CompanyCoverageLoadState;
  readonly page: number;
  readonly onPageChange: (page: number) => void;
  readonly onReload: () => void;
}

function normalizeCompanyCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`企业档案输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("创建企业档案失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function CompanyCreateForm({ onCreated }: CompanyCreateFormProps): JSX.Element {
  const [canonicalName, setCanonicalName] = useState<string>("");
  const [aliasesText, setAliasesText] = useState<string>("");
  const [state, setState] = useState<CompanyCreationState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      activeController.current?.abort();
    };
  }, []);

  const submitCompany = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();

    if (state.status === "submitting") {
      return;
    }

    let request;

    try {
      request = parseCompanyCreateRequest(canonicalName, aliasesText);
    } catch (error: unknown) {
      setState({ status: "error", error: normalizeCompanyCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setState({ status: "submitting" });

    try {
      const company = await createCompany(request, controller.signal);

      if (controller.signal.aborted) {
        return;
      }

      setCanonicalName("");
      setAliasesText("");
      setState({ status: "success", company });
      onCreated(company);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      setState({ status: "error", error: normalizeCompanyCreationError(error) });
    } finally {
      if (activeController.current === controller) {
        activeController.current = null;
      }
    }
  };

  return (
    <form className="company-create-form" onSubmit={(event) => void submitCompany(event)}>
      <div className="company-form-heading">
        <h3>添加监控企业</h3>
        <p>规范名称用于建立档案；别名决定哪些报道会进入名称命中候选。</p>
      </div>

      <label>
        <span>企业规范名称</span>
        <input
          id="company-canonical-name"
          name="canonical_name"
          type="text"
          value={canonicalName}
          required
          maxLength={300}
          autoComplete="organization"
          placeholder="输入企业全称"
          onChange={(event) => {
            setCanonicalName(event.target.value);
            setState({ status: "idle" });
          }}
        />
      </label>

      <label>
        <span>已知别名</span>
        <textarea
          id="company-aliases"
          name="aliases"
          value={aliasesText}
          rows={3}
          aria-describedby="company-alias-help"
          placeholder="简称、英文名；使用逗号或换行分隔"
          onChange={(event) => {
            setAliasesText(event.target.value);
            setState({ status: "idle" });
          }}
        />
      </label>

      <p className="company-form-help" id="company-alias-help">
        规范名称也会参与匹配，无需重复填写；字面命中不代表已完成语义消歧。
      </p>

      {state.status === "error" ? (
        <div className="company-form-message company-form-error" role="alert">
          <strong>企业档案未创建</strong>
          <p>{state.error.message}</p>
        </div>
      ) : null}

      {state.status === "success" ? (
        <div className="company-form-message company-form-success" role="status">
          已创建“{state.company.canonical_name}”，正在读取名称命中候选。
        </div>
      ) : null}

      <button
        className="button button-primary"
        type="submit"
        disabled={canonicalName.trim() === "" || state.status === "submitting"}
        aria-busy={state.status === "submitting"}
      >
        {state.status === "submitting" ? "正在创建…" : "创建企业档案"}
      </button>
    </form>
  );
}

function CompanyListSkeleton(): JSX.Element {
  return (
    <div className="company-list-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取企业档案</span>
      {Array.from({ length: 4 }, (_, index) => (
        <span className="skeleton-block" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function CompanyDirectory({
  state,
  selectedCompanyId,
  onSelect,
  onReload,
  onCreated,
}: CompanyDirectoryProps): JSX.Element {
  const response = state.data;
  const isLoading = state.status === "loading";

  return (
    <aside className="company-directory" aria-labelledby="company-directory-title">
      <div className="company-directory-heading">
        <div>
          <h2 id="company-directory-title">监控档案</h2>
          <p>{response === null ? "等待接口返回" : `${formatMediaCount(response.total)} 家企业`}</p>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          disabled={isLoading}
          aria-busy={isLoading}
          onClick={onReload}
        >
          {isLoading ? "读取中…" : "刷新"}
        </button>
      </div>

      <details className="decision-create-disclosure">
        <summary>新建企业档案</summary>
        <CompanyCreateForm onCreated={onCreated} />
      </details>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取企业档案"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && response === null ? <CompanyListSkeleton /> : null}

      {response !== null && response.items.length === 0 ? (
        <div className="company-directory-empty" role="status">
          <strong>还没有企业档案</strong>
          <p>添加企业规范名称和已知别名后，系统会查询真实报道中的字面命中候选。</p>
        </div>
      ) : null}

      {response !== null && response.items.length > 0 ? (
        <ul className="company-list" aria-busy={isLoading}>
          {response.items.map((company) => {
            const isSelected = selectedCompanyId === company.id;

            return (
              <li key={company.id}>
                <button
                  type="button"
                  data-selected={isSelected}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(company)}
                >
                  <span className="company-list-marker" aria-hidden="true">
                    {company.canonical_name.slice(0, 1)}
                  </span>
                  <span className="company-list-copy">
                    <strong>{company.canonical_name}</strong>
                    <small>
                      {company.aliases.length === 0
                        ? "仅匹配规范名称"
                        : company.aliases.join(" · ")}
                    </small>
                    <time dateTime={company.created_at}>
                      建档于 {formatMediaTimestamp(company.created_at)}
                    </time>
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

function CoverageSkeleton(): JSX.Element {
  return (
    <div className="company-coverage-skeleton" role="status" aria-live="polite">
      <span className="sr-only">正在读取企业名称命中候选</span>
      <div className="company-coverage-ledger" aria-hidden="true">
        {Array.from({ length: 4 }, (_, index) => (
          <span className="skeleton-block" key={index} />
        ))}
      </div>
      {Array.from({ length: 3 }, (_, index) => (
        <span className="skeleton-block company-evidence-skeleton-row" aria-hidden="true" key={index} />
      ))}
    </div>
  );
}

function CoverageLedger({ response }: { readonly response: CompanyCoverageResponse }): JSX.Element {
  return (
    <dl className="company-coverage-ledger" aria-label={`${response.company.canonical_name} 名称命中摘要`}>
      <div>
        <dt>名称命中</dt>
        <dd>{formatMediaCount(response.total_matching_articles)}</dd>
      </div>
      <div>
        <dt>媒体来源</dt>
        <dd>{formatMediaCount(response.source_count)}</dd>
      </div>
      <div>
        <dt>涉及国家</dt>
        <dd>{formatMediaCount(response.country_count)}</dd>
      </div>
      <div>
        <dt>关联议题</dt>
        <dd>{formatMediaCount(response.topic_count)}</dd>
      </div>
    </dl>
  );
}

function EvidenceExplanation({ item }: { readonly item: CompanyCoverageItem }): JSX.Element {
  return (
    <div className="evidence-explanation" aria-label="企业名称命中依据">
      <div className="evidence-aliases">
        <strong>命中别名</strong>
        <span>
          {item.matched_aliases.map((alias) => (
            <mark key={alias}>{alias}</mark>
          ))}
        </span>
      </div>
      <ul className="evidence-context-list">
        {item.evidence_contexts.map((evidenceContext, index) => (
          <li key={`${evidenceContext.alias}-${evidenceContext.start_offset}-${evidenceContext.end_offset}-${index}`}>
            <q>{evidenceContext.context}</q>
            <small>
              “{evidenceContext.alias}” · 原文字符 {evidenceContext.start_offset}–{evidenceContext.end_offset}
            </small>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CoverageArticles({
  response,
  isUpdating,
}: {
  readonly response: CompanyCoverageResponse;
  readonly isUpdating: boolean;
}): JSX.Element {
  if (response.items.length === 0) {
    return (
      <div className="company-coverage-empty" role="status">
        <strong>没有找到名称命中候选</strong>
        <p>接口已完成字面名称匹配，当前企业档案在已采集报道中没有命中。</p>
      </div>
    );
  }

  return (
    <div className="company-evidence-list" aria-busy={isUpdating}>
      {isUpdating ? (
        <div className="results-updating" role="status">
          正在更新候选…
        </div>
      ) : null}
      {response.items.map((item) => (
        <article className="media-article-row company-evidence-article" key={item.article.id}>
          <MediaArticleSummaryContent article={item.article} />
          <EvidenceExplanation item={item} />
        </article>
      ))}
    </div>
  );
}

function CompanyCoveragePanel({
  company,
  state,
  page,
  onPageChange,
  onReload,
}: CompanyCoveragePanelProps): JSX.Element {
  const loadedResponse = state.status === "idle" ? null : state.data;
  const response = company !== null && loadedResponse?.company.id === company.id
    ? loadedResponse
    : null;
  const totalPages = response === null
    ? 1
    : Math.max(1, Math.ceil(response.total_matching_articles / response.page_size));
  const isUpdating = state.status === "loading" && response !== null;

  if (company === null) {
    return (
      <section className="company-coverage company-coverage-unselected" aria-labelledby="company-coverage-title">
        <div>
          <h2 id="company-coverage-title">选择企业查看名称命中候选</h2>
          <p>企业档案建立后，这里会显示字面命中的别名和可回查的原文上下文，供人工核验。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="company-coverage" aria-labelledby="company-coverage-title">
      <div className="company-coverage-heading">
        <div className="company-identity">
          <span aria-hidden="true">{company.canonical_name.slice(0, 1)}</span>
          <div>
            <h2 id="company-coverage-title">{company.canonical_name}</h2>
            <p>
              {company.aliases.length === 0
                ? "使用规范名称查找候选"
                : `同时查找 ${company.aliases.length} 个别名`}
            </p>
          </div>
        </div>
        <div className="coverage-heading-actions">
          <button
            className="button button-secondary button-compact"
            type="button"
            disabled={state.status === "loading"}
            aria-busy={state.status === "loading"}
            onClick={onReload}
          >
            {state.status === "loading" ? "读取中…" : "刷新候选"}
          </button>
          <details className="decision-diagnostics">
            <summary>接口诊断</summary>
            <code>GET /api/v2/companies/&#123;id&#125;/coverage</code>
          </details>
        </div>
      </div>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="无法读取企业名称命中候选"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={onReload}
        />
      ) : null}

      {state.status === "loading" && response === null ? <CoverageSkeleton /> : null}

      {response !== null ? (
        <>
          <CoverageLedger response={response} />
          <div className="company-coverage-results-heading">
            <div>
              <h3>待核验报道</h3>
              <p>每条结果只证明字面名称及其字符位置；仍需结合上下文确认是否真的指向该企业。</p>
            </div>
            <span>第 {response.page} 页</span>
          </div>
          <CoverageArticles response={response} isUpdating={isUpdating} />
          <nav className="pagination" aria-label="企业名称命中候选分页">
            <button
              className="button button-secondary"
              type="button"
              disabled={page <= 1 || state.status === "loading"}
              onClick={() => onPageChange(Math.max(1, page - 1))}
            >
              上一页
            </button>
            <span aria-live="polite">
              第 {response.page} / {totalPages} 页
            </span>
            <button
              className="button button-secondary"
              type="button"
              disabled={page >= totalPages || state.status === "loading"}
              onClick={() => onPageChange(page + 1)}
            >
              下一页
            </button>
          </nav>
        </>
      ) : null}
    </section>
  );
}

export function CompanyEvidencePage(): JSX.Element {
  const { state: companiesState, reload: reloadCompanies } = useCompanies();
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [page, setPage] = useState<number>(1);
  const companyId = selectedCompany?.id ?? null;
  const {
    state: coverageState,
    reload: reloadCoverage,
  } = useCompanyCoverage(companyId, page, coveragePageSize);
  const loadedCoverage = coverageState.status === "idle" ? null : coverageState.data;
  const coverageForSelectedCompany = selectedCompany !== null
    && loadedCoverage?.company.id === selectedCompany.id
    ? loadedCoverage
    : null;

  const selectCompany = (company: Company): void => {
    setSelectedCompany(company);
    setPage(1);
  };

  const companyCreated = (company: Company): void => {
    setSelectedCompany(company);
    setPage(1);
    reloadCompanies();
  };

  return (
    <div className="company-evidence-page decision-surface decision-company-surface">
      <header className="decision-surface-header" aria-labelledby="company-evidence-page-title">
        <div className="decision-surface-heading">
          <span className="decision-stage-index">01 · 企业证据现场</span>
          <div>
            <h2 id="company-evidence-page-title">确认报道里说的是哪家企业</h2>
            <p>从真实媒体报道的名称命中开始，保留原文位置，把机器候选交给研究员核验。</p>
          </div>
        </div>
        <div className="decision-context-bar">
          <div className="decision-context-current" data-active={selectedCompany !== null}>
            <span>当前核验对象</span>
            <strong>
              {selectedCompany === null ? "尚未选择企业" : selectedCompany.canonical_name}
            </strong>
            <small>
              {selectedCompany === null
                ? "请从左侧档案中明确选择，不会自动沿用旧上下文。"
                : `${selectedCompany.aliases.length} 个已知别名 · 选择仅影响当前查看`}
            </small>
          </div>
          <ul className="decision-boundary-legend" aria-label="证据边界">
            <li data-boundary="observed"><span />采集报道</li>
            <li data-boundary="candidate"><span />名称候选</li>
            <li data-boundary="human"><span />人工核验</li>
          </ul>
        </div>
      </header>

      <div className="company-evidence-workbench decision-cockpit">
        <CompanyDirectory
          state={companiesState}
          selectedCompanyId={companyId}
          onSelect={selectCompany}
          onReload={reloadCompanies}
          onCreated={companyCreated}
        />
        <main className="decision-main-stage">
          <CompanyCoveragePanel
            company={selectedCompany}
            state={coverageState}
            page={page}
            onPageChange={setPage}
            onReload={reloadCoverage}
          />
        </main>
        <aside className="decision-inspector" aria-labelledby="company-boundary-title">
          <div className="decision-inspector-heading">
            <span>核验边界</span>
            <h3 id="company-boundary-title">候选不是结论</h3>
          </div>
          {selectedCompany === null ? (
            <div className="decision-inspector-empty">
              <strong>等待明确选择</strong>
              <p>系统不会默认打开第一家企业，避免把历史档案误认为本次任务对象。</p>
            </div>
          ) : (
            <>
              <dl className="decision-context-ledger">
                <div>
                  <dt>规范名称</dt>
                  <dd>{selectedCompany.canonical_name}</dd>
                </div>
                <div>
                  <dt>名称候选</dt>
                  <dd>
                    {coverageForSelectedCompany === null
                      ? "读取中"
                      : formatMediaCount(coverageForSelectedCompany.total_matching_articles)}
                  </dd>
                </div>
                <div>
                  <dt>语义状态</dt>
                  <dd>待人工逐条确认</dd>
                </div>
              </dl>
              <p className="decision-boundary-copy">
                名称和别名只负责召回。原文链接、命中片段与字符位置用于判断是否同一实体。
              </p>
              <a className="button button-secondary" href="#/world">
                前往世界模型进行确认
              </a>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
