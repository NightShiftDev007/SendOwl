"""PostgreSQL records for durable OASIS platform-smoke orchestration."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class SimulationRunRecord(ApplicationBase):
    """One content-addressed immutable input with a constrained execution state."""

    __tablename__ = "simulation_runs"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    scenario_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    world_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_snapshots.id"),
        nullable=False,
    )
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor_user_name: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_bio: Mapped[str] = mapped_column(String(500), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    camel_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ("scenario_id", "variant_id"),
            ("scenario_variants.scenario_id", "scenario_variants.id"),
        ),
        CheckConstraint("mode = 'reddit_manual_smoke'", name="ck_simulation_runs_mode"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_simulation_runs_status",
        ),
        CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_scenario_sha256",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_snapshot_sha256",
        ),
        CheckConstraint(
            "input_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_simulation_runs_input_sha256",
        ),
        CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_simulation_runs_seed"),
        CheckConstraint(
            "length(btrim(variant_name)) BETWEEN 1 AND 200 AND variant_name !~ E'[\\r\\n]'",
            name="ck_simulation_runs_variant_name",
        ),
        CheckConstraint(
            "length(btrim(company_name)) BETWEEN 1 AND 300 AND company_name !~ E'[\\r\\n]'",
            name="ck_simulation_runs_company_name",
        ),
        CheckConstraint(
            "actor_user_name ~ '^[A-Za-z0-9_-]{1,32}$'",
            name="ck_simulation_runs_actor_user_name",
        ),
        CheckConstraint(
            "length(actor_name) BETWEEN 1 AND 200",
            name="ck_simulation_runs_actor_name",
        ),
        CheckConstraint(
            "length(actor_bio) BETWEEN 1 AND 500",
            name="ck_simulation_runs_actor_bio",
        ),
        CheckConstraint(
            "(status = 'queued' AND claimed_by_worker_id IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version = '0.2.5' AND camel_version = '0.2.78' "
            "AND artifact_sha256 ~ '^[a-f0-9]{64}$' AND artifact_size_bytes > 0 "
            "AND user_count = 1 AND post_count BETWEEN 1 AND 20 "
            "AND trace_count = post_count + 1 "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version IS NULL AND camel_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND post_count IS NULL AND trace_count IS NULL "
            "AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) >= 1)",
            name="ck_simulation_runs_state_shape",
        ),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_simulation_runs_sealed_time",
        ),
        CheckConstraint(
            "started_at IS NULL OR (input_sealed_at IS NOT NULL AND started_at >= created_at)",
            name="ck_simulation_runs_started_time",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_simulation_runs_completed_time",
        ),
        UniqueConstraint("input_sha256", name="uq_simulation_runs_input_sha256"),
        Index("ix_simulation_runs_created_at", "created_at"),
        Index("ix_simulation_runs_status_created_at", "status", "created_at"),
    )


class SimulationRunPostRecord(ApplicationBase):
    """Exact ordered initial-post input copied from a Scenario alternative."""

    __tablename__ = "simulation_run_posts"

    run_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("simulation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 19", name="ck_simulation_run_posts_position"),
        CheckConstraint(
            "length(btrim(content)) BETWEEN 1 AND 4000",
            name="ck_simulation_run_posts_content",
        ),
        CheckConstraint(
            "offset_minutes BETWEEN 0 AND 1440",
            name="ck_simulation_run_posts_offset",
        ),
        Index("ix_simulation_run_posts_run_position", "run_id", "position"),
    )


class SimulationWorkerHeartbeatRecord(ApplicationBase):
    """Recent versioned worker presence used for truthful readiness."""

    __tablename__ = "simulation_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    camel_version: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_runtime_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(worker_id) BETWEEN 1 AND 128",
            name="ck_simulation_worker_heartbeats_worker_id",
        ),
        CheckConstraint("engine = 'camel-oasis'", name="ck_simulation_worker_engine"),
        CheckConstraint(
            "engine_version = '0.2.5'",
            name="ck_simulation_worker_engine_version",
        ),
        CheckConstraint("camel_version = '0.2.78'", name="ck_simulation_worker_camel_version"),
        CheckConstraint("mode = 'reddit_manual_smoke'", name="ck_simulation_worker_mode"),
        Index("ix_simulation_worker_heartbeats_last_seen", "last_seen_at"),
    )
