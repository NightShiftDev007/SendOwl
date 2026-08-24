import { useState, type KeyboardEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import "./evidenceWorldGraph.css";
import { useEvidenceWorldGraph } from "./useEvidenceWorldGraph";
import type { EvidenceWorldGraphNode } from "./worldModelContracts";

interface PositionedNode {
  readonly node: EvidenceWorldGraphNode;
  readonly x: number;
  readonly y: number;
}

const canvasWidth = 900;
const canvasHeight = 580;

function graphNodeLabel(node: EvidenceWorldGraphNode): string {
  if (node.kind === "world_snapshot") return "冻结快照";
  return node.label.length > 16 ? `${node.label.slice(0, 15)}…` : node.label;
}

function radiusForKind(kind: EvidenceWorldGraphNode["kind"]): number {
  if (kind === "world_snapshot") return 0;
  if (kind === "article") return 155;
  if (kind === "source") return 245;
  return 285;
}

function singletonAngle(kind: EvidenceWorldGraphNode["kind"]): number {
  if (kind === "article") return -Math.PI / 2;
  if (kind === "source") return Math.PI * 0.78;
  if (kind === "country") return Math.PI * 0.22;
  return 0;
}

function positionNodes(nodes: readonly EvidenceWorldGraphNode[]): readonly PositionedNode[] {
  const groups = new Map<EvidenceWorldGraphNode["kind"], readonly EvidenceWorldGraphNode[]>();
  for (const kind of ["world_snapshot", "article", "source", "country"] as const) {
    groups.set(kind, nodes.filter((node) => node.kind === kind));
  }
  const positioned: PositionedNode[] = [];
  for (const [kind, group] of groups) {
    const radius = radiusForKind(kind);
    group.forEach((node, index) => {
      const angle = group.length === 1
        ? singletonAngle(kind)
        : (Math.PI * 2 * index) / group.length - Math.PI / 2;
      positioned.push({
        node,
        x: canvasWidth / 2 + Math.cos(angle) * radius,
        y: canvasHeight / 2 + Math.sin(angle) * radius,
      });
    });
  }
  return positioned.sort((left, right) => left.node.position - right.node.position);
}

function selectOnKeyboard(
  event: KeyboardEvent<SVGGElement>,
  nodeId: string,
  onSelect: (nodeId: string) => void,
): void {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  onSelect(nodeId);
}

export function EvidenceWorldGraph({
  worldModelId,
  snapshotId,
}: {
  readonly worldModelId: string;
  readonly snapshotId: string;
}): JSX.Element {
  const { state, reload } = useEvidenceWorldGraph(worldModelId, snapshotId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  if (state.status === "loading") {
    return <div className="evidence-graph-loading" role="status">正在从冻结快照生成证据关系图…</div>;
  }
  if (state.status === "error") {
    return (
      <ApiErrorPanel
        title="无法生成证据关系图"
        error={state.error}
        isRetrying={state.isRetrying}
        onRetry={reload}
      />
    );
  }

  const positions = positionNodes(state.data.nodes);
  const positionById = new Map(positions.map((item) => [item.node.id, item]));
  const selectedNode = state.data.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const counts = {
    articles: state.data.nodes.filter((node) => node.kind === "article").length,
    sources: state.data.nodes.filter((node) => node.kind === "source").length,
    countries: state.data.nodes.filter((node) => node.kind === "country").length,
  };

  return (
    <section className="evidence-world-graph" aria-labelledby="evidence-world-graph-title">
      <header>
        <div>
          <span>冻结证据关系</span>
          <h4 id="evidence-world-graph-title">证据关系图</h4>
          <p>展示当前快照中的文章、媒体来源与国家如何直接关联。这不是地理地图，也不推断社会关系。</p>
        </div>
        <dl>
          <div><dt>文章</dt><dd>{counts.articles}</dd></div>
          <div><dt>来源</dt><dd>{counts.sources}</dd></div>
          <div><dt>国家</dt><dd>{counts.countries}</dd></div>
        </dl>
      </header>
      <div className="evidence-graph-stage">
        <div className="evidence-graph-canvas" role="group" aria-label={`证据关系图，${state.data.nodes.length} 个节点，${state.data.edges.length} 条直接关系`}>
          <svg viewBox={`0 0 ${canvasWidth} ${canvasHeight}`}>
            <g className="evidence-graph-edges">
              {state.data.edges.map((edge) => {
                const source = positionById.get(edge.source_node_id);
                const target = positionById.get(edge.target_node_id);
                if (source === undefined || target === undefined) return null;
                return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} data-kind={edge.kind} />;
              })}
            </g>
            <g className="evidence-graph-nodes">
              {positions.map(({ node, x, y }) => (
                <g
                  key={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${node.kind}: ${node.label}`}
                  aria-pressed={node.id === selectedNodeId}
                  data-kind={node.kind}
                  data-selected={node.id === selectedNodeId}
                  transform={`translate(${x} ${y})`}
                  onClick={() => setSelectedNodeId(node.id)}
                  onKeyDown={(event) => selectOnKeyboard(event, node.id, setSelectedNodeId)}
                >
                  <circle className="evidence-graph-hit-target" r={22} />
                  <circle className="evidence-graph-node-marker" r={node.kind === "world_snapshot" ? 24 : node.kind === "article" ? 11 : 8} />
                  <text y={node.kind === "world_snapshot" ? 42 : 27} textAnchor="middle">{graphNodeLabel(node)}</text>
                </g>
              ))}
            </g>
          </svg>
        </div>
        <aside className="evidence-graph-inspector" aria-live="polite">
          {selectedNode === null ? (
            <div><span>节点说明</span><h5>选择节点核验</h5><p>点击带文字标签的节点，查看它在冻结快照中的名称和直接关系。</p></div>
          ) : (
            <div>
              <span>{selectedNode.kind.toUpperCase()}</span>
              <h5>{selectedNode.label}</h5>
              {selectedNode.detail === null ? null : <p>{selectedNode.detail}</p>}
              {selectedNode.article_id === null ? null : <code>article_id {selectedNode.article_id}</code>}
              {selectedNode.country_code === null ? null : <code>country {selectedNode.country_code}</code>}
            </div>
          )}
          <details className="evidence-graph-audit">
            <summary>技术审计</summary>
            <span>存储提供方</span><code>{state.data.provider}</code>
            <span>关系图 SHA-256</span><code title={state.data.graph_sha256}>{state.data.graph_sha256.slice(0, 18)}…</code>
          </details>
        </aside>
      </div>
    </section>
  );
}
