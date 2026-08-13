"""Strict requests and normalized results for MatrAIx and OASIS."""

from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest


class SimulationEngine(StrEnum):
    """Simulation engines retained by the V2 product architecture."""

    MATRAIX = "matraix"
    OASIS = "oasis"


PopulationWeight = Annotated[
    float,
    Field(
        strict=True,
        ge=0.0,
        le=1.0,
        description="Relative cohort weight normalized by the execution adapter.",
    ),
]


class CohortRef(ContractModel):
    """A weighted Persona cohort selected for a MatrAIx evaluation."""

    cohort_id: Identifier
    label: NonEmptyText
    persona_count: PositiveInt
    population_weight: PopulationWeight


Cohorts = Annotated[tuple[CohortRef, ...], Field(min_length=1)]
Questions = Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]
AgentIds = Annotated[tuple[Identifier, ...], Field(min_length=1)]


class MatrAIxEvaluationSpec(ContractModel):
    """Population-response request with positive relative cohort weights."""

    engine: Literal["matraix"]
    run_id: Identifier
    scenario_id: Identifier
    cohorts: Cohorts
    questions: Questions
    model_id: NonEmptyText
    seed: NonNegativeInt

    @model_validator(mode="after")
    def validate_cohorts(self) -> Self:
        """Require unique cohorts and a positive weight total for adapter normalization."""
        seen_cohort_ids: set[str] = set()
        duplicate_cohort_ids: set[str] = set()
        for cohort in self.cohorts:
            if cohort.cohort_id in seen_cohort_ids:
                duplicate_cohort_ids.add(cohort.cohort_id)
            seen_cohort_ids.add(cohort.cohort_id)

        if duplicate_cohort_ids:
            duplicates = ", ".join(sorted(duplicate_cohort_ids))
            raise ValueError(f"cohorts must use unique cohort_id values; duplicates: {duplicates}")

        total_population_weight: float = sum(cohort.population_weight for cohort in self.cohorts)
        if total_population_weight <= 0.0:
            raise ValueError(
                "cohorts must have a total population_weight greater than zero; "
                "execution adapters normalize positive relative weights"
            )
        return self


class OasisSimulationSpec(ContractModel):
    """Network-propagation request sent to the OASIS execution adapter."""

    engine: Literal["oasis"]
    run_id: Identifier
    scenario_id: Identifier
    agent_ids: AgentIds
    rounds: PositiveInt
    seed: NonNegativeInt


SimulationSpec = Annotated[
    MatrAIxEvaluationSpec | OasisSimulationSpec,
    Field(discriminator="engine"),
]


class MetricObservation(ContractModel):
    """One named, unit-bearing numeric result from an engine run."""

    name: Identifier
    value: FiniteFloat
    unit: NonEmptyText
    description: NonEmptyText


class EngineArtifact(ContractModel):
    """Content-addressed artifact emitted by a simulation run."""

    artifact_id: Identifier
    media_type: NonEmptyText
    location: NonEmptyText
    content_sha256: Sha256Digest


class EngineResult(ContractModel):
    """Engine-neutral result envelope without untyped metric dictionaries."""

    run_id: Identifier
    scenario_id: Identifier
    engine: SimulationEngine
    metrics: tuple[MetricObservation, ...]
    artifacts: tuple[EngineArtifact, ...]
    limitations: tuple[NonEmptyText, ...]


type PlatformSmokeMode = Literal["reddit_manual_smoke"]
type PlatformSmokeStatus = Literal["queued", "running", "succeeded", "failed"]
type VariantName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type PlatformPostContent = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type WorkerUserName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$", strict=True),
]


