"""Strict immutable inputs and normalized outputs for semantic OASIS trials."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel

PROMPT_SCHEMA_VERSION = "matraix-semantic-profile/v1"
MAX_PROFILE_ATTRIBUTES = 40
ALLOWED_AUDIENCE_ACTION_NAMES = (
    "create_post",
    "create_comment",
    "like_post",
    "dislike_post",
    "do_nothing",
)
LOW_INFORMATION_VALUES = frozenset(
    {
        "none",
        "unfamiliar",
        "not applicable",
        "absent",
        "no coding activity",
    }
)
PROFILE_TEMPLATE_TEXT = """
# ROLE
You are one simulated Reddit audience member in a bounded SandOwl research run.

# IDENTITY
Display name: {display_name}
Persona source: {source}
Persona profile digest: {profile_sha256}

# BOUNDED PERSONA PROFILE
{profile_projection}

# DECISION CONTEXT
Decision question: {decision_question}

# ACTION CONTRACT
Observe the current Reddit environment and perform exactly one tool call. Choose only one of:
create_post, create_comment, like_post, dislike_post, do_nothing. Remain consistent with the
persona profile. Do not claim that this simulation predicts real behavior.
""".strip()

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        strict=True,
    ),
]
DisplayName = Annotated[RequiredText, Field(max_length=200)]
ActionTypeName = Literal[
    "create_post",
    "create_comment",
    "like_post",
    "dislike_post",
    "do_nothing",
]


class SemanticRuntimeConfig(StrictModel):
    """Complete non-persisted provider configuration and its public identity."""

    api_key: Annotated[str, StringConstraints(min_length=1, max_length=8192, strict=True)] = Field(
        repr=False
    )
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=2000, strict=True)] = Field(
        repr=False
    )
    model_name: Annotated[RequiredText, Field(max_length=200)]
    config_sha256: Sha256
    prompt_schema_version: Literal["matraix-semantic-profile/v1"]


class PersonaProvenance(StrictModel):
    hf_repo: str | None
    origin_persona_id: str | None
    origin_source_row_index: Annotated[int, Field(ge=0)] | None
    parent_pool: str | None


class PersonaProfile(StrictModel):
    display_name: DisplayName
    dimensions: dict[Identifier, Annotated[RequiredText, Field(max_length=500)]]
    persona_id: Identifier
    provenance: PersonaProvenance
    source: Identifier
    version: Identifier

    @field_validator("dimensions")
    @classmethod
    def require_dimensions(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("persona dimensions must not be empty")
        if len(value) > 10_000:
            raise ValueError("persona dimensions must contain at most 10000 attributes")
        return value


class SemanticPersona(StrictModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=7)]
    persona_id: Identifier
    display_name: DisplayName
    source: Identifier
    profile: PersonaProfile
    profile_sha256: Sha256


class SemanticIntervention(StrictModel):
    id: UUID
    position: Annotated[int, Field(ge=0, le=19)]
    kind: Literal["initial_post"]
    actor: Literal["scenario_actor"]
    channel: Literal["reddit"]
    content: Annotated[RequiredText, Field(max_length=4000)]
    offset_minutes: Annotated[int, Field(ge=0, le=2880)]


class SemanticVariant(StrictModel):
    experiment_position: Annotated[int, Field(ge=0, le=2)]
    role: Literal["baseline", "alternative"]
    id: UUID
    scenario_position: Annotated[int, Field(ge=0, le=5)]
    name: DisplayName
    hypothesis: Annotated[RequiredText, Field(max_length=2000)]
    intervention_count: Annotated[int, Field(ge=0, le=20)]
    interventions: Annotated[tuple[SemanticIntervention, ...], Field(max_length=20)]

    @model_validator(mode="after")
    def validate_role_and_interventions(self) -> Self:
        expected_positions = tuple(range(len(self.interventions)))
        observed_positions = tuple(item.position for item in self.interventions)
        if observed_positions != expected_positions:
            raise ValueError("semantic intervention positions must be contiguous from zero")
        if len(self.interventions) != self.intervention_count:
            raise ValueError("semantic intervention count does not match frozen count")
        if len({item.id for item in self.interventions}) != len(self.interventions):
            raise ValueError("semantic intervention IDs must be unique")
        if self.role == "baseline":
            if self.scenario_position != 0 or self.interventions:
                raise ValueError("semantic baseline must be position zero without interventions")
        elif not 1 <= self.scenario_position <= 5 or not self.interventions:
            raise ValueError("semantic alternative must contain interventions")
        return self


class ScenarioVariantIntegrity(StrictModel):
    id: UUID
    role: Literal["baseline", "alternative"]
    position: Annotated[int, Field(ge=0, le=5)]
    name: DisplayName
    hypothesis: Annotated[RequiredText, Field(max_length=2000)]
    interventions: Annotated[tuple[SemanticIntervention, ...], Field(max_length=20)]

    @model_validator(mode="after")
    def validate_role_and_interventions(self) -> Self:
        positions = tuple(item.position for item in self.interventions)
        if positions != tuple(range(len(self.interventions))):
            raise ValueError("scenario intervention positions must be contiguous from zero")
        if len({item.id for item in self.interventions}) != len(self.interventions):
            raise ValueError("scenario intervention IDs must be unique")
        if self.role == "baseline":
            if self.position != 0 or self.interventions:
                raise ValueError("scenario baseline must be position zero without interventions")
        elif not 1 <= self.position <= 5 or not self.interventions:
            raise ValueError("scenario alternative must contain interventions")
        return self


class ScenarioIntegrityInput(StrictModel):
    id: UUID
    title: Annotated[RequiredText, Field(max_length=300)]
    decision_question: Annotated[RequiredText, Field(max_length=6200)]
    world_model_id: UUID
    world_snapshot_id: UUID
    snapshot_version: Annotated[int, Field(ge=1)]
    snapshot_sha256: Sha256
    snapshot_evidence_count: Annotated[int, Field(ge=1, le=50)]
    scenario_sha256: Sha256
    variants: Annotated[tuple[ScenarioVariantIntegrity, ...], Field(min_length=2, max_length=6)]

    @model_validator(mode="after")
    def validate_variant_order(self) -> Self:
        if tuple(item.position for item in self.variants) != tuple(range(len(self.variants))):
            raise ValueError("scenario variants must be contiguous from zero")
        if self.variants[0].role != "baseline" or any(
            item.role != "alternative" for item in self.variants[1:]
        ):
            raise ValueError("scenario variants must contain baseline then alternatives")
        return self


class DatasetIntegrityInput(StrictModel):
    id: UUID
    slug: Identifier
    display_name: DisplayName
    schema_version: Identifier
    parent_pool: Annotated[RequiredText, Field(max_length=500)] | None
    source_repository: Annotated[RequiredText, Field(max_length=500)] | None
    persona_count: Annotated[int, Field(ge=1, le=1_000_000)]
    manifest_sha256: Sha256
    dataset_sha256: Sha256


class CohortIntegrityInput(StrictModel):
    id: UUID
    dataset_id: UUID
    title: DisplayName
    persona_count: Annotated[int, Field(ge=1, le=8)]
    cohort_sha256: Sha256
    personas: Annotated[tuple[SemanticPersona, ...], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def validate_persona_order(self) -> Self:
        if len(self.personas) != self.persona_count:
            raise ValueError("cohort persona rows do not match frozen persona_count")
        positions = tuple(item.position for item in self.personas)
        if positions != tuple(range(len(self.personas))):
            raise ValueError("cohort persona positions must be contiguous from zero")
        if len({item.id for item in self.personas}) != len(self.personas):
            raise ValueError("cohort personas must be unique")
        return self


class SemanticExperiment(StrictModel):
    id: UUID
    scenario_id: UUID
    scenario_sha256: Sha256
    scenario_title: Annotated[RequiredText, Field(max_length=300)]
    decision_question: Annotated[RequiredText, Field(max_length=24_000)]
    cohort_id: UUID
    cohort_sha256: Sha256
    cohort_title: DisplayName
    dataset_sha256: Sha256
    persona_count: Annotated[int, Field(ge=1, le=8)]
    rounds: Annotated[int, Field(ge=1, le=3)]
    minutes_per_round: Annotated[int, Field(ge=15, le=240)]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-semantic-profile/v1"]
    experiment_sha256: Sha256
    variants: Annotated[tuple[SemanticVariant, ...], Field(min_length=2, max_length=3)]
    seeds: Annotated[
        tuple[Annotated[int, Field(ge=0, le=4_294_967_295)], ...], Field(min_length=1, max_length=2)
    ]

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        if tuple(item.experiment_position for item in self.variants) != tuple(
            range(len(self.variants))
        ):
            raise ValueError("experiment variant positions must be contiguous from zero")
        if self.variants[0].role != "baseline" or any(
            item.role != "alternative" for item in self.variants[1:]
        ):
            raise ValueError("experiment variants must contain baseline then alternatives")
        if self.seeds != tuple(sorted(set(self.seeds))):
            raise ValueError("experiment seeds must be unique and ascending")
        budget = len(self.variants) * len(self.seeds) * self.rounds * self.persona_count
        if budget > 96:
            raise ValueError("semantic experiment exceeds the 96-action matrix budget")
        maximum_offset = self.rounds * self.minutes_per_round
        if any(
            intervention.offset_minutes > maximum_offset
            for variant in self.variants
            for intervention in variant.interventions
        ):
            raise ValueError("semantic intervention offset exceeds experiment duration")
        return self


class ClaimedSemanticTrial(StrictModel):
    id: UUID
    status: Literal["running"]
    created_at: datetime
    experiment: SemanticExperiment
    variant_position: Annotated[int, Field(ge=0, le=2)]
    variant_role: Literal["baseline", "alternative"]
    scenario_variant_id: UUID
    scenario_position: Annotated[int, Field(ge=0, le=5)]
    variant_name: DisplayName
    variant_hypothesis: Annotated[RequiredText, Field(max_length=2000)]
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    trial_sha256: Sha256
    scenario: ScenarioIntegrityInput
    dataset: DatasetIntegrityInput
    cohort: CohortIntegrityInput

    @model_validator(mode="after")
    def validate_selected_variant(self) -> Self:
        selected = self.experiment.variants[self.variant_position]
        if (
            selected.role != self.variant_role
            or selected.id != self.scenario_variant_id
            or selected.scenario_position != self.scenario_position
            or selected.name != self.variant_name
            or selected.hypothesis != self.variant_hypothesis
        ):
            raise ValueError("trial variant does not match its frozen experiment variant")
        if self.seed not in self.experiment.seeds:
            raise ValueError("trial seed is absent from its experiment matrix")
        return self

    @property
    def selected_variant(self) -> SemanticVariant:
        return self.experiment.variants[self.variant_position]


class SocialSimulationExecution(StrictModel):
    """SandOwl-native input consumed by the shared OASIS social simulation core."""

    id: UUID
    context_id: UUID
    context_kind: Literal["semantic_experiment", "research_project"]
    decision_question: Annotated[RequiredText, Field(max_length=24_000)]
    actor_user_name: Identifier
    actor_name: DisplayName
    actor_bio: Annotated[RequiredText, Field(max_length=500)]
    seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    rounds: Annotated[int, Field(ge=1, le=6)]
    minutes_per_round: Annotated[int, Field(ge=15, le=480)]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-semantic-profile/v1"]
    initial_posts: Annotated[tuple[SemanticIntervention, ...], Field(max_length=20)]
    cohort: CohortIntegrityInput

    @model_validator(mode="after")
    def validate_initial_posts(self) -> Self:
        if tuple(item.position for item in self.initial_posts) != tuple(
            range(len(self.initial_posts))
        ):
            raise ValueError("initial post positions must be contiguous from zero")
        horizon = self.rounds * self.minutes_per_round
        if any(item.offset_minutes > horizon for item in self.initial_posts):
            raise ValueError("initial post offset exceeds simulation duration")
        return self


class SemanticEvent(StrictModel):
    round: Annotated[int, Field(ge=1, le=6)]
    phase: Literal["intervention", "audience"]
    actor_kind: Literal["scenario", "persona"]
    persona_id: UUID | None
    agent_position: Annotated[int, Field(ge=0, le=8)]
    action_type: ActionTypeName
    content: Annotated[RequiredText, Field(max_length=4000)] | None
    post_id: Annotated[RequiredText, Field(max_length=128)] | None
    comment_id: Annotated[RequiredText, Field(max_length=128)] | None
    target_post_id: Annotated[RequiredText, Field(max_length=128)] | None
    observed_at_raw: Annotated[RequiredText, Field(max_length=200)]

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.phase == "intervention":
            if self.actor_kind != "scenario" or self.persona_id is not None:
                raise ValueError("intervention events require the scenario actor")
            if self.action_type != "create_post":
                raise ValueError("interventions may only create posts")
        elif self.actor_kind != "persona" or self.persona_id is None:
            raise ValueError("audience events require one persona actor")
        if self.action_type == "create_post":
            if self.content is None or self.post_id is None:
                raise ValueError("create_post requires content and post_id")
            if self.comment_id is not None or self.target_post_id is not None:
                raise ValueError("create_post forbids comment and target identifiers")
        elif self.action_type == "create_comment":
            if self.content is None or self.comment_id is None or self.target_post_id is None:
                raise ValueError("create_comment requires content, comment_id, and target_post_id")
            if self.post_id is not None:
                raise ValueError("create_comment forbids post_id")
        elif self.action_type in {"like_post", "dislike_post"}:
            if self.target_post_id is None:
                raise ValueError("post reactions require target_post_id")
            if self.content is not None or self.post_id is not None or self.comment_id is not None:
                raise ValueError("post reactions forbid content and authored identifiers")
        elif any(
            value is not None
            for value in (self.content, self.post_id, self.comment_id, self.target_post_id)
        ):
            raise ValueError("do_nothing forbids content and target identifiers")
        if "\r" in self.observed_at_raw or "\n" in self.observed_at_raw:
            raise ValueError("observed_at_raw must be single-line")
        return self


class SemanticSuccess(StrictModel):
    engine_version: Literal["0.2.5"]
    camel_version: Literal["0.2.78"]
    model_name: Annotated[RequiredText, Field(max_length=200)]
    semantic_config_sha256: Sha256
    prompt_schema_version: Literal["matraix-semantic-profile/v1"]
    artifact_sha256: Sha256
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    user_count: Annotated[int, Field(ge=2, le=9)]
    initial_post_count: Annotated[int, Field(ge=0, le=20)]
    generated_post_count: Annotated[int, Field(ge=0, le=48)]
    comment_count: Annotated[int, Field(ge=0, le=48)]
    reaction_count: Annotated[int, Field(ge=0, le=48)]
    do_nothing_count: Annotated[int, Field(ge=0, le=48)]
    observed_action_count: Annotated[int, Field(ge=1, le=116)]
    rounds_completed: Annotated[int, Field(ge=1, le=6)]
    limitations: Annotated[tuple[RequiredText, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        expected = (
            self.initial_post_count
            + self.generated_post_count
            + self.comment_count
            + self.reaction_count
            + self.do_nothing_count
        )
        if self.observed_action_count != expected:
            raise ValueError("semantic observed action count does not equal typed event counts")
        return self
