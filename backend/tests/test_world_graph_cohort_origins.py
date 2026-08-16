from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.world_graphs.cohort_origins import (
    GRAPH_PERSONA_COHORT_ORIGIN_SCHEMA,
    GRAPH_PERSONA_MATCH_SEMANTICS,
    GRAPH_PERSONA_MATCHER_VERSION,
    calculate_graph_persona_cohort_origin_sha256,
)
from app.world_graphs.contracts import GraphPersonaCohortCreateRequest

GRAPH_ID = UUID("10000000-0000-4000-8000-000000000001")
NODE_ID = UUID("10000000-0000-4000-8000-000000000002")
DATASET_ID = UUID("10000000-0000-4000-8000-000000000003")
COHORT_ID = UUID("10000000-0000-4000-8000-000000000004")
PERSONA_IDS = (
    UUID("10000000-0000-4000-8000-000000000005"),
    UUID("10000000-0000-4000-8000-000000000006"),
)


def test_graph_persona_origin_hash_binds_ordered_selection() -> None:
    parts = (
        GRAPH_PERSONA_COHORT_ORIGIN_SCHEMA,
        str(GRAPH_ID),
        "a" * 64,
        str(NODE_ID),
        str(DATASET_ID),
        "b" * 64,
        str(COHORT_ID),
        "c" * 64,
        GRAPH_PERSONA_MATCH_SEMANTICS,
        GRAPH_PERSONA_MATCHER_VERSION,
        *(str(persona_id) for persona_id in PERSONA_IDS),
    )
    expected = sha256("\0".join(parts).encode()).hexdigest()

    actual = calculate_graph_persona_cohort_origin_sha256(
        GRAPH_ID,
        "a" * 64,
        NODE_ID,
        DATASET_ID,
        "b" * 64,
        COHORT_ID,
        "c" * 64,
        PERSONA_IDS,
    )
    reversed_selection = calculate_graph_persona_cohort_origin_sha256(
        GRAPH_ID,
        "a" * 64,
        NODE_ID,
        DATASET_ID,
        "b" * 64,
        COHORT_ID,
        "c" * 64,
        tuple(reversed(PERSONA_IDS)),
    )

    assert actual == expected
    assert reversed_selection != actual


def test_graph_persona_cohort_request_is_bounded_and_unique() -> None:
    request = GraphPersonaCohortCreateRequest.model_validate(
        {
            "title": "Graph-guided cohort",
            "dataset_id": str(DATASET_ID),
            "persona_ids": [str(persona_id) for persona_id in PERSONA_IDS],
        }
    )

    assert request.persona_ids == PERSONA_IDS
    with pytest.raises(ValidationError, match="duplicates"):
        GraphPersonaCohortCreateRequest.model_validate(
            {
                "title": "Duplicate selection",
                "dataset_id": str(DATASET_ID),
                "persona_ids": [str(PERSONA_IDS[0]), str(PERSONA_IDS[0])],
            }
        )
    with pytest.raises(ValidationError):
        GraphPersonaCohortCreateRequest.model_validate(
            {
                "title": "Oversized selection",
                "dataset_id": str(DATASET_ID),
                "persona_ids": [
                    str(UUID(f"10000000-0000-4000-8000-{position:012d}"))
                    for position in range(10, 19)
                ],
            }
        )
