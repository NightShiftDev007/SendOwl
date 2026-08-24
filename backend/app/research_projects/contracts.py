"""Strict contracts for research projects and independent simulation runs."""

from typing import Annotated, Literal, Self
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

type ResearchProjectTitle = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=300,
        pattern=r"^[^\r\n]+$",
        strip_whitespace=True,
    ),
]
type ResearchQuestion = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
]
type SimulationRequirement = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type SimulationSeed = Annotated[int, Field(ge=0, le=2_147_483_647)]
type ResearchSimulationRunStatus = Literal["configured", "queued", "running", "succeeded", "failed"]
type ResearchRunInitialPost = Annotated[
    str,
    StringConstraints(min_length=1, max_length=4000, strip_whitespace=True),
]
type ResearchRunPlanningMode = Literal["manual", "automatic"]
type ResearchRunActivityIntensity = Literal["low", "standard", "high"]


def _request_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UUID string; received {type(value).__name__}")
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a valid UUID string; received {value!r}") from error


class ResearchProjectRequestModel(ContractModel):
    """Request boundary that rejects unspecified product concepts."""

    model_config = ConfigDict(extra="forbid")


class ResearchProjectCreateRequest(ResearchProjectRequestModel):
    """Seal one Project / Graph context before population and run design."""

    title: ResearchProjectTitle
    research_question: ResearchQuestion
    world_model_id: UUID
    world_snapshot_id: UUID
    world_graph_id: UUID

    @field_validator("world_model_id", "world_snapshot_id", "world_graph_id", mode="before")
    @classmethod
    def parse_resource_id(cls, value: object, info) -> UUID:
        return _request_uuid(value, info.field_name)


class ResearchProjectSnapshotRef(ContractModel):
    """Frozen AgendaScope evidence context reused from an existing snapshot."""

    world_model_id: UUID
    world_snapshot_id: UUID
    snapshot_sha256: Sha256Digest


class ResearchProjectGraphRef(ContractModel):
    """Exact immutable semantic graph bound to one research project."""

    graph_id: UUID
    graph_sha256: Sha256Digest
    node_count: Annotated[int, Field(ge=1, le=500)]
    edge_count: Annotated[int, Field(ge=0, le=2000)]


class ResearchProjectCohortRef(ContractModel):
    """Frozen population identity bound to one simulation requirement."""

    cohort_id: UUID
    cohort_sha256: Sha256Digest
    persona_count: Annotated[int, Field(ge=1, le=100)]


class LegacyResearchProjectDesign(ContractModel):
    """Read-only projection of the v1 project-level run design."""

    cohort: ResearchProjectCohortRef
    simulation_requirement: SimulationRequirement


class ResearchProjectDetail(ContractModel):
    """Content-addressed Project / Graph context."""

    id: UUID
    title: ResearchProjectTitle
    research_question: ResearchQuestion
    snapshot: ResearchProjectSnapshotRef
    graph: ResearchProjectGraphRef | None
    schema_version: Literal[
        "sandowl-research-project/v1",
        "sandowl-research-project/v2",
        "sandowl-research-project/v3",
    ]
    legacy_design: LegacyResearchProjectDesign | None
    project_sha256: Sha256Digest
    created_at: AwareDatetime


class ResearchAgendaSnapshot(ContractModel):
    country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    window_start: AwareDatetime
    window_end: AwareDatetime
    granularity: Literal["hour", "day", "week"]
    article_count: Annotated[int, Field(ge=0)]
    salience_score: Annotated[float, Field(ge=0)]
    salience_rank: Annotated[int, Field(ge=1)]


class ResearchAgendaPropagationEdge(ContractModel):
    position: Annotated[int, Field(ge=0)]
    from_country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    to_country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    lag_hours: Annotated[float, Field(ge=0)]
    first_media_name: str | None
    first_article_id: UUID | None
    first_published_at: AwareDatetime | None
    observation_source: Literal["legacy_projection", "structured_followers", "native_collection"]


