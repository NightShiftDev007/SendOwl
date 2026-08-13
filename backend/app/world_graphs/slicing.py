"""Pure deterministic neighborhood slicing for immutable semantic graphs."""

from collections import defaultdict
from uuid import UUID

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphSlice,
    WorldGraphSliceDirection,
)
from app.world_graphs.errors import WorldGraphNodeNotFoundError, WorldGraphNotReadyError


def _traversal_neighbors(
    edges: tuple[SemanticWorldGraphEdge, ...],
    direction: WorldGraphSliceDirection,
) -> dict[UUID, tuple[UUID, ...]]:
    neighbors: defaultdict[UUID, set[UUID]] = defaultdict(set)
    for edge in edges:
        if direction in {"both", "outbound"}:
            neighbors[edge.source_node_id].add(edge.target_node_id)
        if direction in {"both", "inbound"}:
            neighbors[edge.target_node_id].add(edge.source_node_id)
    return {node_id: tuple(values) for node_id, values in neighbors.items()}


def slice_semantic_world_graph(
    graph: SemanticWorldGraphDetail,
    root_node_id: UUID,
    direction: WorldGraphSliceDirection,
    hops: int,
    max_nodes: int,
) -> SemanticWorldGraphSlice:
    """Return the closest deterministic node neighborhood and its induced edges."""

    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise WorldGraphNotReadyError(
            f"semantic world graph {graph.id} is {graph.status!r}; "
            "only succeeded graphs can be sliced"
        )
    nodes_by_id = {node.id: node for node in graph.nodes}
    if root_node_id not in nodes_by_id:
        raise WorldGraphNodeNotFoundError(
            f"node {root_node_id} does not belong to semantic world graph {graph.id}"
        )
    node_order = {node.id: node.position for node in graph.nodes}
    neighbors = _traversal_neighbors(graph.edges, direction)
    selected_ids: list[UUID] = [root_node_id]
    selected_set = {root_node_id}
    frontier = [root_node_id]
    truncated = False
    for _distance in range(hops):
        next_frontier = sorted(
            {
                neighbor
                for node_id in frontier
                for neighbor in neighbors.get(node_id, ())
                if neighbor not in selected_set
            },
            key=node_order.__getitem__,
        )
        remaining = max_nodes - len(selected_ids)
        if len(next_frontier) > remaining:
            truncated = True
            next_frontier = next_frontier[:remaining]
        selected_ids.extend(next_frontier)
        selected_set.update(next_frontier)
        frontier = next_frontier
        if not frontier or len(selected_ids) == max_nodes:
            if frontier and any(
                neighbor not in selected_set
                for node_id in frontier
                for neighbor in neighbors.get(node_id, ())
            ):
                truncated = True
            break
    selected_nodes = tuple(nodes_by_id[node_id] for node_id in selected_ids)
    selected_edges = tuple(
        edge
        for edge in graph.edges
        if edge.source_node_id in selected_set and edge.target_node_id in selected_set
    )
    return SemanticWorldGraphSlice(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        root_node_id=root_node_id,
        direction=direction,
        hops=hops,
        max_nodes=max_nodes,
        truncated=truncated,
        total_graph_node_count=len(graph.nodes),
        total_graph_edge_count=len(graph.edges),
        nodes=selected_nodes,
        edges=selected_edges,
    )
