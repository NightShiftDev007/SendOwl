"""Strict lightweight progress projections for immutable parent attempts."""

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.shared.contracts import ContractModel, Sha256Digest

type ParentProgressStatus = Literal["queued", "running", "succeeded", "failed"]


class ParentProgress(ContractModel):
    id: UUID
    status: ParentProgressStatus
    observed_at: AwareDatetime
    attempt_number: Annotated[int, Field(ge=1, le=5)]
    trial_count: Annotated[int, Field(ge=1, le=8)]
    queued_trial_count: Annotated[int, Field(ge=0, le=8)]
    running_trial_count: Annotated[int, Field(ge=0, le=8)]
    succeeded_trial_count: Annotated[int, Field(ge=0, le=8)]
    failed_trial_count: Annotated[int, Field(ge=0, le=8)]
    event_count: Annotated[int, Field(ge=0)]
    progress_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_counts_and_status(self) -> Self:
        counts = (
            self.queued_trial_count,
            self.running_trial_count,
            self.succeeded_trial_count,
            self.failed_trial_count,
        )
        if sum(counts) != self.trial_count:
            raise ValueError("progress status counts must equal trial_count")
        statuses = (
            ("queued",) * self.queued_trial_count
            + ("running",) * self.running_trial_count
            + ("succeeded",) * self.succeeded_trial_count
            + ("failed",) * self.failed_trial_count
        )
        if self.status != parent_status(statuses):
            raise ValueError("progress status must match trial status counts")
        expected = calculate_progress_sha256(
            self.id,
            self.attempt_number,
            counts,
            self.event_count,
        )
        if self.progress_sha256 != expected:
            raise ValueError("progress_sha256 does not match the lightweight projection")
        return self


def parent_status(statuses: tuple[ParentProgressStatus, ...]) -> ParentProgressStatus:
    if not statuses:
        raise ValueError("progress requires at least one trial status")
    if all(status == "queued" for status in statuses):
        return "queued"
    if any(status in ("queued", "running") for status in statuses):
        return "running"
    if all(status == "succeeded" for status in statuses):
        return "succeeded"
    return "failed"


def parse_parent_progress_statuses(statuses: tuple[str, ...]) -> tuple[ParentProgressStatus, ...]:
    by_value: dict[str, ParentProgressStatus] = {
        "queued": "queued",
        "running": "running",
        "succeeded": "succeeded",
        "failed": "failed",
    }
    invalid = tuple(status for status in statuses if status not in by_value)
    if invalid:
        raise RuntimeError(f"invalid persisted progress statuses: {', '.join(invalid)}")
    return tuple(by_value[status] for status in statuses)


def calculate_progress_sha256(
    resource_id: UUID,
    attempt_number: int,
    counts: tuple[int, int, int, int],
    event_count: int,
) -> str:
    payload = {
        "attempt_number": attempt_number,
        "event_count": event_count,
        "resource_id": str(resource_id),
        "status_counts": counts,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def build_parent_progress(
    resource_id: UUID,
    attempt_number: int,
    statuses: tuple[ParentProgressStatus, ...],
    event_count: int,
    observed_at: datetime,
) -> ParentProgress:
    counts = (
        statuses.count("queued"),
        statuses.count("running"),
        statuses.count("succeeded"),
        statuses.count("failed"),
    )
    return ParentProgress(
        id=resource_id,
        status=parent_status(statuses),
        observed_at=observed_at,
        attempt_number=attempt_number,
        trial_count=len(statuses),
        queued_trial_count=counts[0],
        running_trial_count=counts[1],
        succeeded_trial_count=counts[2],
        failed_trial_count=counts[3],
        event_count=event_count,
        progress_sha256=calculate_progress_sha256(
            resource_id,
            attempt_number,
            counts,
            event_count,
        ),
    )


__all__ = [
    "ParentProgress",
    "ParentProgressStatus",
    "build_parent_progress",
    "parse_parent_progress_statuses",
]
