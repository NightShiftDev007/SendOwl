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


def derive_company_actor_user_name(world_snapshot_id: UUID, company_name: str) -> str:
    """Derive one stable privacy-neutral platform handle from frozen company identity."""
    material = f"{world_snapshot_id}\0{company_name}".encode()
    return f"company_{sha256(material).hexdigest()[:16]}"


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
        company_name=scenario.snapshot.company_name,
    )
    posts = tuple(
        PlatformSmokePost(
            position=intervention.position,
            content=intervention.content,
            offset_minutes=intervention.offset_minutes,
        )
        for intervention in alternative.interventions
    )
    company_name = scenario.snapshot.company_name
    return CompiledPlatformSmokeInput(
        mode="reddit_manual_smoke",
        scenario=scenario_ref,
        seed=seed,
        actor_user_name=derive_company_actor_user_name(
            scenario.snapshot.world_snapshot_id,
            company_name,
        ),
        actor_name=company_name[:200],
        actor_bio=(
            f"Frozen company actor from WorldSnapshot {scenario.snapshot.world_snapshot_id}. "
            "Manual OASIS platform smoke only."
        ),
        posts=posts,
    )
