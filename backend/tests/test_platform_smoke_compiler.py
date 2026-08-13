"""Pure compilation and content-address tests for OASIS platform-smoke input."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.scenarios.contracts import (
    Intervention,
    ScenarioDetail,
    ScenarioSnapshotRef,
    ScenarioVariant,
)
from app.simulations.compiler import compile_platform_smoke_input
from app.simulations.errors import PlatformSmokeVariantError
from app.simulations.hashing import calculate_platform_smoke_input_sha256

SCENARIO_ID = UUID("11111111-1111-4111-8111-111111111111")
BASELINE_ID = UUID("22222222-2222-4222-8222-222222222222")
ALTERNATIVE_ID = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT_ID = UUID("44444444-4444-4444-8444-444444444444")


def _scenario() -> ScenarioDetail:
    return ScenarioDetail(
        id=SCENARIO_ID,
        title="Response decision",
        decision_question="Publish the verified statement?",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        scenario_sha256="a" * 64,
        snapshot=ScenarioSnapshotRef(
            world_model_id=UUID("55555555-5555-4555-8555-555555555555"),
            world_snapshot_id=SNAPSHOT_ID,
            version=4,
            snapshot_sha256="b" * 64,
            evidence_count=1,
        ),
        baseline=ScenarioVariant(
            id=BASELINE_ID,
            position=0,
            name="No action",
            hypothesis="Observe only.",
            interventions=(),
        ),
        alternatives=(
            ScenarioVariant(
                id=ALTERNATIVE_ID,
                position=1,
                name="Clarify",
                hypothesis="Publish verified context.",
                interventions=(
                    Intervention(
                        id=UUID("66666666-6666-4666-8666-666666666666"),
                        position=0,
                        kind="initial_post",
                        actor="scenario_actor",
                        channel="reddit",
                        content="First exact post.",
                        offset_minutes=0,
                    ),
                    Intervention(
                        id=UUID("77777777-7777-4777-8777-777777777777"),
                        position=1,
                        kind="initial_post",
                        actor="scenario_actor",
                        channel="reddit",
                        content="Second exact post.",
                        offset_minutes=60,
                    ),
                ),
            ),
        ),
    )


def test_compiler_copies_exact_ordered_posts_and_is_deterministic() -> None:
    compiled = compile_platform_smoke_input(_scenario(), ALTERNATIVE_ID, 20260812)
    repeated = compile_platform_smoke_input(_scenario(), ALTERNATIVE_ID, 20260812)

    assert compiled == repeated
    assert compiled.actor_user_name == "scenario_e5cafa48797517e4"
    assert compiled.actor_name == "Scenario actor e5cafa48797517e4"
    assert [(post.position, post.content, post.offset_minutes) for post in compiled.posts] == [
        (0, "First exact post.", 0),
        (1, "Second exact post.", 60),
    ]
    assert len(calculate_platform_smoke_input_sha256(compiled)) == 64


@pytest.mark.parametrize("variant_id", (BASELINE_ID, UUID(int=0)))
def test_compiler_rejects_baseline_and_unknown_variant(variant_id: UUID) -> None:
    with pytest.raises(PlatformSmokeVariantError):
        compile_platform_smoke_input(_scenario(), variant_id, 0)
