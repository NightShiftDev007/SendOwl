"""Application metadata and integrity guards for population tables."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.database import ApplicationBase
from app.populations import models as population_models
from app.populations.models import CohortRecord, PersonaDatasetRecord
from app.populations.repository import _require_sealed_cohort, _require_sealed_dataset

del population_models


def test_population_schema_uses_four_normalized_frozen_tables() -> None:
    assert {
        "persona_datasets",
        "personas",
        "cohorts",
        "cohort_members",
    }.issubset(ApplicationBase.metadata.tables)
    datasets = ApplicationBase.metadata.tables["persona_datasets"]
    personas = ApplicationBase.metadata.tables["personas"]
    cohorts = ApplicationBase.metadata.tables["cohorts"]
    members = ApplicationBase.metadata.tables["cohort_members"]

    assert {"sealed_at", "manifest_sha256", "dataset_sha256"}.issubset(datasets.columns.keys())
    assert {"position", "profile_json", "profile_sha256"}.issubset(personas.columns.keys())
    assert {"sealed_at", "cohort_sha256", "persona_count"}.issubset(cohorts.columns.keys())
    assert {"cohort_id", "dataset_id", "persona_id", "position"}.issubset(members.columns.keys())
    assert any(
        constraint.name == "uq_persona_datasets_dataset_sha256"
        for constraint in datasets.constraints
    )
    assert not any(
        constraint.name == "uq_persona_datasets_slug" for constraint in datasets.constraints
    )
    assert any(
        constraint.name == "uq_personas_dataset_position" for constraint in personas.constraints
    )
    assert any(constraint.name == "uq_cohorts_cohort_sha256" for constraint in cohorts.constraints)
    assert any(constraint.name == "uq_cohort_members_persona" for constraint in members.constraints)


def test_unsealed_dataset_and_cohort_are_rejected() -> None:
    dataset = PersonaDatasetRecord(
        id=uuid4(),
        slug="dev-sample",
        display_name="Dev sample",
        schema_version="1.0",
        parent_pool=None,
        source_repository=None,
        persona_count=1,
        manifest_sha256="a" * 64,
        dataset_sha256="b" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        sealed_at=None,
    )
    cohort = CohortRecord(
        id=uuid4(),
        title="Cohort",
        dataset_id=dataset.id,
        persona_count=1,
        cohort_sha256="c" * 64,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        sealed_at=None,
    )

    with pytest.raises(RuntimeError, match=f"persona dataset {dataset.id} is not sealed"):
        _require_sealed_dataset(dataset)
    with pytest.raises(RuntimeError, match=f"cohort {cohort.id} is not sealed"):
        _require_sealed_cohort(cohort)
