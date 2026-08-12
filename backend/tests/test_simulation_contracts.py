"""Behavior tests for strict simulation request contracts."""

import json

import pytest
from pydantic import ValidationError

from app.simulations.contracts import MatrAIxEvaluationSpec


def build_raw_cohort(cohort_id: str, population_weight: float) -> dict[str, object]:
    return {
        "cohort_id": cohort_id,
        "label": cohort_id,
        "persona_count": 10,
        "population_weight": population_weight,
    }


def build_raw_matraix_spec(cohorts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "engine": "matraix",
        "run_id": "run-001",
        "scenario_id": "scenario-001",
        "cohorts": cohorts,
        "questions": ["Would you support this decision?"],
        "model_id": "model-001",
        "seed": 42,
    }


def test_matraix_spec_accepts_positive_relative_weights_without_requiring_sum_one() -> None:
    raw_spec = build_raw_matraix_spec(
        [
            build_raw_cohort("cohort-001", 0.2),
            build_raw_cohort("cohort-002", 0.3),
        ]
    )

    spec = MatrAIxEvaluationSpec.model_validate_json(json.dumps(raw_spec))

    assert sum(cohort.population_weight for cohort in spec.cohorts) == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("cohorts", "expected_message"),
    [
        (
            [
                build_raw_cohort("cohort-001", 0.4),
                build_raw_cohort("cohort-001", 0.6),
            ],
            "cohorts must use unique cohort_id values; duplicates: cohort-001",
        ),
        (
            [
                build_raw_cohort("cohort-001", 0.0),
                build_raw_cohort("cohort-002", 0.0),
            ],
            "cohorts must have a total population_weight greater than zero",
        ),
    ],
)
def test_matraix_spec_rejects_invalid_cohort_composition(
    cohorts: list[dict[str, object]],
    expected_message: str,
) -> None:
    raw_spec = build_raw_matraix_spec(cohorts)

    with pytest.raises(ValidationError, match=expected_message):
        MatrAIxEvaluationSpec.model_validate_json(json.dumps(raw_spec))
