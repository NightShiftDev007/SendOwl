"""Create Qwen-extracted, evidence-backed semantic world graphs.

Revision ID: 20260812_core_0011
Revises: 20260812_core_0010
Create Date: 2026-08-12
"""

# ruff: noqa: E501

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_core_0011"
down_revision: str | None = "20260812_core_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_tables() -> None:
    op.create_table(
        "semantic_world_graphs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("world_model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("semantic_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("extraction_config_sha256", sa.String(length=64), nullable=False),
        sa.Column("prompt_schema_version", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("graph_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("node_count", sa.Integer(), nullable=True),
        sa.Column("edge_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_semantic_world_graphs_status",
        ),
        sa.CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$' AND "
            "extraction_config_sha256 ~ '^[a-f0-9]{64}$' AND "
            "input_sha256 ~ '^[a-f0-9]{64}$' AND "
            "(graph_sha256 IS NULL OR graph_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_semantic_world_graphs_hashes",
        ),
        sa.CheckConstraint(
            "prompt_schema_version = 'world-graph-extraction/v1'",
            name="ck_semantic_world_graphs_prompt_schema",
        ),
        sa.CheckConstraint(
            "(status = 'queued' AND claimed_by_worker_id IS NULL AND started_at IS NULL "
            "AND completed_at IS NULL AND graph_sha256 IS NULL AND node_count IS NULL "
            "AND edge_count IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND graph_sha256 IS NULL "
            "AND node_count IS NULL AND edge_count IS NULL AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status = 'succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND graph_sha256 ~ '^[a-f0-9]{64}$' AND node_count BETWEEN 1 AND 500 "
            "AND edge_count BETWEEN 0 AND 2000 AND error_code IS NULL "
            "AND error_message IS NULL) OR "
            "(status = 'failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND graph_sha256 IS NULL AND node_count IS NULL AND edge_count IS NULL "
            "AND error_code ~ '^[a-z][a-z0-9_]{0,127}$' "
            "AND length(error_message) BETWEEN 1 AND 500)",
            name="ck_semantic_world_graphs_state_shape",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_semantic_world_graphs_started_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_semantic_world_graphs_completed_time",
        ),
        sa.ForeignKeyConstraint(["world_model_id"], ["world_models.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["world_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("input_sha256", name="uq_semantic_world_graphs_input_sha256"),
    )
    op.create_index(
        "ix_semantic_world_graphs_snapshot_created",
        "semantic_world_graphs",
        ["snapshot_id", "created_at"],
    )
    op.create_index(
        "ix_semantic_world_graphs_status_created",
        "semantic_world_graphs",
        ["status", "created_at"],
    )

    op.create_table(
        "semantic_world_graph_nodes",
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 499", name="ck_semantic_graph_nodes_position"),
        sa.CheckConstraint(
            "entity_type IN ('organization','person','location','policy','event','concept')",
            name="ck_semantic_graph_nodes_entity_type",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200 AND length(btrim(summary)) BETWEEN 1 AND 500",
            name="ck_semantic_graph_nodes_text",
        ),
        sa.ForeignKeyConstraint(["graph_id"], ["semantic_world_graphs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("graph_id", "position"),
        sa.UniqueConstraint("graph_id", "id", name="uq_semantic_graph_nodes_identity"),
    )

    op.create_table(
        "semantic_world_graph_edges",
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("fact", sa.String(length=500), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 1999", name="ck_semantic_graph_edges_position"),
        sa.CheckConstraint(
            "relation_type ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_semantic_graph_edges_relation_type",
        ),
        sa.CheckConstraint(
            "length(btrim(fact)) BETWEEN 1 AND 500",
            name="ck_semantic_graph_edges_fact",
        ),
        sa.ForeignKeyConstraint(["graph_id"], ["semantic_world_graphs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["graph_id", "source_node_id"],
            ["semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["graph_id", "target_node_id"],
            ["semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"],
        ),
        sa.PrimaryKeyConstraint("graph_id", "position"),
        sa.UniqueConstraint("graph_id", "id", name="uq_semantic_graph_edges_identity"),
    )

    op.create_table(
        "semantic_world_graph_evidence",
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_kind", sa.String(length=8), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote", sa.String(length=500), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "object_kind IN ('node','edge')", name="ck_semantic_graph_evidence_kind"
        ),
        sa.CheckConstraint("position BETWEEN 0 AND 19", name="ck_semantic_graph_evidence_position"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset "
            "AND end_offset - start_offset = char_length(quote)",
            name="ck_semantic_graph_evidence_offsets",
        ),
        sa.ForeignKeyConstraint(["graph_id"], ["semantic_world_graphs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("graph_id", "object_kind", "object_id", "position"),
    )
    op.create_index(
        "ix_semantic_graph_evidence_article",
        "semantic_world_graph_evidence",
        ["article_id"],
    )


def _create_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION canonical_semantic_world_graph_json(target_graph_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE selected_graph semantic_world_graphs%ROWTYPE;
        DECLARE nodes_json text;
        DECLARE edges_json text;
        BEGIN
            SELECT * INTO STRICT selected_graph
            FROM semantic_world_graphs WHERE id = target_graph_id;

            SELECT string_agg(
                '{"entity_type":' || to_json(node.entity_type)::text ||
                ',"evidence":[' || coalesce((
                    SELECT string_agg(
                        '{"article_id":' || to_json(evidence.article_id::text)::text ||
                        ',"end_offset":' || evidence.end_offset::text ||
                        ',"position":' || evidence.position::text ||
                        ',"quote":' || to_json(evidence.quote)::text ||
                        ',"start_offset":' || evidence.start_offset::text || '}',
                        ',' ORDER BY evidence.position
                    ) FROM semantic_world_graph_evidence AS evidence
                    WHERE evidence.graph_id = node.graph_id
                      AND evidence.object_kind = 'node'
                      AND evidence.object_id = node.id
                ), '') || ']' ||
                ',"id":' || to_json(node.id::text)::text ||
                ',"name":' || to_json(node.name)::text ||
                ',"position":' || node.position::text ||
                ',"summary":' || to_json(node.summary)::text || '}',
                ',' ORDER BY node.position
            ) INTO nodes_json
            FROM semantic_world_graph_nodes AS node
            WHERE node.graph_id = target_graph_id;

            SELECT string_agg(
                '{"evidence":[' || coalesce((
                    SELECT string_agg(
                        '{"article_id":' || to_json(evidence.article_id::text)::text ||
                        ',"end_offset":' || evidence.end_offset::text ||
                        ',"position":' || evidence.position::text ||
                        ',"quote":' || to_json(evidence.quote)::text ||
                        ',"start_offset":' || evidence.start_offset::text || '}',
                        ',' ORDER BY evidence.position
                    ) FROM semantic_world_graph_evidence AS evidence
                    WHERE evidence.graph_id = edge.graph_id
                      AND evidence.object_kind = 'edge'
                      AND evidence.object_id = edge.id
                ), '') || ']' ||
                ',"fact":' || to_json(edge.fact)::text ||
                ',"id":' || to_json(edge.id::text)::text ||
                ',"position":' || edge.position::text ||
                ',"relation_type":' || to_json(edge.relation_type)::text ||
                ',"source_node_id":' || to_json(edge.source_node_id::text)::text ||
                ',"target_node_id":' || to_json(edge.target_node_id::text)::text || '}',
                ',' ORDER BY edge.position
            ) INTO edges_json
            FROM semantic_world_graph_edges AS edge
            WHERE edge.graph_id = target_graph_id;

            RETURN '{"edges":[' || coalesce(edges_json, '') || ']' ||
                ',"input_sha256":' || to_json(selected_graph.input_sha256)::text ||
                ',"nodes":[' || coalesce(nodes_json, '') || ']' ||
                ',"schema":"semantic-world-graph/v1"}';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_semantic_world_graph_parent() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE selected_snapshot world_snapshots%ROWTYPE;
        DECLARE actual_graph_sha256 text;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'queued' THEN
                    RAISE EXCEPTION 'semantic world graphs must be inserted as queued drafts'
                        USING ERRCODE = '55000';
                END IF;
                SELECT * INTO selected_snapshot
                FROM world_snapshots WHERE id = NEW.snapshot_id FOR UPDATE;
                IF NOT FOUND OR selected_snapshot.sealed_at IS NULL
                   OR selected_snapshot.world_model_id IS DISTINCT FROM NEW.world_model_id
                   OR selected_snapshot.snapshot_sha256 IS DISTINCT FROM NEW.snapshot_sha256
                THEN
                    RAISE EXCEPTION 'semantic world graph must reference one matching sealed snapshot'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'queued' THEN
                    RAISE EXCEPTION 'running or terminal semantic world graphs cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status IN ('succeeded', 'failed') THEN
                RAISE EXCEPTION 'terminal semantic world graphs are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(NEW.world_model_id, NEW.snapshot_id, NEW.snapshot_sha256, NEW.model_name,
                   NEW.semantic_config_sha256, NEW.extraction_config_sha256,
                   NEW.prompt_schema_version, NEW.input_sha256, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.world_model_id, OLD.snapshot_id, OLD.snapshot_sha256, OLD.model_name,
                   OLD.semantic_config_sha256, OLD.extraction_config_sha256,
                   OLD.prompt_schema_version, OLD.input_sha256, OLD.created_at) THEN
                RAISE EXCEPTION 'semantic world graph frozen input cannot change'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'queued' AND NEW.status <> 'running' THEN
                RAISE EXCEPTION 'semantic world graph must transition queued to running'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'running' AND NEW.status NOT IN ('succeeded', 'failed') THEN
                RAISE EXCEPTION 'semantic world graph must transition running to terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = 'succeeded' THEN
                actual_graph_sha256 := encode(
                    sha256(convert_to(canonical_semantic_world_graph_json(NEW.id), 'UTF8')),
                    'hex'
                );
                IF NEW.node_count <> (SELECT count(*) FROM semantic_world_graph_nodes WHERE graph_id = NEW.id)
                   OR NEW.edge_count <> (SELECT count(*) FROM semantic_world_graph_edges WHERE graph_id = NEW.id)
                   OR EXISTS (
                       SELECT expected.position FROM generate_series(0, NEW.node_count - 1) expected(position)
                       EXCEPT SELECT position FROM semantic_world_graph_nodes WHERE graph_id = NEW.id
                   ) OR EXISTS (
                       SELECT expected.position FROM generate_series(0, NEW.edge_count - 1) expected(position)
                       EXCEPT SELECT position FROM semantic_world_graph_edges WHERE graph_id = NEW.id
                   ) OR EXISTS (
                       SELECT 1 FROM semantic_world_graph_nodes node
                       WHERE node.graph_id = NEW.id AND NOT EXISTS (
                           SELECT 1 FROM semantic_world_graph_evidence evidence
                           WHERE evidence.graph_id = NEW.id AND evidence.object_kind = 'node'
                             AND evidence.object_id = node.id
                       )
                   ) OR EXISTS (
                       SELECT 1 FROM semantic_world_graph_edges edge
                       WHERE edge.graph_id = NEW.id AND NOT EXISTS (
                           SELECT 1 FROM semantic_world_graph_evidence evidence
                           WHERE evidence.graph_id = NEW.id AND evidence.object_kind = 'edge'
                             AND evidence.object_id = edge.id
                       )
                   ) OR NEW.graph_sha256 IS DISTINCT FROM actual_graph_sha256 THEN
                    RAISE EXCEPTION 'semantic world graph cannot seal with incomplete graph records'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_semantic_world_graph_parent
        BEFORE INSERT OR UPDATE OR DELETE ON semantic_world_graphs
        FOR EACH ROW EXECUTE FUNCTION guard_semantic_world_graph_parent();
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_semantic_world_graph_child() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE parent_status text;
        DECLARE parent_snapshot uuid;
        DECLARE selected_graph_id uuid;
        DECLARE frozen_text text;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'semantic world graph tables cannot be truncated'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                selected_graph_id := OLD.graph_id;
            ELSE
                selected_graph_id := NEW.graph_id;
            END IF;
            SELECT status, snapshot_id INTO parent_status, parent_snapshot
            FROM semantic_world_graphs WHERE id = selected_graph_id
            FOR UPDATE;
            IF parent_status <> 'running' THEN
                RAISE EXCEPTION 'semantic world graph children may change only while running'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_TABLE_NAME = 'semantic_world_graph_evidence' AND TG_OP <> 'DELETE' THEN
                IF NEW.object_kind = 'node' AND NOT EXISTS (
                    SELECT 1 FROM semantic_world_graph_nodes
                    WHERE graph_id = NEW.graph_id AND id = NEW.object_id
                ) THEN
                    RAISE EXCEPTION 'semantic graph evidence references a missing node'
                        USING ERRCODE = '23503';
                ELSIF NEW.object_kind = 'edge' AND NOT EXISTS (
                    SELECT 1 FROM semantic_world_graph_edges
                    WHERE graph_id = NEW.graph_id AND id = NEW.object_id
                ) THEN
                    RAISE EXCEPTION 'semantic graph evidence references a missing edge'
                        USING ERRCODE = '23503';
                END IF;
                SELECT captured_text INTO frozen_text
                FROM world_snapshot_evidence
                WHERE snapshot_id = parent_snapshot AND article_id = NEW.article_id;
                IF frozen_text IS NULL THEN
                    RAISE EXCEPTION 'semantic graph evidence article is not in the frozen snapshot'
                        USING ERRCODE = '23503';
                END IF;
                IF substring(frozen_text FROM NEW.start_offset + 1
                             FOR NEW.end_offset - NEW.start_offset) <> NEW.quote THEN
                    RAISE EXCEPTION 'semantic graph evidence offsets do not match frozen text'
                        USING ERRCODE = '22000';
                END IF;
            END IF;
            RETURN COALESCE(NEW, OLD);
        END;
        $$;
        """
    )
    for table in (
        "semantic_world_graph_nodes",
        "semantic_world_graph_edges",
        "semantic_world_graph_evidence",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_row BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_semantic_world_graph_child()"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION guard_semantic_world_graph_child()"
        )


def upgrade() -> None:
    _create_tables()
    _create_guards()


def downgrade() -> None:
    for table in (
        "semantic_world_graph_evidence",
        "semantic_world_graph_edges",
        "semantic_world_graph_nodes",
    ):
        op.execute(f"DROP TRIGGER trg_{table}_truncate ON {table}")
        op.execute(f"DROP TRIGGER trg_{table}_row ON {table}")
    op.execute("DROP TRIGGER trg_semantic_world_graph_parent ON semantic_world_graphs")
    op.execute("DROP FUNCTION guard_semantic_world_graph_child()")
    op.execute("DROP FUNCTION guard_semantic_world_graph_parent()")
    op.execute("DROP FUNCTION canonical_semantic_world_graph_json(uuid)")
    op.drop_index("ix_semantic_graph_evidence_article", table_name="semantic_world_graph_evidence")
    op.drop_table("semantic_world_graph_evidence")
    op.drop_table("semantic_world_graph_edges")
    op.drop_table("semantic_world_graph_nodes")
    op.drop_index("ix_semantic_world_graphs_status_created", table_name="semantic_world_graphs")
    op.drop_index("ix_semantic_world_graphs_snapshot_created", table_name="semantic_world_graphs")
    op.drop_table("semantic_world_graphs")
