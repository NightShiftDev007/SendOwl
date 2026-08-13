"""Strict immutable population request and hashing contracts."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.populations.contracts import (
    CohortCreateRequest,
    DatasetSummary,
    StoredPersonaProfile,
    StoredPersonaProvenance,
)
from app.populations.hashing import (
    calculate_cohort_sha256,
    calculate_persona_profile_sha256,
    canonical_cohort_json,
)


def _profile(dimensions: dict[str, str]) -> StoredPersonaProfile:
    return StoredPersonaProfile(
        display_name="Tomas Horvat",
        dimensions=dimensions,
        persona_id="0001",
        provenance=StoredPersonaProvenance(
            hf_repo=None,
            origin_persona_id=None,
            origin_source_row_index=None,
            parent_pool="matraix-persona-dev-sample",
        ),
        source="wiki",
        version="1.0",
    )


def test_profile_digest_is_independent_of_dimension_input_order() -> None:
    first = _profile({"region": "Eastern Europe", "risk_tolerance": "Risk-seeking"})
    second = _profile({"risk_tolerance": "Risk-seeking", "region": "Eastern Europe"})

    assert calculate_persona_profile_sha256(first) == calculate_persona_profile_sha256(second)


def test_stored_profile_rejects_extra_profile_and_provenance_fields() -> None:
    profile = _profile({"region": "Eastern Europe"}).model_dump(mode="json")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StoredPersonaProfile.model_validate({**profile, "unexpected": True})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StoredPersonaProfile.model_validate(
            {
                **profile,
                "provenance": {**profile["provenance"], "unexpected": True},
            }
        )


def test_cohort_hash_uses_dataset_profiles_and_order_but_not_generated_ids() -> None:
    first_members = (("0001", "1" * 64), ("0002", "2" * 64))
    reversed_members = tuple(reversed(first_members))
    canonical = json.loads(canonical_cohort_json("Policy readers", "a" * 64, first_members))

    assert canonical == {
        "schema": "matraix-cohort/v1",
        "title": "Policy readers",
        "dataset_sha256": "a" * 64,
        "persona_count": 2,
        "members": [
            {"persona_id": "0001", "profile_sha256": "1" * 64},
            {"persona_id": "0002", "profile_sha256": "2" * 64},
        ],
    }
    assert calculate_cohort_sha256(
        "Policy readers", "a" * 64, first_members
    ) != calculate_cohort_sha256("Policy readers", "a" * 64, reversed_members)


def test_cohort_request_rejects_duplicate_personas_and_extra_fields() -> None:
    persona_id = uuid4()

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        CohortCreateRequest.model_validate(
            {
                "title": "Duplicate",
                "dataset_id": str(uuid4()),
                "persona_ids": [str(persona_id), str(persona_id)],
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CohortCreateRequest.model_validate(
            {
                "title": "Extra",
                "dataset_id": str(uuid4()),
                "persona_ids": [str(uuid4())],
                "unexpected": True,
            }
        )


def test_dataset_slug_uses_the_shared_identifier_alphabet() -> None:
    valid = {
        "id": uuid4(),
        "slug": "matraix-persona_dev.sample:v1",
        "display_name": "MatrAIx sample",
        "schema_version": "1.0",
        "parent_pool": None,
        "source_repository": None,
        "persona_count": 200,
        "manifest_sha256": "a" * 64,
        "dataset_sha256": "b" * 64,
        "created_at": datetime(2026, 8, 12, tzinfo=UTC),
    }

    assert DatasetSummary.model_validate(valid).slug == valid["slug"]
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        DatasetSummary.model_validate({**valid, "slug": "invalid slug"})
