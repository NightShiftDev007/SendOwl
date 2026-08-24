"""Independent canonical hashes for semantic trial inputs and provider identity."""

from __future__ import annotations

import hashlib
import json

from oasis_worker.semantic_contracts import (
    ALLOWED_AUDIENCE_ACTION_NAMES,
    LOW_INFORMATION_VALUES,
    MAX_PROFILE_ATTRIBUTES,
    PROFILE_TEMPLATE_TEXT,
    CohortIntegrityInput,
    PersonaProfile,
    ScenarioIntegrityInput,
    SemanticExperiment,
)

MODEL_CONTEXT_TOKEN_LIMIT = 32_768
MODEL_OUTPUT_MAX_TOKENS = 512
REPORT_DOMAIN_OUTPUT_MAX_TOKENS = 2048
MODEL_TOOL_CHOICE = "required"
MODEL_ENABLE_THINKING = False


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _semantic_config_payload(
    base_url: str,
    model_name: str,
    profile_template_text: str,
    low_information_values: frozenset[str],
    max_profile_attributes: int,
) -> dict[str, object]:
    return {
        "provider": "openai_compatible",
        "base_url": base_url,
        "model_name": model_name,
        "engine_version": "0.2.5",
        "camel_version": "0.2.78",
        "prompt_schema_version": "matraix-semantic-profile/v1",
        "model_config": {
            "context_token_limit": MODEL_CONTEXT_TOKEN_LIMIT,
            "output_max_tokens": MODEL_OUTPUT_MAX_TOKENS,
            "tool_choice": MODEL_TOOL_CHOICE,
            "enable_thinking": MODEL_ENABLE_THINKING,
        },
        "allowed_audience_actions": list(ALLOWED_AUDIENCE_ACTION_NAMES),
        "profile_projection": {
            "schema": "matraix-semantic-profile/v1",
            "template_sha256": _sha256(profile_template_text),
            "low_information_values": sorted(low_information_values),
            "max_attributes": max_profile_attributes,
        },
    }


def semantic_config_sha256(base_url: str, model_name: str) -> str:
    """Hash output-affecting semantics; timeout and retries remain operational settings."""
    payload = _semantic_config_payload(
        base_url,
        model_name,
        PROFILE_TEMPLATE_TEXT,
        LOW_INFORMATION_VALUES,
        MAX_PROFILE_ATTRIBUTES,
    )
    return _sha256(_canonical_json(payload))


def report_domain_config_sha256(base_url: str, model_name: str) -> str:
    """Hash the larger bounded output budget used by report-domain tools."""
    payload = _semantic_config_payload(
        base_url,
        model_name,
        PROFILE_TEMPLATE_TEXT,
        LOW_INFORMATION_VALUES,
        MAX_PROFILE_ATTRIBUTES,
    )
    model_config = payload["model_config"]
    if not isinstance(model_config, dict):
        raise RuntimeError("semantic model config payload must be an object")
    model_config["output_max_tokens"] = REPORT_DOMAIN_OUTPUT_MAX_TOKENS
    payload["worker_domain"] = "report"
    payload["report_output_schema"] = "bounded-tool-json/v1"
    payload["output_validation_attempts"] = 2
    payload["citation_policy"] = "indexed_deterministic_exact_quote_windows/v1"
    return _sha256(_canonical_json(payload))


def persona_profile_sha256(profile: PersonaProfile) -> str:
    return _sha256(_canonical_json(profile.model_dump(mode="json")))


def cohort_sha256(cohort: CohortIntegrityInput, frozen_dataset_sha256: str) -> str:
    payload = {
        "schema": "matraix-cohort/v1",
        "title": cohort.title,
        "dataset_sha256": frozen_dataset_sha256,
        "persona_count": cohort.persona_count,
        "members": [
            {"persona_id": persona.persona_id, "profile_sha256": persona.profile_sha256}
            for persona in cohort.personas
        ],
    }
    return _sha256(_canonical_json(payload))


def scenario_sha256(scenario: ScenarioIntegrityInput) -> str:
    baseline = scenario.variants[0]
    alternatives = scenario.variants[1:]
    payload = {
        "schema_version": "scenario/v2",
        "title": scenario.title,
        "decision_question": scenario.decision_question,
        "snapshot": {
            "world_model_id": str(scenario.world_model_id),
            "world_snapshot_id": str(scenario.world_snapshot_id),
            "version": scenario.snapshot_version,
            "snapshot_sha256": scenario.snapshot_sha256,
            "evidence_count": scenario.snapshot_evidence_count,
        },
        "baseline": {
            "position": baseline.position,
            "name": baseline.name,
            "hypothesis": baseline.hypothesis,
            "interventions": [],
        },
        "alternatives": [
            {
                "position": alternative.position,
                "name": alternative.name,
                "hypothesis": alternative.hypothesis,
                "interventions": [
                    {
                        "position": intervention.position,
                        "kind": intervention.kind,
                        "actor": intervention.actor,
                        "channel": intervention.channel,
                        "content": intervention.content,
                        "offset_minutes": intervention.offset_minutes,
                    }
                    for intervention in alternative.interventions
                ],
            }
            for alternative in alternatives
        ],
    }
    return _sha256(_canonical_json(payload))


def experiment_sha256(experiment: SemanticExperiment) -> str:
    payload = {
        "schema": "oasis-semantic-experiment/v1",
        "scenario": {
            "id": str(experiment.scenario_id),
            "scenario_sha256": experiment.scenario_sha256,
        },
        "cohort": {
            "id": str(experiment.cohort_id),
            "cohort_sha256": experiment.cohort_sha256,
        },
        "variants": [
            {
                "role": variant.role,
                "id": str(variant.id),
                "position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
            }
            for variant in experiment.variants
        ],
        "seeds": list(experiment.seeds),
        "rounds": experiment.rounds,
        "minutes_per_round": experiment.minutes_per_round,
        "model": {
            "name": experiment.model_name,
            "config_sha256": experiment.semantic_config_sha256,
            "prompt_schema_version": experiment.prompt_schema_version,
        },
    }
    return _sha256(_canonical_json(payload))


def trial_sha256(experiment: SemanticExperiment, variant_position: int, seed: int) -> str:
    variant = experiment.variants[variant_position]
    payload = {
        "schema": "oasis-semantic-trial/v1",
        "experiment_sha256": experiment.experiment_sha256,
        "prompt_schema_version": experiment.prompt_schema_version,
        "variant": {
            "role": variant.role,
            "id": str(variant.id),
            "position": variant.scenario_position,
            "name": variant.name,
        },
        "seed": seed,
    }
    return _sha256(_canonical_json(payload))
