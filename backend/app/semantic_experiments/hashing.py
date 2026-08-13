"""Canonical addresses for semantic experiment and trial inputs."""

import json
from hashlib import sha256

from app.semantic_experiments.contracts import FrozenSemanticVariant

PROMPT_SCHEMA_VERSION = "matraix-semantic-profile/v1"


def canonical_semantic_experiment_json(
    scenario_id: str,
    scenario_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    variants: tuple[FrozenSemanticVariant, ...],
    seeds: tuple[int, ...],
    rounds: int,
    minutes_per_round: int,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    """Serialize the complete selected batch independently of resource identities."""
    if tuple(variant.position for variant in variants) != tuple(range(len(variants))):
        raise ValueError("semantic variants must be contiguous from experiment position zero")
    if not 2 <= len(variants) <= 3:
        raise ValueError("semantic experiment must include baseline plus 1..2 alternatives")
    if seeds != tuple(sorted(set(seeds))) or not 1 <= len(seeds) <= 2:
        raise ValueError("semantic seeds must contain 1..2 unique ascending values")
    payload = {
        "schema": "oasis-semantic-experiment/v1",
        "scenario": {"id": scenario_id, "scenario_sha256": scenario_sha256},
        "cohort": {"id": cohort_id, "cohort_sha256": cohort_sha256},
        "variants": [
            {
                "role": variant.role,
                "id": str(variant.id),
                "position": variant.scenario_position,
                "name": variant.name,
                "hypothesis": variant.hypothesis,
            }
            for variant in variants
        ],
        "seeds": list(seeds),
        "rounds": rounds,
        "minutes_per_round": minutes_per_round,
        "model": {
            "name": model_name,
            "config_sha256": semantic_config_sha256,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_semantic_experiment_sha256(
    scenario_id: str,
    scenario_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    variants: tuple[FrozenSemanticVariant, ...],
    seeds: tuple[int, ...],
    rounds: int,
    minutes_per_round: int,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    canonical = canonical_semantic_experiment_json(
        scenario_id,
        scenario_sha256,
        cohort_id,
        cohort_sha256,
        variants,
        seeds,
        rounds,
        minutes_per_round,
        model_name,
        semantic_config_sha256,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_semantic_trial_json(
    experiment_sha256: str,
    variant: FrozenSemanticVariant,
    seed: int,
) -> str:
    payload = {
        "schema": "oasis-semantic-trial/v1",
        "experiment_sha256": experiment_sha256,
        "prompt_schema_version": PROMPT_SCHEMA_VERSION,
        "variant": {
            "role": variant.role,
            "id": str(variant.id),
            "position": variant.scenario_position,
            "name": variant.name,
        },
        "seed": seed,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_semantic_trial_sha256(
    experiment_sha256: str,
    variant: FrozenSemanticVariant,
    seed: int,
) -> str:
    canonical = canonical_semantic_trial_json(experiment_sha256, variant, seed)
    return sha256(canonical.encode("utf-8")).hexdigest()