class ResearchAgendaPropagationEvent(ContractModel):
    id: UUID
    status: Literal["watching", "suspected", "confirmed", "dismissed", "revised", "archived"]
    confidence: Literal["watching", "suspected", "confirmed"]
    origin_country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    origin_source_name: str | None
    origin_at: AwareDatetime
    origin_confidence: Literal["high", "medium", "low"]
    detection_method: str
    edges: Annotated[tuple[ResearchAgendaPropagationEdge, ...], Field(max_length=20)]


class ResearchAgendaFirstUtterance(ContractModel):
    id: UUID
    entity_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    entity_type: Literal["person", "thinktank", "intl_org", "gov_body"]
    country_code: Annotated[str, StringConstraints(min_length=2, max_length=2)]
    article_id: UUID
    occurred_at: AwareDatetime | None
    evidence_quote: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    model_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    prompt_version: Annotated[str, StringConstraints(min_length=1, max_length=100)]


class ResearchAgendaTopic(ContractModel):
    id: UUID
    name: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    summary: str | None
    category: str | None
    status: Literal["emerging", "heating", "stable", "declining", "archived"]
    lifecycle_state: Literal["nascent", "forming", "confirmed", "evolving", "archived"]
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    linked_article_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=50)]
    salience: Annotated[tuple[ResearchAgendaSnapshot, ...], Field(max_length=24)]
    propagation: Annotated[tuple[ResearchAgendaPropagationEvent, ...], Field(max_length=10)]
    first_utterances: Annotated[tuple[ResearchAgendaFirstUtterance, ...], Field(max_length=10)]


class ResearchProjectAgendaPayload(ContractModel):
    schema_version: Literal["sandowl-project-agenda-context/v1"]
    snapshot_sha256: Sha256Digest
    frozen_article_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=50)]
    topics: Annotated[tuple[ResearchAgendaTopic, ...], Field(max_length=50)]
    source_sync_run_id: UUID | None
    source_observed_at: AwareDatetime | None
    limitations: Annotated[tuple[str, ...], Field(min_length=1)]


class ResearchProjectAgendaContext(ContractModel):
    project_id: UUID
    project_sha256: Sha256Digest
    payload: ResearchProjectAgendaPayload
    context_sha256: Sha256Digest
    captured_at: AwareDatetime


class ResearchProjectsResponse(ContractModel):
    """Complete research-project directory."""

    items: tuple[ResearchProjectDetail, ...]
    total: Annotated[int, Field(ge=0)]


