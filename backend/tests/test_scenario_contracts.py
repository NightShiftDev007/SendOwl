"""Strict request, response, and canonical-hash checks for scenarios."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.scenarios.contracts import (
    Intervention,
    ScenarioCreateRequest,
    ScenarioDetail,
    ScenarioSnapshotRef,
    ScenarioVariant,
)
from app.scenarios.hashing import calculate_scenario_sha256, canonical_scenario_json


def _raw_request(model_id: UUID, snapshot_id: UUID) -> dict[str, object]:
    return {
        "title": "华为全球媒体应对实验",
        "decision_question": "是否应当发布一条澄清帖？",
        "world_model_id": str(model_id),
        "world_snapshot_id": str(snapshot_id),
        "baseline": {
            "name": "保持现状",
            "hypothesis": "不主动发帖时讨论自然演化。",
        },
        "alternatives": [
            {
                "name": "主动澄清",
                "hypothesis": "及时澄清能降低误解。",
                "interventions": [
                    {
                        "kind": "initial_post",
                        "actor": "scenario_actor",
                        "channel": "reddit",
                        "content": "We are publishing the verified facts.",
                        "offset_minutes": 15,
                    }
                ],
            }
        ],
    }


def _public_variants() -> tuple[ScenarioVariant, tuple[ScenarioVariant, ...]]:
    baseline = ScenarioVariant(
        id=uuid4(),
        position=0,
        name="保持现状",
        hypothesis="不主动发帖时讨论自然演化。",
        interventions=(),
    )
    alternative = ScenarioVariant(
        id=uuid4(),
        position=1,
        name="主动澄清",
        hypothesis="及时澄清能降低误解。",
        interventions=(
            Intervention(
                id=uuid4(),
                position=0,
                kind="initial_post",
                actor="scenario_actor",
                channel="reddit",
                content="We are publishing the verified facts.",
                offset_minutes=15,
            ),
        ),
    )
    return baseline, (alternative,)


def test_scenario_create_accepts_json_uuid_strings_and_arrays() -> None:
    model_id = uuid4()
    snapshot_id = uuid4()

    request = ScenarioCreateRequest.model_validate(
        _raw_request(model_id, snapshot_id),
        strict=True,
    )

    assert request.world_model_id == model_id
    assert request.world_snapshot_id == snapshot_id
    assert isinstance(request.alternatives, tuple)
    assert isinstance(request.alternatives[0].interventions, tuple)


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    (
        (
            lambda payload: payload["baseline"].update({"unrecognized": True}),
            "Extra inputs are not permitted",
        ),
        (
            lambda payload: payload["alternatives"][0]["interventions"][0].update(
                {"channel": "twitter"}
            ),
            "Input should be 'reddit'",
        ),
        (
            lambda payload: payload.update({"title": "line one\nline two"}),
            "String should match pattern",
        ),
    ),
)
def test_scenario_create_rejects_contract_drift(
    mutation: object,
    expected_message: str,
) -> None:
    payload = _raw_request(uuid4(), uuid4())
    mutation(payload)

    with pytest.raises(ValidationError, match=expected_message):
        ScenarioCreateRequest.model_validate(payload, strict=True)


def test_scenario_response_rejects_uuid_transport_strings() -> None:
    snapshot = ScenarioSnapshotRef(
        world_model_id=uuid4(),
        world_snapshot_id=uuid4(),
        version=1,
        snapshot_sha256="a" * 64,
        evidence_count=2,
    )
    baseline, alternatives = _public_variants()
    digest = calculate_scenario_sha256("Scenario", "Question?", snapshot, baseline, alternatives)

    with pytest.raises(ValidationError, match="instance of UUID"):
        ScenarioDetail(
            id=str(uuid4()),
            title="Scenario",
            decision_question="Question?",
            created_at=datetime(2026, 8, 12, tzinfo=UTC),
            scenario_sha256=digest,
            snapshot=snapshot,
            baseline=baseline,
            alternatives=alternatives,
        )


def test_scenario_hash_excludes_generated_ids_but_preserves_ordered_semantics() -> None:
    snapshot = ScenarioSnapshotRef(
        world_model_id=uuid4(),
        world_snapshot_id=uuid4(),
        version=2,
        snapshot_sha256="b" * 64,
        evidence_count=3,
    )
    baseline, alternatives = _public_variants()
    replacement_baseline, replacement_alternatives = _public_variants()

    first_json = canonical_scenario_json(
        "Scenario",
        "Question?",
        snapshot,
        baseline,
        alternatives,
    )
    second_json = canonical_scenario_json(
        "Scenario",
        "Question?",
        snapshot,
        replacement_baseline,
        replacement_alternatives,
    )

    assert first_json == second_json
    assert calculate_scenario_sha256(
        "Scenario",
        "Question?",
        snapshot,
        baseline,
        alternatives,
    ) != calculate_scenario_sha256(
        "Scenario",
        "Different question?",
        snapshot,
        baseline,
        alternatives,
    )
