import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  cohortCreateRequestSchema,
  createCohort,
  type CohortCreateRequest,
  type CohortDetail,
  type PopulationDatasetSummary,
} from "./populationContracts";
import {
  useCohortDetail,
  useCohorts,
  usePopulationDatasets,
  usePopulationPersonas,
} from "./usePopulations";
import { useGraphPersonaCohortOrigins } from "./useGraphPersonaCohortOrigins";
import "./populationContext.css";

const personaPageSize = 10;

type CohortCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly cohort: CohortDetail }
  | { readonly status: "error"; readonly error: Error };

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 10)}…${digest.slice(-8)}`;
}

function normalizeCohortCreationError(error: unknown): Error {
  if (error instanceof ZodError) {
    const issues = error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ");

    return new Error(`Cohort 冻结输入无效：${issues}`);
  }

  return error instanceof Error
    ? error
    : new Error("冻结 Cohort 失败：请求抛出了非标准错误。请检查后端日志。");
}

function findDataset(
  datasets: readonly PopulationDatasetSummary[],
  datasetId: string | null,
): PopulationDatasetSummary | null {
  if (datasetId === null) {
    return null;
  }

  return datasets.find((dataset) => dataset.id === datasetId) ?? null;
}

function queryValidationMessage(value: string): string | null {
  const normalizedValue = value.trim();

  if (normalizedValue.length === 1) {
    return "搜索词至少需要 2 个字符；也可以清空后查看全部 Persona。";
  }

  if (normalizedValue.length > 100) {
    return "搜索词不能超过 100 个字符。";
  }

  return null;
}

function cohortTitleValidationMessage(value: string): string | null {
  const normalizedValue = value.trim();

  if (normalizedValue.length === 0) {
    return "请输入 Cohort 名称。";
  }

  if (normalizedValue.length > 200) {
    return "Cohort 名称不能超过 200 个字符。";
  }

  if (/\r|\n/u.test(normalizedValue)) {
    return "Cohort 名称只能使用一行文本。";
  }

  return null;
}

interface PopulationContextPanelProps {
  readonly selectedCohortId: string | null;
  readonly onSelectedCohortIdChange: (cohortId: string | null) => void;
}

export function PopulationContextPanel({
  selectedCohortId,
  onSelectedCohortIdChange,
}: PopulationContextPanelProps): JSX.Element {
  const { state: datasetsState, reload: reloadDatasets } = usePopulationDatasets();
  const { state: cohortsState, reload: reloadCohorts } = useCohorts();
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [page, setPage] = useState<number>(1);
  const [selectedPersonaIds, setSelectedPersonaIds] = useState<readonly string[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [cohortTitle, setCohortTitle] = useState<string>("");
  const [isCohortTitleTouched, setIsCohortTitleTouched] = useState<boolean>(false);
  const [creationState, setCreationState] = useState<CohortCreationState>({ status: "idle" });
  const [graphOriginPage, setGraphOriginPage] = useState<number>(1);
  const activeCreationController = useRef<AbortController | null>(null);
  const {
    state: personasState,
    reload: reloadPersonas,
  } = usePopulationPersonas(
    selectedDatasetId,
    appliedQuery,
    page,
    personaPageSize,
  );
  const {
    state: cohortDetailState,
    reload: reloadCohortDetail,
  } = useCohortDetail(selectedCohortId);
  const {
    state: graphOriginsState,
    reload: reloadGraphOrigins,
  } = useGraphPersonaCohortOrigins(selectedCohortId, graphOriginPage, 5);
  const datasets = datasetsState.data?.items ?? [];
  const selectedDataset = findDataset(datasets, selectedDatasetId);
  const personasResponse = personasState.status === "idle" ? null : personasState.data;
  const cohortsResponse = cohortsState.data;
  const loadedCohort = cohortDetailState.status === "idle" ? null : cohortDetailState.data;
  const selectedCohort = selectedCohortId !== null && loadedCohort?.id === selectedCohortId
    ? loadedCohort
    : null;
  const selectedCohortDataset = findDataset(
    datasets,
    selectedCohort?.dataset.id ?? null,
  );
  const totalPages = personasResponse === null
    ? 1
    : Math.max(1, Math.ceil(personasResponse.total / personasResponse.page_size));
  const isCreating = creationState.status === "submitting";
  const titleError = isCohortTitleTouched
    ? cohortTitleValidationMessage(cohortTitle)
    : null;
  const canCreateCohort = selectedDataset !== null
    && selectedPersonaIds.length >= 1
    && selectedPersonaIds.length <= 100
    && cohortTitleValidationMessage(cohortTitle) === null
    && !isCreating;

  useEffect(() => {
    return () => {
      activeCreationController.current?.abort();
    };
  }, []);

  useEffect(() => {
    setGraphOriginPage(1);
  }, [selectedCohortId]);

  const changeDataset = (datasetId: string): void => {
    if (isCreating) {
      return;
    }

    setSelectedDatasetId(datasetId === "" ? null : datasetId);
    setSearchDraft("");
    setAppliedQuery(null);
    setPage(1);
    setSelectedPersonaIds([]);
    setSelectionError(null);
    setQueryError(null);
    setCohortTitle("");
    setIsCohortTitleTouched(false);
    setCreationState({ status: "idle" });
  };

  const applySearch = (): void => {
    const error = queryValidationMessage(searchDraft);

    setQueryError(error);

    if (error !== null) {
      return;
    }

    const normalizedQuery = searchDraft.trim();
    setAppliedQuery(normalizedQuery === "" ? null : normalizedQuery);
    setPage(1);
  };

  const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== "Enter") {
      return;
    }

    event.preventDefault();
    applySearch();
  };

  const togglePersona = (personaId: string, isSelected: boolean): void => {
    if (isSelected) {
      if (selectedPersonaIds.includes(personaId)) {
        return;
      }

      if (selectedPersonaIds.length >= 100) {
        setSelectionError("一个 Cohort 最多只能冻结 100 个 Persona；请先取消其他成员。");
        return;
      }

      setSelectedPersonaIds((currentIds) => [...currentIds, personaId]);
      setSelectionError(null);
      setCreationState({ status: "idle" });
      return;
    }

    setSelectedPersonaIds((currentIds) => currentIds.filter((id) => id !== personaId));
    setSelectionError(null);
    setCreationState({ status: "idle" });
  };

  const freezeCohort = async (): Promise<void> => {
    setIsCohortTitleTouched(true);

    if (!canCreateCohort || selectedDataset === null || activeCreationController.current !== null) {
      return;
    }

    let request: CohortCreateRequest;

    try {
      request = cohortCreateRequestSchema.parse({
        title: cohortTitle.trim(),
        dataset_id: selectedDataset.id,
        persona_ids: selectedPersonaIds,
      });
    } catch (error: unknown) {
      setCreationState({ status: "error", error: normalizeCohortCreationError(error) });
      return;
    }

    const controller = new AbortController();
    activeCreationController.current = controller;
    setCreationState({ status: "submitting" });

    try {
      const cohort = await createCohort(request, controller.signal);

      if (controller.signal.aborted || activeCreationController.current !== controller) {
        return;
      }

      setCreationState({ status: "success", cohort });
      onSelectedCohortIdChange(cohort.id);
      reloadCohorts();
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      if (activeCreationController.current !== controller) {
        return;
      }

      setCreationState({ status: "error", error: normalizeCohortCreationError(error) });
    } finally {
      if (activeCreationController.current === controller) {
        activeCreationController.current = null;
      }
    }
  };

  const handleTitleKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key !== "Enter") {
      return;
    }

    event.preventDefault();
    void freezeCohort();
  };

  return (
    <section className="population-context" aria-labelledby="population-context-title">
      <header className="population-context-heading">
        <div>
          <span>CONTEXT / 00</span>
          <h4 id="population-context-title">冻结人群上下文</h4>
          <p>从真实 MatrAIx Persona 数据集中明确挑选成员，再封存为可追溯 Cohort。</p>
        </div>
        <code>immutable cohort</code>
      </header>

      <div className="population-context-boundary" role="note">
        <strong>冻结不等于推演</strong>
          <p>Cohort 只在语义实验提交时成为受众输入；platform smoke 不读取这项选择。</p>
      </div>

      {datasetsState.status === "error" ? (
        <ApiErrorPanel
          title="无法读取 Persona 数据集"
          error={datasetsState.error}
          isRetrying={datasetsState.isRetrying}
          onRetry={reloadDatasets}
        />
      ) : null}

      {datasetsState.status === "loading" && datasetsState.data === null ? (
        <div className="population-skeleton" role="status" aria-live="polite">
          <span className="sr-only">正在读取 Persona 数据集</span>
          <span className="skeleton-block" aria-hidden="true" />
          <span className="skeleton-block" aria-hidden="true" />
        </div>
      ) : null}

      {datasetsState.data !== null && datasets.length === 0 ? (
        <div className="population-empty" role="status">
          <strong>还没有可用的 Persona 数据集</strong>
          <p>导入并登记 MatrAIx 数据集后，才能选择 Persona 和冻结 Cohort。</p>
        </div>
      ) : null}

      {datasets.length > 0 ? (
        <div className="population-dataset-control">
          <label htmlFor="population-dataset">
            <span>Persona 数据集</span>
            <select
              id="population-dataset"
              value={selectedDatasetId ?? ""}
              disabled={isCreating}
              onChange={(event) => changeDataset(event.target.value)}
            >
              <option value="">请选择数据集</option>
              {datasets.map((dataset) => (
                <option value={dataset.id} key={dataset.id}>
                  {dataset.display_name} · {formatMediaCount(dataset.persona_count)} 人
                </option>
              ))}
            </select>
          </label>
          <small>系统不会自动选择第一项；切换数据集会清空当前勾选。</small>
        </div>
      ) : null}

      {selectedDataset !== null ? (
        <details className="population-dataset-ledger">
          <summary>
            <span>{selectedDataset.display_name}</span>
            <code>{abbreviatedDigest(selectedDataset.dataset_sha256)}</code>
          </summary>
          <dl>
            <div><dt>slug</dt><dd>{selectedDataset.slug}</dd></div>
            <div><dt>schema</dt><dd>{selectedDataset.schema_version}</dd></div>
            <div><dt>parent pool</dt><dd>{selectedDataset.parent_pool ?? "未声明"}</dd></div>
            <div><dt>repository</dt><dd>{selectedDataset.source_repository ?? "未声明"}</dd></div>
            <div><dt>manifest</dt><dd><code>{selectedDataset.manifest_sha256}</code></dd></div>
            <div><dt>dataset</dt><dd><code>{selectedDataset.dataset_sha256}</code></dd></div>
          </dl>
        </details>
      ) : null}

      {selectedDataset !== null ? (
        <div className="population-persona-workbench">
          <div className="population-subheading">
            <div>
              <strong>挑选 Persona</strong>
              <span>{selectedPersonaIds.length} / 100 已选</span>
            </div>
            <button
              className="population-text-button"
              type="button"
              disabled={selectedPersonaIds.length === 0 || isCreating}
              onClick={() => {
                setSelectedPersonaIds([]);
                setSelectionError(null);
                setCreationState({ status: "idle" });
              }}
            >
              清空勾选
            </button>
          </div>

          <div className="population-search" role="search">
            <label htmlFor="population-persona-query">
              <span>搜索姓名、Persona ID 或来源</span>
              <input
                id="population-persona-query"
                type="search"
                value={searchDraft}
                maxLength={100}
                placeholder="至少 2 个字符；留空查看全部"
                aria-invalid={queryError !== null}
                aria-describedby={queryError === null ? undefined : "population-query-error"}
                onBlur={() => setQueryError(queryValidationMessage(searchDraft))}
                onChange={(event) => {
                  setSearchDraft(event.target.value);
                  setQueryError(null);
                }}
                onKeyDown={handleSearchKeyDown}
              />
            </label>
            <div className="population-search-actions">
              <button
                className="button button-secondary button-compact"
                type="button"
                onClick={applySearch}
              >
                搜索 Persona
              </button>
              {appliedQuery !== null ? (
                <button
                  className="population-text-button"
                  type="button"
                  onClick={() => {
                    setSearchDraft("");
                    setAppliedQuery(null);
                    setQueryError(null);
                    setPage(1);
                  }}
                >
                  清除搜索
                </button>
              ) : null}
            </div>
            {queryError !== null ? (
              <p className="population-field-error" id="population-query-error" role="alert">
                {queryError}
              </p>
            ) : null}
          </div>

          {personasState.status === "error" ? (
            <ApiErrorPanel
              title="无法读取 Persona 列表"
              error={personasState.error}
              isRetrying={personasState.isRetrying}
              onRetry={reloadPersonas}
            />
          ) : null}

          {personasState.status === "loading" && personasState.data === null ? (
            <div className="population-skeleton" role="status" aria-live="polite">
              <span className="sr-only">正在读取 Persona</span>
              <span className="skeleton-block" aria-hidden="true" />
              <span className="skeleton-block" aria-hidden="true" />
              <span className="skeleton-block" aria-hidden="true" />
            </div>
          ) : null}

          {personasResponse !== null && personasResponse.items.length === 0 ? (
            <div className="population-empty" role="status">
              <strong>{appliedQuery === null ? "这个数据集没有 Persona" : "没有匹配的 Persona"}</strong>
              <p>
                {appliedQuery === null
                  ? "请核对数据集清单和后端导入结果。"
                  : "调整搜索词或清除搜索后再试。"}
              </p>
            </div>
          ) : null}

          {personasResponse !== null && personasResponse.items.length > 0 ? (
            <ul className="population-persona-list" aria-busy={personasState.status === "loading"}>
              {personasResponse.items.map((persona) => {
                const isSelected = selectedPersonaIds.includes(persona.id);
                const isSelectionLocked = !isSelected && selectedPersonaIds.length >= 100;

                return (
                  <li key={persona.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={isSelectionLocked || isCreating}
                        onChange={(event) => togglePersona(persona.id, event.target.checked)}
                      />
                      <span className="population-persona-copy">
                        <span>
                          <strong>{persona.display_name}</strong>
                          <small>{persona.persona_id}</small>
                        </span>
                        <small>{persona.source}</small>
                        {persona.attributes.length > 0 ? (
                          <span className="population-attribute-list">
                            {persona.attributes.slice(0, 3).map((attribute) => (
                              <span key={attribute.name} title={`${attribute.name}: ${attribute.value}`}>
                                {attribute.name}: {attribute.value}
                              </span>
                            ))}
                            {persona.attributes.length > 3 ? (
                              <span>+{persona.attributes.length - 3}</span>
                            ) : null}
                          </span>
                        ) : null}
                        <code title={persona.profile_sha256}>
                          profile {abbreviatedDigest(persona.profile_sha256)}
                        </code>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          ) : null}

          {selectionError !== null ? (
            <p className="population-field-error" role="alert">{selectionError}</p>
          ) : null}

          {personasResponse !== null && personasResponse.total > 0 ? (
            <nav className="population-pagination" aria-label="Persona 分页">
              <button
                className="button button-secondary button-compact"
                type="button"
                disabled={page <= 1 || personasState.status === "loading"}
                onClick={() => setPage((currentPage) => currentPage - 1)}
              >
                上一页
              </button>
              <span>第 {page} / {totalPages} 页 · {formatMediaCount(personasResponse.total)} 人</span>
              <button
                className="button button-secondary button-compact"
                type="button"
                disabled={page >= totalPages || personasState.status === "loading"}
                onClick={() => setPage((currentPage) => currentPage + 1)}
              >
                下一页
              </button>
            </nav>
          ) : null}
        </div>
      ) : null}

      {selectedDataset !== null ? (
        <div className="population-freeze-control">
          <div className="population-subheading">
            <div>
              <strong>封存 Cohort</strong>
              <span>只记录明确勾选的 {selectedPersonaIds.length} 人</span>
            </div>
          </div>
          <label htmlFor="population-cohort-title">
            <span>Cohort 名称</span>
            <input
              id="population-cohort-title"
              type="text"
              value={cohortTitle}
              maxLength={200}
              placeholder="例如：华东供应链观察组"
              disabled={isCreating}
              aria-invalid={titleError !== null}
              aria-describedby={titleError === null ? undefined : "population-title-error"}
              onBlur={() => setIsCohortTitleTouched(true)}
              onChange={(event) => {
                setCohortTitle(event.target.value);
                setCreationState({ status: "idle" });
              }}
              onKeyDown={handleTitleKeyDown}
            />
          </label>
          {titleError !== null ? (
            <p className="population-field-error" id="population-title-error" role="alert">
              {titleError}
            </p>
          ) : null}
          <button
            className="button button-primary population-freeze-button"
            type="button"
            disabled={!canCreateCohort}
            aria-busy={isCreating}
            onClick={() => void freezeCohort()}
          >
            {isCreating ? "正在冻结 Cohort…" : `冻结 ${selectedPersonaIds.length} 人 Cohort`}
          </button>

          {creationState.status === "error" ? (
            <div className="population-create-message" data-status="error" role="alert">
              <strong>
                {isAmbiguousPostResultError(creationState.error)
                  ? "冻结结果未知，请先刷新 Cohort 目录核对"
                  : "Cohort 没有冻结"}
              </strong>
              <p>{creationState.error.message}</p>
              <small>POST 不会自动重试，以免创建重复 Cohort。</small>
            </div>
          ) : null}

          {creationState.status === "success" ? (
            <div className="population-create-message" data-status="success" role="status">
              <strong>已冻结，可用于语义实验</strong>
              <p>{creationState.cohort.title} · {creationState.cohort.persona_count} 人</p>
              <code>{creationState.cohort.cohort_sha256}</code>
            </div>
          ) : null}
        </div>
      ) : null}

      <details className="population-cohort-directory">
        <summary>
          <span>冻结 Cohort 目录</span>
          <strong data-status={cohortsState.status}>
            {cohortsState.status === "error"
              ? "读取失败 · 展开重试"
              : cohortsResponse === null
                ? "等待接口"
                : formatMediaCount(cohortsResponse.total)}
          </strong>
        </summary>
        <div className="population-directory-actions">
          <p>明确选择一个 Cohort，核对成员和来源哈希。</p>
          <button
            className="button button-secondary button-compact"
            type="button"
            disabled={cohortsState.status === "loading"}
            aria-busy={cohortsState.status === "loading"}
            onClick={reloadCohorts}
          >
            {cohortsState.status === "loading" ? "读取中…" : "刷新目录"}
          </button>
        </div>

        {cohortsState.status === "error" ? (
          <ApiErrorPanel
            title="无法读取 Cohort 目录"
            error={cohortsState.error}
            isRetrying={cohortsState.isRetrying}
            onRetry={reloadCohorts}
          />
        ) : null}

        {cohortsState.status === "loading" && cohortsState.data === null ? (
          <div className="population-skeleton" role="status" aria-live="polite">
            <span className="sr-only">正在读取冻结 Cohort</span>
            <span className="skeleton-block" aria-hidden="true" />
            <span className="skeleton-block" aria-hidden="true" />
          </div>
        ) : null}

        {cohortsResponse !== null && cohortsResponse.items.length === 0 ? (
          <div className="population-empty" role="status">
            <strong>还没有冻结 Cohort</strong>
            <p>选择 1–100 个 Persona 并命名后，冻结结果会持久化到这里。</p>
          </div>
        ) : null}

        {cohortsResponse !== null && cohortsResponse.items.length > 0 ? (
          <ul className="population-cohort-list">
            {cohortsResponse.items.map((cohort) => (
              <li key={cohort.id}>
                <button
                  type="button"
                  data-selected={cohort.id === selectedCohortId}
                  aria-pressed={cohort.id === selectedCohortId}
                  onClick={() => onSelectedCohortIdChange(cohort.id)}
                >
                  <span>
                    <strong>{cohort.title}</strong>
                    <small>{cohort.dataset.slug} · {cohort.persona_count} 人</small>
                  </span>
                  <code title={cohort.cohort_sha256}>{abbreviatedDigest(cohort.cohort_sha256)}</code>
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {selectedCohortId === null ? (
          <div className="population-empty population-cohort-prompt" role="status">
            <strong>尚未选择 Cohort</strong>
            <p>系统不会自动打开第一项；请选择后查看成员与来源链。</p>
          </div>
        ) : null}

        {cohortDetailState.status === "error" ? (
          <ApiErrorPanel
            title="无法读取 Cohort 成员"
            error={cohortDetailState.error}
            isRetrying={cohortDetailState.isRetrying}
            onRetry={reloadCohortDetail}
          />
        ) : null}

        {cohortDetailState.status === "loading" && selectedCohort === null ? (
          <div className="population-skeleton" role="status" aria-live="polite">
            <span className="sr-only">正在读取 Cohort 成员和来源</span>
            <span className="skeleton-block" aria-hidden="true" />
            <span className="skeleton-block" aria-hidden="true" />
            <span className="skeleton-block" aria-hidden="true" />
          </div>
        ) : null}

        {selectedCohort !== null ? (
          <section className="population-cohort-detail" aria-labelledby={`cohort-${selectedCohort.id}`}>
            <header>
              <span>FROZEN COHORT</span>
              <h5 id={`cohort-${selectedCohort.id}`}>{selectedCohort.title}</h5>
              <p>已冻结，可作为语义实验的受众输入</p>
            </header>
            <dl className="population-provenance">
              <div><dt>创建时间</dt><dd>{formatMediaTimestamp(selectedCohort.created_at)}</dd></div>
              <div><dt>Cohort hash</dt><dd><code>{selectedCohort.cohort_sha256}</code></dd></div>
              <div><dt>Dataset</dt><dd>{selectedCohort.dataset.slug}</dd></div>
              <div><dt>Dataset hash</dt><dd><code>{selectedCohort.dataset.dataset_sha256}</code></dd></div>
              <div>
                <dt>Repository</dt>
                <dd>
                  {selectedCohortDataset === null
                    ? "当前数据集目录未返回此数据集"
                    : selectedCohortDataset.source_repository ?? "未声明"}
                </dd>
              </div>
              <div>
                <dt>Parent pool</dt>
                <dd>
                  {selectedCohortDataset === null
                    ? "当前数据集目录未返回此数据集"
                    : selectedCohortDataset.parent_pool ?? "未声明"}
                </dd>
              </div>
              <div>
                <dt>Manifest hash</dt>
                <dd>
                  {selectedCohortDataset === null
                    ? "当前数据集目录未返回此数据集"
                    : <code>{selectedCohortDataset.manifest_sha256}</code>}
                </dd>
              </div>
            </dl>
            <section className="population-graph-origins" aria-label="图谱 Persona 选择来源">
              <header>
                <div>
                  <span>GRAPH SELECTION LINEAGE</span>
                  <strong>图谱筛选来源</strong>
                </div>
                {graphOriginsState.status === "success" ? (
                  <small>{formatMediaCount(graphOriginsState.data.total)} 条封存来源</small>
                ) : null}
              </header>
              {graphOriginsState.status === "loading" ? (
                <p role="status">正在核验图谱、节点与成员顺序…</p>
              ) : null}
              {graphOriginsState.status === "error" ? (
                <ApiErrorPanel
                  title="无法读取图谱选择来源"
                  error={graphOriginsState.error}
                  isRetrying={graphOriginsState.isRetrying}
                  onRetry={reloadGraphOrigins}
                />
              ) : null}
              {graphOriginsState.status === "success" && graphOriginsState.data.total === 0 ? (
                <p>这个 Cohort 由 Persona World 直接创建，没有声明图谱筛选来源。</p>
              ) : null}
              {graphOriginsState.status === "success" && graphOriginsState.data.items.length > 0 ? (
                <ol>
                  {graphOriginsState.data.items.map((origin) => (
                    <li key={origin.id}>
                      <span>{formatMediaTimestamp(origin.created_at)}</span>
                      <strong>节点 {origin.node_id}</strong>
                      <small>图谱 {abbreviatedDigest(origin.graph_sha256)} · 匹配器 v{origin.matcher_version}</small>
                      <code title={origin.origin_sha256}>origin {origin.origin_sha256}</code>
                    </li>
                  ))}
                </ol>
              ) : null}
              {graphOriginsState.status === "success" && graphOriginsState.data.total > 5 ? (
                <div className="population-graph-origin-pagination">
                  <button
                    type="button"
                    disabled={graphOriginPage === 1}
                    onClick={() => setGraphOriginPage((current) => Math.max(1, current - 1))}
                  >
                    上一页
                  </button>
                  <span>
                    {graphOriginPage} / {Math.ceil(graphOriginsState.data.total / 5)}
                  </span>
                  <button
                    type="button"
                    disabled={graphOriginPage * 5 >= graphOriginsState.data.total}
                    onClick={() => setGraphOriginPage((current) => current + 1)}
                  >
                    下一页
                  </button>
                </div>
              ) : null}
            </section>
            <ol className="population-member-list">
              {selectedCohort.members.map((member) => (
                <li key={member.persona.id}>
                  <span>POS {member.position}</span>
                  <div>
                    <strong>{member.persona.display_name}</strong>
                    <small>{member.persona.persona_id} · {member.persona.source}</small>
                    {member.persona.attributes.length > 0 ? (
                      <dl>
                        {member.persona.attributes.map((attribute) => (
                          <div key={attribute.name}>
                            <dt>{attribute.name}</dt>
                            <dd>{attribute.value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : null}
                    <code title={member.persona.profile_sha256}>
                      profile_sha256 {member.persona.profile_sha256}
                    </code>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </details>
    </section>
  );
}
