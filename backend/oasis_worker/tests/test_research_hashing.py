"""Independent research-run content addresses used by the worker."""

from oasis_worker.research_hashing import (
    context_bound_research_run_spec_sha256,
    planned_research_run_spec_sha256,
    research_run_report_sha256,
    research_run_spec_sha256,
    simulation_context_sha256,
    simulation_plan_sha256,
)


def test_research_run_hash_changes_with_execution_input() -> None:
    first = research_run_spec_sha256(
        "a" * 64,
        "10000000-0000-4000-8000-000000000001",
        "c" * 64,
        5,
        "运行一次有界群体模拟。",
        7,
        1,
        60,
        "虚构机构发布一条合成说明。",
        "provider-model",
        "b" * 64,
    )
    second = research_run_spec_sha256(
        "a" * 64,
        "10000000-0000-4000-8000-000000000001",
        "c" * 64,
        5,
        "运行一次有界群体模拟。",
        8,
        1,
        60,
        "虚构机构发布一条合成说明。",
        "provider-model",
        "b" * 64,
    )

    assert first != second
    assert research_run_report_sha256(first, "c" * 64) == research_run_report_sha256(
        first, "c" * 64
    )


def test_context_bound_run_hash_binds_the_exact_context_digest() -> None:
    context_digest = simulation_context_sha256(
        {
            "schema_version": "sandowl-simulation-context/v1",
            "snapshot_sha256": "d" * 64,
        }
    )
    values = (
        "a" * 64,
        "10000000-0000-4000-8000-000000000001",
        "c" * 64,
        5,
        "运行一次有界群体模拟。",
        7,
        1,
        60,
        "虚构机构发布一条合成说明。",
        "provider-model",
        "b" * 64,
    )

    assert context_bound_research_run_spec_sha256(*values, context_digest) != (
        context_bound_research_run_spec_sha256(*values, "e" * 64)
    )


def test_planned_run_hash_binds_the_exact_schedule_digest() -> None:
    plan_digest = simulation_plan_sha256(
        {
            "schema_version": "sandowl-simulation-plan/v1",
            "rounds": 3,
            "minutes_per_round": 480,
        }
    )
    values = (
        "a" * 64,
        "10000000-0000-4000-8000-000000000001",
        "c" * 64,
        5,
        "运行一次有界群体模拟。",
        7,
        "provider-model",
        "b" * 64,
        "d" * 64,
    )

    assert planned_research_run_spec_sha256(*values, plan_digest) != (
        planned_research_run_spec_sha256(*values, "e" * 64)
    )
