import { useState, type KeyboardEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import "./semanticWorldGraph.css";
import {
  selectedSemanticWorldGraph,
  useSemanticWorldGraphSlice,
  useSemanticWorldGraphTimeline,
  useSemanticWorldGraphs,
} from "./useSemanticWorldGraphs";
import type {
  SemanticWorldGraphEdge,
  SemanticWorldGraphNode,
  SemanticWorldGraphSliceDirection,
} from "./worldModelContracts";

const width = 880;
const height = 560;

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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"full" | "slice" | "timeline">("full");
  const [sliceDirection, setSliceDirection] = useState<SemanticWorldGraphSliceDirection>("both");
  const [sliceHops, setSliceHops] = useState<number>(1);
  const selectedGraph = selectedSemanticWorldGraph(state.data, selectedGraphId);
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
          disabled={enqueueState === "submitting"}
          aria-busy={enqueueState === "submitting"}
          onClick={() => void enqueue()}
        >
          {enqueueState === "submitting" ? "正在提交…" : "用当前快照生成语义图"}
        </button>
      </header>

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
                setViewMode("full");
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
                                onClick={() => setSelectedNodeId(node.id)}
                              >
                                {entityTypeLabels[node.entity_type]} · {node.name}
                              </button>
                            );
                          })}
                          {item.edge_ids.map((edgeId) => {
                            const edge = graphEdgesById.get(edgeId);
                            return edge === undefined ? null : (
                              <span key={edge.id}>{edge.relation_type} · {edge.fact}</span>
                            );
                          })}
                        </div>
                      </div>
                    </article>
                  )) : null}
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
                          setViewMode("slice");
                        }}
                        onKeyDown={(event) => onNodeKeyDown(event, node.id, (nodeId) => {
                          setSelectedNodeId(nodeId);
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
              <div className="semantic-related-relations">
                <strong>{viewMode === "slice" ? "切片内关系" : "相邻关系"} · {selectedRelations.length}</strong>
                {selectedRelations.map((edge) => (
                  <article key={edge.id}>
                    <code>{edge.relation_type}</code>
                    <p>{edge.fact}</p>
                    {edge.evidence.map((evidence) => (
                      <q key={`${evidence.article_id}-${evidence.position}`}>{evidence.quote}</q>
                    ))}
                  </article>
                ))}
              </div>
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
