"""Deterministic, auditable planning for native research simulation runs."""

import json
from hashlib import sha256
from math import ceil

from app.research_projects.contracts import (
    ResearchScheduledPost,
    ResearchSimulationPlan,
    ResearchSimulationRunCreateRequest,
)

_AUTOMATIC_ROUNDS = {"low": 2, "standard": 3, "high": 6}


def compile_simulation_plan(
    request: ResearchSimulationRunCreateRequest,
    context_item_count: int,
    persona_count: int,
) -> ResearchSimulationPlan:
    """Compile one bounded schedule without inventing event content."""
    if request.planning_mode == "manual":
        if request.rounds is None or request.minutes_per_round is None:
            raise ValueError("manual planning inputs are incomplete")
        rounds = request.rounds
        minutes_per_round = request.minutes_per_round
        planner_version = "manual/v1"
        activity_intensity = "manual"
    else:
        if request.time_horizon_minutes is None or request.activity_intensity is None:
            raise ValueError("automatic planning inputs are incomplete")
        context_round = 1 if context_item_count < 12 else 2
        audience_round = 1 if persona_count <= 4 else 2
        minimum_rounds = max(
            _AUTOMATIC_ROUNDS[request.activity_intensity],
            context_round + audience_round,
        )
        rounds = max(minimum_rounds, ceil(request.time_horizon_minutes / 480))
        rounds = min(rounds, 6)
        minutes_per_round = ceil(request.time_horizon_minutes / rounds)
        minutes_per_round = max(15, min(minutes_per_round, 480))
        planner_version = "deterministic-context-planner/v1"
        activity_intensity = request.activity_intensity

    horizon_minutes = rounds * minutes_per_round
    scheduled_posts = (
        ResearchScheduledPost(
            position=0,
            content=request.initial_post,
            offset_minutes=0,
            source="user_synthetic",
        ),
        *tuple(
            ResearchScheduledPost(
                position=position,
                content=item.content,
                offset_minutes=item.offset_minutes,
                source="user_synthetic",
            )
            for position, item in enumerate(request.scheduled_posts, start=1)
        ),
    )
    if scheduled_posts[-1].offset_minutes > horizon_minutes:
        raise ValueError(
            "the latest scheduled post exceeds the compiled simulation horizon; "
            "increase the observation duration or move the post earlier"
        )
    return ResearchSimulationPlan(
        schema_version="sandowl-simulation-plan/v1",
        planning_mode=request.planning_mode,
        planner_version=planner_version,
        platform="reddit",
        activity_intensity=activity_intensity,
        context_item_count=context_item_count,
        persona_count=persona_count,
        rounds=rounds,
        minutes_per_round=minutes_per_round,
        horizon_minutes=horizon_minutes,
        scheduled_posts=scheduled_posts,
    )


def canonical_simulation_plan_json(plan: ResearchSimulationPlan) -> str:
    return json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_simulation_plan_sha256(plan: ResearchSimulationPlan) -> str:
    return sha256(canonical_simulation_plan_json(plan).encode("utf-8")).hexdigest()


__all__ = [
    "calculate_simulation_plan_sha256",
    "canonical_simulation_plan_json",
    "compile_simulation_plan",
]
