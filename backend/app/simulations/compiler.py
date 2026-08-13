"""Pure compilation from immutable Scenarios to OASIS platform-smoke input."""

from hashlib import sha256
from uuid import UUID

from app.scenarios.contracts import ScenarioDetail, ScenarioVariant
from app.simulations.contracts import (
    CompiledPlatformSmokeInput,
    PlatformSmokePost,
    PlatformSmokeScenarioRef,
)
from app.simulations.errors import baseline_variant_error, unknown_variant_error


def _scenario_actor_digest(scenario_id: UUID, variant_id: UUID) -> str:
    return sha256(f"{scenario_id}\0{variant_id}".encode()).hexdigest()[:16]


def derive_scenario_actor_user_name(scenario_id: UUID, variant_id: UUID) -> str:
    """Derive a stable privacy-neutral handle from the immutable scenario path."""
    return f"scenario_{_scenario_actor_digest(scenario_id, variant_id)}"


def derive_scenario_actor_name(scenario_id: UUID, variant_id: UUID) -> str:
    """Derive a stable display name from the immutable scenario path."""
    return f"Scenario actor {_scenario_actor_digest(scenario_id, variant_id)}"


def derive_scenario_actor_bio(scenario_id: UUID, variant_id: UUID) -> str:
    """Describe the synthetic actor's exact immutable source."""
    return (
        f"Synthetic actor compiled from Scenario {scenario_id} variant {variant_id}. "
        "Manual OASIS platform smoke only."
    )


def _selected_alternative(scenario: ScenarioDetail, variant_id: UUID) -> ScenarioVariant:
    if scenario.baseline.id == variant_id:
        raise baseline_variant_error(scenario.id, variant_id)
    selected = next((item for item in scenario.alternatives if item.id == variant_id), None)
    if selected is None:
        raise unknown_variant_error(scenario.id, variant_id)
    return selected


def compile_platform_smoke_input(
    scenario: ScenarioDetail,
    variant_id: UUID,
    seed: int,
) -> CompiledPlatformSmokeInput:
    """Copy one sealed alternative into a deterministic, key-free worker input."""
    alternative = _selected_alternative(scenario, variant_id)
    scenario_ref = PlatformSmokeScenarioRef(
        id=scenario.id,
        scenario_sha256=scenario.scenario_sha256,
        variant_id=alternative.id,
        variant_name=alternative.name,
        world_snapshot_id=scenario.snapshot.world_snapshot_id,
        snapshot_sha256=scenario.snapshot.snapshot_sha256,
    )
    posts = tuple(
        PlatformSmokePost(
            position=intervention.position,
            content=intervention.content,
            offset_minutes=intervention.offset_minutes,
        )
        for intervention in alternative.interventions
    )
    return CompiledPlatformSmokeInput(
        mode="reddit_manual_smoke",
        scenario=scenario_ref,
        seed=seed,
        actor_user_name=derive_scenario_actor_user_name(scenario.id, alternative.id),
        actor_name=derive_scenario_actor_name(scenario.id, alternative.id),
        actor_bio=derive_scenario_actor_bio(scenario.id, alternative.id),
        posts=posts,
    )
