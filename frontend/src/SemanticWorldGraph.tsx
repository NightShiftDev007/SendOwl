import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ZodError } from "zod";

import { ApiErrorPanel } from "./ApiErrorPanel";
import { isAmbiguousPostResultError } from "./apiClient";
import {
  cohortCreateRequestSchema,
  type CohortCreateRequest,
} from "./populationContracts";
import { createRunStudioHash } from "./runStudioRoute";
import { usePopulationDatasets } from "./usePopulations";
import { useSemanticReadiness } from "./useSemanticExperiments";
import "./semanticWorldGraph.css";
import {
  selectedSemanticWorldGraph,
  useSemanticWorldGraphEdgeHistory,
  useSemanticWorldGraphPersonaMatches,
  useSemanticWorldGraphSlice,
  useSemanticWorldGraphSearch,
  useSemanticWorldGraphTimeline,
  useSemanticWorldGraphs,
} from "./useSemanticWorldGraphs";
import type {
  GraphPersonaCohortCreation,
  SemanticWorldGraphEdge,
  SemanticWorldGraphNode,
  SemanticWorldGraphSliceDirection,
} from "./worldModelContracts";
import { createGraphPersonaCohort } from "./worldModelContracts";

const width = 880;
const height = 560;

type GraphCohortCreationState =
  | { readonly status: "idle" }
  | { readonly status: "submitting" }
  | { readonly status: "success"; readonly result: GraphPersonaCohortCreation }
  | { readonly status: "error"; readonly error: Error };

interface PositionedSemanticNode {
  readonly node: SemanticWorldGraphNode;
  readonly x: number;
  readonly y: number;
}

const entityTypeLabels: Readonly<Record<SemanticWorldGraphNode["entity_type"], string>> = {
  organization: "组织",
  person: "人物",
  location: "地点",
  policy: "政策",
  event: "事件",
  concept: "概念",
};

function positionSemanticNodes(
  nodes: readonly SemanticWorldGraphNode[],
): readonly PositionedSemanticNode[] {
  return nodes.map((node, index) => {
    const ring = Math.floor(index / 18);
    const itemsBeforeRing = ring * 18;
    const ringItems = Math.min(18, nodes.length - itemsBeforeRing);
    const radius = Math.min(220, 92 + ring * 46);
    const angle = ((index - itemsBeforeRing) / ringItems) * Math.PI * 2 - Math.PI / 2;
    return {
      node,
      x: width / 2 + Math.cos(angle) * radius,
      y: height / 2 + Math.sin(angle) * radius,
    };
  });
}

function onNodeKeyDown(
  event: KeyboardEvent<SVGGElement>,
  nodeId: string,
  selectNode: (selectedNodeId: string) => void,
): void {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  selectNode(nodeId);
}

function relatedEdges(
  edges: readonly SemanticWorldGraphEdge[],
  nodeId: string,
): readonly SemanticWorldGraphEdge[] {
  return edges.filter(
    (edge) => edge.source_node_id === nodeId || edge.target_node_id === nodeId,
  );
}

function graphStatusLabel(status: "queued" | "running" | "succeeded" | "failed"): string {
  if (status === "queued") return "等待抽取";
  if (status === "running") return "千问抽取中";
  if (status === "succeeded") return "证据校验通过";
  return "抽取失败";
}

function cohortTitleError(value: string): string | null {
  const normalized = value.trim();
  if (normalized.length === 0) return "请输入 Cohort 名称。";
  if (normalized.length > 200) return "Cohort 名称不能超过 200 个字符。";
  if (/\r|\n/u.test(normalized)) return "Cohort 名称只能使用一行文本。";
  return null;
}

function normalizeCohortError(error: unknown): Error {
  if (error instanceof ZodError) {
    return new Error(`Cohort 冻结输入无效：${error.issues
      .map((issue) => `${issue.path.join(".") || "request"}: ${issue.message}`)
      .join("; ")}`);
  }
  return error instanceof Error
    ? error
    : new Error("冻结 Cohort 失败：请求抛出了非标准错误。请检查后端日志。");
}

function cohortRunStudioHref(cohortId: string): string {
  return createRunStudioHash({
    mode: "semantic",
    cohortId,
    scenarioId: null,
    experimentId: null,
    trialId: null,
    panel: null,
  });
}

