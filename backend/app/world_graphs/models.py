"""Normalized PostgreSQL records for semantic world graph extraction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class SemanticWorldGraphRecord(ApplicationBase):
    __tablename__ = "semantic_world_graphs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("world_models.id"), nullable=False
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("world_snapshots.id"), nullable=False
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    node_count: Mapped[int | None] = mapped_column(Integer)
    edge_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_semantic_world_graphs_status",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND "
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$' AND "
            "extraction_config_sha256 ~ '^[a-f0-9]{64}$' AND "
            "input_sha256 ~ '^[a-f0-9]{64}$' AND "
            "(graph_sha256 IS NULL OR graph_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_semantic_world_graphs_hashes",
        ),
        CheckConstraint(
            "prompt_schema_version = 'world-graph-extraction/v1'",
            name="ck_semantic_world_graphs_prompt_schema",
        ),
        CheckConstraint(
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
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at",
            name="ck_semantic_world_graphs_started_time",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_semantic_world_graphs_completed_time",
        ),
        UniqueConstraint("input_sha256", name="uq_semantic_world_graphs_input_sha256"),
        Index("ix_semantic_world_graphs_snapshot_created", "snapshot_id", "created_at"),
        Index("ix_semantic_world_graphs_status_created", "status", "created_at"),
    )


class SemanticWorldGraphNodeRecord(ApplicationBase):
    __tablename__ = "semantic_world_graph_nodes"

    graph_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("graph_id", "position"),
        ForeignKeyConstraint(("graph_id",), ("semantic_world_graphs.id",), ondelete="CASCADE"),
        CheckConstraint("position BETWEEN 0 AND 499", name="ck_semantic_graph_nodes_position"),
        CheckConstraint(
            "entity_type IN ('organization','person','location','policy','event','concept')",
            name="ck_semantic_graph_nodes_entity_type",
        ),
        CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200 AND length(btrim(summary)) BETWEEN 1 AND 500",
            name="ck_semantic_graph_nodes_text",
        ),
        UniqueConstraint("graph_id", "id", name="uq_semantic_graph_nodes_identity"),
    )


class SemanticWorldGraphEdgeRecord(ApplicationBase):
    __tablename__ = "semantic_world_graph_edges"

    graph_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_node_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    target_node_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    fact: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("graph_id", "position"),
        ForeignKeyConstraint(("graph_id",), ("semantic_world_graphs.id",), ondelete="CASCADE"),
        ForeignKeyConstraint(
            ("graph_id", "source_node_id"),
            ("semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"),
        ),
        ForeignKeyConstraint(
            ("graph_id", "target_node_id"),
            ("semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"),
        ),
        CheckConstraint("position BETWEEN 0 AND 1999", name="ck_semantic_graph_edges_position"),
        CheckConstraint(
            "relation_type ~ '^[a-z][a-z0-9_]{0,63}$'",
            name="ck_semantic_graph_edges_relation_type",
        ),
        CheckConstraint(
            "length(btrim(fact)) BETWEEN 1 AND 500",
            name="ck_semantic_graph_edges_fact",
        ),
        UniqueConstraint("graph_id", "id", name="uq_semantic_graph_edges_identity"),
    )


class SemanticWorldGraphEvidenceRecord(ApplicationBase):
    __tablename__ = "semantic_world_graph_evidence"

    graph_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    object_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    article_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    quote: Mapped[str] = mapped_column(String(500), nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("graph_id", "object_kind", "object_id", "position"),
        ForeignKeyConstraint(("graph_id",), ("semantic_world_graphs.id",), ondelete="CASCADE"),
        CheckConstraint("object_kind IN ('node','edge')", name="ck_semantic_graph_evidence_kind"),
        CheckConstraint("position BETWEEN 0 AND 19", name="ck_semantic_graph_evidence_position"),
        CheckConstraint(
            "start_offset >= 0 AND end_offset > start_offset "
            "AND end_offset - start_offset = char_length(quote)",
            name="ck_semantic_graph_evidence_offsets",
        ),
        Index("ix_semantic_graph_evidence_article", "article_id"),
    )


class SemanticWorldGraphCohortOriginRecord(ApplicationBase):
    """Immutable lineage from one graph-node match to a sealed cohort."""

    __tablename__ = "semantic_world_graph_cohort_origins"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    graph_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    graph_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    match_semantics: Mapped[str] = mapped_column(String(80), nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(16), nullable=False)
    selected_persona_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PostgreSQLUUID(as_uuid=True)),
        nullable=False,
    )
    origin_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(("graph_id",), ("semantic_world_graphs.id",)),
        ForeignKeyConstraint(
            ("graph_id", "node_id"),
            ("semantic_world_graph_nodes.graph_id", "semantic_world_graph_nodes.id"),
        ),
        ForeignKeyConstraint(("dataset_id",), ("persona_datasets.id",)),
        ForeignKeyConstraint(
            ("cohort_id", "dataset_id"),
            ("cohorts.id", "cohorts.dataset_id"),
        ),
        CheckConstraint(
            "graph_sha256 ~ '^[a-f0-9]{64}$' AND "
            "dataset_sha256 ~ '^[a-f0-9]{64}$' AND "
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND "
            "origin_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_graph_cohort_origin_hashes",
        ),
        CheckConstraint(
            "match_semantics='exact_token_overlap_non_low_information_attributes'",
            name="ck_semantic_graph_cohort_origin_semantics",
        ),
        CheckConstraint(
            "matcher_version='1.0.0'",
            name="ck_semantic_graph_cohort_origin_matcher",
        ),
        CheckConstraint(
            "cardinality(selected_persona_ids) BETWEEN 1 AND 8",
            name="ck_semantic_graph_cohort_origin_personas",
        ),
        UniqueConstraint("origin_sha256", name="uq_semantic_graph_cohort_origin_sha"),
        Index("ix_semantic_graph_cohort_origin_cohort", "cohort_id", "created_at"),
    )
