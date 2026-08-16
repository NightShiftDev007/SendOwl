"""Strict public contracts for AgendaScope media refresh observability."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.shared.contracts import ContractModel, Identifier, NonEmptyText


class MediaSyncTrigger(StrEnum):
    """Supported explicit refresh origins."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"


class MediaSyncRunStatus(StrEnum):
    """Durable refresh lifecycle states."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED_CONCURRENT = "skipped_concurrent"


class MediaSyncTableName(StrEnum):
    """Imported tables exposed without physical target names."""

    SOURCES = "sources"
    ARTICLES = "articles"
    TOPICS = "topics"
    TOPIC_ARTICLES = "topic_articles"
    TOPIC_SNAPSHOTS = "topic_snapshots"
    PROPAGATION_EVENTS = "propagation_events"
    PROPAGATION_EDGES = "propagation_edges"
    FIRST_UTTERANCES = "first_utterances"


class MediaSyncWatermarks(ContractModel):
    """Source-owned business timestamps observed in one consistent snapshot."""

    latest_source_updated_at: AwareDatetime | None
    latest_article_crawled_at: AwareDatetime | None
    latest_topic_updated_at: AwareDatetime | None
    latest_topic_article_assigned_at: AwareDatetime | None
    latest_snapshot_created_at: AwareDatetime | None
    latest_snapshot_window_end: AwareDatetime | None
    latest_propagation_updated_at: AwareDatetime | None


class MediaArticleReconciliation(ContractModel):
    """Current target-side visibility derived from the latest complete source scan."""

    present_count: Annotated[int, Field(ge=0)]
    absent_count: Annotated[int, Field(ge=0)]
    latest_absent_at: AwareDatetime | None

    @model_validator(mode="after")
    def validate_absence_time(self) -> Self:
        if (self.absent_count == 0) != (self.latest_absent_at is None):
            raise ValueError("article absence timestamp must match absent_count")
        return self


class MediaSyncTableCount(ContractModel):
    """Complete accounting for one imported table."""

    table_name: MediaSyncTableName
    read_count: Annotated[int, Field(ge=0)]
    inserted_count: Annotated[int, Field(ge=0)]
    updated_count: Annotated[int, Field(ge=0)]
    skipped_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_accounting(self) -> Self:
        if self.read_count != self.inserted_count + self.updated_count + self.skipped_count:
            raise ValueError("media sync table counts must account for every source row")
        return self


type SafeSyncErrorCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]{0,127}$",
    ),
]


class MediaSyncRunError(ContractModel):
    """Credential-free failure exposed for one terminal attempt."""

    code: SafeSyncErrorCode
    message: Annotated[NonEmptyText, Field(max_length=500)]


class MediaSyncRun(ContractModel):
    """One persisted manual or scheduled refresh attempt."""

    id: UUID
    trigger: MediaSyncTrigger
    status: MediaSyncRunStatus
    worker_id: Identifier
    started_at: AwareDatetime
    completed_at: AwareDatetime | None
    next_scheduled_at: AwareDatetime | None
    source_observed_at: AwareDatetime | None
    source_watermarks: MediaSyncWatermarks | None
    table_counts: tuple[MediaSyncTableCount, ...]
    error: MediaSyncRunError | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        publishes_next_schedule = self.trigger is MediaSyncTrigger.SCHEDULED and self.status in (
            MediaSyncRunStatus.SUCCEEDED,
            MediaSyncRunStatus.SKIPPED_CONCURRENT,
        )
        if (self.next_scheduled_at is not None) is not publishes_next_schedule:
            raise ValueError(
                "only successful or concurrently skipped scheduled syncs publish a next timestamp"
            )
        if self.status is MediaSyncRunStatus.RUNNING:
            valid = (
                self.completed_at is None
                and self.source_observed_at is None
                and self.source_watermarks is None
                and not self.table_counts
                and self.error is None
            )
        elif self.status is MediaSyncRunStatus.SUCCEEDED:
            valid = (
                self.completed_at is not None
                and self.source_observed_at is not None
                and self.source_watermarks is not None
                and len(self.table_counts) == len(MediaSyncTableName)
                and self.error is None
            )
        elif self.status is MediaSyncRunStatus.FAILED:
            valid = (
                self.completed_at is not None
                and self.source_observed_at is None
                and self.source_watermarks is None
                and not self.table_counts
                and self.error is not None
            )
        else:
            valid = (
                self.completed_at is not None
                and self.source_observed_at is None
                and self.source_watermarks is None
                and not self.table_counts
                and self.error is None
            )
        if not valid:
            raise ValueError("media sync run fields do not match its lifecycle status")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("media sync completion cannot precede its start")
        return self


class MediaSyncStatusResponse(ContractModel):
    """Current refresh history and target business-time watermarks."""

    generated_at: AwareDatetime
    mode: Literal["periodic_snapshot_refresh"]
    latest_run: MediaSyncRun | None
    latest_success: MediaSyncRun | None
    target_watermarks: MediaSyncWatermarks
    article_reconciliation: MediaArticleReconciliation
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_latest_success(self) -> Self:
        if (
            self.latest_success is not None
            and self.latest_success.status is not MediaSyncRunStatus.SUCCEEDED
        ):
            raise ValueError("latest_success must reference a succeeded media sync run")
        return self
