"""Application metadata and read-integrity checks for scenarios."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import ApplicationBase
from app.scenarios import models as scenario_models
from app.scenarios.models import ScenarioRecord
from app.scenarios.repository import _require_sealed_scenario

del scenario_models


def _scenario_record() -> ScenarioRecord:
    return ScenarioRecord(
        id=uuid4(),
        title="Scenario",
        decision_question="Question?",
        world_model_id=uuid4(),
        world_snapshot_id=uuid4(),
        snapshot_version=1,
        snapshot_sha256="a" * 64,
        snapshot_company_name="Acme",
        snapshot_evidence_count=1,
        scenario_sha256="b" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        sealed_at=None,
    )


def test_scenario_schema_uses_three_normalized_ordered_tables() -> None:
    assert {"scenarios", "scenario_variants", "scenario_interventions"}.issubset(
        ApplicationBase.metadata.tables
    )
    variants = ApplicationBase.metadata.tables["scenario_variants"]
    interventions = ApplicationBase.metadata.tables["scenario_interventions"]

    assert {"sealed_at", "scenario_sha256", "world_snapshot_id"}.issubset(
        ApplicationBase.metadata.tables["scenarios"].columns.keys()
    )
    assert {"scenario_id", "position", "role"}.issubset(variants.columns.keys())
    assert {"scenario_id", "variant_id", "position"}.issubset(interventions.columns.keys())
    assert any(
        constraint.name == "uq_scenario_variants_position" for constraint in variants.constraints
    )
    assert any(
        constraint.name == "uq_scenario_interventions_position"
        for constraint in interventions.constraints
    )
    assert any(
        constraint.name == "uq_scenarios_sha256"
        for constraint in ApplicationBase.metadata.tables["scenarios"].constraints
    )


def test_unsealed_scenario_is_rejected_by_read_projection_guard() -> None:
    scenario = _scenario_record()

    with pytest.raises(RuntimeError, match=f"scenario {scenario.id} is not sealed"):
        _require_sealed_scenario(scenario)
