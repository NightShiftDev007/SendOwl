"""Application metadata checks for normalized OASIS platform-smoke state."""

from app.database import ApplicationBase
from app.simulations import models as simulation_models

del simulation_models


def test_platform_smoke_schema_uses_normalized_run_post_and_heartbeat_tables() -> None:
    assert {
        "simulation_runs",
        "simulation_run_posts",
        "simulation_worker_heartbeats",
    }.issubset(ApplicationBase.metadata.tables)
    runs = ApplicationBase.metadata.tables["simulation_runs"]
    posts = ApplicationBase.metadata.tables["simulation_run_posts"]

    assert {
        "input_sha256",
        "input_sealed_at",
        "claimed_by_worker_id",
        "artifact_sha256",
        "error_code",
    }.issubset(runs.columns.keys())
    assert {"run_id", "position", "content", "offset_minutes"}.issubset(posts.columns.keys())
    assert any(
        constraint.name == "uq_simulation_runs_input_sha256" for constraint in runs.constraints
    )