class ResearchSimulationRunCreateRequest(ResearchProjectRequestModel):
    """Bind one population and requirement, then queue one independent run."""

    cohort_id: UUID
    simulation_requirement: SimulationRequirement
    seed: SimulationSeed
    planning_mode: ResearchRunPlanningMode = "manual"
    rounds: Annotated[int, Field(ge=1, le=6)] | None = None
    minutes_per_round: Annotated[int, Field(ge=15, le=480)] | None = None
    time_horizon_minutes: Annotated[int, Field(ge=60, le=2880)] | None = None
    activity_intensity: ResearchRunActivityIntensity | None = None
    initial_post: ResearchRunInitialPost
    scheduled_posts: Annotated[
        tuple["ResearchScheduledPostRequest", ...],
        Field(max_length=5),
    ] = ()

    @field_validator("cohort_id", mode="before")
    @classmethod
    def parse_cohort_id(cls, value: object) -> UUID:
        return _request_uuid(value, "cohort_id")

    @field_validator("scheduled_posts", mode="before")
    @classmethod
    def parse_scheduled_posts(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_planning_inputs(self):
        if self.planning_mode == "manual":
            if self.rounds is None or self.minutes_per_round is None:
                raise ValueError("manual planning requires rounds and minutes_per_round")
            if self.time_horizon_minutes is not None or self.activity_intensity is not None:
                raise ValueError("manual planning does not accept automatic planning inputs")
        elif (
            self.rounds is not None
            or self.minutes_per_round is not None
            or self.time_horizon_minutes is None
            or self.activity_intensity is None
        ):
            raise ValueError(
                "automatic planning requires time_horizon_minutes and activity_intensity only"
            )
        offsets = tuple(item.offset_minutes for item in self.scheduled_posts)
        if offsets != tuple(sorted(set(offsets))):
            raise ValueError("scheduled post offsets must be unique and ascending")
        return self


class ResearchScheduledPostRequest(ResearchProjectRequestModel):
    """One explicitly authored synthetic update scheduled after the initial post."""

    content: ResearchRunInitialPost
    offset_minutes: Annotated[int, Field(ge=15, le=2880)]


class ResearchScheduledPost(ContractModel):
    position: Annotated[int, Field(ge=0, le=5)]
    content: ResearchRunInitialPost
    offset_minutes: Annotated[int, Field(ge=0, le=2880)]
    source: Literal["user_synthetic"]


class ResearchSimulationPlan(ContractModel):
    """Auditable platform schedule compiled without an additional model call."""

    schema_version: Literal["sandowl-simulation-plan/v1"]
    planning_mode: ResearchRunPlanningMode
    planner_version: Literal["manual/v1", "deterministic-context-planner/v1"]
    platform: Literal["reddit"]
    activity_intensity: Literal["manual", "low", "standard", "high"]
    context_item_count: Annotated[int, Field(ge=1, le=2550)]
    persona_count: Annotated[int, Field(ge=1, le=8)]
    rounds: Annotated[int, Field(ge=1, le=6)]
    minutes_per_round: Annotated[int, Field(ge=15, le=480)]
    horizon_minutes: Annotated[int, Field(ge=15, le=2880)]
    scheduled_posts: Annotated[tuple[ResearchScheduledPost, ...], Field(min_length=1, max_length=6)]

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.horizon_minutes != self.rounds * self.minutes_per_round:
            raise ValueError("simulation plan horizon must equal rounds times minutes_per_round")
        if tuple(item.position for item in self.scheduled_posts) != tuple(
            range(len(self.scheduled_posts))
        ):
            raise ValueError("scheduled post positions must be contiguous from zero")
        if self.scheduled_posts[0].offset_minutes != 0:
            raise ValueError("the first scheduled post must start at minute zero")
        offsets = tuple(item.offset_minutes for item in self.scheduled_posts)
        if offsets != tuple(sorted(set(offsets))):
            raise ValueError("scheduled post offsets must be unique and ascending")
        if offsets[-1] > self.horizon_minutes:
            raise ValueError("scheduled post offset exceeds the simulation horizon")
        return self


class ResearchSimulationRunResult(ContractModel):
    """Verified facts derived from one OASIS artifact and its typed events."""

    artifact_sha256: Sha256Digest
    artifact_size_bytes: Annotated[int, Field(gt=0)]
    user_count: Annotated[int, Field(ge=2, le=9)]
    initial_post_count: Annotated[int, Field(ge=1, le=6)]
    generated_post_count: Annotated[int, Field(ge=0)]
    comment_count: Annotated[int, Field(ge=0)]
    reaction_count: Annotated[int, Field(ge=0)]
    do_nothing_count: Annotated[int, Field(ge=0)]
    observed_action_count: Annotated[int, Field(ge=1)]
    rounds_completed: Annotated[int, Field(ge=1, le=6)]
    limitations: Annotated[tuple[str, ...], Field(min_length=1)]


class ResearchSimulationRunError(ContractModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class SimulationContextMediaItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=9)]
    article_id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    source_name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    excerpt: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class SimulationContextPolicyItem(ContractModel):
    position: Annotated[int, Field(ge=0, le=9)]
    policy_version_id: UUID
    title: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    authority_name: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    jurisdiction_code: Annotated[str, StringConstraints(min_length=2, max_length=16)]


