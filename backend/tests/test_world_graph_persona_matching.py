from uuid import UUID

from app.populations.contracts import CohortDatasetRef, PersonaAttribute, PersonaSummary
from app.world_graphs.persona_matching import match_graph_node_to_personas
from tests.test_world_graph_search import _graph


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _persona(value: int, attributes: tuple[PersonaAttribute, ...]) -> PersonaSummary:
    return PersonaSummary(
        id=_uuid(value),
        dataset_id=_uuid(500),
        persona_id=f"persona-{value}",
        display_name=f"Persona {value}",
        source="matraix",
        profile_sha256="a" * 64,
        attributes=attributes,
    )


def test_persona_matching_uses_non_low_information_exact_tokens_only() -> None:
    graph = _graph()
    dataset = CohortDatasetRef(
        id=_uuid(500),
        slug="sample",
        dataset_sha256="b" * 64,
    )
    matching = _persona(
        501,
        (
            PersonaAttribute(name="topic_clean", value="Interested"),
            PersonaAttribute(name="work_domain", value="Port operations"),
        ),
    )
    low_information = _persona(
        502,
        (PersonaAttribute(name="topic_policy", value="None"),),
    )

    result = match_graph_node_to_personas(
        graph,
        graph.nodes[1].id,
        dataset,
        300,
        (matching, low_information),
        20,
    )

    assert result.query_terms == ("clean", "policy", "port")
    assert tuple(item.persona.id for item in result.matches) == (matching.id,)
    assert result.matches[0].matched_terms == ("clean", "port")
    assert result.scan_truncated is True
    assert result.total_match_count_in_scan == 1
    assert "stance" in result.limitations[1]


def test_persona_matching_caps_query_terms_before_scoring() -> None:
    graph = _graph()
    node_name = " ".join(f"term{index:02d}" for index in range(24))
    selected_node = graph.nodes[1].model_copy(update={"name": node_name})
    limited_graph = graph.model_copy(
        update={"nodes": (graph.nodes[0], selected_node, *graph.nodes[2:])}
    )
    dataset = CohortDatasetRef(
        id=_uuid(500),
        slug="sample",
        dataset_sha256="b" * 64,
    )
    persona = _persona(
        501,
        (PersonaAttribute(name="topics", value=node_name),),
    )

    result = match_graph_node_to_personas(
        limited_graph,
        selected_node.id,
        dataset,
        1,
        (persona,),
        20,
    )

    assert len(result.query_terms) == 20
    assert result.matches[0].score == 20
    assert result.matches[0].matched_terms == result.query_terms
