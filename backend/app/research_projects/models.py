"""PostgreSQL records for single-run research projects."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class ResearchProjectRecord(ApplicationBase):
    """Immutable Project / Graph context with read-only v1 design fields."""

    __tablename__ = "research_projects"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    research_question: Mapped[str] = mapped_column(Text, nullable=False)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_models.id", ondelete="RESTRICT"),
        nullable=False,
    )
    world_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    world_graph_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("semantic_world_graphs.id", ondelete="RESTRICT")
    )
    graph_sha256: Mapped[str | None] = mapped_column(String(64))
    graph_node_count: Mapped[int | None] = mapped_column(Integer)
    graph_edge_count: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id", ondelete="RESTRICT")
    )
    cohort_sha256: Mapped[str | None] = mapped_column(String(64))
    persona_count: Mapped[int | None] = mapped_column(Integer)
    simulation_requirement: Mapped[str | None] = mapped_column(Text)
    project_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300",
            name="ck_research_projects_title",
        ),
        CheckConstraint(
            "length(btrim(research_question)) BETWEEN 1 AND 2000",
            name="ck_research_projects_question",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$' AND project_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_projects_digests",
        ),
        CheckConstraint(
            "(schema_version = 'sandowl-research-project/v1' "
            "AND cohort_id IS NOT NULL AND cohort_sha256 ~ '^[a-f0-9]{64}$' "
            "AND persona_count BETWEEN 1 AND 100 "
            "AND length(btrim(simulation_requirement)) BETWEEN 1 AND 4000 "
            "AND world_graph_id IS NULL AND graph_sha256 IS NULL "
            "AND graph_node_count IS NULL AND graph_edge_count IS NULL) OR "
            "(schema_version = 'sandowl-research-project/v2' "
            "AND cohort_id IS NULL AND cohort_sha256 IS NULL "
            "AND persona_count IS NULL AND simulation_requirement IS NULL "
            "AND world_graph_id IS NULL AND graph_sha256 IS NULL "
            "AND graph_node_count IS NULL AND graph_edge_count IS NULL) OR "
            "(schema_version = 'sandowl-research-project/v3' "
            "AND cohort_id IS NULL AND cohort_sha256 IS NULL "
            "AND persona_count IS NULL AND simulation_requirement IS NULL "
            "AND world_graph_id IS NOT NULL AND graph_sha256 ~ '^[a-f0-9]{64}$' "
            "AND graph_node_count BETWEEN 1 AND 500 "
            "AND graph_edge_count BETWEEN 0 AND 2000)",
            name="ck_research_projects_schema_shape",
        ),
        Index("ix_research_projects_created_at", "created_at"),
    )


class ResearchProjectAgendaContextRecord(ApplicationBase):
    """Immutable AgendaScope topic context captured for one Project."""

    __tablename__ = "research_project_agenda_contexts"

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    project_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sync_run_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("media_sync_runs.id", ondelete="RESTRICT")
    )
    source_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "schema_version='sandowl-project-agenda-context/v1'",
            name="ck_research_project_agenda_context_schema",
        ),
        CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' AND context_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_project_agenda_context_digests",
        ),
        CheckConstraint(
            "jsonb_typeof(payload_json)='object'",
            name="ck_research_project_agenda_context_payload",
        ),
        Index("ix_research_project_agenda_context_captured", "captured_at"),
    )


class ResearchSimulationRunRecord(ApplicationBase):
    """Independent run claimed and completed by the semantic worker domain."""

    __tablename__ = "research_simulation_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    research_project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_projects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id", ondelete="RESTRICT"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    simulation_requirement: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    rounds: Mapped[int | None] = mapped_column(Integer)
    minutes_per_round: Mapped[int | None] = mapped_column(Integer)
    initial_post: Mapped[str | None] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(200))
    semantic_config_sha256: Mapped[str | None] = mapped_column(String(64))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(64))
    simulation_context: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    simulation_context_sha256: Mapped[str | None] = mapped_column(String(64))
    simulation_plan: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    simulation_plan_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    run_spec_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    user_count: Mapped[int | None] = mapped_column(Integer)
    initial_post_count: Mapped[int | None] = mapped_column(Integer)
    generated_post_count: Mapped[int | None] = mapped_column(Integer)
    comment_count: Mapped[int | None] = mapped_column(Integer)
    reaction_count: Mapped[int | None] = mapped_column(Integer)
    do_nothing_count: Mapped[int | None] = mapped_column(Integer)
    observed_action_count: Mapped[int | None] = mapped_column(Integer)
    rounds_completed: Mapped[int | None] = mapped_column(Integer)
    limitations: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("seed BETWEEN 0 AND 2147483647", name="ck_research_runs_seed"),
        CheckConstraint(
            "engine = 'camel-oasis' AND engine_version = '0.2.5'",
            name="ck_research_runs_engine",
        ),
        CheckConstraint(
            "status IN ('configured', 'queued', 'running', 'succeeded', 'failed')",
            name="ck_research_runs_status",
        ),
        CheckConstraint(
            "status = 'configured' OR (rounds BETWEEN 1 AND 6 "
            "AND minutes_per_round BETWEEN 15 AND 480 "
            "AND length(btrim(initial_post)) BETWEEN 1 AND 4000 "
            "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version = 'matraix-semantic-profile/v1')",
            name="ck_research_runs_execution_input",
        ),
        CheckConstraint(
            "project_sha256 ~ '^[a-f0-9]{64}$' AND run_spec_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_runs_digests",
        ),
        CheckConstraint(
            "schema_version IN ('sandowl-research-simulation-run/v1', "
            "'sandowl-research-simulation-run/v2', 'sandowl-research-simulation-run/v3', "
            "'sandowl-research-simulation-run/v4')",
            name="ck_research_runs_schema_version",
        ),
        CheckConstraint(
            "(schema_version IN ('sandowl-research-simulation-run/v1', "
            "'sandowl-research-simulation-run/v2') AND simulation_context IS NULL "
            "AND simulation_context_sha256 IS NULL AND simulation_plan IS NULL "
            "AND simulation_plan_sha256 IS NULL) OR "
            "(schema_version = 'sandowl-research-simulation-run/v3' "
            "AND jsonb_typeof(simulation_context) = 'object' "
            "AND simulation_context_sha256 ~ '^[a-f0-9]{64}$' "
            "AND simulation_plan IS NULL AND simulation_plan_sha256 IS NULL) OR "
            "(schema_version = 'sandowl-research-simulation-run/v4' "
            "AND jsonb_typeof(simulation_context) = 'object' "
            "AND simulation_context_sha256 ~ '^[a-f0-9]{64}$' "
            "AND jsonb_typeof(simulation_plan) = 'object' "
            "AND simulation_plan_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_research_runs_context_shape",
        ),
        CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$' AND persona_count BETWEEN 1 AND 100 "
            "AND length(btrim(simulation_requirement)) BETWEEN 1 AND 4000",
            name="ck_research_runs_design",
        ),
        Index("ix_research_runs_project_created", "research_project_id", "created_at"),
        Index("ix_research_runs_spec_sha256", "run_spec_sha256"),
        UniqueConstraint("run_spec_sha256", name="uq_research_runs_spec_sha256"),
    )


class ResearchRunEventRecord(ApplicationBase):
    __tablename__ = "research_run_events"

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    persona_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    agent_position: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    post_id: Mapped[str | None] = mapped_column(String(128))
    comment_id: Mapped[str | None] = mapped_column(String(128))
    target_post_id: Mapped[str | None] = mapped_column(String(128))
    observed_at_raw: Mapped[str] = mapped_column(String(200), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_research_run_events_sequence"),
        CheckConstraint("round BETWEEN 1 AND 6", name="ck_research_run_events_round"),
        Index("ix_research_run_events_run_sequence", "run_id", "sequence"),
    )


class ResearchRunReportRecord(ApplicationBase):
    __tablename__ = "research_run_reports"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("report_sha256 ~ '^[a-f0-9]{64}$'", name="ck_research_run_reports_sha256"),
        UniqueConstraint("run_id", name="uq_research_run_reports_run"),
        UniqueConstraint("report_sha256", name="uq_research_run_reports_sha256"),
    )


class ResearchRunGraphMemoryRecord(ApplicationBase):
    __tablename__ = "research_run_graph_memory"

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("research_simulation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    round: Mapped[int] = mapped_column(Integer, primary_key=True)
    previous_sha256: Mapped[str | None] = mapped_column(String(64))
    memory: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    memory_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("round BETWEEN 1 AND 6", name="ck_research_graph_memory_round"),
        CheckConstraint(
            "(round = 1 AND previous_sha256 IS NULL) OR "
            "(round > 1 AND previous_sha256 ~ '^[a-f0-9]{64}$')",
            name="ck_research_graph_memory_previous",
        ),
        CheckConstraint(
            "jsonb_typeof(memory) = 'object' AND memory_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_research_graph_memory_shape",
        ),
        UniqueConstraint("memory_sha256", name="uq_research_graph_memory_sha256"),
    )
