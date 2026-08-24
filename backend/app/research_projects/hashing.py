"""Canonical content addresses for projects and independent run specifications."""

import json
from hashlib import sha256

from app.research_projects.contracts import (
    ResearchProjectCohortRef,
    ResearchProjectGraphRef,
    ResearchProjectSnapshotRef,
    ResearchRunReport,
)

LEGACY_PROJECT_SCHEMA_VERSION = "sandowl-research-project/v1"
PROJECT_SCHEMA_VERSION = "sandowl-research-project/v2"
GRAPH_BOUND_PROJECT_SCHEMA_VERSION = "sandowl-research-project/v3"
LEGACY_RUN_SCHEMA_VERSION = "sandowl-research-simulation-run/v1"
RUN_SCHEMA_VERSION = "sandowl-research-simulation-run/v2"
CONTEXT_BOUND_RUN_SCHEMA_VERSION = "sandowl-research-simulation-run/v3"
PLANNED_RUN_SCHEMA_VERSION = "sandowl-research-simulation-run/v4"
RUN_ENGINE = "camel-oasis"
RUN_ENGINE_VERSION = "0.2.5"


def canonical_research_project_json(
    title: str,
    research_question: str,
    snapshot: ResearchProjectSnapshotRef,
) -> str:
    """Serialize one Project / Graph context independently from run design."""
    payload = {
        "schema": PROJECT_SCHEMA_VERSION,
        "title": title,
        "research_question": research_question,
        "snapshot": {
            "world_model_id": str(snapshot.world_model_id),
            "world_snapshot_id": str(snapshot.world_snapshot_id),
            "snapshot_sha256": snapshot.snapshot_sha256,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_research_project_sha256(
    title: str,
    research_question: str,
    snapshot: ResearchProjectSnapshotRef,
) -> str:
    """Calculate one stable research-project digest."""
    canonical = canonical_research_project_json(
        title,
        research_question,
        snapshot,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_graph_bound_research_project_json(
    title: str,
    research_question: str,
    snapshot: ResearchProjectSnapshotRef,
    graph: ResearchProjectGraphRef,
) -> str:
    """Serialize a project that binds one exact semantic graph."""
    payload = {
        "schema": GRAPH_BOUND_PROJECT_SCHEMA_VERSION,
        "title": title,
        "research_question": research_question,
        "snapshot": {
            "world_model_id": str(snapshot.world_model_id),
            "world_snapshot_id": str(snapshot.world_snapshot_id),
            "snapshot_sha256": snapshot.snapshot_sha256,
        },
        "graph": {
            "graph_id": str(graph.graph_id),
            "graph_sha256": graph.graph_sha256,
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_graph_bound_research_project_sha256(
    title: str,
    research_question: str,
    snapshot: ResearchProjectSnapshotRef,
    graph: ResearchProjectGraphRef,
) -> str:
    canonical = canonical_graph_bound_research_project_json(
        title,
        research_question,
        snapshot,
        graph,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_research_simulation_run_json(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    """Serialize one independent simulation-run specification."""
    payload = {
        "schema": RUN_SCHEMA_VERSION,
        "project_sha256": project_sha256,
        "cohort": {
            "cohort_id": str(cohort.cohort_id),
            "cohort_sha256": cohort.cohort_sha256,
            "persona_count": cohort.persona_count,
        },
        "simulation_requirement": simulation_requirement,
        "seed": seed,
        "rounds": rounds,
        "minutes_per_round": minutes_per_round,
        "initial_post": initial_post,
        "engine": RUN_ENGINE,
        "engine_version": RUN_ENGINE_VERSION,
        "model": {
            "name": model_name,
            "semantic_config_sha256": semantic_config_sha256,
            "prompt_schema_version": "matraix-semantic-profile/v1",
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_research_simulation_run_sha256(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
) -> str:
    """Calculate one stable run-specification digest."""
    canonical = canonical_research_simulation_run_json(
        project_sha256,
        cohort,
        simulation_requirement,
        seed,
        rounds,
        minutes_per_round,
        initial_post,
        model_name,
        semantic_config_sha256,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_context_bound_research_simulation_run_json(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
    simulation_context_sha256: str,
) -> str:
    """Serialize a run that binds the exact Persona-visible reality context."""
    payload = {
        "schema": CONTEXT_BOUND_RUN_SCHEMA_VERSION,
        "project_sha256": project_sha256,
        "cohort": {
            "cohort_id": str(cohort.cohort_id),
            "cohort_sha256": cohort.cohort_sha256,
            "persona_count": cohort.persona_count,
        },
        "simulation_requirement": simulation_requirement,
        "seed": seed,
        "rounds": rounds,
        "minutes_per_round": minutes_per_round,
        "initial_post": initial_post,
        "engine": RUN_ENGINE,
        "engine_version": RUN_ENGINE_VERSION,
        "model": {
            "name": model_name,
            "semantic_config_sha256": semantic_config_sha256,
            "prompt_schema_version": "matraix-semantic-profile/v1",
        },
        "simulation_context_sha256": simulation_context_sha256,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_context_bound_research_simulation_run_sha256(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    rounds: int,
    minutes_per_round: int,
    initial_post: str,
    model_name: str,
    semantic_config_sha256: str,
    simulation_context_sha256: str,
) -> str:
    canonical = canonical_context_bound_research_simulation_run_json(
        project_sha256,
        cohort,
        simulation_requirement,
        seed,
        rounds,
        minutes_per_round,
        initial_post,
        model_name,
        semantic_config_sha256,
        simulation_context_sha256,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_planned_research_simulation_run_json(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    model_name: str,
    semantic_config_sha256: str,
    simulation_context_sha256: str,
    simulation_plan_sha256: str,
) -> str:
    """Serialize a v4 run that binds both reality context and platform schedule."""
    payload = {
        "schema": PLANNED_RUN_SCHEMA_VERSION,
        "project_sha256": project_sha256,
        "cohort": {
            "cohort_id": str(cohort.cohort_id),
            "cohort_sha256": cohort.cohort_sha256,
            "persona_count": cohort.persona_count,
        },
        "simulation_requirement": simulation_requirement,
        "seed": seed,
        "engine": RUN_ENGINE,
        "engine_version": RUN_ENGINE_VERSION,
        "model": {
            "name": model_name,
            "semantic_config_sha256": semantic_config_sha256,
            "prompt_schema_version": "matraix-semantic-profile/v1",
        },
        "simulation_context_sha256": simulation_context_sha256,
        "simulation_plan_sha256": simulation_plan_sha256,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_planned_research_simulation_run_sha256(
    project_sha256: str,
    cohort: ResearchProjectCohortRef,
    simulation_requirement: str,
    seed: int,
    model_name: str,
    semantic_config_sha256: str,
    simulation_context_sha256: str,
    simulation_plan_sha256: str,
) -> str:
    canonical = canonical_planned_research_simulation_run_json(
        project_sha256,
        cohort,
        simulation_requirement,
        seed,
        model_name,
        semantic_config_sha256,
        simulation_context_sha256,
        simulation_plan_sha256,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def calculate_research_run_report_sha256(
    run_spec_sha256: str,
    artifact_sha256: str,
) -> str:
    payload = {
        "schema": "sandowl-research-run-report/v1",
        "run_spec_sha256": run_spec_sha256,
        "artifact_sha256": artifact_sha256,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def canonical_research_run_report_source(report: ResearchRunReport) -> str:
    """Serialize the complete sealed single-run record for cited ReportAgent use."""
    return json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )


def calculate_research_run_report_source_sha256(source: str) -> str:
    return sha256(source.encode("utf-8")).hexdigest()
