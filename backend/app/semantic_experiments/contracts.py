"""Strict requests and verified projections for OASIS semantic experiments."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.shared.contracts import ContractModel, Identifier, NonEmptyText, Sha256Digest

type SemanticStatus = Literal["queued", "running", "succeeded", "failed"]
type SemanticRole = Literal["baseline", "alternative"]
type PromptSchemaVersion = Literal["matraix-semantic-profile/v1"]
type SemanticPhase = Literal["intervention", "audience"]
type SemanticActorKind = Literal["scenario", "persona"]
type SemanticActionType = Literal[
    "create_post",
    "create_comment",
    "like_post",
    "dislike_post",
    "do_nothing",
]
type ComparisonState = Literal["pending", "partial", "complete", "failed"]
type ComparisonMetricName = Literal[
    "observed_action_count",
    "authored_content_count",
    "reaction_count",
    "do_nothing_count",
]
type SemanticModelName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=300, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenCohortTitle = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type FrozenHypothesis = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type ObservedIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type ObservedAtRaw = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$", strip_whitespace=True),
]
type EventContent = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


def _request_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array; received {type(value).__name__}")
    return tuple(value)


class SemanticExperimentCreateRequest(ContractModel):
    """One bounded Cartesian experiment over a sealed Scenario and Cohort."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scenario_id: UUID
    cohort_id: UUID
    alternative_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=2)]
    seeds: Annotated[tuple[int, ...], Field(min_length=1, max_length=2)]
    rounds: Annotated[int, Field(ge=1, le=3)]
    minutes_per_round: Annotated[int, Field(ge=15, le=240)]

    @field_validator("scenario_id", "cohort_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info: ValidationInfo) -> UUID:
        return _request_uuid(value, info.field_name)

    @field_validator("alternative_ids", mode="before")
    @classmethod
    def parse_alternative_ids(cls, value: object) -> tuple[UUID, ...]:
        return tuple(
            _request_uuid(item, "alternative_ids item")
            for item in _request_tuple(value, "alternative_ids")
        )

    @field_validator("seeds", mode="before")
    @classmethod
    def parse_seeds(cls, value: object) -> tuple[object, ...]:
        return _request_tuple(value, "seeds")

    @model_validator(mode="after")
    def reject_duplicate_dimensions(self) -> Self:
        if len(set(self.alternative_ids)) != len(self.alternative_ids):
            raise ValueError("alternative_ids must not contain duplicates")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must not contain duplicates")
        if any(seed < 0 or seed > 4_294_967_295 for seed in self.seeds):
            raise ValueError("each seed must be an unsigned 32-bit integer")
        return self


class SemanticScenarioRef(ContractModel):
    id: UUID
    title: FrozenTitle
    decision_question: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    scenario_sha256: Sha256Digest


class SemanticCohortRef(ContractModel):
    id: UUID
    title: FrozenCohortTitle
    cohort_sha256: Sha256Digest
    dataset_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=8)]


class FrozenSemanticVariant(ContractModel):
    """Variant identity used by both canonical inputs and public projections."""

    position: Annotated[int, Field(ge=0, le=2)]
    role: SemanticRole
    id: UUID
    scenario_position: Annotated[int, Field(ge=0, le=5)]
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200, pattern=r"^[^\r\n]+$"),
    ]
    hypothesis: FrozenHypothesis
    intervention_count: Annotated[int, Field(ge=0, le=20)]

    @model_validator(mode="after")
    def validate_role(self) -> Self:
        if self.position == 0 and (self.role != "baseline" or self.scenario_position != 0):
            raise ValueError("experiment position zero must be the Scenario baseline")
        if self.position > 0 and (self.role != "alternative" or self.scenario_position < 1):
            raise ValueError("nonzero experiment positions must be Scenario alternatives")
        if self.role == "baseline" and self.intervention_count != 0:
            raise ValueError("baseline intervention_count must be zero")
        if self.role == "alternative" and self.intervention_count < 1:
            raise ValueError("alternative intervention_count must be at least one")
        return self


