"""Deterministic bounded lexical search over one verified semantic graph."""

from dataclasses import dataclass

from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphEdge,
    SemanticWorldGraphEdgeSearchResult,
    SemanticWorldGraphNode,
    SemanticWorldGraphNodeSearchResult,
    SemanticWorldGraphSearchResponse,
    WorldGraphSearchMatchField,
)
from app.world_graphs.errors import WorldGraphNotReadyError

SEARCH_LIMITATIONS = (
    "Search is deterministic case-folded substring matching, not vector or semantic retrieval.",
    "Every result remains bound to the immutable graph and its exact article evidence quotes.",
)


@dataclass(frozen=True)
class _NodeMatch:
    score: int
    node: SemanticWorldGraphNode
    fields: tuple[WorldGraphSearchMatchField, ...]


@dataclass(frozen=True)
class _EdgeMatch:
    score: int
    edge: SemanticWorldGraphEdge
    fields: tuple[WorldGraphSearchMatchField, ...]


type _Match = _NodeMatch | _EdgeMatch


def _text_score(value: str, query: str, exact: int, prefix: int, contains: int) -> int:
    normalized = value.casefold()
    if normalized == query:
        return exact
    if normalized.startswith(query):
        return prefix
    if query in normalized:
        return contains
    return 0


def _node_match(node: SemanticWorldGraphNode, query: str) -> _NodeMatch | None:
    fields: list[WorldGraphSearchMatchField] = []
    scores: list[int] = []
    name_score = _text_score(node.name, query, 100, 90, 80)
    if name_score:
        fields.append("name")
        scores.append(name_score)
    if query in node.summary.casefold():
        fields.append("summary")
        scores.append(50)
    if query in node.entity_type.casefold():
        fields.append("entity_type")
        scores.append(30)
    if any(query in evidence.quote.casefold() for evidence in node.evidence):
        fields.append("evidence_quote")
        scores.append(60)
    if not scores:
        return None
    return _NodeMatch(score=max(scores), node=node, fields=tuple(fields))


def _edge_match(edge: SemanticWorldGraphEdge, query: str) -> _EdgeMatch | None:
    fields: list[WorldGraphSearchMatchField] = []
    scores: list[int] = []
    relation_score = _text_score(edge.relation_type, query, 100, 90, 80)
    if relation_score:
        fields.append("relation_type")
        scores.append(relation_score)
    if query in edge.fact.casefold():
        fields.append("fact")
        scores.append(50)
    if any(query in evidence.quote.casefold() for evidence in edge.evidence):
        fields.append("evidence_quote")
        scores.append(60)
    if not scores:
        return None
    return _EdgeMatch(score=max(scores), edge=edge, fields=tuple(fields))


def search_semantic_world_graph(
    graph: SemanticWorldGraphDetail,
    query: str,
    limit: int,
) -> SemanticWorldGraphSearchResponse:
    """Search normalized graph fields without weakening graph integrity checks."""
    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise WorldGraphNotReadyError(
            f"semantic world graph {graph.id} is not succeeded and cannot be searched"
        )
    normalized_query = query.strip().casefold()
    node_matches = tuple(
        match for node in graph.nodes if (match := _node_match(node, normalized_query)) is not None
    )
    edge_matches = tuple(
        match for edge in graph.edges if (match := _edge_match(edge, normalized_query)) is not None
    )
    ordered: tuple[_Match, ...] = tuple(
        sorted(
            (*node_matches, *edge_matches),
            key=lambda match: (
                -match.score,
                0 if isinstance(match, _NodeMatch) else 1,
                match.node.position if isinstance(match, _NodeMatch) else match.edge.position,
            ),
        )
    )
    selected = ordered[:limit]
    results = tuple(
        SemanticWorldGraphNodeSearchResult(
            kind="node",
            rank=rank,
            matched_fields=match.fields,
            node=match.node,
        )
        if isinstance(match, _NodeMatch)
        else SemanticWorldGraphEdgeSearchResult(
            kind="edge",
            rank=rank,
            matched_fields=match.fields,
            edge=match.edge,
        )
        for rank, match in enumerate(selected)
    )
    return SemanticWorldGraphSearchResponse(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        query=query.strip(),
        search_semantics="casefolded_lexical_substring",
        total_match_count=len(ordered),
        truncated=len(ordered) > len(results),
        results=results,
        limitations=SEARCH_LIMITATIONS,
    )


__all__ = ["search_semantic_world_graph"]
