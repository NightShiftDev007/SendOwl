"""Metadata checks for normalized semantic experiment resources."""

from app.database import ApplicationBase
from app.semantic_experiments import models as semantic_models
from app.simulations import models as simulation_models

del semantic_models, simulation_models


def test_semantic_schema_is_normalized_and_heartbeat_has_no_secret_columns() -> None:
    assert {
        "semantic_experiments",
        "semantic_experiment_variants",
        "semantic_trials",
        "semantic_trial_events",
    }.issubset(ApplicationBase.metadata.tables)
    trials = ApplicationBase.metadata.tables["semantic_trials"]
    events = ApplicationBase.metadata.tables["semantic_trial_events"]
    heartbeats = ApplicationBase.metadata.tables["simulation_worker_heartbeats"]

    assert {"trial_sha256", "current_round", "observed_action_count", "limitations"}.issubset(
        trials.columns.keys()
    )
    assert {"trial_id", "sequence", "round", "actor_kind", "action_type"}.issubset(
        events.columns.keys()
    )
    assert {
        "semantic_runtime_ready",
        "semantic_model_name",
        "semantic_config_sha256",
        "semantic_prompt_schema_version",
    }.issubset(heartbeats.columns.keys())
    assert "authored_content_count" not in trials.columns
    assert "api_key" not in heartbeats.columns
    assert "base_url" not in heartbeats.columns
    assert str(heartbeats.c.semantic_runtime_ready.server_default.arg) == "false"
