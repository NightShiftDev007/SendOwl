"""Strict contracts for persistent, versioned decision context."""

from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Sha256Digest

type DecisionThreadTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type DecisionQuestion = Annotated[
    str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)
]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class DecisionThreadRequestModel(ContractModel):
    model_config = ConfigDict(extra="forbid")


class DecisionThreadContextCreate(DecisionThreadRequestModel):
    world_model_id: UUID
    world_snapshot_id: UUID
    scenario_id: UUID | None
    cohort_id: UUID | None
    semantic_experiment_id: UUID | None

    @field_validator(
        "world_model_id",
        "world_snapshot_id",
        "scenario_id",
        "cohort_id",
        "semantic_experiment_id",
        mode="before",
    )
    @classmethod
    def parse_resource_id(cls, value: object, info) -> UUID | None:
        if value is None:
            return None
        return _request_uuid(value, info.field_name)

    @model_validator(mode="after")
    def validate_dependency_shape(self) -> Self:
        if self.semantic_experiment_id is not None and (
            self.scenario_id is None or self.cohort_id is None
        ):
            raise ValueError("semantic_experiment_id requires scenario_id and cohort_id")
        return self


class DecisionThreadCreateRequest(DecisionThreadContextCreate):
    title: DecisionThreadTitle
    decision_question: DecisionQuestion


class DecisionThreadRevision(ContractModel):
    id: UUID
    version: Annotated[int, Field(ge=1)]
    world_model_id: UUID
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest
    scenario_id: UUID | None
    scenario_sha256: Sha256Digest | None
    cohort_id: UUID | None
    cohort_sha256: Sha256Digest | None
    semantic_experiment_id: UUID | None
    experiment_sha256: Sha256Digest | None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_optional_digests(self) -> Self:
        pairs = (
            (self.scenario_id, self.scenario_sha256),
            (self.cohort_id, self.cohort_sha256),
            (self.semantic_experiment_id, self.experiment_sha256),
        )
        if any((identity is None) != (digest is None) for identity, digest in pairs):
            raise ValueError("optional decision context identities and digests must be paired")
        if self.semantic_experiment_id is not None and (
            self.scenario_id is None or self.cohort_id is None
        ):
            raise ValueError("semantic experiment context requires scenario and cohort context")
        return self


class DecisionThreadSummary(ContractModel):
    id: UUID
    title: DecisionThreadTitle
    decision_question: DecisionQuestion
    created_at: AwareDatetime
    latest_revision: DecisionThreadRevision


class DecisionThreadDetail(DecisionThreadSummary):
    revisions: Annotated[tuple[DecisionThreadRevision, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_history(self) -> Self:
        versions = tuple(revision.version for revision in self.revisions)
        if versions != tuple(range(1, len(self.revisions) + 1)):
            raise ValueError("decision thread revision versions must be contiguous from one")
        if self.latest_revision != self.revisions[-1]:
            raise ValueError("latest_revision must equal the final history revision")
        return self


class DecisionThreadsResponse(ContractModel):
    items: tuple[DecisionThreadSummary, ...]
    total: Annotated[int, Field(ge=0)]