class SemanticTrialResult(ContractModel):
    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    model_name: SemanticModelName
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: PromptSchemaVersion
    artifact_sha256: Sha256Digest
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    user_count: Annotated[int, Field(ge=2, le=9)]
    initial_post_count: Annotated[int, Field(ge=0)]
    generated_post_count: Annotated[int, Field(ge=0)]
    comment_count: Annotated[int, Field(ge=0)]
    reaction_count: Annotated[int, Field(ge=0)]
    do_nothing_count: Annotated[int, Field(ge=0)]
    observed_action_count: Annotated[int, Field(ge=0)]
    authored_content_count: Annotated[int, Field(ge=0)]
    rounds_completed: Annotated[int, Field(ge=1, le=3)]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def verify_counts(self) -> Self:
        if self.authored_content_count != self.generated_post_count + self.comment_count:
            raise ValueError("authored_content_count must equal generated posts plus comments")
        expected_observed = (
            self.initial_post_count
            + self.generated_post_count
            + self.comment_count
            + self.reaction_count
            + self.do_nothing_count
        )
        if self.observed_action_count != expected_observed:
            raise ValueError("observed_action_count must equal the normalized action counts")
        return self


class SemanticTrialError(ContractModel):
    code: Identifier
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class SemanticTrial(ContractModel):
    id: UUID
    status: SemanticStatus
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    trial_sha256: Sha256Digest
    current_round: Annotated[int, Field(ge=0, le=3)]
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    result: SemanticTrialResult | None
    error: SemanticTrialError | None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.status == "queued":
            valid = (
                self.current_round == 0 and self.started_at is None and self.completed_at is None
            )
            valid = valid and self.result is None and self.error is None
        elif self.status == "running":
            valid = self.started_at is not None and self.completed_at is None
            valid = valid and self.result is None and self.error is None
        elif self.status == "succeeded":
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and self.result is not None and self.error is None
        else:
            valid = self.started_at is not None and self.completed_at is not None
            valid = valid and self.result is None and self.error is not None
        if not valid:
            raise ValueError(f"semantic trial fields do not match status {self.status}")
        return self


class SemanticExperimentSummary(ContractModel):
    id: UUID
    status: SemanticStatus
    created_at: AwareDatetime
    scenario: SemanticScenarioRef
    cohort: SemanticCohortRef
    variant_count: Annotated[int, Field(ge=2, le=3)]
    trial_count: Annotated[int, Field(ge=2, le=6)]
    rounds: Annotated[int, Field(ge=1, le=3)]
    minutes_per_round: Annotated[int, Field(ge=15, le=240)]
    seeds: Annotated[tuple[int, ...], Field(min_length=1, max_length=2)]
    model_name: SemanticModelName
    semantic_config_sha256: Sha256Digest
    prompt_schema_version: PromptSchemaVersion
    experiment_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_dimensions(self) -> Self:
        if self.seeds != tuple(sorted(set(self.seeds))):
            raise ValueError("experiment seeds must be unique and ascending")
        if self.trial_count != self.variant_count * len(self.seeds):
            raise ValueError("trial_count must equal variant_count multiplied by seed count")
        return self


