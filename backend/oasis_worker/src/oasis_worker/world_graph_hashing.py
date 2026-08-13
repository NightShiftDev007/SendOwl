"""Canonical identities shared with the semantic world graph control plane."""

import hashlib
import json
from uuid import UUID

from oasis_worker.world_graph_contracts import NormalizedGraphEdge, NormalizedGraphNode


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def extraction_config_sha256(semantic_config_sha256: str) -> str:
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


def graph_input_sha256(
    world_model_id: UUID,
    snapshot_id: UUID,
    snapshot_sha256: str,
    model_name: str,
    semantic_config_sha256: str,
    graph_config_sha256: str,
) -> str:
    return _digest(
        {
            "schema": "world-graph-input/v1",
            "world_model_id": str(world_model_id),
            "snapshot_id": str(snapshot_id),
            "snapshot_sha256": snapshot_sha256,
            "model_name": model_name,
            "semantic_config_sha256": semantic_config_sha256,
            "extraction_config_sha256": graph_config_sha256,
            "prompt_schema_version": "world-graph-extraction/v1",
        }
    )


def semantic_graph_sha256(
    input_sha256: str,
    nodes: tuple[NormalizedGraphNode, ...],
    edges: tuple[NormalizedGraphEdge, ...],
) -> str:
    return _digest(
        {
            "schema": "semantic-world-graph/v1",
            "input_sha256": input_sha256,
            "nodes": [node.model_dump(mode="json") for node in nodes],
            "edges": [edge.model_dump(mode="json") for edge in edges],
        }
    )
