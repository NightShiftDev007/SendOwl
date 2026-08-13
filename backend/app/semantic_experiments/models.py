"""Normalized PostgreSQL records for durable semantic experiments."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import ApplicationBase


class SemanticExperimentRecord(ApplicationBase):
    """Content-addressed batch assembled as a draft and then sealed."""

    __tablename__ = "semantic_experiments"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    scenario_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False
    )
    scenario_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_title: Mapped[str] = mapped_column(String(300), nullable=False)
    decision_question: Mapped[str] = mapped_column(Text, nullable=False)
    cohort_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("cohorts.id"), nullable=False
    )
    cohort_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cohort_title: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes_per_round: Mapped[int] = mapped_column(Integer, nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    semantic_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "scenario_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_scenario_sha256",
        ),
        CheckConstraint(
            "cohort_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_cohort_sha256",
        ),
        CheckConstraint(
            "dataset_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_dataset_sha256",
        ),
        CheckConstraint(
            "semantic_config_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_config_sha256",
        ),
        CheckConstraint(
            "experiment_sha256 ~ '^[a-f0-9]{64}$'",
            name="ck_semantic_experiments_sha256",
        ),
        CheckConstraint("persona_count BETWEEN 1 AND 8", name="ck_semantic_persona_count"),
        CheckConstraint("rounds BETWEEN 1 AND 3", name="ck_semantic_rounds"),
        CheckConstraint(
            "minutes_per_round BETWEEN 15 AND 240", name="ck_semantic_minutes_per_round"
        ),
        CheckConstraint(
            "prompt_schema_version = 'matraix-semantic-profile/v1'",
            name="ck_semantic_prompt_schema",
        ),
        CheckConstraint(
            "length(btrim(model_name)) BETWEEN 1 AND 200 AND model_name !~ E'[\\r\\n]'",
            name="ck_semantic_model_name",
        ),
        CheckConstraint(
            "input_sealed_at IS NULL OR input_sealed_at >= created_at",
            name="ck_semantic_experiments_sealed_time",
        ),
        UniqueConstraint("experiment_sha256", name="uq_semantic_experiments_sha256"),
        Index("ix_semantic_experiments_created_at", "created_at"),
    )


class SemanticExperimentVariantRecord(ApplicationBase):
    """Selected baseline or alternative copied from the sealed Scenario."""

    __tablename__ = "semantic_experiment_variants"

    experiment_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    scenario_variant_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("scenario_variants.id"), nullable=False
    )
    scenario_position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    intervention_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("experiment_id", "position"),
        ForeignKeyConstraint(("experiment_id",), ("semantic_experiments.id",), ondelete="CASCADE"),
        CheckConstraint(
            "(position = 0 AND role = 'baseline' AND scenario_position = 0 "
            "AND intervention_count = 0) OR "
            "(position BETWEEN 1 AND 2 AND role = 'alternative' "
            "AND scenario_position BETWEEN 1 AND 5 AND intervention_count BETWEEN 1 AND 20)",
            name="ck_semantic_variants_role_position",
        ),
        UniqueConstraint(
            "experiment_id", "scenario_variant_id", name="uq_semantic_variants_selection"
        ),
        Index(
            "ix_semantic_variants_scenario_variant",
            "scenario_variant_id",
        ),
    )


class SemanticTrialRecord(ApplicationBase):
    """One durable variant-by-seed execution and its verified terminal facts."""

    __tablename__ = "semantic_trials"

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    variant_position: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_role: Mapped[str] = mapped_column(String(16), nullable=False)
    scenario_variant_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    scenario_position: Mapped[int] = mapped_column(Integer, nullable=False)
    variant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    variant_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trial_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    engine_version: Mapped[str | None] = mapped_column(String(32))
    camel_version: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(200))
    semantic_config_sha256: Mapped[str | None] = mapped_column(String(64))
    prompt_schema_version: Mapped[str | None] = mapped_column(String(64))
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
        ForeignKeyConstraint(
            ("experiment_id", "variant_position"),
            ("semantic_experiment_variants.experiment_id", "semantic_experiment_variants.position"),
            ondelete="CASCADE",
        ),
        CheckConstraint("seed BETWEEN 0 AND 4294967295", name="ck_semantic_trials_seed"),
        CheckConstraint("trial_sha256 ~ '^[a-f0-9]{64}$'", name="ck_semantic_trials_sha256"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_semantic_trials_status",
        ),
        CheckConstraint("current_round BETWEEN 0 AND 3", name="ck_semantic_current_round"),
        CheckConstraint(
            "(variant_position = 0 AND variant_role = 'baseline' "
            "AND scenario_position = 0) OR "
            "(variant_position BETWEEN 1 AND 2 AND variant_role = 'alternative' "
            "AND scenario_position BETWEEN 1 AND 5)",
            name="ck_semantic_trials_variant",
        ),
        CheckConstraint(
            "(status = 'queued' AND current_round = 0 AND claimed_by_worker_id IS NULL "
            "AND started_at IS NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL AND model_name IS NULL "
            "AND semantic_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND initial_post_count IS NULL "
            "AND generated_post_count IS NULL AND comment_count IS NULL "
            "AND reaction_count IS NULL AND do_nothing_count IS NULL "
            "AND observed_action_count IS NULL AND rounds_completed IS NULL "
            "AND limitations IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'running' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NULL "
            "AND engine_version IS NULL AND camel_version IS NULL AND model_name IS NULL "
            "AND semantic_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND initial_post_count IS NULL "
            "AND generated_post_count IS NULL AND comment_count IS NULL "
            "AND reaction_count IS NULL AND do_nothing_count IS NULL "
            "AND observed_action_count IS NULL AND rounds_completed IS NULL "
            "AND limitations IS NULL AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'succeeded' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version = '0.2.5' AND camel_version = '0.2.78' "
            "AND length(btrim(model_name)) BETWEEN 1 AND 200 "
            "AND semantic_config_sha256 ~ '^[a-f0-9]{64}$' "
            "AND prompt_schema_version = 'matraix-semantic-profile/v1' "
            "AND artifact_sha256 ~ '^[a-f0-9]{64}$' AND artifact_size_bytes > 0 "
            "AND user_count BETWEEN 2 AND 9 AND initial_post_count >= 0 "
            "AND generated_post_count >= 0 AND comment_count >= 0 "
            "AND reaction_count >= 0 AND do_nothing_count >= 0 "
            "AND observed_action_count = initial_post_count + generated_post_count "
            "+ comment_count + reaction_count + do_nothing_count "
            "AND rounds_completed BETWEEN 1 AND 3 AND cardinality(limitations) >= 1 "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(status = 'failed' AND length(claimed_by_worker_id) BETWEEN 1 AND 128 "
            "AND started_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND engine_version IS NULL AND camel_version IS NULL AND model_name IS NULL "
            "AND semantic_config_sha256 IS NULL AND prompt_schema_version IS NULL "
            "AND artifact_sha256 IS NULL AND artifact_size_bytes IS NULL "
            "AND user_count IS NULL AND initial_post_count IS NULL "
            "AND generated_post_count IS NULL AND comment_count IS NULL "
            "AND reaction_count IS NULL AND do_nothing_count IS NULL "
            "AND observed_action_count IS NULL AND rounds_completed IS NULL "
            "AND limitations IS NULL AND length(error_code) BETWEEN 1 AND 128 "
            "AND length(error_message) BETWEEN 1 AND 4000)",
            name="ck_semantic_trials_state_shape",
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_semantic_started_time"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_semantic_completed_time",
        ),
        UniqueConstraint("trial_sha256", name="uq_semantic_trials_sha256"),
        UniqueConstraint(
            "experiment_id", "variant_position", "seed", name="uq_semantic_trials_cartesian"
        ),
        Index("ix_semantic_trials_status_created", "status", "created_at"),
    )


class SemanticTrialEventRecord(ApplicationBase):
    """One normalized append-only OASIS action observed inside a trial."""

    __tablename__ = "semantic_trial_events"

    trial_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("semantic_trials.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    persona_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), ForeignKey("personas.id")
    )
    agent_position: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    post_id: Mapped[str | None] = mapped_column(String(128))
    comment_id: Mapped[str | None] = mapped_column(String(128))
    target_post_id: Mapped[str | None] = mapped_column(String(128))
    observed_at_raw: Mapped[str] = mapped_column(String(200), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("trial_id", "sequence"),
        CheckConstraint("sequence >= 1", name="ck_semantic_events_sequence"),
        CheckConstraint("round BETWEEN 1 AND 3", name="ck_semantic_events_round"),
        CheckConstraint("phase IN ('intervention', 'audience')", name="ck_semantic_events_phase"),
        CheckConstraint(
            "(actor_kind = 'scenario' AND persona_id IS NULL AND agent_position = 0 "
            "AND phase = 'intervention' AND action_type = 'create_post') OR "
            "(actor_kind = 'persona' AND persona_id IS NOT NULL "
            "AND agent_position BETWEEN 1 AND 8 AND phase = 'audience')",
            name="ck_semantic_events_actor",
        ),
        CheckConstraint(
            "action_type IN ('create_post', 'create_comment', 'like_post', "
            "'dislike_post', 'do_nothing')",
            name="ck_semantic_events_action",
        ),
        CheckConstraint(
            "content IS NULL OR char_length(content) <= 4000",
            name="ck_semantic_events_content_length",
        ),
        CheckConstraint(
            "(action_type = 'create_post' AND length(btrim(content)) >= 1 "
            "AND length(post_id) BETWEEN 1 AND 128 AND comment_id IS NULL "
            "AND target_post_id IS NULL) OR "
            "(action_type = 'create_comment' AND length(btrim(content)) >= 1 "
            "AND post_id IS NULL AND length(comment_id) BETWEEN 1 AND 128 "
            "AND length(target_post_id) BETWEEN 1 AND 128) OR "
            "(action_type IN ('like_post', 'dislike_post') AND content IS NULL "
            "AND post_id IS NULL AND comment_id IS NULL "
            "AND length(target_post_id) BETWEEN 1 AND 128) OR "
            "(action_type = 'do_nothing' AND content IS NULL AND post_id IS NULL "
            "AND comment_id IS NULL AND target_post_id IS NULL)",
            name="ck_semantic_events_action_shape",
        ),
        CheckConstraint(
            "length(btrim(observed_at_raw)) BETWEEN 1 AND 200 AND observed_at_raw !~ E'[\\r\\n]'",
            name="ck_semantic_events_observed_at",
        ),
        Index("ix_semantic_events_trial_sequence", "trial_id", "sequence"),
    )
