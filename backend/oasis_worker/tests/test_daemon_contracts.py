import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from oasis_worker.contracts import (
    ArtifactResult,
    JobResult,
    ObservedPost,
    ObservedState,
    ObservedUser,
    SignupTrace,
    SignupTraceInfo,
)
from oasis_worker.daemon import load_daemon_settings, normalize_job_result
from oasis_worker.errors import OasisWorkerError
from oasis_worker.queue_contracts import ClaimedRun, QueuePost

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
SNAPSHOT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _claimed() -> ClaimedRun:
    company_name = "Acme"
    username = "company_9e6956e73c96d447"
    return ClaimedRun(
        id=RUN_ID,
        status="running",
        mode="reddit_manual_smoke",
        scenario_id=UUID("33333333-3333-4333-8333-333333333333"),
        scenario_sha256="a" * 64,
        variant_id=UUID("44444444-4444-4444-8444-444444444444"),
        variant_name="Clarify",
        world_snapshot_id=SNAPSHOT_ID,
        snapshot_sha256="b" * 64,
        company_name=company_name,
        seed=7,
        actor_user_name=username,
        actor_name=company_name,
        actor_bio=(
            f"Frozen company actor from WorldSnapshot {SNAPSHOT_ID}. "
            "Manual OASIS platform smoke only."
        ),
        input_sha256="c" * 64,
        posts=(QueuePost(position=0, content="Verified post.", offset_minutes=0),),
    )


def _job_result(artifact: Path, reported_path: Path) -> JobResult:
    run = _claimed()
    content = artifact.read_bytes()
    created_at = "2026-08-12 00:00:00"
    return JobResult(
        schema_version="oasis-manual-smoke/v1",
        run_id=str(run.id),
        seed=run.seed,
        engine="camel-oasis",
        engine_version="0.2.5",
        camel_version="0.2.78",
        mode="reddit_manual_smoke",
        artifact=ArtifactResult(
            database_path=str(reported_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        ),
        observed=ObservedState(
            user=ObservedUser(
                user_id=0,
                agent_id=0,
                user_name=run.actor_user_name,
                name=run.actor_name,
                bio=run.actor_bio,
                created_at=created_at,
            ),
            posts=(
                ObservedPost(
                    post_id=1,
                    user_id=0,
                    content="Verified post.",
                    created_at=created_at,
                ),
            ),
            traces=(
                SignupTrace(
                    position=0,
                    user_id=0,
                    created_at=created_at,
                    action="sign_up",
                    info=SignupTraceInfo(
                        name=run.actor_name,
                        user_name=run.actor_user_name,
                        bio=run.actor_bio,
                    ),
                ),
                # The exact trace subtype is exercised by the real integration test.
            ),
        ),
        limitations=("Manual smoke only.",),
    )


def test_daemon_settings_require_explicit_environment_and_normalize_async_url() -> None:
    settings = load_daemon_settings(
        {
            "DATABASE_URL": "postgresql+asyncpg://app:secret@postgres:5432/decision",
            "OASIS_ARTIFACT_ROOT": "/artifacts",
            "OASIS_WORKER_ID": "compose-oasis-worker",
        }
    )

    assert settings.database_url == "postgresql://app:secret@postgres:5432/decision"
    assert settings.artifact_root == Path("/artifacts")
    assert settings.worker_id == "compose-oasis-worker"


def test_daemon_settings_reject_missing_values_without_echoing_secrets() -> None:
    with pytest.raises(OasisWorkerError, match="OASIS_ARTIFACT_ROOT is required"):
        load_daemon_settings(
            {
                "DATABASE_URL": "postgresql://app:secret@postgres:5432/decision",
                "OASIS_WORKER_ID": "worker",
            }
        )


def test_normalize_result_rejects_artifact_path_misbinding(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    expected_directory = artifact_root / str(RUN_ID)
    expected_directory.mkdir(parents=True)
    expected_path = expected_directory / f"{RUN_ID}.sqlite3"
    expected_path.write_bytes(b"verified artifact")
    wrong_path = tmp_path / "wrong.sqlite3"

    with pytest.raises(OasisWorkerError, match="artifact path mismatch"):
        normalize_job_result(
            _claimed(),
            artifact_root,
            _job_result(expected_path, wrong_path),
        )
