import { useMemo, useState, type KeyboardEvent } from "react";

import { ApiErrorPanel } from "./ApiErrorPanel";
import type { SemanticTrial, SemanticTrialEvent } from "./semanticExperimentContracts";
import { useCohortDetail } from "./usePopulations";
import { useSemanticTrialEvents } from "./useSemanticExperiments";
import "./runInteractionGraph.css";

type InteractionNodeKind = "scenario" | "persona" | "post" | "comment";
type InteractionEdgeKind = "authored" | "replied_to" | "reacted_to";

interface InteractionNode {
  readonly id: string;
  readonly kind: InteractionNodeKind;
  readonly label: string;
  readonly detail: string;
  readonly x: number;
  readonly y: number;
}

interface InteractionEdge {
  readonly id: string;
  readonly sourceId: string;
  readonly targetId: string;
  readonly kind: InteractionEdgeKind;
  readonly sequence: number;
}

interface InteractionGraph {
  readonly nodes: readonly InteractionNode[];
  readonly edges: readonly InteractionEdge[];
  readonly width: number;
  readonly height: number;
}

function shortened(value: string): string {
  return value.length <= 18 ? value : `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function actorNodeId(event: SemanticTrialEvent): string {
  return event.actor_kind === "scenario"
    ? "actor:scenario"
    : `actor:${event.persona_id ?? "invalid"}`;
}

function appendNode(
  nodes: Map<string, Omit<InteractionNode, "x" | "y">>,
  node: Omit<InteractionNode, "x" | "y">,
): void {
  if (!nodes.has(node.id)) {
    nodes.set(node.id, node);
  }
}

function buildInteractionGraph(
  events: readonly SemanticTrialEvent[],
  personaNames: ReadonlyMap<string, string>,
): InteractionGraph {
  const nodes = new Map<string, Omit<InteractionNode, "x" | "y">>();
  const edges: InteractionEdge[] = [];

  for (const event of events) {
    const actorId = actorNodeId(event);
    const personaName = event.persona_id === null ? null : personaNames.get(event.persona_id) ?? null;
    appendNode(nodes, {
      id: actorId,
      kind: event.actor_kind,
      label: event.actor_kind === "scenario" ? "Scenario actor" : personaName ?? `Persona ${event.agent_position}`,
      detail: event.actor_kind === "scenario" ? "实验干预来源" : shortened(event.persona_id ?? ""),
    });

    if (event.action_type === "create_post" && event.post_id !== null) {
      const postId = `post:${event.post_id}`;
      appendNode(nodes, { id: postId, kind: "post", label: `Post ${shortened(event.post_id)}`, detail: event.content ?? "" });
      edges.push({ id: `edge:${event.sequence}:authored`, sourceId: actorId, targetId: postId, kind: "authored", sequence: event.sequence });
    } else if (event.action_type === "create_comment"
      && event.comment_id !== null
      && event.target_post_id !== null) {
      const commentId = `comment:${event.comment_id}`;
      const targetId = `post:${event.target_post_id}`;
      appendNode(nodes, { id: commentId, kind: "comment", label: `Comment ${shortened(event.comment_id)}`, detail: event.content ?? "" });
      appendNode(nodes, { id: targetId, kind: "post", label: `Post ${shortened(event.target_post_id)}`, detail: "被评论的真实平台对象" });
      edges.push({ id: `edge:${event.sequence}:authored`, sourceId: actorId, targetId: commentId, kind: "authored", sequence: event.sequence });
      edges.push({ id: `edge:${event.sequence}:reply`, sourceId: commentId, targetId, kind: "replied_to", sequence: event.sequence });
    } else if ((event.action_type === "like_post" || event.action_type === "dislike_post")
      && event.target_post_id !== null) {
      const targetId = `post:${event.target_post_id}`;
      appendNode(nodes, { id: targetId, kind: "post", label: `Post ${shortened(event.target_post_id)}`, detail: "被反应的真实平台对象" });
      edges.push({ id: `edge:${event.sequence}:reaction`, sourceId: actorId, targetId, kind: "reacted_to", sequence: event.sequence });
    }
  }

  const grouped: Readonly<Record<InteractionNodeKind, readonly Omit<InteractionNode, "x" | "y">[]>> = {
    scenario: [...nodes.values()].filter((node) => node.kind === "scenario"),
    persona: [...nodes.values()].filter((node) => node.kind === "persona"),
    comment: [...nodes.values()].filter((node) => node.kind === "comment"),
    post: [...nodes.values()].filter((node) => node.kind === "post"),
  };
  const maximumRows = Math.max(1, ...Object.values(grouped).map((items) => items.length));
  const height = Math.max(330, 100 + maximumRows * 76);
  const columnX: Readonly<Record<InteractionNodeKind, number>> = {
    scenario: 85,
    persona: 85,
    comment: 410,
    post: 710,
  };
  const positioned = (Object.keys(grouped) as readonly InteractionNodeKind[]).flatMap((kind) => {
    const entries = grouped[kind];
    const availableHeight = height - 100;
    return entries.map((node, index) => ({
      ...node,
      x: columnX[kind],
      y: 60 + availableHeight * ((index + 1) / (entries.length + 1)),
    }));
  });

  return { nodes: positioned, edges, width: 800, height };
}

function nodeRadius(kind: InteractionNodeKind): number {
  return kind === "scenario" ? 22 : kind === "persona" ? 18 : 15;
}

function edgePath(source: InteractionNode, target: InteractionNode): string {
  const controlOffset = Math.max(48, Math.abs(target.x - source.x) * 0.45);
  return `M ${source.x} ${source.y} C ${source.x + controlOffset} ${source.y}, ${target.x - controlOffset} ${target.y}, ${target.x} ${target.y}`;
}

export function RunInteractionGraph({
  trial,
  cohortId,
}: {
  readonly trial: SemanticTrial | null;
  readonly cohortId: string | null;
}): JSX.Element {
  const { state: eventState, reload: reloadEvents } = useSemanticTrialEvents(
    trial?.id ?? null,
    trial?.status ?? null,
  );
  const { state: cohortState } = useCohortDetail(cohortId);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const personaNames = useMemo(() => {
    if (cohortState.status !== "success") return new Map<string, string>();
    return new Map(cohortState.data.members.map((member) => [member.persona.id, member.persona.display_name]));
  }, [cohortState]);
  const events = eventState.status === "idle" ? [] : eventState.items;
  const graph = useMemo(() => buildInteractionGraph(events, personaNames), [events, personaNames]);
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const selectFromKeyboard = (event: KeyboardEvent<SVGGElement>, nodeId: string): void => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setSelectedNodeId(nodeId);
    }
  };

  return (
    <section className="run-interaction-graph" aria-labelledby="run-interaction-graph-title">
      <header>
        <div><span>MIROFISH LENS / REAL EVENTS</span><h3 id="run-interaction-graph-title">Trial 运行互动图</h3><p>Actor、Post、Comment 与 Reaction 全部由当前 Trial 的类型化事件生成。</p></div>
        <div><strong>{graph.nodes.length}</strong><small>nodes</small><strong>{graph.edges.length}</strong><small>edges</small><button type="button" onClick={reloadEvents}>刷新事件</button></div>
      </header>
      {trial === null ? <div className="run-interaction-empty"><strong>选择一个 Trial</strong><p>点击矩阵单元格后，中央画布才会读取该 Trial 的真实互动关系。</p></div> : null}
      {eventState.status === "error" ? <ApiErrorPanel title="无法构建运行互动图" error={eventState.error} isRetrying={false} onRetry={reloadEvents} /> : null}
      {trial !== null && eventState.status !== "idle" && events.length === 0 ? <div className="run-interaction-empty"><strong>{eventState.status === "loading" ? "正在读取事件" : "当前 Trial 没有可连边事件"}</strong><p>do_nothing 仍保留在事件时间线中，但不会制造虚假的对象节点。</p></div> : null}
      {graph.nodes.length > 0 ? (
        <div className="run-interaction-canvas">
          <svg viewBox={`0 0 ${graph.width} ${graph.height}`} role="img" aria-label={`当前 Trial 互动图，${graph.nodes.length} 个节点，${graph.edges.length} 条边`}>
            <defs><marker id="interaction-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
            <g className="run-interaction-edges">{graph.edges.map((edge) => {
              const source = nodesById.get(edge.sourceId);
              const target = nodesById.get(edge.targetId);
              if (source === undefined || target === undefined) return null;
              return <path key={edge.id} d={edgePath(source, target)} data-kind={edge.kind} markerEnd="url(#interaction-arrow)"><title>#{edge.sequence} {edge.kind}</title></path>;
            })}</g>
            <g className="run-interaction-nodes">{graph.nodes.map((node) => (
              <g key={node.id} transform={`translate(${node.x} ${node.y})`} data-kind={node.kind} data-selected={node.id === selectedNodeId} role="button" tabIndex={0} aria-label={`${node.label}，${node.kind}`} onClick={() => setSelectedNodeId(node.id)} onKeyDown={(event) => selectFromKeyboard(event, node.id)}>
                <circle r={nodeRadius(node.kind)} /><circle className="run-interaction-node-halo" r={nodeRadius(node.kind) + 7} /><text x={node.kind === "post" ? -18 : 22} y="4" textAnchor={node.kind === "post" ? "end" : "start"}>{node.label}</text>
              </g>
            ))}</g>
          </svg>
          <aside aria-live="polite">{selectedNode === null ? <><strong>选择一个节点</strong><p>点击圆点核对对象类型与真实内容摘要。</p></> : <><span>{selectedNode.kind}</span><strong>{selectedNode.label}</strong><p>{selectedNode.detail || "该节点没有文本内容。"}</p><code>{selectedNode.id}</code></>}</aside>
        </div>
      ) : null}
      <footer><span><i data-kind="scenario" />Scenario</span><span><i data-kind="persona" />Persona</span><span><i data-kind="post" />Post</span><span><i data-kind="comment" />Comment</span><p>这是运行事件图，不是 Zep 世界图，也不表示现实社会关系。</p></footer>
    </section>
  );
}