def _request_uuid(value: object, field_name: str) -> UUID:
    """Parse one UUID transport string without weakening response validation."""
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class PlatformSmokeCreateRequest(ContractModel):
    """Request one key-free OASIS platform and persistence smoke run."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario_id: UUID
    variant_id: UUID
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]

    @field_validator("scenario_id", mode="before")
    @classmethod
    def parse_scenario_id(cls, value: object) -> UUID:
        return _request_uuid(value, "scenario_id")

    @field_validator("variant_id", mode="before")
    @classmethod
    def parse_variant_id(cls, value: object) -> UUID:
        return _request_uuid(value, "variant_id")


class PlatformSmokeScenarioRef(ContractModel):
    """Frozen Scenario and WorldSnapshot identity compiled into one run."""

    id: UUID
    scenario_sha256: Sha256Digest
    variant_id: UUID
    variant_name: VariantName
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest


class PlatformSmokePost(ContractModel):
    """One exact ordered initial post copied from the selected alternative."""

    position: Annotated[int, Field(ge=0, le=19)]
    content: PlatformPostContent
    offset_minutes: Annotated[int, Field(ge=0, le=1440)]


class PlatformSmokeResult(ContractModel):
    """Normalized facts verified from the real OASIS SQLite artifact."""

    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    artifact_sha256: Sha256Digest
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    user_count: Literal[1]
    post_count: Annotated[int, Field(ge=1, le=20)]
    trace_count: Annotated[int, Field(ge=2, le=21)]
    limitations: tuple[NonEmptyText, ...]

    @model_validator(mode="after")
    def validate_observed_counts(self) -> Self:
        if self.trace_count != self.post_count + 1:
            raise ValueError("trace_count must equal post_count + 1")
        return self


class PlatformSmokeError(ContractModel):
    """Explicit terminal worker failure without configuration secrets."""

    code: Identifier
    message: NonEmptyText


class PlatformSmokeRunSummary(ContractModel):
    """Directory projection for one platform-smoke run."""

    id: UUID
    mode: PlatformSmokeMode
    status: PlatformSmokeStatus
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    scenario: PlatformSmokeScenarioRef
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    input_sha256: Sha256Digest


class PlatformSmokeRunDetail(PlatformSmokeRunSummary):
    """Complete immutable input plus normalized terminal output for one run."""

    posts: Annotated[tuple[PlatformSmokePost, ...], Field(min_length=1, max_length=20)]
    result: PlatformSmokeResult | None
    error: PlatformSmokeError | None

    @model_validator(mode="after")
    def validate_state_projection(self) -> Self:
        positions = tuple(post.position for post in self.posts)
        if positions != tuple(range(len(self.posts))):
            raise ValueError("platform-smoke post positions must be contiguous and start at zero")
        if self.status == "queued":
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("queued platform-smoke runs cannot have execution timestamps")
            if self.result is not None or self.error is not None:
                raise ValueError("queued platform-smoke runs cannot have terminal output")
        elif self.status == "running":
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("running platform-smoke runs require only started_at")
            if self.result is not None or self.error is not None:
                raise ValueError("running platform-smoke runs cannot have terminal output")
        elif self.status == "succeeded":
            if self.started_at is None or self.completed_at is None:
                raise ValueError("succeeded platform-smoke runs require execution timestamps")
            if self.result is None or self.error is not None:
                raise ValueError("succeeded platform-smoke runs require only a result")
        elif self.status == "failed":
            if self.started_at is None or self.completed_at is None:
                raise ValueError("failed platform-smoke runs require execution timestamps")
            if self.result is not None or self.error is None:
                raise ValueError("failed platform-smoke runs require only an error")
        return self


class PlatformSmokeRunsResponse(ContractModel):
    """Platform-smoke run directory."""

    items: tuple[PlatformSmokeRunSummary, ...]
    total: Annotated[int, Field(ge=0)]


class OasisReadiness(ContractModel):
    """Truthful runtime readiness derived from a recent PostgreSQL heartbeat."""

    engine: Literal["camel-oasis"]
    engine_version: Literal["0.2.5"]
    mode: PlatformSmokeMode
    worker_online: bool
    platform_runtime_ready: bool
    semantic_run_ready: Literal[False]
    limitations: tuple[NonEmptyText, ...]


class CompiledPlatformSmokeInput(ContractModel):
    """Complete content-addressed worker input before a run resource is assigned."""

    mode: PlatformSmokeMode
    scenario: PlatformSmokeScenarioRef
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    actor_user_name: WorkerUserName
    actor_name: Annotated[str, StringConstraints(min_length=1, max_length=200, strict=True)]
    actor_bio: Annotated[str, StringConstraints(min_length=1, max_length=500, strict=True)]
    posts: Annotated[tuple[PlatformSmokePost, ...], Field(min_length=1, max_length=20)]
