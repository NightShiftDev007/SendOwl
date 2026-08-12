"""Strict PostgreSQL queue records and normalized terminal facts."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel, UserName

RunStatus = Literal["queued", "running", "succeeded", "failed"]


class QueuePost(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    content: Annotated[RequiredText, Field(max_length=4000)]
    offset_minutes: Annotated[int, Field(ge=0, le=1440)]


class ClaimedRun(StrictModel):
    id: UUID
    status: Literal["running"]
    mode: Literal["reddit_manual_smoke"]
    scenario_id: UUID
    scenario_sha256: Sha256
    variant_id: UUID
    variant_name: Annotated[RequiredText, Field(max_length=200)]
    world_snapshot_id: UUID
    snapshot_sha256: Sha256
    company_name: Annotated[RequiredText, Field(max_length=300)]
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    actor_user_name: UserName
    actor_name: Annotated[RequiredText, Field(max_length=200)]
    actor_bio: Annotated[RequiredText, Field(max_length=500)]
    input_sha256: Sha256
    posts: Annotated[tuple[QueuePost, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def validate_post_order(self) -> Self:
        positions = tuple(post.position for post in self.posts)
        if positions != tuple(range(len(self.posts))):
            raise ValueError("queue post positions must be contiguous and start at zero")
        return self


class NormalizedSuccess(StrictModel):
    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    artifact_sha256: Sha256
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    user_count: Literal[1]
    post_count: Annotated[int, Field(ge=1, le=20)]
    trace_count: Annotated[int, Field(ge=2, le=21)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.trace_count != self.post_count + 1:
            raise ValueError("trace_count must equal post_count + 1")
        return self


class NormalizedFailure(StrictModel):
    code: Annotated[
        str,
        StringConstraints(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
            strict=True,
        ),
    ]
    message: RequiredText


class WorkerHeartbeat(StrictModel):
    worker_id: Annotated[RequiredText, Field(max_length=128)]
    started_at: datetime
    last_seen_at: datetime
    platform_runtime_ready: bool
