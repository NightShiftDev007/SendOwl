"""PostgreSQL queue operations for evidence-backed semantic world graphs."""

from datetime import datetime
from hashlib import sha256
from uuid import UUID

from psycopg import Connection
from pydantic import ValidationError

from oasis_worker.queue_contracts import NormalizedFailure
from oasis_worker.semantic_contracts import SemanticRuntimeConfig
from oasis_worker.world_graph_contracts import (
    GRAPH_PROMPT_SCHEMA_VERSION,
    ClaimedWorldGraph,
    FrozenGraphEvidence,
    NormalizedWorldGraph,
)
from oasis_worker.world_graph_hashing import (
    extraction_config_sha256,
    graph_input_sha256,
)


def _uuid(value: object, location: str) -> UUID:
    if not isinstance(value, UUID):
        raise RuntimeError(f"expected PostgreSQL UUID at {location}")
    return value


def _queue_integrity_failure(error: BaseException) -> NormalizedFailure:
    if isinstance(error, ValidationError):
        first = error.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in first["loc"]) or "input"
        detail = f"validation failed at {location} ({first['type']})"
    elif isinstance(error, (RuntimeError, ValueError)):
        detail = str(error)
    else:
        detail = f"validation failed with {type(error).__name__}"
    return NormalizedFailure(
        code="queue_integrity",
        message="World graph queue integrity check failed: " + " ".join(detail.split())[:450],
    )


def world_graph_queue_head(
    connection: Connection[dict[str, object]],
    runtime_config: SemanticRuntimeConfig,
) -> tuple[UUID, datetime] | None:
    graph_config_sha256 = extraction_config_sha256(runtime_config.config_sha256)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, created_at
            FROM semantic_world_graphs
            WHERE status = 'queued' AND model_name = %s
              AND semantic_config_sha256 = %s
              AND extraction_config_sha256 = %s
              AND prompt_schema_version = %s
            ORDER BY created_at, id
            LIMIT 1
            """,
            (
                runtime_config.model_name,
                runtime_config.config_sha256,
                graph_config_sha256,
                GRAPH_PROMPT_SCHEMA_VERSION,
            ),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("queued world graph created_at is not a PostgreSQL timestamp")
    return _uuid(row["id"], "semantic_world_graphs.id"), created_at


def _load_claimed_graph(
    connection: Connection[dict[str, object]],
    graph_id: UUID,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedWorldGraph | None:
    graph_config_sha256 = extraction_config_sha256(runtime_config.config_sha256)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT graph.id, graph.world_model_id, graph.snapshot_id,
                   graph.snapshot_sha256, graph.model_name,
                   graph.semantic_config_sha256, graph.extraction_config_sha256,
                   graph.prompt_schema_version, graph.input_sha256, graph.created_at,
                   snapshot.world_model_id AS actual_world_model_id,
                   snapshot.snapshot_sha256 AS actual_snapshot_sha256,
                   snapshot.sealed_at
            FROM semantic_world_graphs AS graph
            JOIN world_snapshots AS snapshot ON snapshot.id = graph.snapshot_id
            WHERE graph.id = %s AND graph.status = 'queued'
              AND graph.model_name = %s
              AND graph.semantic_config_sha256 = %s
              AND graph.extraction_config_sha256 = %s
              AND graph.prompt_schema_version = %s
            FOR UPDATE OF graph SKIP LOCKED
            """,
            (
                graph_id,
                runtime_config.model_name,
                runtime_config.config_sha256,
                graph_config_sha256,
                GRAPH_PROMPT_SCHEMA_VERSION,
            ),
        )
        graph_row = cursor.fetchone()
        if graph_row is None:
            return None
        if graph_row["sealed_at"] is None:
            raise RuntimeError(f"world graph {graph_id} references an unsealed snapshot")
        if graph_row["actual_world_model_id"] != graph_row["world_model_id"]:
            raise RuntimeError(f"world graph {graph_id} world model identity mismatch")
        if graph_row["actual_snapshot_sha256"] != graph_row["snapshot_sha256"]:
            raise RuntimeError(f"world graph {graph_id} frozen snapshot digest mismatch")
        cursor.execute(
            """
            SELECT position, article_id, title, captured_text, captured_text_sha256
            FROM world_snapshot_evidence
            WHERE snapshot_id = %s
            ORDER BY position
            """,
            (graph_row["snapshot_id"],),
        )
        evidence_rows = cursor.fetchall()
    evidence = tuple(
        FrozenGraphEvidence.model_validate(
            {
                "position": row["position"],
                "article_id": row["article_id"],
                "title": row["title"],
                "captured_text": row["captured_text"],
                "captured_text_sha256": row["captured_text_sha256"],
            }
        )
        for row in evidence_rows
    )
    for item in evidence:
        observed = sha256(item.captured_text.encode("utf-8")).hexdigest()
        if observed != item.captured_text_sha256:
            raise RuntimeError(
                f"world graph {graph_id} article {item.article_id} content hash mismatch"
            )
    job = ClaimedWorldGraph.model_validate(
        {
            "id": graph_row["id"],
            "world_model_id": graph_row["world_model_id"],
            "snapshot_id": graph_row["snapshot_id"],
            "snapshot_sha256": graph_row["snapshot_sha256"],
            "model_name": graph_row["model_name"],
            "semantic_config_sha256": graph_row["semantic_config_sha256"],
            "extraction_config_sha256": graph_row["extraction_config_sha256"],
            "prompt_schema_version": graph_row["prompt_schema_version"],
            "input_sha256": graph_row["input_sha256"],
            "created_at": graph_row["created_at"],
            "evidence": evidence,
        }
    )
    expected_input_sha256 = graph_input_sha256(
        job.world_model_id,
        job.snapshot_id,
        job.snapshot_sha256,
        job.model_name,
        job.semantic_config_sha256,
        job.extraction_config_sha256,
    )
    if job.input_sha256 != expected_input_sha256:
        raise RuntimeError(f"world graph {graph_id} input hash mismatch")
    return job