class SimulationContextNode(ContractModel):
    position: Annotated[int, Field(ge=0, le=19)]
    node_id: UUID
    entity_type: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    evidence_quote: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class SimulationContextEdge(ContractModel):
    position: Annotated[int, Field(ge=0, le=29)]
    edge_id: UUID
    source_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    relation_type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    target_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    fact: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    evidence_quote: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ResearchSimulationContext(ContractModel):
    """Bounded reality context compiled from one exact snapshot and semantic graph."""

    schema_version: Literal["sandowl-simulation-context/v1"]
    snapshot_sha256: Sha256Digest
    graph: ResearchProjectGraphRef
    media_items: Annotated[
        tuple[SimulationContextMediaItem, ...],
        Field(min_length=1, max_length=10),
    ]
    policy_items: Annotated[tuple[SimulationContextPolicyItem, ...], Field(max_length=10)]
    nodes: Annotated[tuple[SimulationContextNode, ...], Field(min_length=1, max_length=20)]
    edges: Annotated[tuple[SimulationContextEdge, ...], Field(max_length=30)]
    total_media_count: Annotated[int, Field(ge=1, le=50)]
    total_policy_count: Annotated[int, Field(ge=0, le=50)]
    total_node_count: Annotated[int, Field(ge=1, le=500)]
    total_edge_count: Annotated[int, Field(ge=0, le=2000)]
    truncated: bool


class ResearchSimulationRunDetail(ContractModel):
    """One independently queued or completed run without comparison semantics."""

    id: UUID
    research_project_id: UUID
    project_sha256: Sha256Digest
    schema_version: Literal[
        "sandowl-research-simulation-run/v1",
        "sandowl-research-simulation-run/v2",
        "sandowl-research-simulation-run/v3",
        "sandowl-research-simulation-run/v4",
    ]
    cohort: ResearchProjectCohortRef
    simulation_requirement: SimulationRequirement
    seed: SimulationSeed
    rounds: Annotated[int, Field(ge=1, le=6)] | None
    minutes_per_round: Annotated[int, Field(ge=15, le=480)] | None
    initial_post: ResearchRunInitialPost | None
    engine: Literal["camel-oasis"]
    engine_version: Literal["0.2.5"]
    model_name: str | None
    semantic_config_sha256: Sha256Digest | None
    prompt_schema_version: Literal["matraix-semantic-profile/v1"] | None
    simulation_context: ResearchSimulationContext | None
    simulation_context_sha256: Sha256Digest | None
    simulation_plan: ResearchSimulationPlan | None
    simulation_plan_sha256: Sha256Digest | None
    status: ResearchSimulationRunStatus
    run_spec_sha256: Sha256Digest
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    result: ResearchSimulationRunResult | None
    error: ResearchSimulationRunError | None


class ResearchRunEvent(ContractModel):
    sequence: Annotated[int, Field(ge=1)]
    round: Annotated[int, Field(ge=1, le=6)]
    phase: Literal["intervention", "audience"]
    actor_kind: Literal["scenario", "persona"]
    persona_id: UUID | None
    agent_position: Annotated[int, Field(ge=0, le=8)]
    action_type: Literal["create_post", "create_comment", "like_post", "dislike_post", "do_nothing"]
    content: str | None
    post_id: str | None
    comment_id: str | None
    target_post_id: str | None
    observed_at_raw: str
    recorded_at: AwareDatetime


class ResearchRunEventsResponse(ContractModel):
    items: tuple[ResearchRunEvent, ...]
    total: Annotated[int, Field(ge=0)]


