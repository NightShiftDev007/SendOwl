"""Content addressing for semantic graph inputs, outputs, and provider semantics."""

import json
from hashlib import sha256
from uuid import UUID

from app.world_graphs.contracts import SemanticWorldGraphEdge, SemanticWorldGraphNode


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: object) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def calculate_extraction_config_sha256(semantic_config_sha256: str) -> str:
    return _digest(
        {
            "schema": "world-graph-provider-config/v1",
            "semantic_config_sha256": semantic_config_sha256,
            "prompt_schema_version": "world-graph-extraction/v1",
            "tool_choice": "required",
            "output_max_tokens": 4096,
            "normalizer_version": "world-graph-normalizer/v5",
            "prompt_policy": "explicit_facts_untrusted_input_no_hidden_inference",
            "output_validation_attempts": 2,
            "unsupported_object_policy": "exclude_with_structured_warning",
            "entity_types": [
                "organization",
                "person",
                "location",
                "policy",
                "event",
                "concept",
            ],
            "evidence_mode": "verbatim_quote_with_verified_first_occurrence_offset",
        }
    )


def calculate_graph_input_sha256(
    world_model_id: UUID,
    snapshot_id: UUID,
    snapshot_sha256: str,
    model_name: str,
    semantic_config_sha256: str,
    extraction_config_sha256: str,
) -> str:
    return _digest(
        {
            "schema": "world-graph-input/v1",
            "world_model_id": str(world_model_id),
            "snapshot_id": str(snapshot_id),
            "snapshot_sha256": snapshot_sha256,
            "model_name": model_name,
            "semantic_config_sha256": semantic_config_sha256,
            "extraction_config_sha256": extraction_config_sha256,
            "prompt_schema_version": "world-graph-extraction/v1",
        }
    )


def calculate_semantic_graph_sha256(
    input_sha256: str,
    nodes: tuple[SemanticWorldGraphNode, ...],
    edges: tuple[SemanticWorldGraphEdge, ...],
) -> str:
    return _digest(
        {
            "schema": "semantic-world-graph/v1",
            "input_sha256": input_sha256,
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
        }
    )
