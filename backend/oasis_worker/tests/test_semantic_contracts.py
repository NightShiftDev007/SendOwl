from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError
from semantic_fixtures import CONFIG_SHA256, build_trial

from oasis_worker.semantic_contracts import SemanticEvent
from oasis_worker.semantic_hashing import experiment_sha256, scenario_sha256
from oasis_worker.semantic_queue import (
    _claimed_semantic_trial_from_row,
    _queue_integrity_failure,
    _semantic_persona_from_row,
    _validate_claim_integrity,
)


def test_full_scenario_hash_remains_valid_when_experiment_selects_one_of_three_alternatives() -> (
    None
):
    trial = build_trial(persona_count=1, selected_position=1)

    assert len(trial.scenario.variants) == 3
    assert len(trial.experiment.variants) == 2
    assert scenario_sha256(trial.scenario) == trial.scenario.scenario_sha256
    assert experiment_sha256(trial.experiment) == trial.experiment.experiment_sha256
    assert trial.dataset.persona_count == 1_000_000
    assert len(trial.cohort.personas) == 1


def test_profile_projection_is_deterministic_bounded_and_excludes_known_sentinels() -> None:
    from oasis_worker.semantic_engine import PROFILE_TEMPLATE, project_persona_profile

    trial = build_trial(persona_count=1, selected_position=0)
    projection = project_persona_profile(trial.cohort.personas[0])

    assert projection.included_count == 40
    assert projection.eligible_count == 47
    assert projection.total_count == 48
    assert "No coding activity" not in projection.text
    assert "Decision question" not in projection.text
    assert "Attributes included: 40" in projection.text
    assert "variant" not in PROFILE_TEMPLATE.casefold()


def test_semantic_config_digest_covers_profile_projection_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from oasis_worker import semantic_hashing

    base_url = "https://provider.example/v1"
    model_name = "provider-model"
    baseline = semantic_hashing.semantic_config_sha256(base_url, model_name)

    monkeypatch.setattr(
        semantic_hashing,
        "PROFILE_TEMPLATE_TEXT",
        semantic_hashing.PROFILE_TEMPLATE_TEXT + "\nExplicit projection behavior change.",
    )
    template_changed = semantic_hashing.semantic_config_sha256(base_url, model_name)
    monkeypatch.setattr(
        semantic_hashing,
        "PROFILE_TEMPLATE_TEXT",
        semantic_hashing.PROFILE_TEMPLATE_TEXT.removesuffix(
            "\nExplicit projection behavior change."
        ),
    )

    monkeypatch.setattr(
        semantic_hashing,
        "LOW_INFORMATION_VALUES",
        semantic_hashing.LOW_INFORMATION_VALUES | {"unknown"},
    )
    sentinels_changed = semantic_hashing.semantic_config_sha256(base_url, model_name)
    monkeypatch.setattr(
        semantic_hashing,
        "LOW_INFORMATION_VALUES",
        semantic_hashing.LOW_INFORMATION_VALUES - {"unknown"},
    )

    monkeypatch.setattr(
        semantic_hashing,
        "MAX_PROFILE_ATTRIBUTES",
        semantic_hashing.MAX_PROFILE_ATTRIBUTES - 1,
    )
    maximum_changed = semantic_hashing.semantic_config_sha256(base_url, model_name)

    assert len({baseline, template_changed, sentinels_changed, maximum_changed}) == 4


def test_semantic_event_rejects_action_specific_extra_fields_and_maps_public_positions() -> None:
    with pytest.raises(ValidationError, match="forbids comment and target"):
        SemanticEvent(
            round=1,
            phase="audience",
            actor_kind="persona",
            persona_id=UUID("40000000-0000-4000-8000-000000000001"),
            agent_position=1,
            action_type="create_post",
            content="Post",
            post_id="1",
            comment_id="2",
            target_post_id=None,
            observed_at_raw="2026-08-12 00:00:00",
        )

    with pytest.raises(ValidationError, match="single-line"):
        SemanticEvent(
            round=1,
            phase="audience",
            actor_kind="persona",
            persona_id=UUID("40000000-0000-4000-8000-000000000001"),
            agent_position=1,
            action_type="do_nothing",
            content=None,
            post_id=None,
            comment_id=None,
            target_post_id=None,
            observed_at_raw="bad\ntime",
        )


def test_claim_integrity_accepts_bounded_cohort_without_loading_full_dataset() -> None:
    from oasis_worker.semantic_contracts import SemanticRuntimeConfig

    trial = build_trial(persona_count=2, selected_position=0)
    config = SemanticRuntimeConfig(
        api_key="secret",
        base_url="https://provider.example/v1",
        model_name=trial.experiment.model_name,
        config_sha256=CONFIG_SHA256,
        prompt_schema_version="matraix-semantic-profile/v1",
    )

    _validate_claim_integrity(trial, config)


def test_postgresql_persona_row_projects_away_profile_json_storage_column() -> None:
    persona = build_trial(persona_count=1, selected_position=0).cohort.personas[0]
    row = {
        "position": persona.position,
        "id": persona.id,
        "persona_id": persona.persona_id,
        "display_name": persona.display_name,
        "source": persona.source,
        "profile_json": persona.profile.model_dump(mode="json"),
        "profile_sha256": persona.profile_sha256,
    }

    projected = _semantic_persona_from_row(row)

    assert projected == persona


def test_postgresql_trial_row_projects_away_experiment_id_storage_column() -> None:
    trial = build_trial(persona_count=1, selected_position=1)
    row = {
        "id": trial.id,
        "experiment_id": trial.experiment.id,
        "variant_position": trial.variant_position,
        "variant_role": trial.variant_role,
        "scenario_variant_id": trial.scenario_variant_id,
        "scenario_position": trial.scenario_position,
        "variant_name": trial.variant_name,
        "variant_hypothesis": trial.variant_hypothesis,
        "seed": trial.seed,
        "trial_sha256": trial.trial_sha256,
        "created_at": trial.created_at,
    }

    projected = _claimed_semantic_trial_from_row(
        row,
        trial.experiment,
        trial.scenario,
        trial.dataset,
        trial.cohort,
    )

    assert projected == trial


def test_queue_integrity_failure_preserves_safe_location_without_input_values() -> None:
    with pytest.raises(ValidationError) as captured:
        SemanticEvent.model_validate(
            {
                "round": 1,
                "phase": "audience",
                "actor_kind": "persona",
                "persona_id": UUID("40000000-0000-4000-8000-000000000001"),
                "agent_position": 1,
                "action_type": "do_nothing",
                "content": "private-persona-value",
                "post_id": None,
                "comment_id": None,
                "target_post_id": None,
                "observed_at_raw": "2026-08-12 00:00:00",
            }
        )

    failure = _queue_integrity_failure(captured.value)

    assert failure.code == "queue_integrity"
    assert "validation failed at" in failure.message
    assert "private-persona-value" not in failure.message
