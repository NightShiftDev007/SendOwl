import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from oasis_worker.errors import OasisExecutionError
from oasis_worker.world_graph_contracts import (
    ClaimedWorldGraph,
    ExtractedEntity,
    ExtractedEvidence,
    ExtractedRelationship,
    ExtractedWorldGraph,
    FrozenGraphEvidence,
)
from oasis_worker.world_graph_engine import normalize_extracted_graph
from oasis_worker.world_graph_hashing import (
    extraction_config_sha256,
    graph_input_sha256,
)


def _job(text: str) -> ClaimedWorldGraph:
    graph_id = UUID("10000000-0000-4000-8000-000000000001")
    model_id = UUID("20000000-0000-4000-8000-000000000002")
    snapshot_id = UUID("30000000-0000-4000-8000-000000000003")
    article_id = UUID("40000000-0000-4000-8000-000000000004")
    semantic_digest = "a" * 64
    config_digest = extraction_config_sha256(semantic_digest)
    return ClaimedWorldGraph(
        id=graph_id,
        world_model_id=model_id,
        snapshot_id=snapshot_id,
        snapshot_sha256="b" * 64,
        model_name="qwen-test",
        semantic_config_sha256=semantic_digest,
        extraction_config_sha256=config_digest,
        prompt_schema_version="world-graph-extraction/v1",
        input_sha256=graph_input_sha256(
            model_id,
            snapshot_id,
            "b" * 64,
            "qwen-test",
            semantic_digest,
            config_digest,
        ),
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        evidence=(
            FrozenGraphEvidence(
                article_id=article_id,
                position=0,
                title="Policy update",
                captured_text=text,
                captured_text_sha256="c" * 64,
            ),
        ),
    )


def test_normalize_extracted_graph_keeps_only_exact_frozen_evidence() -> None:
    job = _job("Acme signed the Green Policy in Hangzhou.")
    article_id = job.evidence[0].article_id
    extracted = ExtractedWorldGraph(
        entities=(
            ExtractedEntity(
                local_id="acme",
                entity_type="organization",
                name="Acme",
                summary="A named organization in the source.",
                evidence=(ExtractedEvidence(article_id=article_id, quote="Acme"),),
            ),
            ExtractedEntity(
                local_id="green_policy",
                entity_type="policy",
                name="Green Policy",
                summary="A policy named in the source.",
                evidence=(ExtractedEvidence(article_id=article_id, quote="Green Policy"),),
            ),
        ),
        relationships=(
            ExtractedRelationship(
                source_local_id="acme",
                target_local_id="green_policy",
                relation_type="signed",
                fact="Acme signed the Green Policy.",
                evidence=(
                    ExtractedEvidence(
                        article_id=article_id,
                        quote="Acme signed the Green Policy",
                    ),
                ),
            ),
        ),
    )

    normalized = normalize_extracted_graph(job, extracted)

    assert normalized.nodes[0].evidence[0].start_offset == 0
    assert normalized.nodes[1].evidence[0].start_offset == 16
    assert normalized.edges[0].evidence[0].end_offset == 28
    assert normalized.edges[0].source_node_id == normalized.nodes[0].id
    assert normalized.edges[0].target_node_id == normalized.nodes[1].id


def test_normalize_extracted_graph_rejects_missing_quotes() -> None:
    job = _job("Acme appears once.")
    extracted = ExtractedWorldGraph(
        entities=(
            ExtractedEntity(
                local_id="acme",
                entity_type="organization",
                name="Acme",
                summary="A named organization in the source.",
                evidence=(
                    ExtractedEvidence(
                        article_id=job.evidence[0].article_id,
                        quote="unsupported fact",
                    ),
                ),
            ),
        ),
        relationships=(),
    )

    with pytest.raises(OasisExecutionError):
        normalize_extracted_graph(job, extracted)


def test_repeated_verbatim_quote_is_bound_to_deterministic_first_occurrence() -> None:
    job = _job("Acme appears and Acme returns.")
    extracted = ExtractedWorldGraph(
        entities=(
            ExtractedEntity(
                local_id="acme",
                entity_type="organization",
                name="Acme",
                summary="A named organization in the source.",
                evidence=(ExtractedEvidence(article_id=job.evidence[0].article_id, quote="Acme"),),
            ),
        ),
        relationships=(),
    )

    normalized = normalize_extracted_graph(job, extracted)

    assert normalized.nodes[0].evidence[0].start_offset == 0


def test_extracted_graph_rejects_relationships_to_unknown_entities() -> None:
    article_id = uuid4()
    with pytest.raises(ValueError, match="unknown entity"):
        ExtractedWorldGraph(
            entities=(
                ExtractedEntity(
                    local_id="known",
                    entity_type="concept",
                    name="Known",
                    summary="Known concept.",
                    evidence=(ExtractedEvidence(article_id=article_id, quote="Known"),),
                ),
            ),
            relationships=(
                ExtractedRelationship(
                    source_local_id="known",
                    target_local_id="missing",
                    relation_type="relates_to",
                    fact="Known relates to missing.",
                    evidence=(ExtractedEvidence(article_id=article_id, quote="Known"),),
                ),
            ),
        )


def test_provider_json_arrays_are_parsed_into_strict_immutable_tuples() -> None:
    article_id = uuid4()
    payload = {
        "entities": [
            {
                "local_id": "policy",
                "entity_type": "policy",
                "name": "Policy",
                "summary": "Named policy.",
                "evidence": [{"article_id": str(article_id), "quote": "Policy"}],
            }
        ],
        "relationships": [],
    }

    parsed = ExtractedWorldGraph.model_validate_json(json.dumps(payload))

    assert isinstance(parsed.entities, tuple)
    assert isinstance(parsed.entities[0].evidence, tuple)
