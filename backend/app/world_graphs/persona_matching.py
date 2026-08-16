"""Deterministic graph-node to Persona attribute candidate matching."""

import re
from uuid import UUID

from app.populations.contracts import CohortDatasetRef, PersonaAttribute, PersonaSummary
from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphPersonaMatch,
    SemanticWorldGraphPersonaMatches,
)
from app.world_graphs.errors import WorldGraphNodeNotFoundError, WorldGraphNotReadyError

LOW_INFORMATION_VALUES = frozenset(
    {"none", "not applicable", "unfamiliar", "neutral", "unknown", "null"}
)
MATCH_LIMITATIONS = (
    "Matches are exact token overlap with non-low-information frozen Persona attributes.",
    "Candidates do not imply audience membership, stance, preference, or causal relevance.",
    "At most 200 Personas are inspected in stable dataset order; larger datasets are truncated.",
)


def _tokens(value: str) -> frozenset[str]:
    normalized = value.casefold().replace("_", "-")
    return frozenset(token for token in re.findall(r"[^\W_]+", normalized) if len(token) >= 3)


def match_graph_node_to_personas(
    graph: SemanticWorldGraphDetail,
    node_id: UUID,
    dataset: CohortDatasetRef,
    dataset_persona_count: int,
    personas: tuple[PersonaSummary, ...],
    limit: int,
) -> SemanticWorldGraphPersonaMatches:
    if graph.status != "succeeded" or graph.graph_sha256 is None:
        raise WorldGraphNotReadyError("only succeeded semantic graphs support Persona matching")
    node = next((item for item in graph.nodes if item.id == node_id), None)
    if node is None:
        raise WorldGraphNodeNotFoundError(f"semantic world graph node {node_id} was not found")
    query_terms = tuple(sorted(_tokens(node.name)))[:20]
    if not query_terms:
        query_terms = (node.name.casefold(),)
    ranked: list[tuple[int, PersonaSummary, tuple[str, ...], tuple[PersonaAttribute, ...]]] = []
    for persona in personas:
        matched_terms: set[str] = set()
        matched_attributes = []
        for attribute in persona.attributes:
            if attribute.value.casefold() in LOW_INFORMATION_VALUES:
                continue
            overlap = set(query_terms) & (_tokens(attribute.name) | _tokens(attribute.value))
            if overlap:
                matched_terms.update(overlap)
                matched_attributes.append(attribute)
        if matched_terms:
            ranked.append(
                (
                    len(matched_terms),
                    persona,
                    tuple(sorted(matched_terms)),
                    tuple(matched_attributes[:20]),
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1].persona_id, item[1].id.int))
    matches = tuple(
        SemanticWorldGraphPersonaMatch(
            position=position,
            score=score,
            matched_terms=terms,
            matched_attributes=attributes,
            persona=persona,
        )
        for position, (score, persona, terms, attributes) in enumerate(ranked[:limit])
    )
    return SemanticWorldGraphPersonaMatches(
        graph_id=graph.id,
        graph_sha256=graph.graph_sha256,
        node_id=node.id,
        dataset=dataset,
        match_semantics="exact_token_overlap_non_low_information_attributes",
        query_terms=query_terms,
        inspected_persona_count=len(personas),
        dataset_persona_count=dataset_persona_count,
        scan_truncated=dataset_persona_count > len(personas),
        total_match_count_in_scan=len(ranked),
        matches=matches,
        limitations=MATCH_LIMITATIONS,
    )
