"""PostgreSQL ORM for the imported AgendaScope media read model."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class MediaSourceRecord(ApplicationBase):
    """Media source fields required for provenance, filtering, and health."""

    __tablename__ = "media_sources"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    homepage_url: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "media_type IN ('newspaper','agency','broadcast','online')",
            name="ck_media_sources_media_type",
        ),
        CheckConstraint(
            "status IN ('active','degraded','failed','disabled')",
            name="ck_media_sources_status",
        ),
        Index("ix_media_sources_country_status", "country_code", "status"),
    )


class MediaArticleRecord(ApplicationBase):
    """Article read model without AgendaScope's pgvector processing state."""

    __tablename__ = "media_articles"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_sources.id"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_present: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    source_last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_absent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_media_articles_published_at", "published_at"),
        Index("ix_media_articles_country", "country_code"),
        Index("ix_media_articles_source", "source_id"),
        Index("ix_media_articles_source_presence_published", "source_present", "published_at"),
        CheckConstraint(
            "(source_present AND source_absent_at IS NULL) OR "
            "(NOT source_present AND source_absent_at IS NOT NULL)",
            name="ck_media_articles_source_presence",
        ),
        CheckConstraint(
            "source_absent_at IS NULL OR source_last_observed_at IS NULL "
            "OR source_absent_at >= source_last_observed_at",
            name="ck_media_articles_source_observation_time",
        ),
        Index(
            "ix_media_articles_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_media_articles_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
        Index(
            "ix_media_articles_summary_trgm",
            "summary",
            postgresql_using="gin",
            postgresql_ops={"summary": "gin_trgm_ops"},
        ),
    )


class MediaTopicRecord(ApplicationBase):
    """Topic fields required to discover a decision scenario."""

    __tablename__ = "media_topics"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(300))
    summary_zh: Mapped[str | None] = mapped_column(Text)
    topic_category: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(15), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(15), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('emerging','heating','stable','declining','archived')",
            name="ck_media_topics_status",
        ),
        CheckConstraint(
            "lifecycle_state IN ('nascent','forming','confirmed','evolving','archived')",
            name="ck_media_topics_lifecycle",
        ),
        Index("ix_media_topics_last_seen", "last_seen_at"),
    )


class MediaTopicArticleRecord(ApplicationBase):
    """Deterministic many-to-many topic assignment preserved from AgendaScope."""

    __tablename__ = "media_topic_articles"

    topic_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    article_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    assign_method: Mapped[str] = mapped_column(String(15), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "assign_method IN ('online','recluster','merge','manual')",
            name="ck_media_topic_articles_assign_method",
        ),
        Index("ix_media_topic_articles_article", "article_id"),
    )


class MediaTopicSnapshotRecord(ApplicationBase):
    """Country/topic salience snapshot used for overview ranking."""

    __tablename__ = "media_topic_snapshots"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    topic_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    granularity: Mapped[str] = mapped_column(String(5), nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False)
    salience_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    salience_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("window_end > window_start", name="ck_media_topic_snapshots_window"),
        CheckConstraint(
            "granularity IN ('hour','day','week')",
            name="ck_media_topic_snapshots_granularity",
        ),
        CheckConstraint(
            "article_count >= 0",
            name="ck_media_topic_snapshots_article_count",
        ),
        CheckConstraint(
            "salience_rank >= 1",
            name="ck_media_topic_snapshots_rank",
        ),
        UniqueConstraint(
            "country_code",
            "topic_id",
            "window_start",
            "granularity",
            name="uq_media_topic_snapshots_scope",
        ),
        Index("ix_media_topic_snapshots_topic_window", "topic_id", "window_start"),
        Index("ix_media_topic_snapshots_country_window", "country_code", "window_start"),
    )


class MediaFirstUtteranceRecord(ApplicationBase):
    """Evidence-bound positive first-utterance observation imported from AgendaScope."""

    __tablename__ = "media_first_utterances"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    topic_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_topics.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(15), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    article_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(12), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('person','thinktank','intl_org','gov_body')",
            name="ck_media_first_utterance_entity_type",
        ),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_media_first_utterance_country"),
        CheckConstraint("confidence='high'", name="ck_media_first_utterance_confidence"),
        CheckConstraint(
            "length(btrim(entity_name)) BETWEEN 1 AND 200",
            name="ck_media_first_utterance_entity_name",
        ),
        CheckConstraint(
            "length(btrim(evidence_quote)) BETWEEN 1 AND 2000",
            name="ck_media_first_utterance_quote",
        ),
        CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND "
            "length(btrim(prompt_version)) BETWEEN 1 AND 100",
            name="ck_media_first_utterance_provenance",
        ),
        Index("ix_media_first_utterances_topic_time", "topic_id", occurred_at.desc(), "id"),
        Index("ix_media_first_utterances_article", "article_id"),
    )


class MediaPropagationEventRecord(ApplicationBase):
    """Imported AgendaScope origin event without model reasoning payloads."""

    __tablename__ = "media_propagation_events"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    topic_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("media_topics.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    confidence: Mapped[str] = mapped_column(String(12), nullable=False)
    origin_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    origin_source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("media_sources.id", ondelete="SET NULL")
    )
    origin_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin_confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    detection_method: Mapped[str] = mapped_column(String(20), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('watching','suspected','confirmed','dismissed','revised','archived')",
            name="ck_media_propagation_event_status",
        ),
        CheckConstraint(
            "confidence IN ('watching','suspected','confirmed')",
            name="ck_media_propagation_event_confidence",
        ),
        CheckConstraint(
            "origin_country_code ~ '^[A-Z]{2}$'",
            name="ck_media_propagation_origin_country",
        ),
        CheckConstraint(
            "origin_confidence IN ('high','medium','low')",
            name="ck_media_propagation_origin_confidence",
        ),
        Index("ix_media_propagation_events_origin_at", origin_at.desc()),
        Index("ix_media_propagation_events_status", "status"),
    )


class MediaPropagationEdgeRecord(ApplicationBase):
    """One ordered source observation from an imported AgendaScope event."""

    __tablename__ = "media_propagation_edges"

    event_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("media_propagation_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    to_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    lag_hours: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    first_media_name: Mapped[str | None] = mapped_column(String(200))
    first_article_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("media_articles.id", ondelete="SET NULL")
    )
    first_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_follower_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    follower_source_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("media_sources.id", ondelete="SET NULL")
    )
    observation_source: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="legacy_projection"
    )

    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_media_propagation_edge_position"),
        CheckConstraint(
            "from_country_code ~ '^[A-Z]{2}$' AND to_country_code ~ '^[A-Z]{2}$'",
            name="ck_media_propagation_edge_countries",
        ),
        CheckConstraint("lag_hours >= 0", name="ck_media_propagation_edge_lag"),
        UniqueConstraint(
            "event_id",
            "source_follower_id",
            name="uq_media_propagation_source_follower",
        ),
        CheckConstraint(
            "(observation_source='legacy_projection' AND source_follower_id IS NULL) OR "
            "(observation_source='structured_followers' AND source_follower_id IS NOT NULL "
            "AND follower_source_id IS NOT NULL)",
            name="ck_media_propagation_edge_observation_source",
        ),
        Index("ix_media_propagation_edges_destination", "to_country_code"),
        Index("ix_media_propagation_edges_follower_source", "follower_source_id"),
    )
