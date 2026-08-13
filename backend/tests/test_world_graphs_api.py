from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api import world_graphs as world_graphs_api
from app.api.world_graphs import require_world_graph_session
from app.config import load_runtime_settings
from app.main import create_app
from app.world_graphs.contracts import (
    SemanticWorldGraphDetail,
    SemanticWorldGraphNode,
    SemanticWorldGraphSlice,
    WorldGraphEvidenceReference,
)
from app.world_graphs.errors import WorldGraphUnavailableError


def _queued_graph(
    world_model_id: UUID,
    snapshot_id: UUID,
) -> SemanticWorldGraphDetail:
    return SemanticWorldGraphDetail(
        id=uuid4(),
        world_model_id=world_model_id,
        snapshot_id=snapshot_id,
        snapshot_sha256="a" * 64,
        status="queued",
        model_name="qwen-test",
        semantic_config_sha256="b" * 64,
        extraction_config_sha256="c" * 64,
        prompt_schema_version="world-graph-extraction/v1",
        input_sha256="d" * 64,
        graph_sha256=None,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        started_at=None,
        completed_at=None,
        nodes=(),
        edges=(),
        error_code=None,
        error_message=None,
    )


def test_world_graph_endpoints_are_explicitly_unavailable_without_database() -> None:
    client = TestClient(create_app(load_runtime_settings({})))
    model_id = uuid4()
    snapshot_id = uuid4()
    graph_id = uuid4()

    responses = (
        client.post(f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/semantic-graphs"),
        client.get(f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/semantic-graphs"),
        client.get(f"/api/v2/world-graphs/{graph_id}"),
        client.get(
            f"/api/v2/world-graphs/{graph_id}/slice",
            params={
                "root_node_id": uuid4(),
                "direction": "both",
                "hops": 1,
                "max_nodes": 20,
            },
        ),
        client.get(f"/api/v2/world-graphs/{graph_id}/evidence-timeline"),
    )

    assert {response.status_code for response in responses} == {503}


def test_enqueue_world_graph_returns_strict_accepted_job(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    model_id = uuid4()
    snapshot_id = uuid4()
    expected = _queued_graph(model_id, snapshot_id)

    async def override_session() -> AsyncIterator[object]:
        yield object()

    async def enqueue(session: object, requested_model: UUID, requested_snapshot: UUID):
        assert session is not None
        assert (requested_model, requested_snapshot) == (model_id, snapshot_id)
        return expected

    application.dependency_overrides[require_world_graph_session] = override_session
    monkeypatch.setattr(world_graphs_api, "enqueue_semantic_world_graph", enqueue)

    response = TestClient(application).post(
        f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/semantic-graphs"
    )

    assert response.status_code == 202
    assert SemanticWorldGraphDetail.model_validate_json(response.content) == expected


def test_enqueue_world_graph_maps_missing_ready_model_to_503(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    model_id = uuid4()
    snapshot_id = uuid4()

    async def override_session() -> AsyncIterator[object]:
        yield object()

    async def unavailable(session: object, requested_model: UUID, requested_snapshot: UUID):
        assert session is not None
        assert (requested_model, requested_snapshot) == (model_id, snapshot_id)
        raise WorldGraphUnavailableError("no graph-capable model worker is ready")

    application.dependency_overrides[require_world_graph_session] = override_session
    monkeypatch.setattr(world_graphs_api, "enqueue_semantic_world_graph", unavailable)

    response = TestClient(application).post(
        f"/api/v2/world-models/{model_id}/snapshots/{snapshot_id}/semantic-graphs"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "no graph-capable model worker is ready"}


def test_world_graph_slice_forwards_strict_query(monkeypatch) -> None:
    application = create_app(load_runtime_settings({}))
    graph_id = uuid4()
    root_node_id = uuid4()
    node = SemanticWorldGraphNode(
        id=root_node_id,
        position=4,
        entity_type="policy",
        name="Policy",
        summary="Policy summary",
        evidence=(
            WorldGraphEvidenceReference(
                position=0,
                article_id=uuid4(),
                quote="verified quote",
                start_offset=0,
                end_offset=14,
            ),
        ),
    )
    expected = SemanticWorldGraphSlice(
        graph_id=graph_id,
        graph_sha256="e" * 64,
        root_node_id=root_node_id,
        direction="outbound",
        hops=2,
        max_nodes=30,
        truncated=False,
        total_graph_node_count=1,
        total_graph_edge_count=0,
        nodes=(node,),
        edges=(),
    )

    async def override_session() -> AsyncIterator[object]:
        yield object()

    async def graph_slice(
        session: object,
        requested_graph: UUID,
        requested_root: UUID,
        direction: str,
        hops: int,
        max_nodes: int,
    ) -> SemanticWorldGraphSlice:
        assert session is not None
        assert (requested_graph, requested_root) == (graph_id, root_node_id)
        assert (direction, hops, max_nodes) == ("outbound", 2, 30)
        return expected

    application.dependency_overrides[require_world_graph_session] = override_session
    monkeypatch.setattr(world_graphs_api, "get_semantic_world_graph_slice", graph_slice)

    response = TestClient(application).get(
        f"/api/v2/world-graphs/{graph_id}/slice",
        params={
            "root_node_id": root_node_id,
            "direction": "outbound",
            "hops": 2,
            "max_nodes": 30,
        },
    )

    assert response.status_code == 200
    assert SemanticWorldGraphSlice.model_validate_json(response.content) == expected
