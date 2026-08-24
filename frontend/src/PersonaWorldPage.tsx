import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import { formatMediaCount, formatMediaTimestamp } from "./mediaPresentation";
import {
  cohortCreateRequestSchema,
  createCohort,
  type CohortCreateRequest,
  type CohortDetail,
  type CohortSummary,
  type PersonaSummary,
  type PopulationDatasetSummary,
} from "./populationContracts";
import { createRunStudioHash } from "./runStudioRoute";
import {
  useCohortDetail,
  useCohorts,
  usePopulationDatasets,
  usePopulationPersonas,
} from "./usePopulations";
import "./personaWorld.css";

const personaPageSize = 20;

type FreezeState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly cohort: CohortDetail }
  | { readonly status: "error"; readonly error: Error };

function abbreviatedDigest(digest: string): string {
  return `${digest.slice(0, 10)}…${digest.slice(-8)}`;
}

function queryError(value: string): string | null {
  const normalized = value.trim();

  if (normalized.length === 1) {
    return "搜索词至少需要 2 个字符；清空可查看全部 Persona。";
  }
  if (normalized.length > 100) {
    return "搜索词不能超过 100 个字符。";
  }
  return null;
}

function titleError(value: string): string | null {
  const normalized = value.trim();

  if (normalized.length === 0) return "请输入 Cohort 名称。";
  if (normalized.length > 200) return "Cohort 名称不能超过 200 个字符。";
  if (/\r|\n/u.test(normalized)) return "Cohort 名称只能使用一行文本。";
  return null;
}

function normalizeFreezeError(error: unknown): Error {
  if (error instanceof ZodError) {
    return new Error(`Cohort 冻结输入无效：${error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ")}`);
  }

  return error instanceof Error
    ? error
    : new Error("冻结 Cohort 失败：请求抛出了非标准错误。请检查后端日志。");
}

function datasetById(
  datasets: readonly PopulationDatasetSummary[],
  datasetId: string | null,
): PopulationDatasetSummary | null {
  return datasets.find((dataset) => dataset.id === datasetId) ?? null;
}

function personaById(
  personas: readonly PersonaSummary[],
  personaId: string | null,
): PersonaSummary | null {
  return personas.find((persona) => persona.id === personaId) ?? null;
}

function cohortRunStudioHref(): string {
  return createRunStudioHash({ mode: "native", projectId: null, runId: null });
}

function DatasetLedger({ dataset }: { readonly dataset: PopulationDatasetSummary }): JSX.Element {
  return (
    <section className="persona-world-ledger" aria-labelledby="persona-dataset-ledger-title">
      <header>
        <span>DATASET / SEALED</span>
        <h3 id="persona-dataset-ledger-title">{dataset.display_name}</h3>
        <p>{formatMediaCount(dataset.persona_count)} 个 Persona · schema {dataset.schema_version}</p>
      </header>
      <dl>
        <div><dt>slug</dt><dd>{dataset.slug}</dd></div>
        <div><dt>parent pool</dt><dd>{dataset.parent_pool ?? "未声明"}</dd></div>
        <div><dt>repository</dt><dd>{dataset.source_repository ?? "未声明"}</dd></div>
        <div><dt>captured</dt><dd>{formatMediaTimestamp(dataset.created_at)}</dd></div>
        <div><dt>manifest</dt><dd><code>{dataset.manifest_sha256}</code></dd></div>
        <div><dt>dataset</dt><dd><code>{dataset.dataset_sha256}</code></dd></div>
      </dl>
    </section>
  );
}

