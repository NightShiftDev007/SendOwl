"""Content addressing for graph-guided Persona cohort selection."""

from hashlib import sha256
from uuid import UUID

GRAPH_PERSONA_COHORT_ORIGIN_SCHEMA = "graph-persona-cohort-origin/v1"
GRAPH_PERSONA_MATCHER_VERSION = "1.0.0"
GRAPH_PERSONA_MATCH_SEMANTICS = "exact_token_overlap_non_low_information_attributes"


def calculate_graph_persona_cohort_origin_sha256(
    graph_id: UUID,
    graph_sha256: str,
    node_id: UUID,
    dataset_id: UUID,
    dataset_sha256: str,
    cohort_id: UUID,
    cohort_sha256: str,
    selected_persona_ids: tuple[UUID, ...],
) -> str:
    """Return the deterministic lineage address for one explicit selection."""
    parts = (
        GRAPH_PERSONA_COHORT_ORIGIN_SCHEMA,
        str(graph_id),
        graph_sha256,
        str(node_id),
        str(dataset_id),
        dataset_sha256,
        str(cohort_id),
        cohort_sha256,
        GRAPH_PERSONA_MATCH_SEMANTICS,
        GRAPH_PERSONA_MATCHER_VERSION,
        *(str(persona_id) for persona_id in selected_persona_ids),
    )
    return sha256("\0".join(parts).encode()).hexdigest()
