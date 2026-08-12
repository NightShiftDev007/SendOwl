import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from oasis_worker.contracts import ActorSpec, ErrorResult, JobResult, JobSpec, PostSpec


@pytest.mark.integration
def test_cli_runs_real_oasis_and_persists_verified_sqlite(tmp_path: Path) -> None:
    output_directory = tmp_path / "artifacts"
    spec_path = tmp_path / "job.json"
    spec = JobSpec(
        schema_version="oasis-manual-smoke/v1",
        run_id="real-oasis-smoke",
        seed=20260812,
        output_directory=str(output_directory),
        actor=ActorSpec(
            agent_id=0,
            user_name="snapshot_company",
            name="Snapshot Company",
            bio="Frozen company actor for a manual platform smoke test.",
        ),
        posts=(
            PostSpec(content="First ordered intervention."),
            PostSpec(content="Second ordered intervention."),
        ),
    )
    spec_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "oasis_worker", "--job-spec", str(spec_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    result = JobResult.model_validate_json(completed.stdout)
    database_path = Path(result.artifact.database_path)
    assert database_path == output_directory / "real-oasis-smoke.sqlite3"
    assert database_path.is_file()
    assert result.artifact.sha256 == hashlib.sha256(database_path.read_bytes()).hexdigest()
    assert result.observed.user.user_name == "snapshot_company"
    assert [post.content for post in result.observed.posts] == [
        "First ordered intervention.",
        "Second ordered intervention.",
    ]
    assert [trace.action for trace in result.observed.traces] == [
        "sign_up",
        "create_post",
        "create_post",
    ]
    assert "no LLM inference" in result.limitations[1]

    with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT user_id, agent_id, user_name, name, bio FROM user ORDER BY user_id"
        ).fetchall() == [
            (
                0,
                0,
                "snapshot_company",
                "Snapshot Company",
                "Frozen company actor for a manual platform smoke test.",
            )
        ]
        assert connection.execute(
            "SELECT post_id, user_id, content FROM post ORDER BY post_id"
        ).fetchall() == [
            (1, 0, "First ordered intervention."),
            (2, 0, "Second ordered intervention."),
        ]
        assert connection.execute("SELECT action FROM trace ORDER BY rowid").fetchall() == [
            ("sign_up",),
            ("create_post",),
            ("create_post",),
        ]

    repeated = subprocess.run(
        [sys.executable, "-m", "oasis_worker", "--job-spec", str(spec_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 1
    assert repeated.stdout == ""
    error_result = ErrorResult.model_validate_json(repeated.stderr)
    assert error_result.error.type == "ArtifactConflictError"
    assert "refusing to overwrite existing OASIS artifact" in error_result.error.message