class SemanticExperimentVariant(FrozenSemanticVariant):
    trials: Annotated[tuple[SemanticTrial, ...], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def validate_trials(self) -> Self:
        seeds = tuple(trial.seed for trial in self.trials)
        if seeds != tuple(sorted(set(seeds))):
            raise ValueError("variant trials must use unique ascending seeds")
        return self


class SemanticExperimentDetail(SemanticExperimentSummary):
    variants: Annotated[tuple[SemanticExperimentVariant, ...], Field(min_length=2, max_length=3)]

    @model_validator(mode="after")
    def validate_cartesian_projection(self) -> Self:
        positions = tuple(variant.position for variant in self.variants)
        if positions != tuple(range(len(self.variants))):
            raise ValueError("experiment variant positions must be contiguous from zero")
        if len(self.variants) != self.variant_count:
            raise ValueError("variant_count must equal variants length")
        if any(
            tuple(trial.seed for trial in variant.trials) != self.seeds for variant in self.variants
        ):
            raise ValueError("every variant must contain the complete seed selection")
        trials = tuple(trial for variant in self.variants for trial in variant.trials)
        if any(trial.current_round > self.rounds for trial in trials):
            raise ValueError("trial current_round cannot exceed experiment rounds")
        if any(
            trial.result is not None and trial.result.rounds_completed != self.rounds
            for trial in trials
        ):
            raise ValueError("successful trial rounds_completed must equal experiment rounds")
        statuses = {trial.status for trial in trials}
        if statuses == {"queued"}:
            expected_status = "queued"
        elif statuses & {"queued", "running"}:
            expected_status = "running"
        elif statuses == {"succeeded"}:
            expected_status = "succeeded"
        else:
            expected_status = "failed"
        if self.status != expected_status:
            raise ValueError("experiment status does not match its trial states")
        return self


class SemanticExperimentsResponse(ContractModel):
    items: tuple[SemanticExperimentSummary, ...]
    total: Annotated[int, Field(ge=0)]


class SemanticTrialEvent(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    round: Annotated[int, Field(ge=1, le=3)]
    phase: SemanticPhase
    actor_kind: SemanticActorKind
    persona_id: UUID | None
    agent_position: Annotated[int, Field(ge=0, le=8)]
    action_type: SemanticActionType
    content: EventContent | None
    post_id: ObservedIdentifier | None
    comment_id: ObservedIdentifier | None
    target_post_id: ObservedIdentifier | None
    observed_at_raw: ObservedAtRaw
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def validate_actor(self) -> Self:
        if self.actor_kind == "scenario":
            if self.persona_id is not None or self.agent_position != 0:
                raise ValueError("scenario events require null persona_id and agent_position zero")
            if self.phase != "intervention" or self.action_type != "create_post":
                raise ValueError("scenario events must be intervention create_post actions")
        elif self.persona_id is None or self.agent_position < 1:
            raise ValueError("persona events require persona_id and positive agent_position")
        elif self.phase != "audience":
            raise ValueError("persona events must use the audience phase")
        if self.action_type == "create_post":
            valid = (
                self.content is not None
                and self.post_id is not None
                and self.comment_id is None
                and self.target_post_id is None
            )
        elif self.action_type == "create_comment":
            valid = (
                self.content is not None
                and self.post_id is None
                and self.comment_id is not None
                and self.target_post_id is not None
            )
        elif self.action_type in ("like_post", "dislike_post"):
            valid = (
                self.content is None
                and self.post_id is None
                and self.comment_id is None
                and self.target_post_id is not None
            )
        else:
            valid = (
                self.content is None
                and self.post_id is None
                and self.comment_id is None
                and self.target_post_id is None
            )
        if not valid:
            raise ValueError(f"event payload fields do not match action_type {self.action_type}")
        return self


class SemanticTrialEventsResponse(ContractModel):
    trial_id: UUID
    after_sequence: Annotated[int, Field(ge=0)]
    next_after_sequence: Annotated[int, Field(ge=0)]
    has_more: bool
    items: tuple[SemanticTrialEvent, ...]

    @model_validator(mode="after")
    def validate_cursor_page(self) -> Self:
        sequences = tuple(item.sequence for item in self.items)
        if sequences and sequences != tuple(
            range(self.after_sequence + 1, self.after_sequence + 1 + len(sequences))
        ):
            raise ValueError("event page sequences must be contiguous after the cursor")
        expected_next = sequences[-1] if sequences else self.after_sequence
        if self.next_after_sequence != expected_next:
            raise ValueError("next_after_sequence must equal the final returned sequence")
        return self


class SemanticVariantObservation(ContractModel):
    position: Annotated[int, Field(ge=0, le=2)]
    role: SemanticRole
    id: UUID
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    n: Annotated[int, Field(ge=1, le=2)]
    mean: FiniteFloat
    stddev: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]


class SemanticPairedDelta(ContractModel):
    alternative_position: Annotated[int, Field(ge=1, le=2)]
    alternative_id: UUID
    alternative_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    n: Annotated[int, Field(ge=1, le=2)]
    mean_delta: FiniteFloat
    stddev_delta: Annotated[float, Field(strict=True, ge=0.0, allow_inf_nan=False)]


class SemanticMetricComparison(ContractModel):
    metric: ComparisonMetricName
    variants: Annotated[tuple[SemanticVariantObservation, ...], Field(max_length=3)]
    paired_deltas: Annotated[tuple[SemanticPairedDelta, ...], Field(max_length=2)]

    @model_validator(mode="after")
    def validate_unique_positions(self) -> Self:
        positions = tuple(item.position for item in self.variants)
        alternative_positions = tuple(item.alternative_position for item in self.paired_deltas)
        if positions != tuple(sorted(set(positions))):
            raise ValueError("comparison variant positions must be unique and ascending")
        if alternative_positions != tuple(sorted(set(alternative_positions))):
            raise ValueError("paired delta positions must be unique and ascending")
        return self


class SemanticExperimentComparison(ContractModel):
    experiment_id: UUID
    complete: bool
    state: ComparisonState
    metrics: tuple[SemanticMetricComparison, ...]
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_metric_set(self) -> Self:
        expected = (
            "observed_action_count",
            "authored_content_count",
            "reaction_count",
            "do_nothing_count",
        )
        if tuple(metric.metric for metric in self.metrics) != expected:
            raise ValueError("comparison must contain the four normalized metrics in fixed order")
        if self.complete:
            if self.state != "complete":
                raise ValueError("complete comparison must use state complete")
            variant_counts = {len(metric.variants) for metric in self.metrics}
            delta_counts = {len(metric.paired_deltas) for metric in self.metrics}
            if len(variant_counts) != 1 or len(delta_counts) != 1:
                raise ValueError("complete comparison metric dimensions must agree")
            variant_count = next(iter(variant_counts))
            delta_count = next(iter(delta_counts))
            if not 2 <= variant_count <= 3 or delta_count != variant_count - 1:
                raise ValueError("complete comparison requires all variants and alternatives")
        elif self.state == "complete":
            raise ValueError("state complete requires complete=true")
        return self


class SemanticReadiness(ContractModel):
    engine: Literal["camel-oasis"]
    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    worker_online: bool
    live_worker_count: Annotated[int, Field(ge=0)]
    semantic_runtime_ready: bool
    configuration_conflict: bool
    model_name: SemanticModelName | None
    semantic_config_sha256: Sha256Digest | None
    prompt_schema_version: PromptSchemaVersion | None
    limitations: Annotated[tuple[NonEmptyText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.worker_online != (self.live_worker_count > 0):
            raise ValueError("worker_online must equal live_worker_count > 0")
        has_config = (
            self.model_name is not None
            and self.semantic_config_sha256 is not None
            and self.prompt_schema_version is not None
        )
        if self.semantic_runtime_ready != (
            self.worker_online and not self.configuration_conflict and has_config
        ):
            raise ValueError("semantic_runtime_ready requires one non-conflicting live config")
        if not self.semantic_runtime_ready and has_config:
            raise ValueError("unready semantic projection must not expose a selected config")
        if (
            any(
                value is not None
                for value in (
                    self.model_name,
                    self.semantic_config_sha256,
                    self.prompt_schema_version,
                )
            )
            != has_config
        ):
            raise ValueError("semantic config fields must be all present or all absent")
        return self


__all__ = [
    "FrozenSemanticVariant",
    "PromptSchemaVersion",
    "SemanticExperimentComparison",
    "SemanticExperimentCreateRequest",
    "SemanticExperimentDetail",
    "SemanticExperimentSummary",
    "SemanticExperimentsResponse",
    "SemanticReadiness",
    "SemanticTrialEventsResponse",
]
