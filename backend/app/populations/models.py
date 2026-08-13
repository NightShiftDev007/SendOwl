"""PostgreSQL records for immutable MatrAIx datasets, personas, and cohorts."""

from datetime import datetime
from typing import TypedDict
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class PersonaProvenanceJson(TypedDict):
    """Exact nullable provenance shape stored inside a persona profile."""

    hf_repo: str | None
    origin_persona_id: str | None
    origin_source_row_index: int | None
    parent_pool: str | None


class PersonaProfileJson(TypedDict):
    """Exact JSONB profile shape validated and content-addressed by the domain."""

    display_name: str
    dimensions: dict[str, str]
    persona_id: str
    provenance: PersonaProvenanceJson
    source: str
    version: str


class PersonaDatasetRecord(ApplicationBase):
    """One imported dataset version assembled as a draft and then sealed."""

    __tablename__ = "persona_datasets"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_pool: Mapped[str | None] = mapped_column(String(500))
    source_repository: Mapped[str | None] = mapped_column(String(500))
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "slug ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_persona_datasets_slug",
        ),
        CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 200 AND display_name !~ E'[\\r\\n]'",
            name="ck_persona_datasets_display_name",
        ),
        CheckConstraint(
            "schema_version ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_persona_datasets_schema_version",
        ),
        CheckConstraint(
            "parent_pool IS NULL OR "
            "(length(btrim(parent_pool)) BETWEEN 1 AND 500 "
            "AND parent_pool !~ E'[\\r\\n]')",
            name="ck_persona_datasets_parent_pool",
        ),
        CheckConstraint(
            "source_repository IS NULL OR "
            "(length(btrim(source_repository)) BETWEEN 1 AND 500 "
            "AND source_repository !~ E'[\\r\\n]')",
            name="ck_persona_datasets_source_repository",
        ),
        CheckConstraint(
            "persona_count BETWEEN 1 AND 1000000",
            name="ck_persona_datasets_persona_count",
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_datasets_manifest_sha256",
        ),
        CheckConstraint(
            "dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_persona_datasets_dataset_sha256",
        ),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_persona_datasets_sealed_time",
        ),
        UniqueConstraint("dataset_sha256", name="uq_persona_datasets_dataset_sha256"),
        Index("ix_persona_datasets_slug", "slug"),
        Index("ix_persona_datasets_created_at", "created_at"),
    )


class PersonaRecord(ApplicationBase):
    """One ordered frozen persona owned by an imported dataset version."""

    __tablename__ = "personas"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("persona_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    persona_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_json: Mapped[PersonaProfileJson] = mapped_column(
        JSONB,
        nullable=False,
    )
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 999999", name="ck_personas_position"),
        CheckConstraint(
            "persona_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_personas_persona_id",
        ),
        CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 200 AND display_name !~ E'[\\r\\n]'",
            name="ck_personas_display_name",
        ),
        CheckConstraint(
            "source ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'",
            name="ck_personas_source",
        ),
        CheckConstraint(
            "profile_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_personas_profile_sha256",
        ),
        UniqueConstraint("dataset_id", "position", name="uq_personas_dataset_position"),
        UniqueConstraint("dataset_id", "persona_id", name="uq_personas_dataset_persona_id"),
        UniqueConstraint("dataset_id", "id", name="uq_personas_dataset_id"),
        Index("ix_personas_dataset_source", "dataset_id", "source"),
    )


class CohortRecord(ApplicationBase):
    """Content-addressed cohort parent assembled as a draft and then sealed."""

    __tablename__ = "cohorts"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("persona_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 200 AND title !~ E'[\\r\\n]'",
            name="ck_cohorts_title",
        ),
        CheckConstraint(
            "persona_count BETWEEN 1 AND 100",
            name="ck_cohorts_persona_count",
        ),
        CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_cohorts_cohort_sha256",
        ),
        CheckConstraint(
            "sealed_at IS NULL OR sealed_at >= created_at",
            name="ck_cohorts_sealed_time",
        ),
        UniqueConstraint("cohort_sha256", name="uq_cohorts_cohort_sha256"),
        UniqueConstraint("id", "dataset_id", name="uq_cohorts_id_dataset"),
        Index("ix_cohorts_dataset_created_at", "dataset_id", "created_at"),
    )


class CohortMemberRecord(ApplicationBase):
    """One ordered persona member owned by an immutable cohort."""

    __tablename__ = "cohort_members"

    cohort_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    dataset_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    persona_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("cohort_id", "position"),
        ForeignKeyConstraint(
            ("cohort_id", "dataset_id"),
            ("cohorts.id", "cohorts.dataset_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("dataset_id", "persona_id"),
            ("personas.dataset_id", "personas.id"),
        ),
        CheckConstraint(
            "position BETWEEN 0 AND 99",
            name="ck_cohort_members_position",
        ),
        UniqueConstraint("cohort_id", "persona_id", name="uq_cohort_members_persona"),
        Index("ix_cohort_members_dataset_persona", "dataset_id", "persona_id"),
    )