class ResearchRunMemoryNode(ContractModel):
    position: Annotated[int, Field(ge=0, le=127)]
    key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    kind: Literal["scenario", "persona", "post", "comment"]
    label: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ResearchRunMemoryEdge(ContractModel):
    position: Annotated[int, Field(ge=0, le=127)]
    sequence: Annotated[int, Field(ge=1)]
    source_key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    relation: Literal["authored", "commented_on", "liked", "disliked"]
    target_key: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ResearchRunGraphMemoryState(ContractModel):
    schema_version: Literal["sandowl-run-graph-memory/v1"]
    run_spec_sha256: Sha256Digest
    round: Annotated[int, Field(ge=1, le=6)]
    previous_sha256: Sha256Digest | None
    cumulative_event_count: Annotated[int, Field(ge=1, le=54)]
    nodes: Annotated[tuple[ResearchRunMemoryNode, ...], Field(min_length=1, max_length=128)]
    edges: Annotated[tuple[ResearchRunMemoryEdge, ...], Field(max_length=128)]

    @model_validator(mode="after")
    def validate_positions(self) -> Self:
        if tuple(item.position for item in self.nodes) != tuple(range(len(self.nodes))):
            raise ValueError("graph memory node positions must be contiguous from zero")
        if tuple(item.position for item in self.edges) != tuple(range(len(self.edges))):
            raise ValueError("graph memory edge positions must be contiguous from zero")
        if (self.round == 1) != (self.previous_sha256 is None):
            raise ValueError("graph memory previous digest does not match its round")
        return self


class ResearchRunGraphMemorySnapshot(ResearchRunGraphMemoryState):
    memory_sha256: Sha256Digest
    created_at: AwareDatetime


class ResearchRunGraphMemoryResponse(ContractModel):
    items: Annotated[tuple[ResearchRunGraphMemorySnapshot, ...], Field(max_length=6)]
    total: Annotated[int, Field(ge=0, le=6)]


class ResearchRunReport(ContractModel):
    """Deterministic single-run report; it never ranks or compares alternatives."""

    id: UUID
    research_project: ResearchProjectDetail
    run: ResearchSimulationRunDetail
    events: tuple[ResearchRunEvent, ...]
    graph_memory: tuple[ResearchRunGraphMemorySnapshot, ...]
    report_sha256: Sha256Digest
    created_at: AwareDatetime


class ResearchRunReportSummary(ContractModel):
    """Directory projection for one sealed native single-run report."""

    id: UUID
    research_project: ResearchProjectDetail
    run: ResearchSimulationRunDetail
    report_sha256: Sha256Digest
    created_at: AwareDatetime


class ResearchRunReportsResponse(ContractModel):
    """Native single-run reports ordered by newest first."""

    items: tuple[ResearchRunReportSummary, ...]
    total: Annotated[int, Field(ge=0)]


class ResearchSimulationRunsResponse(ContractModel):
    """Runs configured for one research project."""

    items: tuple[ResearchSimulationRunDetail, ...]
    total: Annotated[int, Field(ge=0)]


__all__ = [
    "LegacyResearchProjectDesign",
    "ResearchProjectCohortRef",
    "ResearchProjectCreateRequest",
    "ResearchProjectDetail",
    "ResearchProjectAgendaContext",
    "ResearchProjectGraphRef",
    "ResearchProjectSnapshotRef",
    "ResearchProjectsResponse",
    "ResearchSimulationRunCreateRequest",
    "ResearchSimulationRunDetail",
    "ResearchSimulationRunError",
    "ResearchSimulationRunResult",
    "ResearchSimulationRunsResponse",
    "ResearchRunEvent",
    "ResearchRunEventsResponse",
    "ResearchRunGraphMemoryResponse",
    "ResearchRunGraphMemorySnapshot",
    "ResearchRunGraphMemoryState",
    "ResearchRunReport",
    "ResearchRunReportSummary",
    "ResearchRunReportsResponse",
    "ResearchSimulationContext",
    "ResearchSimulationPlan",
    "ResearchScheduledPost",
    "ResearchScheduledPostRequest",
]