function PersonaInspector({ persona }: { readonly persona: PersonaSummary | null }): JSX.Element {
  const [attributeQuery, setAttributeQuery] = useState<string>("");
  const attributes = useMemo(() => {
    if (persona === null) return [];
    const normalizedQuery = attributeQuery.trim().toLocaleLowerCase();
    if (normalizedQuery === "") return persona.attributes;
    return persona.attributes.filter((attribute) =>
      `${attribute.name}\n${attribute.value}`.toLocaleLowerCase().includes(normalizedQuery),
    );
  }, [attributeQuery, persona]);

  useEffect(() => setAttributeQuery(""), [persona?.id]);

  if (persona === null) {
    return (
      <section className="persona-world-inspector-empty" role="status">
        <span>INSPECTOR / PERSONA</span>
        <strong>打开一个 Persona</strong>
        <p>点击中央目录中的档案，核对完整属性和内容哈希。系统不会自动打开第一项。</p>
      </section>
    );
  }

  return (
    <section className="persona-world-inspector" aria-labelledby="persona-inspector-title">
      <header>
        <span>INSPECTOR / PERSONA</span>
        <h3 id="persona-inspector-title">{persona.display_name}</h3>
        <p>{persona.persona_id} · {persona.source}</p>
        <code title={persona.profile_sha256}>{persona.profile_sha256}</code>
      </header>
      <label htmlFor="persona-attribute-query">
        <span>筛选当前 Persona 属性</span>
        <input
          id="persona-attribute-query"
          name="attribute_query"
          type="search"
          value={attributeQuery}
          placeholder="例如 region、education"
          onChange={(event) => setAttributeQuery(event.target.value)}
        />
      </label>
      <div className="persona-world-attribute-count">
        {attributes.length} / {persona.attributes.length} 项属性
      </div>
      {attributes.length === 0 ? (
        <p className="persona-world-no-attributes">当前筛选没有匹配属性。</p>
      ) : (
        <dl className="persona-world-attributes">
          {attributes.map((attribute) => (
            <div key={attribute.name}>
              <dt>{attribute.name}</dt>
              <dd>{attribute.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function CohortDirectory({
  cohorts,
  selectedCohortId,
  onSelect,
}: {
  readonly cohorts: readonly CohortSummary[];
  readonly selectedCohortId: string | null;
  readonly onSelect: (cohortId: string) => void;
}): JSX.Element {
  if (cohorts.length === 0) {
    return (
      <div className="persona-world-empty-compact">
        <strong>还没有 Cohort</strong>
        <p>从中央目录勾选 Persona 后，在右侧冻结第一组人群。</p>
      </div>
    );
  }

  return (
    <ul className="persona-world-cohort-list">
      {cohorts.map((cohort) => (
        <li key={cohort.id}>
          <button
            type="button"
            data-selected={cohort.id === selectedCohortId}
            aria-pressed={cohort.id === selectedCohortId}
            onClick={() => onSelect(cohort.id)}
          >
            <span><strong>{cohort.title}</strong><small>{cohort.persona_count} 人 · {cohort.dataset.slug}</small></span>
            <code>{abbreviatedDigest(cohort.cohort_sha256)}</code>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function PersonaWorldPage(): JSX.Element {
  const { state: datasetsState, reload: reloadDatasets } = usePopulationDatasets();
  const { state: cohortsState, reload: reloadCohorts } = useCohorts();
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState<string>("");
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [page, setPage] = useState<number>(1);
  const [selectedPersonaIds, setSelectedPersonaIds] = useState<readonly string[]>([]);
  const [inspectedPersonaId, setInspectedPersonaId] = useState<string | null>(null);
  const [selectedCohortId, setSelectedCohortId] = useState<string | null>(null);
  const [cohortTitle, setCohortTitle] = useState<string>("");
  const [titleTouched, setTitleTouched] = useState<boolean>(false);
  const [freezeState, setFreezeState] = useState<FreezeState>({ status: "idle" });
  const activeController = useRef<AbortController | null>(null);
  const { state: personasState, reload: reloadPersonas } = usePopulationPersonas(
    datasetId,
    appliedQuery,
    page,
    personaPageSize,
  );
  const { state: cohortDetailState, reload: reloadCohortDetail } = useCohortDetail(selectedCohortId);
  const datasets = datasetsState.data?.items ?? [];
  const dataset = datasetById(datasets, datasetId);
  const personasResponse = personasState.status === "idle" ? null : personasState.data;
  const personas = personasResponse?.items ?? [];
  const inspectedPersona = personaById(personas, inspectedPersonaId);
  const cohorts = cohortsState.data?.items ?? [];
  const selectedCohort = cohortDetailState.status === "success"
    && cohortDetailState.data.id === selectedCohortId
    ? cohortDetailState.data
    : null;
  const totalPages = personasResponse === null
    ? 1
    : Math.max(1, Math.ceil(personasResponse.total / personasResponse.page_size));
  const currentTitleError = titleTouched ? titleError(cohortTitle) : null;
  const isSubmitting = freezeState.status === "submitting";
  const canFreeze = dataset !== null
    && selectedPersonaIds.length >= 1
    && selectedPersonaIds.length <= 100
    && titleError(cohortTitle) === null
    && !isSubmitting;

  useEffect(() => () => activeController.current?.abort(), []);

  const changeDataset = (nextDatasetId: string): void => {
    if (isSubmitting) return;
    setDatasetId(nextDatasetId === "" ? null : nextDatasetId);
    setSearchDraft("");
    setAppliedQuery(null);
    setSearchError(null);
    setPage(1);
    setSelectedPersonaIds([]);
    setInspectedPersonaId(null);
    setCohortTitle("");
    setTitleTouched(false);
    setFreezeState({ status: "idle" });
  };

  const applySearch = (): void => {
    const validationError = queryError(searchDraft);
    setSearchError(validationError);
    if (validationError !== null) return;
    const normalized = searchDraft.trim();
    setAppliedQuery(normalized === "" ? null : normalized);
    setPage(1);
    setInspectedPersonaId(null);
  };

  const handleSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Enter") {
      event.preventDefault();
      applySearch();
    }
  };

  const togglePersona = (personaId: string): void => {
    if (selectedPersonaIds.includes(personaId)) {
      setSelectedPersonaIds(selectedPersonaIds.filter((id) => id !== personaId));
    } else if (selectedPersonaIds.length < 100) {
      setSelectedPersonaIds([...selectedPersonaIds, personaId]);
    }
    setFreezeState({ status: "idle" });
  };

  const freezeCohort = async (): Promise<void> => {
    setTitleTouched(true);
    if (!canFreeze || dataset === null || activeController.current !== null) return;

    let request: CohortCreateRequest;
    try {
      request = cohortCreateRequestSchema.parse({
        title: cohortTitle.trim(),
        dataset_id: dataset.id,
        persona_ids: selectedPersonaIds,
      });
    } catch (error: unknown) {
      setFreezeState({ status: "error", error: normalizeFreezeError(error) });
      return;
    }

    const controller = new AbortController();
    activeController.current = controller;
    setFreezeState({ status: "submitting" });
    try {
      const cohort = await createCohort(request, controller.signal);
      if (!controller.signal.aborted && activeController.current === controller) {
        setFreezeState({ status: "success", cohort });
        setSelectedCohortId(cohort.id);
        reloadCohorts();
      }
    } catch (error: unknown) {
      if (!(error instanceof DOMException && error.name === "AbortError")
        && activeController.current === controller) {
        setFreezeState({ status: "error", error: normalizeFreezeError(error) });
      }
    } finally {
      if (activeController.current === controller) activeController.current = null;
    }
  };

  return (
    <div className="persona-world-page">
      <header className="persona-world-hero">
        <div>
          <span>合成人群 / PERSONA WORLD</span>
          <h1>从公开 Persona 数据构造可复核的人群上下文</h1>
          <p>浏览真实导入的数据集、核对完整属性、跨页选择成员，并将选择封存为可进入语义实验的 Cohort。</p>
        </div>
        <div className="persona-world-boundary" role="note">
          <strong>数据边界</strong>
          <p>这里展示的是已导入并内容寻址的 Persona，不代表真实人口，也不会用 8.3B 营销数字替代实际数据量。</p>
        </div>
      </header>

      <div className="persona-world-layout">
        <aside className="persona-world-left" aria-label="Persona 数据集与 Cohort">
          <section className="persona-world-datasets" aria-labelledby="persona-world-datasets-title">
            <header><span>WORLD / SOURCE</span><h3 id="persona-world-datasets-title">Persona 数据集</h3></header>
            {datasetsState.status === "error" ? (
              <ApiErrorPanel title="无法读取 Persona 数据集" error={datasetsState.error} isRetrying={datasetsState.isRetrying} onRetry={reloadDatasets} />
            ) : null}
            {datasetsState.status === "loading" && datasetsState.data === null ? (
              <div className="persona-world-skeleton" role="status"><span className="skeleton-block" /><span className="skeleton-block" /></div>
            ) : null}
            {datasetsState.data !== null && datasets.length === 0 ? (
              <div className="persona-world-empty-compact"><strong>没有可用数据集</strong><p>先导入合成人物数据集。</p></div>
            ) : null}
            {datasets.length > 0 ? (
              <label htmlFor="persona-world-dataset">
                <span>选择冻结版本</span>
                <select id="persona-world-dataset" name="dataset_id" value={datasetId ?? ""} onChange={(event) => changeDataset(event.target.value)}>
                  <option value="">请选择数据集</option>
                  {datasets.map((item) => <option value={item.id} key={item.id}>{item.display_name} · {formatMediaCount(item.persona_count)}</option>)}
                </select>
              </label>
            ) : null}
          </section>
          {dataset !== null ? <DatasetLedger dataset={dataset} /> : null}
          <section className="persona-world-cohorts" aria-labelledby="persona-world-cohorts-title">
            <header><div><span>COHORT / SEALED</span><h3 id="persona-world-cohorts-title">冻结人群</h3></div><button type="button" onClick={reloadCohorts} disabled={cohortsState.status === "loading"}>刷新</button></header>
            {cohortsState.status === "error" ? <ApiErrorPanel title="无法读取 Cohort" error={cohortsState.error} isRetrying={cohortsState.isRetrying} onRetry={reloadCohorts} /> : null}
            <CohortDirectory cohorts={cohorts} selectedCohortId={selectedCohortId} onSelect={setSelectedCohortId} />
          </section>
        </aside>

        <section className="persona-world-center" aria-labelledby="persona-directory-title">
          <header>
            <div><span>CATALOG / PERSONAS</span><h3 id="persona-directory-title">Persona 目录</h3><p>{dataset === null ? "先明确选择一个数据集。" : `${dataset.display_name} · ${formatMediaCount(personasResponse?.total ?? dataset.persona_count)} 人`}</p></div>
            <div className="persona-world-selection-count"><strong>{selectedPersonaIds.length}</strong><span>/ 100 已选</span></div>
          </header>
          {dataset !== null ? (
            <div className="persona-world-search" role="search">
              <label htmlFor="persona-world-query"><span>搜索姓名、Persona ID 或来源</span><input id="persona-world-query" name="persona_query" type="search" value={searchDraft} maxLength={100} placeholder="至少 2 个字符；留空查看全部" aria-invalid={searchError !== null} onKeyDown={handleSearchKeyDown} onChange={(event) => { setSearchDraft(event.target.value); setSearchError(null); }} /></label>
              <button type="button" onClick={applySearch}>搜索</button>
              {appliedQuery !== null ? <button type="button" onClick={() => { setSearchDraft(""); setAppliedQuery(null); setSearchError(null); setPage(1); }}>清除</button> : null}
              {searchError !== null ? <p role="alert">{searchError}</p> : null}
            </div>
          ) : null}
          {personasState.status === "error" ? <ApiErrorPanel title="无法读取 Persona" error={personasState.error} isRetrying={personasState.isRetrying} onRetry={reloadPersonas} /> : null}
          {personasState.status === "loading" && personasState.data === null ? <div className="persona-world-card-skeleton" role="status">{Array.from({ length: 6 }, (_, index) => <span className="skeleton-block" key={index} />)}</div> : null}
          {dataset === null ? <div className="persona-world-stage-empty"><strong>选择一个 Persona 数据集</strong><p>系统不会自动选择第一项，也不会混用不同数据集版本。</p></div> : null}
          {personasResponse !== null && personas.length === 0 ? <div className="persona-world-stage-empty"><strong>没有匹配 Persona</strong><p>调整搜索词或清除搜索后再试。</p></div> : null}
          {personas.length > 0 ? (
            <ul className="persona-world-grid" aria-busy={personasState.status === "loading"}>
              {personas.map((persona) => {
                const selected = selectedPersonaIds.includes(persona.id);
                const inspected = inspectedPersonaId === persona.id;
                return (
                  <li key={persona.id} data-selected={selected} data-inspected={inspected}>
                    <button className="persona-world-open" type="button" aria-pressed={inspected} onClick={() => setInspectedPersonaId(persona.id)}>
                      <span className="persona-world-avatar" aria-hidden="true">{persona.display_name.slice(0, 1).toUpperCase()}</span>
                      <span><strong>{persona.display_name}</strong><small>{persona.persona_id} · {persona.source}</small></span>
                    </button>
                    <div className="persona-world-card-attributes">{persona.attributes.slice(0, 4).map((attribute) => <span key={attribute.name}><small>{attribute.name}</small>{attribute.value}</span>)}</div>
                    <footer><code>{abbreviatedDigest(persona.profile_sha256)}</code><button type="button" aria-pressed={selected} disabled={!selected && selectedPersonaIds.length >= 100} onClick={() => togglePersona(persona.id)}>{selected ? "已加入 Cohort" : "加入 Cohort"}</button></footer>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {personasResponse !== null && personasResponse.total > 0 ? <nav className="persona-world-pagination" aria-label="Persona 分页"><button type="button" disabled={page <= 1 || personasState.status === "loading"} onClick={() => { setPage(page - 1); setInspectedPersonaId(null); }}>上一页</button><span>第 {page} / {totalPages} 页</span><button type="button" disabled={page >= totalPages || personasState.status === "loading"} onClick={() => { setPage(page + 1); setInspectedPersonaId(null); }}>下一页</button></nav> : null}
        </section>

        <aside className="persona-world-right" aria-label="Persona 核验与 Cohort 冻结">
          <PersonaInspector persona={inspectedPersona} />
          <section className="persona-world-freeze" aria-labelledby="persona-freeze-title">
            <header><span>SELECTION / COHORT</span><h3 id="persona-freeze-title">冻结当前选择</h3><p>{selectedPersonaIds.length} 人已跨页保留</p></header>
            {selectedPersonaIds.length > 0 ? <button className="persona-world-clear" type="button" disabled={isSubmitting} onClick={() => { setSelectedPersonaIds([]); setFreezeState({ status: "idle" }); }}>清空全部选择</button> : null}
            <label htmlFor="persona-world-cohort-title"><span>Cohort 名称</span><input id="persona-world-cohort-title" name="cohort_title" type="text" maxLength={200} value={cohortTitle} placeholder="例如：核心政策观察组" disabled={isSubmitting} aria-invalid={currentTitleError !== null} onBlur={() => setTitleTouched(true)} onChange={(event) => { setCohortTitle(event.target.value); setFreezeState({ status: "idle" }); }} /></label>
            {currentTitleError !== null ? <p className="persona-world-field-error" role="alert">{currentTitleError}</p> : null}
            <button className="persona-world-freeze-action" type="button" disabled={!canFreeze} aria-busy={isSubmitting} onClick={() => void freezeCohort()}>{isSubmitting ? "正在封存…" : `冻结 ${selectedPersonaIds.length} 人 Cohort`}</button>
            {freezeState.status === "error" ? <div className="persona-world-message" data-status="error" role="alert"><strong>{isAmbiguousPostResultError(freezeState.error) ? "冻结结果未知，请先刷新目录核对" : "Cohort 没有冻结"}</strong><p>{freezeState.error.message}</p></div> : null}
            {freezeState.status === "success" ? <div className="persona-world-message" data-status="success" role="status"><strong>已冻结，可进入模拟运行</strong><p>{freezeState.cohort.title} · {freezeState.cohort.persona_count} 人</p><code>{freezeState.cohort.cohort_sha256}</code><a href={cohortRunStudioHref()}>进入模拟运行工作台 →</a></div> : null}
          </section>
          {selectedCohortId !== null ? (
            <section className="persona-world-cohort-detail" aria-labelledby="persona-cohort-detail-title">
              <header><span>COHORT / INSPECTOR</span><h3 id="persona-cohort-detail-title">{selectedCohort?.title ?? "正在核验 Cohort"}</h3></header>
              {cohortDetailState.status === "error" ? <ApiErrorPanel title="无法读取 Cohort 详情" error={cohortDetailState.error} isRetrying={cohortDetailState.isRetrying} onRetry={reloadCohortDetail} /> : null}
              {selectedCohort !== null ? <><dl><div><dt>成员</dt><dd>{selectedCohort.persona_count}</dd></div><div><dt>dataset</dt><dd>{selectedCohort.dataset.slug}</dd></div><div><dt>hash</dt><dd><code>{selectedCohort.cohort_sha256}</code></dd></div></dl><ol>{selectedCohort.members.map((member) => <li key={member.persona.id}><span>{member.position + 1}</span><strong>{member.persona.display_name}</strong><small>{member.persona.persona_id}</small></li>)}</ol><a href={cohortRunStudioHref()}>进入模拟运行工作台 →</a></> : null}
            </section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
