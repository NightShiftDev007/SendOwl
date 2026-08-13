"""Strict semantic experiment request, hashing, and aggregate-state checks."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.semantic_experiments.contracts import (
    FrozenSemanticVariant,
    SemanticExperimentCreateRequest,
    SemanticTrial,
    SemanticTrialError,
)
from app.semantic_experiments.hashing import (
    PROMPT_SCHEMA_VERSION,
    calculate_semantic_experiment_sha256,
    canonical_semantic_experiment_json,
    canonical_semantic_trial_json,
)
from app.semantic_experiments.repository import _experiment_status


def _request_payload() -> dict[str, object]:
    return {
        "scenario_id": str(uuid4()),
        "cohort_id": str(uuid4()),
        "alternative_ids": [str(uuid4())],
        "seeds": [7, 11],
        "rounds": 2,
        "minutes_per_round": 60,
    }


def _variant(position: int, role: str, scenario_position: int) -> FrozenSemanticVariant:
    return FrozenSemanticVariant(
        position=position,
        role=role,
        id=uuid4(),
        scenario_position=scenario_position,
        name="No action" if position == 0 else "Clarify",
        hypothesis="Observe the bounded synthetic discussion.",
        intervention_count=0 if position == 0 else 1,
    )


def _trial(status: str) -> SemanticTrial:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    if status == "queued":
        started_at = None
        completed_at = None
        error = None
    elif status == "running":
        started_at = now
        completed_at = None
        error = None
    else:
        started_at = now
        completed_at = now
        error = SemanticTrialError(code="worker_failed", message="Explicit failure")
    return SemanticTrial(
        id=uuid4(),
        status=status,
        seed=1,
        trial_sha256="a" * 64,
        current_round=0,
        created_at=now,
        started_at=started_at,
        completed_at=completed_at,
        result=None,
        error=error,
    )


def test_create_request_converts_uuid_arrays_and_preserves_strict_uint32_seeds() -> None:
    payload = _request_payload()

    request = SemanticExperimentCreateRequest.model_validate(payload, strict=True)

    assert isinstance(request.scenario_id, UUID)
    assert isinstance(request.alternative_ids, tuple)
    assert request.seeds == (7, 11)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update({"extra": True}),
        lambda payload: payload.update({"seeds": [1, 1]}),
        lambda payload: payload.update({"seeds": ["1"]}),
        lambda payload: payload.update({"alternative_ids": [payload["alternative_ids"][0]] * 2}),
        lambda payload: payload.update({"rounds": 4}),
        lambda payload: payload.update({"minutes_per_round": 14}),
    ),
)
def test_create_request_rejects_unbounded_or_ambiguous_dimensions(mutation: object) -> None:
    payload = _request_payload()
    mutation(payload)

    with pytest.raises(ValidationError):
        SemanticExperimentCreateRequest.model_validate(payload, strict=True)


def test_experiment_and_trial_canonicals_freeze_prompt_schema_and_selected_order() -> None:
    scenario_id = uuid4()
    cohort_id = uuid4()
    variants = (_variant(0, "baseline", 0), _variant(1, "alternative", 2))

    canonical = canonical_semantic_experiment_json(
        str(scenario_id),
        "a" * 64,
        str(cohort_id),
        "b" * 64,
        variants,
        (7, 11),
        2,
        60,
        "semantic-model",
        "c" * 64,
    )
    trial_canonical = canonical_semantic_trial_json("d" * 64, variants[1], 7)

    assert f'"prompt_schema_version":"{PROMPT_SCHEMA_VERSION}"' in canonical
    assert f'"prompt_schema_version":"{PROMPT_SCHEMA_VERSION}"' in trial_canonical
    assert canonical.index('"role":"baseline"') < canonical.index('"role":"alternative"')
    assert (
        len(
            calculate_semantic_experiment_sha256(
                str(scenario_id),
                "a" * 64,
                str(cohort_id),
                "b" * 64,
                variants,
                (7, 11),
                2,
                60,
                "semantic-model",
                "c" * 64,
            )
        )
        == 64
    )


def test_experiment_status_stays_running_until_every_trial_is_terminal() -> None:
    failed = _trial("failed")
    queued = _trial("queued")
    running = _trial("running")

    assert _experiment_status((failed, queued)) == "running"
    assert _experiment_status((failed, running)) == "running"
    assert _experiment_status((failed,)) == "failed"
