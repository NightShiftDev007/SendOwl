"""Persist immutable graph-guided Persona cohort origins.

Revision ID: 20260814_core_0029
Revises: 20260813_core_0028
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_core_0029"
down_revision: str | None = "20260813_core_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_world_graph_cohort_origins",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("graph_sha256", sa.String(length=64), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_sha256", sa.String(length=64), nullable=False),
        sa.Column("cohort_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cohort_sha256", sa.String(length=64), nullable=False),
        sa.Column("match_semantics", sa.String(length=80), nullable=False),
        sa.Column("matcher_version", sa.String(length=16), nullable=False),
        sa.Column(
            "selected_persona_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("origin_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["graph_id"], ["semantic_world_graphs.id"]),
        sa.ForeignKeyConstraint(
            ["graph_id", "node_id"],
            ["semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"],
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["persona_datasets.id"]),
        sa.ForeignKeyConstraint(
            ["cohort_id", "dataset_id"],
            ["cohorts.id", "cohorts.dataset_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "graph_sha256 ~ '^[a-f0-9]{64}$' AND "
            "dataset_sha256 ~ '^[a-f0-9]{64}$' AND "
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND "
            "origin_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_graph_cohort_origin_hashes",
        ),
        sa.CheckConstraint(
            "match_semantics='exact_token_overlap_non_low_information_attributes'",
            name="ck_semantic_graph_cohort_origin_semantics",
        ),
        sa.CheckConstraint(
            "matcher_version='1.0.0'",
            name="ck_semantic_graph_cohort_origin_matcher",
        ),
        sa.CheckConstraint(
            "cardinality(selected_persona_ids) BETWEEN 1 AND 8",
            name="ck_semantic_graph_cohort_origin_personas",
        ),
        sa.UniqueConstraint("origin_sha256", name="uq_semantic_graph_cohort_origin_sha"),
    )
    op.create_index(
        "ix_semantic_graph_cohort_origin_cohort",
        "semantic_world_graph_cohort_origins",
        ["cohort_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION enforce_semantic_graph_cohort_origin()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE actual_persona_ids uuid[];
        DECLARE actual_origin_sha256 text;
        BEGIN
            IF cardinality(NEW.selected_persona_ids) <> (
                SELECT count(DISTINCT persona_id)
                FROM unnest(NEW.selected_persona_ids) AS persona_id
            ) THEN
                RAISE EXCEPTION 'graph Persona cohort origin contains duplicate Personas'
                    USING ERRCODE='55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM semantic_world_graphs graph
                JOIN semantic_world_graph_nodes node
                  ON node.graph_id=graph.id AND node.id=NEW.node_id
                WHERE graph.id=NEW.graph_id AND graph.status='succeeded'
                  AND graph.graph_sha256=NEW.graph_sha256
            ) THEN
                RAISE EXCEPTION 'graph Persona cohort origin does not match a sealed graph node'
                    USING ERRCODE='55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM cohorts cohort
                JOIN persona_datasets dataset ON dataset.id=cohort.dataset_id
                WHERE cohort.id=NEW.cohort_id AND cohort.dataset_id=NEW.dataset_id
                  AND cohort.sealed_at IS NOT NULL AND dataset.sealed_at IS NOT NULL
                  AND cohort.cohort_sha256=NEW.cohort_sha256
                  AND dataset.dataset_sha256=NEW.dataset_sha256
            ) THEN
                RAISE EXCEPTION 'graph Persona cohort origin does not match sealed cohort inputs'
                    USING ERRCODE='55000';
            END IF;
            SELECT array_agg(member.persona_id ORDER BY member.position)
            INTO actual_persona_ids
            FROM cohort_members member
            WHERE member.cohort_id=NEW.cohort_id;
            IF actual_persona_ids IS DISTINCT FROM NEW.selected_persona_ids THEN
                RAISE EXCEPTION 'graph Persona selection does not equal cohort member order'
                    USING ERRCODE='55000';
            END IF;
            actual_origin_sha256 := encode(sha256(convert_to(
                'graph-persona-cohort-origin/v1' || chr(0) || NEW.graph_id::text || chr(0) ||
                NEW.graph_sha256 || chr(0) || NEW.node_id::text || chr(0) ||
                NEW.dataset_id::text || chr(0) || NEW.dataset_sha256 || chr(0) ||
                NEW.cohort_id::text || chr(0) || NEW.cohort_sha256 || chr(0) ||
                NEW.match_semantics || chr(0) || NEW.matcher_version || chr(0) ||
                array_to_string(NEW.selected_persona_ids, chr(0)),
                'UTF8'
            )), 'hex');
            IF actual_origin_sha256 IS DISTINCT FROM NEW.origin_sha256 THEN
                RAISE EXCEPTION 'graph Persona cohort origin_sha256 mismatch'
                    USING ERRCODE='55000';
            END IF;
            RETURN NEW;
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_semantic_graph_cohort_origin_insert "
        "BEFORE INSERT ON semantic_world_graph_cohort_origins FOR EACH ROW "
        "EXECUTE FUNCTION enforce_semantic_graph_cohort_origin()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_semantic_graph_cohort_origin()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'graph Persona cohort origins are immutable' USING ERRCODE='55000';
        END; $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_semantic_graph_cohort_origin_immutable "
        "BEFORE UPDATE OR DELETE ON semantic_world_graph_cohort_origins FOR EACH ROW "
        "EXECUTE FUNCTION protect_semantic_graph_cohort_origin()"
    )
    op.execute(
        "CREATE TRIGGER trg_semantic_graph_cohort_origin_reject_truncate "
        "BEFORE TRUNCATE ON semantic_world_graph_cohort_origins FOR EACH STATEMENT "
        "EXECUTE FUNCTION protect_semantic_graph_cohort_origin()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_semantic_graph_cohort_origin_reject_truncate "
        "ON semantic_world_graph_cohort_origins"
    )
    op.execute(
        "DROP TRIGGER trg_semantic_graph_cohort_origin_immutable "
        "ON semantic_world_graph_cohort_origins"
    )
    op.execute(
        "DROP TRIGGER trg_semantic_graph_cohort_origin_insert "
        "ON semantic_world_graph_cohort_origins"
    )
    op.execute("DROP FUNCTION protect_semantic_graph_cohort_origin()")
    op.execute("DROP FUNCTION enforce_semantic_graph_cohort_origin()")
    op.drop_index(
        "ix_semantic_graph_cohort_origin_cohort",
        table_name="semantic_world_graph_cohort_origins",
    )
    op.drop_table("semantic_world_graph_cohort_origins")
