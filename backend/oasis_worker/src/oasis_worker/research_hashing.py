"""Canonical research-run addresses mirrored by the API boundary."""

import hashlib
import json


def _sha256(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def legacy_research_run_spec_sha256(
    project_sha256: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    return _sha256(
        {
            "schema": "sandowl-research-simulation-run/v1",
            "project_sha256": project_sha256,
            "seed": seed,
            "rounds": rounds,
            "minutes_per_round": minutes_per_round,
            "initial_post": initial_post,
            "engine": "camel-oasis",
            "engine_version": "0.2.5",
            "model": {
                "name": model_name,
                "semantic_config_sha256": semantic_config_sha256,
                "prompt_schema_version": "matraix-semantic-profile/v1",
            },
        }
    )


def research_run_spec_sha256(
    project_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    persona_count: int,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    return _sha256(
        {
            "schema": "sandowl-research-simulation-run/v2",
            "project_sha256": project_sha256,
            "cohort": {
                "cohort_id": cohort_id,
                "cohort_sha256": cohort_sha256,
                "persona_count": persona_count,
            },
            "simulation_requirement": simulation_requirement,
            "seed": seed,
            "rounds": rounds,
            "minutes_per_round": minutes_per_round,
            "initial_post": initial_post,
            "engine": "camel-oasis",
            "engine_version": "0.2.5",
            "model": {
                "name": model_name,
                "semantic_config_sha256": semantic_config_sha256,
                "prompt_schema_version": "matraix-semantic-profile/v1",
            },
        }
    )


def simulation_context_sha256(context: object) -> str:
    return _sha256(context)


def context_bound_research_run_spec_sha256(
    project_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    persona_count: int,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
    context_sha256: str,
) -> str:
    return _sha256(
        {
            "schema": "sandowl-research-simulation-run/v3",
            "project_sha256": project_sha256,
            "cohort": {
                "cohort_id": cohort_id,
                "cohort_sha256": cohort_sha256,
                "persona_count": persona_count,
            },
            "simulation_requirement": simulation_requirement,
            "seed": seed,
            "rounds": rounds,
            "minutes_per_round": minutes_per_round,
            "initial_post": initial_post,
            "engine": "camel-oasis",
            "engine_version": "0.2.5",
            "model": {
                "name": model_name,
                "semantic_config_sha256": semantic_config_sha256,
                "prompt_schema_version": "matraix-semantic-profile/v1",
            },
            "simulation_context_sha256": context_sha256,
        }
    )


def simulation_plan_sha256(plan: object) -> str:
    return _sha256(plan)


def planned_research_run_spec_sha256(
    project_sha256: str,
    cohort_id: str,
    cohort_sha256: str,
    persona_count: int,
    simulation_requirement: str,
    seed: int,
    model_name: str,
    semantic_config_sha256: str,
    context_sha256: str,
    plan_sha256: str,
) -> str:
    return _sha256(
        {
            "schema": "sandowl-research-simulation-run/v4",
            "project_sha256": project_sha256,
            "cohort": {
                "cohort_id": cohort_id,
                "cohort_sha256": cohort_sha256,
                "persona_count": persona_count,
            },
            "simulation_requirement": simulation_requirement,
            "seed": seed,
            "engine": "camel-oasis",
            "engine_version": "0.2.5",
            "model": {
                "name": model_name,
                "semantic_config_sha256": semantic_config_sha256,
                "prompt_schema_version": "matraix-semantic-profile/v1",
            },
            "simulation_context_sha256": context_sha256,
            "simulation_plan_sha256": plan_sha256,
        }
    )


def research_run_report_sha256(run_spec_sha256: str, artifact_sha256: str) -> str:
    return _sha256(
        {
            "schema": "sandowl-research-run-report/v1",
            "run_spec_sha256": run_spec_sha256,
            "artifact_sha256": artifact_sha256,
        }
    )
