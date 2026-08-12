"""PostgreSQL records for immutable decision scenarios."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class ScenarioRecord(ApplicationBase):
    """Content-addressed scenario parent inserted as a draft and then sealed."""

    __tablename__ = "scenarios"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    decision_question: Mapped[str] = mapped_column(Text, nullable=False)
    world_model_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_models.id"),
        nullable=False,
    )
    world_snapshot_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("world_snapshots.id"),
        nullable=False,
    )
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_company_name: Mapped[str] = mapped_column(String(300), nullable=False)
    snapshot_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 300 AND title !~ E'[\\r\\n]'",
            name="ck_scenarios_title",
        ),
        CheckConstraint(
            "length(btrim(decision_question)) BETWEEN 1 AND 2000",
            name="ck_scenarios_decision_question",
        ),
        CheckConstraint("snapshot_version >= 1", name="ck_scenarios_snapshot_version"),
        CheckConstraint(
            "snapshot_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_scenarios_snapshot_sha256",
        ),
        CheckConstraint(
            "length(btrim(snapshot_company_name)) BETWEEN 1 AND 300 "
            "AND snapshot_company_name !~ E'[\\r\\n]'",
            name="ck_scenarios_snapshot_company_name",
        ),
        CheckConstraint(
            "snapshot_evidence_count BETWEEN 1 AND 50",
            name="ck_scenarios_snapshot_evidence_count",
        ),
        CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_scenarios_sha256",
        ),
        UniqueConstraint("scenario_sha256", name="uq_scenarios_sha256"),
        Index("ix_scenarios_created_at", "created_at"),
        Index("ix_scenarios_world_snapshot", "world_snapshot_id"),
    )


class ScenarioVariantRecord(ApplicationBase):
    """Ordered baseline or alternative owned by one scenario draft."""

    __tablename__ = "scenario_variants"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(role = 'baseline' AND position = 0) OR "
            "(role = 'alternative' AND position BETWEEN 1 AND 5)",
            name="ck_scenario_variants_role_position",
        ),
        CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 200 AND name !~ E'[\\r\\n]'",
            name="ck_scenario_variants_name",
        ),
        CheckConstraint(
            "length(btrim(hypothesis)) BETWEEN 1 AND 2000",
            name="ck_scenario_variants_hypothesis",
        ),
        UniqueConstraint("scenario_id", "position", name="uq_scenario_variants_position"),
        UniqueConstraint("scenario_id", "id", name="uq_scenario_variants_scenario_id"),
        Index("ix_scenario_variants_scenario_position", "scenario_id", "position"),
    )


class ScenarioInterventionRecord(ApplicationBase):
    """Ordered supported action owned by one alternative scenario variant."""

    __tablename__ = "scenario_interventions"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    variant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ("scenario_id", "variant_id"),
            ("scenario_variants.scenario_id", "scenario_variants.id"),
            ondelete="CASCADE",
        ),
        CheckConstraint("position BETWEEN 0 AND 19", name="ck_scenario_interventions_position"),
        CheckConstraint("kind = 'initial_post'", name="ck_scenario_interventions_kind"),
        CheckConstraint("actor = 'snapshot_company'", name="ck_scenario_interventions_actor"),
        CheckConstraint("channel = 'reddit'", name="ck_scenario_interventions_channel"),
        CheckConstraint(
            "length(btrim(content)) BETWEEN 1 AND 4000",
            name="ck_scenario_interventions_content",
        ),
        CheckConstraint(
            "offset_minutes BETWEEN 0 AND 1440",
            name="ck_scenario_interventions_offset",
        ),
        UniqueConstraint(
            "scenario_id",
            "variant_id",
            "position",
            name="uq_scenario_interventions_position",
        ),
        Index(
            "ix_scenario_interventions_variant_position",
            "scenario_id",
            "variant_id",
            "position",
        ),
    )