export function SemanticWorldGraph({
  worldModelId,
  snapshotId,
}: {
  readonly worldModelId: string;
  readonly snapshotId: string;
}): JSX.Element {
  const {
    state,
    enqueueState,
    selectedGraphId,
    selectGraph,
    enqueue,
    reload,
  } = useSemanticWorldGraphs(worldModelId, snapshotId);
  const { state: readinessState, reload: reloadReadiness } = useSemanticReadiness();
  const { state: datasetsState, reload: reloadDatasets } = usePopulationDatasets();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"full" | "slice" | "timeline" | "search">("full");
  const [sliceDirection, setSliceDirection] = useState<SemanticWorldGraphSliceDirection>("both");
  const [sliceHops, setSliceHops] = useState<number>(1);
  const [searchDraft, setSearchDraft] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<readonly string[]>([]);
  const [cohortTitle, setCohortTitle] = useState<string>("");
  const [cohortTitleTouched, setCohortTitleTouched] = useState<boolean>(false);
  const [cohortCreationState, setCohortCreationState] = useState<GraphCohortCreationState>({
    status: "idle",
  });
  const activeCohortController = useRef<AbortController | null>(null);
  const selectedGraph = selectedSemanticWorldGraph(state.data, selectedGraphId);
  const readiness = readinessState.data;
  const runtimeReady = readiness?.semantic_runtime_ready === true;
  const { state: sliceState, reload: reloadSlice } = useSemanticWorldGraphSlice(
    selectedGraph?.status === "succeeded" && viewMode === "slice" ? selectedGraph.id : null,
    viewMode === "slice" ? selectedNodeId : null,
    sliceDirection,
    sliceHops,
    40,
  );
  const { state: timelineState, reload: reloadTimeline } = useSemanticWorldGraphTimeline(
    selectedGraph?.status === "succeeded" && viewMode === "timeline" ? selectedGraph.id : null,
  );
  const { state: searchState, reload: reloadSearch } = useSemanticWorldGraphSearch(
    selectedGraph?.status === "succeeded" && viewMode === "search" ? selectedGraph.id : null,
    viewMode === "search" ? searchQuery : null,
  );
  const { state: edgeHistoryState, reload: reloadEdgeHistory } = useSemanticWorldGraphEdgeHistory(
    selectedGraph?.status === "succeeded" ? selectedGraph.id : null,
    selectedGraph?.status === "succeeded" ? selectedEdgeId : null,
  );
  const {
    state: personaMatchesState,
    reload: reloadPersonaMatches,
  } = useSemanticWorldGraphPersonaMatches(
    selectedGraph?.status === "succeeded" ? selectedGraph.id : null,
    selectedGraph?.status === "succeeded" ? selectedNodeId : null,
    selectedDatasetId,
  );
  useEffect(() => {
    if (
      selectedDatasetId !== null
      && datasetsState.data !== null
      && !datasetsState.data.items.some((dataset) => dataset.id === selectedDatasetId)
    ) {
      setSelectedDatasetId(null);
    }
  }, [datasetsState.data, selectedDatasetId]);
  const candidateScopeKey = `${selectedGraph?.id ?? ""}:${selectedNodeId ?? ""}:${selectedDatasetId ?? ""}`;
  useEffect(() => {
    activeCohortController.current?.abort();
    activeCohortController.current = null;
    setSelectedCandidateIds([]);
    setCohortTitle("");
    setCohortTitleTouched(false);
    setCohortCreationState({ status: "idle" });
    return () => activeCohortController.current?.abort();
  }, [candidateScopeKey]);
  const selectedNode = selectedGraph?.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const graphNodesById = new Map((selectedGraph?.nodes ?? []).map((node) => [node.id, node]));
  const graphEdgesById = new Map((selectedGraph?.edges ?? []).map((edge) => [edge.id, edge]));
  const visibleNodes = viewMode === "slice" && sliceState.status === "success"
    ? sliceState.data.nodes
    : selectedGraph?.nodes ?? [];
  const visibleEdges = viewMode === "slice" && sliceState.status === "success"
    ? sliceState.data.edges
    : selectedGraph?.edges ?? [];
  const positions = positionSemanticNodes(visibleNodes);
  const positionsById = new Map(positions.map((item) => [item.node.id, item]));
  const selectedRelations = selectedGraph === null || selectedNode === null
    ? []
    : relatedEdges(visibleEdges, selectedNode.id);
  const applySearch = (): void => {
    const query = searchDraft.trim();
    if (query.length < 2 || query.length > 100 || /[\r\n]/u.test(query)) {
      setSearchError("请输入 2–100 个字符的单行检索词。");
      return;
    }
    setSearchError(null);
    setSearchQuery(query);
    setViewMode("search");
  };
  const toggleCandidate = (personaId: string): void => {
    setSelectedCandidateIds((current) => {
      if (current.includes(personaId)) {
        return current.filter((id) => id !== personaId);
      }
      return current.length >= 8 ? current : [...current, personaId];
    });
    setCohortCreationState({ status: "idle" });
  };
  const createCandidateCohort = async (): Promise<void> => {
    setCohortTitleTouched(true);
    if (
      personaMatchesState.status !== "success"
      || selectedCandidateIds.length === 0
      || selectedCandidateIds.length > 8
      || selectedGraph === null
      || selectedNodeId === null
      || cohortTitleError(cohortTitle) !== null
      || activeCohortController.current !== null
    ) {
      return;
    }
    let request: CohortCreateRequest;
    try {
      request = cohortCreateRequestSchema.parse({
        title: cohortTitle.trim(),
        dataset_id: personaMatchesState.data.dataset.id,
        persona_ids: selectedCandidateIds,
      });
    } catch (error: unknown) {
      setCohortCreationState({ status: "error", error: normalizeCohortError(error) });
      return;
    }
    const controller = new AbortController();
    activeCohortController.current = controller;
    setCohortCreationState({ status: "submitting" });
    try {
      const result = await createGraphPersonaCohort(
        selectedGraph.id,
        selectedNodeId,
        request,
        controller.signal,
      );
      if (!controller.signal.aborted && activeCohortController.current === controller) {
        setCohortCreationState({ status: "success", result });
      }
    } catch (error: unknown) {
      if (!(error instanceof DOMException && error.name === "AbortError")
        && activeCohortController.current === controller) {
        setCohortCreationState({ status: "error", error: normalizeCohortError(error) });
      }
    } finally {
      if (activeCohortController.current === controller) {
        activeCohortController.current = null;
      }
    }
  };

  return (
    <section className="semantic-world-graph" aria-labelledby="semantic-world-graph-title">
      <header>
        <div>
          <h4 id="semantic-world-graph-title">千问语义世界图</h4>
          <p>
            千问只负责从冻结正文提取实体与关系；PostgreSQL 保存图结构，并逐条核验原文引用和字符位置。
          </p>
        </div>
        <button
          className="button button-primary button-compact"
          type="button"
          disabled={enqueueState === "submitting" || !runtimeReady}
          aria-busy={enqueueState === "submitting"}
          onClick={() => void enqueue()}
        >
          {enqueueState === "submitting"
            ? "正在提交…"
            : runtimeReady
              ? "用当前快照生成语义图"
              : "语义运行时未就绪"}
        </button>
      </header>

      <section className="semantic-graph-readiness" aria-live="polite">
        <div>
          <span>Qwen Worker</span>
          <strong data-ready={runtimeReady}>
            {readinessState.status === "loading"
              ? "正在核验"
              : runtimeReady
                ? `可提交 · ${readiness?.model_name ?? "模型身份缺失"}`
                : "配置阻塞"}
          </strong>
          <p>
            {runtimeReady
              ? "提交前仍会重新读取 readiness，配置漂移时不会发送 POST。"
              : readiness?.limitations.at(-1)
                ?? "无法读取语义运行时状态；图谱提交保持锁定。"}
          </p>
        </div>
        <button type="button" onClick={reloadReadiness}>重新核验</button>
      </section>

      {state.status === "error" ? (
        <ApiErrorPanel
          title="语义图接口不可用"
          error={state.error}
          isRetrying={state.isRetrying}
          onRetry={reload}
        />
      ) : null}

      <div className="semantic-graph-workspace">
        <aside className="semantic-graph-runs" aria-label="语义图抽取记录">
          <div>
            <strong>抽取记录</strong>
            <span>{state.data === null ? "读取中" : `${state.data.total} 次`}</span>
          </div>
          {state.data !== null && state.data.items.length === 0 ? (
            <p>尚未提交语义抽取。直接证据图仍可独立使用。</p>
          ) : null}
          {state.data?.items.map((graph) => (
            <button
              type="button"
              key={graph.id}
              data-selected={selectedGraphId === graph.id}
              aria-pressed={selectedGraphId === graph.id}
              onClick={() => {
                selectGraph(graph.id);
                setSelectedNodeId(null);
                setSelectedEdgeId(null);
                setViewMode("full");
                setSearchDraft("");
                setSearchQuery(null);
                setSearchError(null);
              }}
            >
              <span data-status={graph.status}>{graphStatusLabel(graph.status)}</span>
              <code>{graph.model_name}</code>
              <small>{new Date(graph.created_at).toLocaleString("zh-CN")}</small>
            </button>
          ))}
        </aside>

        <div className="semantic-graph-center">
          {selectedGraph === null ? (
            <div className="semantic-graph-empty" role="status">
              <strong>选择一条抽取记录</strong>
              <p>成功记录会在这里显示实体网络；等待和失败记录保留真实状态，不生成占位图。</p>
            </div>
          ) : null}
          {selectedGraph?.status === "queued" || selectedGraph?.status === "running" ? (
            <div className="semantic-graph-empty" role="status" aria-live="polite">
              <strong>{graphStatusLabel(selectedGraph.status)}</strong>
              <p>Worker 正在使用冻结快照和固定模型配置；页面每 2 秒读取一次持久状态。</p>
            </div>
          ) : null}
          {selectedGraph?.status === "failed" ? (
            <div className="semantic-graph-failure" role="alert">
              <strong>{selectedGraph.error_code}</strong>
              <p>{selectedGraph.error_message}</p>
            </div>
          ) : null}
          {selectedGraph?.status === "succeeded" ? (
            <>
              <div className="semantic-slice-toolbar" aria-label="World Slice 控制">
                <div className="semantic-slice-mode" role="group" aria-label="图谱视图">
                  <button
                    type="button"
                    data-active={viewMode === "full"}
                    aria-pressed={viewMode === "full"}
                    onClick={() => setViewMode("full")}
                  >
                    整图
                  </button>
                  <button
                    type="button"
                    data-active={viewMode === "slice"}
                    aria-pressed={viewMode === "slice"}
                    disabled={selectedNodeId === null}
                    onClick={() => setViewMode("slice")}
                  >
                    World Slice
                  </button>
                  <button
                    type="button"
                    data-active={viewMode === "timeline"}
                    aria-pressed={viewMode === "timeline"}
                    onClick={() => setViewMode("timeline")}
                  >
                    Evidence Timeline
                  </button>
                  <button
                    type="button"
                    data-active={viewMode === "search"}
                    aria-pressed={viewMode === "search"}
                    onClick={() => setViewMode("search")}
                  >
                    图谱检索
                  </button>
                </div>
                {viewMode === "slice" ? (
                  <div className="semantic-slice-options">
                    <label htmlFor="semantic-slice-direction">
                      方向
                      <select
                        id="semantic-slice-direction"
                        name="semantic_slice_direction"
                        value={sliceDirection}
                        onChange={(event) => setSliceDirection(
                          event.target.value as SemanticWorldGraphSliceDirection,
                        )}
                      >
                        <option value="both">双向</option>
                        <option value="outbound">向外</option>
                        <option value="inbound">向内</option>
                      </select>
                    </label>
                    <label htmlFor="semantic-slice-hops">
                      跳数
                      <select
                        id="semantic-slice-hops"
                        name="semantic_slice_hops"
                        value={sliceHops}
                        onChange={(event) => setSliceHops(Number(event.target.value))}
                      >
                        <option value={1}>1 hop</option>
                        <option value={2}>2 hops</option>
                        <option value={3}>3 hops</option>
                      </select>
                    </label>
                    <span aria-live="polite">
                      {sliceState.status === "loading" ? "切片读取中…" : null}
                      {sliceState.status === "success"
                        ? `${sliceState.data.nodes.length} 实体 · ${sliceState.data.edges.length} 关系${sliceState.data.truncated ? " · 已按上限截断" : ""}`
                        : null}
                    </span>
                    {sliceState.status === "error" ? (
                      <button type="button" onClick={reloadSlice}>切片失败，重试</button>
                    ) : null}
                  </div>
                ) : viewMode === "timeline" ? (
                  <div className="semantic-timeline-status" aria-live="polite">
                    <span>按冻结文章发布时间排序，不代表事实生效时间</span>
                    {timelineState.status === "loading" ? <span>时间线读取中…</span> : null}
                    {timelineState.status === "error" ? (
                      <button type="button" onClick={reloadTimeline}>时间线失败，重试</button>
                    ) : null}
                  </div>
                ) : viewMode === "search" ? (
                  <div className="semantic-search-controls">
                    <label htmlFor="semantic-world-graph-search">词法检索</label>
                    <input
                      id="semantic-world-graph-search"
                      name="semantic_world_graph_search"
                      type="search"
                      minLength={2}
                      maxLength={100}
                      value={searchDraft}
                      aria-invalid={searchError !== null}
                      placeholder="实体、关系、事实或证据原文"
                      onChange={(event) => {
                        setSearchDraft(event.target.value);
                        setSearchError(null);
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          applySearch();
                        }
                      }}
                    />
                    <button type="button" onClick={applySearch}>检索</button>
                    {searchState.status === "loading" ? <span role="status">检索中…</span> : null}
                    {searchState.status === "error" ? <button type="button" onClick={reloadSearch}>失败，重试</button> : null}
                    {searchError === null ? null : <span role="alert">{searchError}</span>}
                  </div>
                ) : (
                  <span>选择实体后可查看有界邻域</span>
                )}
              </div>
              {viewMode === "timeline" ? (
                <div className="semantic-evidence-timeline" role="region" aria-label="图谱证据发布时间线">
                  {timelineState.status === "success" ? timelineState.data.items.map((item) => (
                    <article key={item.article_id}>
                      <time dateTime={item.published_at}>
                        {new Date(item.published_at).toLocaleString("zh-CN")}
                      </time>
                      <div>
                        <header>
                          <span>{item.source_name}{item.country_code === null ? "" : ` · ${item.country_code}`}</span>
                          <h5>{item.title}</h5>
                          <small>{item.evidence_reference_count} 条逐字引用 · 捕获于 {new Date(item.captured_at).toLocaleString("zh-CN")}</small>
                        </header>
                        <div className="semantic-timeline-objects">
                          {item.node_ids.map((nodeId) => {
                            const node = graphNodesById.get(nodeId);
                            return node === undefined ? null : (
                              <button
                                type="button"
                                key={node.id}
                                data-selected={selectedNodeId === node.id}
                                onClick={() => {
                                  setSelectedNodeId(node.id);
                                  setSelectedEdgeId(null);
                                }}
                              >
                                {entityTypeLabels[node.entity_type]} · {node.name}
                              </button>
                            );
                          })}
                          {item.edge_ids.map((edgeId) => {
                            const edge = graphEdgesById.get(edgeId);
                            return edge === undefined ? null : (
                              <button
                                type="button"
                                key={edge.id}
                                data-selected={selectedEdgeId === edge.id}
                                onClick={() => {
                                  setSelectedNodeId(edge.source_node_id);
                                  setSelectedEdgeId(edge.id);
                                  setViewMode("slice");
                                }}
                              >
                                {edge.relation_type} · {edge.fact}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </article>
                  )) : null}
                </div>
              ) : viewMode === "search" ? (
                <div className="semantic-search-results" role="region" aria-label="语义图谱词法检索结果">
                  {searchQuery === null ? (
                    <div className="semantic-graph-empty"><strong>输入检索词</strong><p>可查实体名、摘要、关系类型、事实和逐字证据；结果不使用向量相似度。</p></div>
                  ) : null}
                  {searchState.status === "success" && searchState.data.results.length === 0 ? (
                    <div className="semantic-graph-empty"><strong>没有词法匹配</strong><p>尝试更短的实体名、关系词或证据原文片段。</p></div>
                  ) : null}
                  {searchState.status === "success" ? (
                    <>
                      <header>
                        <strong>{searchState.data.total_match_count} 个匹配</strong>
                        <span>{searchState.data.truncated ? "仅显示前 20 项" : "已显示全部"}</span>
                      </header>
                      <ol>
                        {searchState.data.results.map((result) => {
                          const object = result.kind === "node" ? result.node : result.edge;
                          const label = result.kind === "node"
                            ? `${entityTypeLabels[result.node.entity_type]} · ${result.node.name}`
                            : `${result.edge.relation_type} · ${result.edge.fact}`;
                          const targetNodeId = result.kind === "node"
                            ? result.node.id
                            : result.edge.source_node_id;
                          return (
                            <li key={`${result.kind}:${object.id}`}>
                              <button type="button" onClick={() => {
                                setSelectedNodeId(targetNodeId);
                                setSelectedEdgeId(result.kind === "edge" ? result.edge.id : null);
                                setViewMode("slice");
                              }}>
                                <span>{result.kind === "node" ? "实体" : "关系"} · #{result.rank + 1}</span>
                                <strong>{label}</strong>
                                <small>命中：{result.matched_fields.join(" · ")} · {object.evidence.length} 条证据</small>
                                <q>{object.evidence[0]?.quote}</q>
                              </button>
                            </li>
                          );
                        })}
                      </ol>
                      <footer>{searchState.data.limitations.map((item) => <span key={item}>{item}</span>)}</footer>
                    </>
                  ) : null}
                </div>
              ) : (
                <svg
                  className="semantic-graph-canvas"
                  viewBox={`0 0 ${width} ${height}`}
                  role="group"
                  aria-label={`${viewMode === "slice" ? "World Slice" : "语义世界图"}，${visibleNodes.length} 个实体，${visibleEdges.length} 条证据关系`}
                >
                  <g className="semantic-graph-edges">
                    {visibleEdges.map((edge) => {
                      const source = positionsById.get(edge.source_node_id);
                      const target = positionsById.get(edge.target_node_id);
                      if (source === undefined || target === undefined) return null;
                      return (
                        <line
                          key={edge.id}
                          x1={source.x}
                          y1={source.y}
                          x2={target.x}
                          y2={target.y}
                          data-related={selectedNodeId === null
                            || edge.source_node_id === selectedNodeId
                            || edge.target_node_id === selectedNodeId}
                        />
                      );
                    })}
                  </g>
                  <g className="semantic-graph-nodes">
                    {positions.map(({ node, x, y }) => (
                      <g
                        key={node.id}
                        role="button"
                        tabIndex={0}
                        aria-label={`${entityTypeLabels[node.entity_type]}：${node.name}`}
                        aria-pressed={selectedNodeId === node.id}
                        data-type={node.entity_type}
                        data-selected={selectedNodeId === node.id}
                        transform={`translate(${x} ${y})`}
                        onClick={() => {
                          setSelectedNodeId(node.id);
                          setSelectedEdgeId(null);
                          setViewMode("slice");
                        }}
                        onKeyDown={(event) => onNodeKeyDown(event, node.id, (nodeId) => {
                          setSelectedNodeId(nodeId);
                          setSelectedEdgeId(null);
                          setViewMode("slice");
                        })}
                      >
                        <circle r={selectedNodeId === node.id ? 10 : 7} />
                      </g>
                    ))}
                  </g>
                </svg>
              )}
            </>
          ) : null}
        </div>

        <aside className="semantic-graph-inspector" aria-live="polite">
          {selectedGraph?.status !== "succeeded" ? (
            <div>
              <strong>证据检查器</strong>
              <p>只有经过服务端逐字引用校验的成功图谱才能在这里展开。</p>
            </div>
          ) : selectedNode === null ? (
            <div>
              <strong>选择一个实体</strong>
              <p>节点详情会同时列出实体证据及其相邻关系证据。</p>
            </div>
          ) : (
            <div>
              <span>{entityTypeLabels[selectedNode.entity_type]}</span>
              <h5>{selectedNode.name}</h5>
              <p>{selectedNode.summary}</p>
              <ul className="semantic-evidence-list">
                {selectedNode.evidence.map((evidence) => (
                  <li key={`${evidence.article_id}-${evidence.position}`}>
                    <q>{evidence.quote}</q>
                    <code>{evidence.article_id} · {evidence.start_offset}:{evidence.end_offset}</code>
                  </li>
                ))}
              </ul>
              <section className="semantic-persona-matches" aria-label="Persona 候选映射">
                <header>
                  <div>
                    <span>POPULATION / EXACT TOKEN OVERLAP</span>
                    <strong>Persona 候选映射</strong>
                  </div>
                  {datasetsState.status === "error" ? (
                    <button type="button" onClick={reloadDatasets}>数据集读取失败，重试</button>
                  ) : null}
                </header>
                <p>
                  用实体名称与冻结 Persona 的非低信息属性做可复算词法匹配；候选不代表受众、立场、偏好或因果相关性。
                </p>
                <label htmlFor="semantic-persona-dataset">
                  Persona 数据集
                  <select
                    id="semantic-persona-dataset"
                    name="semantic_persona_dataset"
                    value={selectedDatasetId ?? ""}
                    disabled={datasetsState.status === "loading" && datasetsState.data === null}
                    onChange={(event) => setSelectedDatasetId(
                      event.target.value === "" ? null : event.target.value,
                    )}
                  >
                    <option value="">显式选择数据集</option>
                    {datasetsState.data?.items.map((dataset) => (
                      <option key={dataset.id} value={dataset.id}>
                        {dataset.display_name} · {dataset.persona_count} Personas
                      </option>
                    ))}
                  </select>
                </label>
                {selectedDatasetId === null ? (
                  <div className="semantic-persona-match-empty">
                    <strong>尚未选择候选范围</strong>
                    <span>选择数据集后，仅扫描稳定顺序中的前 200 个 Persona。</span>
                  </div>
                ) : null}
                {personaMatchesState.status === "loading" ? (
                  <div className="semantic-persona-match-empty" role="status">
                    <strong>正在复算候选</strong>
                    <span>只比较冻结属性，不调用模型。</span>
                  </div>
                ) : null}
                {personaMatchesState.status === "error" ? (
                  <div className="semantic-persona-match-error" role="alert">
                    <span>{personaMatchesState.error.message}</span>
                    <button type="button" onClick={reloadPersonaMatches}>重新读取</button>
                  </div>
                ) : null}
                {personaMatchesState.status === "success" ? (
                  <>
                    <div className="semantic-persona-match-summary">
                      <strong>{personaMatchesState.data.total_match_count_in_scan} 个候选</strong>
                      <span>
                        已核验 {personaMatchesState.data.inspected_persona_count}
                        /{personaMatchesState.data.dataset_persona_count}
                        {personaMatchesState.data.scan_truncated ? " · 扫描已按上限截断" : ""}
                      </span>
                      <code>匹配词：{personaMatchesState.data.query_terms.join(" · ")}</code>
                    </div>
                    {personaMatchesState.data.matches.length === 0 ? (
                      <div className="semantic-persona-match-empty">
                        <strong>没有精确词法候选</strong>
                        <span>不会用相似度或模型补出匹配。</span>
                      </div>
                    ) : (
                      <ol className="semantic-persona-match-list">
                        {personaMatchesState.data.matches.map((match) => (
                          <li key={match.persona.id}>
                            <header>
                              <span>#{match.position + 1} · {match.score} 个匹配词</span>
                              <strong>{match.persona.display_name}</strong>
                              <code>{match.persona.persona_id}</code>
                              <button
                                type="button"
                                aria-pressed={selectedCandidateIds.includes(match.persona.id)}
                                disabled={
                                  !selectedCandidateIds.includes(match.persona.id)
                                  && selectedCandidateIds.length >= 8
                                }
                                onClick={() => toggleCandidate(match.persona.id)}
                              >
                                {selectedCandidateIds.includes(match.persona.id)
                                  ? "已选择"
                                  : "加入候选 Cohort"}
                              </button>
                            </header>
                            <p>命中：{match.matched_terms.join(" · ")}</p>
                            <dl>
                              {match.matched_attributes.map((attribute) => (
                                <div key={attribute.name}>
                                  <dt>{attribute.name}</dt>
                                  <dd title={attribute.value}>{attribute.value}</dd>
                                </div>
                              ))}
                            </dl>
                          </li>
                        ))}
                      </ol>
                    )}
                    {personaMatchesState.data.matches.length > 0 ? (
                      <section className="semantic-persona-cohort-composer" aria-label="冻结候选 Cohort">
                        <header>
                          <strong>冻结人工选择</strong>
                          <span>{selectedCandidateIds.length} / 8 人</span>
                        </header>
                        <p>
                          Cohort 封存成员顺序，并同时封存本次图谱、节点、数据集与人工选择来源；不会被写成 Persona 的立场或偏好。
                        </p>
                        <label htmlFor="semantic-persona-cohort-title">
                          Cohort 名称
                          <input
                            id="semantic-persona-cohort-title"
                            name="semantic_persona_cohort_title"
                            type="text"
                            maxLength={200}
                            value={cohortTitle}
                            disabled={cohortCreationState.status === "submitting"}
                            aria-invalid={cohortTitleTouched && cohortTitleError(cohortTitle) !== null}
                            placeholder="例如：港口政策观察候选组"
                            onBlur={() => setCohortTitleTouched(true)}
                            onChange={(event) => {
                              setCohortTitle(event.target.value);
                              setCohortCreationState({ status: "idle" });
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void createCandidateCohort();
                              }
                            }}
                          />
                        </label>
                        {cohortTitleTouched && cohortTitleError(cohortTitle) !== null ? (
                          <span role="alert">{cohortTitleError(cohortTitle)}</span>
                        ) : null}
                        <button
                          type="button"
                          disabled={
                            selectedCandidateIds.length === 0
                            || cohortTitleError(cohortTitle) !== null
                            || cohortCreationState.status === "submitting"
                          }
                          aria-busy={cohortCreationState.status === "submitting"}
                          onClick={() => void createCandidateCohort()}
                        >
                          {cohortCreationState.status === "submitting"
                            ? "正在冻结…"
                            : `冻结 ${selectedCandidateIds.length} 人 Cohort`}
                        </button>
                        {cohortCreationState.status === "error" ? (
                          <div className="semantic-persona-cohort-message" data-status="error" role="alert">
                            <strong>{isAmbiguousPostResultError(cohortCreationState.error)
                              ? "冻结结果未知，请到 Persona World 刷新目录核对"
                              : "Cohort 没有冻结"}</strong>
                            <span>{cohortCreationState.error.message}</span>
                            <small>POST 不会自动重试。</small>
                          </div>
                        ) : null}
                        {cohortCreationState.status === "success" ? (
                          <div className="semantic-persona-cohort-message" data-status="success" role="status">
                            <strong>已冻结 {cohortCreationState.result.cohort.persona_count} 人 Cohort</strong>
                            <span>{cohortCreationState.result.cohort.title}</span>
                            <small>图谱选择来源已封存</small>
                            <code>{cohortCreationState.result.origin.origin_sha256}</code>
                            <a href={cohortRunStudioHref(cohortCreationState.result.cohort.id)}>
                              带着这个 Cohort 进入 Run Studio →
                            </a>
                          </div>
                        ) : null}
                      </section>
                    ) : null}
                    <footer>
                      {personaMatchesState.data.limitations.map((limitation) => (
                        <span key={limitation}>{limitation}</span>
                      ))}
                    </footer>
                  </>
                ) : null}
              </section>
              <div className="semantic-related-relations">
                <strong>{viewMode === "slice" ? "切片内关系" : "相邻关系"} · {selectedRelations.length}</strong>
                {selectedRelations.map((edge) => (
                  <article key={edge.id} data-selected={selectedEdgeId === edge.id}>
                    <code>{edge.relation_type}</code>
                    <p>{edge.fact}</p>
                    {edge.evidence.map((evidence) => (
                      <q key={`${evidence.article_id}-${evidence.position}`}>{evidence.quote}</q>
                    ))}
                    <button
                      type="button"
                      className="semantic-edge-history-trigger"
                      aria-pressed={selectedEdgeId === edge.id}
                      onClick={() => setSelectedEdgeId(
                        selectedEdgeId === edge.id ? null : edge.id,
                      )}
                    >
                      {selectedEdgeId === edge.id ? "收起跨版本观察" : "查看跨版本观察"}
                    </button>
                  </article>
                ))}
              </div>
              {selectedEdgeId === null ? null : (
                <section className="semantic-edge-history" aria-label="关系跨版本观察历史">
                  <header>
                    <div><span>TEMPORAL / EXACT SIGNATURE</span><strong>跨版本事实观察</strong></div>
                    {edgeHistoryState.status === "loading" ? <small role="status">读取中…</small> : null}
                    {edgeHistoryState.status === "error" ? (
                      <button type="button" onClick={reloadEdgeHistory}>读取失败，重试</button>
                    ) : null}
                  </header>
                  {edgeHistoryState.status === "success" ? (
                    <>
                      <p>
                        {edgeHistoryState.data.signature.source_name}
                        {" → "}{edgeHistoryState.data.signature.relation_type}{" → "}
                        {edgeHistoryState.data.signature.target_name}
                      </p>
                      <ol>
                        {edgeHistoryState.data.items.map((item) => (
                          <li key={`${item.graph_id}:${item.edge_id}`}>
                            <span>V{item.snapshot_version}</span>
                            <div>
                              <strong>{item.evidence_article_ids.length} 篇冻结证据</strong>
                              <time dateTime={item.evidence_published_from}>
                                {new Date(item.evidence_published_from).toLocaleString("zh-CN")}
                                {item.evidence_published_from === item.evidence_published_through
                                  ? ""
                                  : ` — ${new Date(item.evidence_published_through).toLocaleString("zh-CN")}`}
                              </time>
                            </div>
                          </li>
                        ))}
                      </ol>
                      <footer>
                        <strong>{edgeHistoryState.data.items.length} 个版本观察</strong>
                        <span>{edgeHistoryState.data.truncated
                          ? `仅核验最近 ${edgeHistoryState.data.inspected_graph_count} 张成功图谱`
                          : `已核验全部 ${edgeHistoryState.data.total_succeeded_graph_count} 张成功图谱`}</span>
                        <p>这不是 valid_at / invalid_at；缺失也不代表事实失效。</p>
                      </footer>
                    </>
                  ) : null}
                </section>
              )}
            </div>
          )}
          {selectedGraph === null ? null : (
            <footer>
              <span>模型</span><code>{selectedGraph.model_name}</code>
              <span>输入哈希</span><code title={selectedGraph.input_sha256}>{selectedGraph.input_sha256.slice(0, 18)}…</code>
              {selectedGraph.graph_sha256 === null ? null : (
                <><span>图谱哈希</span><code title={selectedGraph.graph_sha256}>{selectedGraph.graph_sha256.slice(0, 18)}…</code></>
              )}
            </footer>
          )}
        </aside>
      </div>
    </section>
  );
}
