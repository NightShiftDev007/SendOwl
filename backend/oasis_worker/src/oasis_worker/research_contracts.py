"""Worker-only envelope for one independent SandOwl research run."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from oasis_worker.contracts import RequiredText, Sha256, StrictModel
from oasis_worker.semantic_contracts import SocialSimulationExecution


class ResearchGraphRef(StrictModel):
    graph_id: UUID
    graph_sha256: Sha256
    node_count: Annotated[int, Field(ge=1, le=500)]
    edge_count: Annotated[int, Field(ge=0, le=2000)]


class ResearchContextMediaItem(StrictModel):
    position: Annotated[int, Field(ge=0, le=9)]
    article_id: UUID
    title: Annotated[RequiredText, Field(max_length=1000)]
    source_name: Annotated[RequiredText, Field(max_length=500)]
    excerpt: Annotated[RequiredText, Field(max_length=1000)]


class ResearchContextPolicyItem(StrictModel):
    position: Annotated[int, Field(ge=0, le=9)]
    policy_version_id: UUID
    title: Annotated[RequiredText, Field(max_length=1000)]
    authority_name: Annotated[RequiredText, Field(max_length=500)]
    jurisdiction_code: Annotated[
        str,
        StringConstraints(min_length=2, max_length=16, strict=True),
    ]


class ResearchContextNode(StrictModel):
    position: Annotated[int, Field(ge=0, le=19)]
    node_id: UUID
    entity_type: Annotated[RequiredText, Field(max_length=32)]
    name: Annotated[RequiredText, Field(max_length=200)]
    summary: Annotated[RequiredText, Field(max_length=500)]
    evidence_quote: Annotated[RequiredText, Field(max_length=500)]


class ResearchContextEdge(StrictModel):
    position: Annotated[int, Field(ge=0, le=29)]
    edge_id: UUID
    source_name: Annotated[RequiredText, Field(max_length=200)]
    relation_type: Annotated[RequiredText, Field(max_length=64)]
    target_name: Annotated[RequiredText, Field(max_length=200)]
    fact: Annotated[RequiredText, Field(max_length=500)]
    evidence_quote: Annotated[RequiredText, Field(max_length=500)]


class ResearchSimulationContext(StrictModel):
    schema_version: Literal["sandowl-simulation-context/v1"]
    snapshot_sha256: Sha256
    graph: ResearchGraphRef
    media_items: Annotated[tuple[ResearchContextMediaItem, ...], Field(min_length=1, max_length=10)]
    policy_items: Annotated[tuple[ResearchContextPolicyItem, ...], Field(max_length=10)]
    nodes: Annotated[tuple[ResearchContextNode, ...], Field(min_length=1, max_length=20)]
    edges: Annotated[tuple[ResearchContextEdge, ...], Field(max_length=30)]
    total_media_count: Annotated[int, Field(ge=1, le=50)]
    total_policy_count: Annotated[int, Field(ge=0, le=50)]
    total_node_count: Annotated[int, Field(ge=1, le=500)]
    total_edge_count: Annotated[int, Field(ge=0, le=2000)]
    truncated: bool

    @model_validator(mode="after")
    def validate_positions_and_counts(self) -> Self:
        collections = (self.media_items, self.policy_items, self.nodes, self.edges)
        if any(
            tuple(item.position for item in collection) != tuple(range(len(collection)))
            for collection in collections
        ):
            raise ValueError("simulation context positions must be contiguous from zero")
        if (
            len(self.media_items) > self.total_media_count
            or len(self.policy_items) > self.total_policy_count
            or len(self.nodes) > self.total_node_count
            or len(self.edges) > self.total_edge_count
        ):
            raise ValueError("simulation context selected counts exceed frozen totals")
        return self


class ResearchScheduledPost(StrictModel):
    position: Annotated[int, Field(ge=0, le=5)]
    content: Annotated[RequiredText, Field(max_length=4000)]
    offset_minutes: Annotated[int, Field(ge=0, le=2880)]
    source: Literal["user_synthetic"]


class ResearchSimulationPlan(StrictModel):
    schema_version: Literal["sandowl-simulation-plan/v1"]
    planning_mode: Literal["manual", "automatic"]
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
    def validate_schedule(self) -> Self:
        if self.horizon_minutes != self.rounds * self.minutes_per_round:
            raise ValueError("simulation plan horizon mismatch")
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


class ResearchRunMemoryNode(StrictModel):
    position: Annotated[int, Field(ge=0, le=127)]
    key: Annotated[RequiredText, Field(max_length=200)]
    kind: Literal["scenario", "persona", "post", "comment"]
    label: Annotated[RequiredText, Field(max_length=500)]


class ResearchRunMemoryEdge(StrictModel):
    position: Annotated[int, Field(ge=0, le=127)]
    sequence: Annotated[int, Field(ge=1)]
    source_key: Annotated[RequiredText, Field(max_length=200)]
    relation: Literal["authored", "commented_on", "liked", "disliked"]
    target_key: Annotated[RequiredText, Field(max_length=200)]


class ResearchRunGraphMemoryState(StrictModel):
    schema_version: Literal["sandowl-run-graph-memory/v1"]
    run_spec_sha256: Sha256
    round: Annotated[int, Field(ge=1, le=6)]
    previous_sha256: Sha256 | None
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


class ClaimedResearchRun(StrictModel):
    run_spec_sha256: Sha256
    execution: SocialSimulationExecution