def _mark_integrity_failure(
    connection: Connection[dict[str, object]],
    graph_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'running', claimed_by_worker_id = %s, started_at = now()
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, graph_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"queued world graph {graph_id} could not enter running state")
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'failed', completed_at = now(), error_code = %s, error_message = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (failure.code, failure.message, graph_id, worker_id),
        )
    connection.commit()


def claim_world_graph(
    connection: Connection[dict[str, object]],
    graph_id: UUID,
    worker_id: str,
    runtime_config: SemanticRuntimeConfig,
) -> ClaimedWorldGraph | None:
    try:
        job = _load_claimed_graph(connection, graph_id, runtime_config)
    except (ValidationError, RuntimeError, ValueError, KeyError) as error:
        failure = _queue_integrity_failure(error)
        _mark_integrity_failure(connection, graph_id, worker_id, failure)
        return None
    if job is None:
        connection.commit()
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'running', claimed_by_worker_id = %s, started_at = now()
            WHERE id = %s AND status = 'queued'
            """,
            (worker_id, graph_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise RuntimeError(f"queued world graph {graph_id} could not be claimed")
    connection.commit()
    return job


def complete_world_graph(
    connection: Connection[dict[str, object]],
    graph_id: UUID,
    worker_id: str,
    result: NormalizedWorldGraph,
) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO semantic_world_graph_nodes
                (graph_id, position, id, entity_type, name, summary)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (graph_id, node.position, node.id, node.entity_type, node.name, node.summary)
                for node in result.nodes
            ],
        )
        if result.edges:
            cursor.executemany(
                """
                INSERT INTO semantic_world_graph_edges
                    (graph_id, position, id, source_node_id, target_node_id,
                     relation_type, fact)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        graph_id,
                        edge.position,
                        edge.id,
                        edge.source_node_id,
                        edge.target_node_id,
                        edge.relation_type,
                        edge.fact,
                    )
                    for edge in result.edges
                ],
            )
        evidence_rows = [
            (
                graph_id,
                object_kind,
                object_id,
                evidence.position,
                evidence.article_id,
                evidence.quote,
                evidence.start_offset,
                evidence.end_offset,
            )
            for object_kind, objects in (("node", result.nodes), ("edge", result.edges))
            for item in objects
            for object_id in (item.id,)
            for evidence in item.evidence
        ]
        cursor.executemany(
            """
            INSERT INTO semantic_world_graph_evidence
                (graph_id, object_kind, object_id, position, article_id, quote,
                 start_offset, end_offset)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            evidence_rows,
        )
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'succeeded', completed_at = now(), graph_sha256 = %s,
                node_count = %s, edge_count = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (result.graph_sha256, len(result.nodes), len(result.edges), graph_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"world graph {graph_id} is no longer running")
    connection.commit()


def fail_world_graph(
    connection: Connection[dict[str, object]],
    graph_id: UUID,
    worker_id: str,
    failure: NormalizedFailure,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM semantic_world_graph_evidence WHERE graph_id = %s", (graph_id,))
        cursor.execute("DELETE FROM semantic_world_graph_edges WHERE graph_id = %s", (graph_id,))
        cursor.execute("DELETE FROM semantic_world_graph_nodes WHERE graph_id = %s", (graph_id,))
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'failed', completed_at = now(), error_code = %s, error_message = %s
            WHERE id = %s AND status = 'running' AND claimed_by_worker_id = %s
            """,
            (failure.code, failure.message, graph_id, worker_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"world graph {graph_id} is no longer running")
    connection.commit()


def fail_orphaned_world_graphs(
    connection: Connection[dict[str, object]],
    cutoff: datetime,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_world_graphs AS graph
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_heartbeat_lost',
                error_message = 'The model worker stopped before completing this world graph.'
            WHERE graph.status = 'running' AND NOT EXISTS (
                SELECT 1 FROM simulation_worker_heartbeats AS heartbeat
                WHERE heartbeat.worker_id = graph.claimed_by_worker_id
                  AND heartbeat.last_seen_at >= %s
            )
            """,
            (cutoff,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated


def fail_world_graphs_owned_by_worker(
    connection: Connection[dict[str, object]],
    worker_id: str,
) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE semantic_world_graphs
            SET status = 'failed', completed_at = now(),
                error_code = 'worker_process_restarted',
                error_message = 'The owning model worker restarted before completing this graph.'
            WHERE status = 'running' AND claimed_by_worker_id = %s
            """,
            (worker_id,),
        )
        updated = cursor.rowcount
    connection.commit()
    return updated
