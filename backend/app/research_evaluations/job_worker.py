"""Dispatch queued Project-bound evaluations to the pinned MatrAIx Harbor runner."""

import asyncio
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import load_runtime_settings
from app.database import DatabaseConnector
from app.research_evaluations.harbor import materialize_harbor_job
from app.research_evaluations.jobs import (
    claim_research_evaluation_job,
    complete_research_evaluation_job,
    fail_active_research_evaluation_jobs,
    fail_research_evaluation_job,
)


def _json_request(method: str, url: str, payload: dict[str, object] | None = None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        url,
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Harbor runner request failed: {type(error).__name__}") from error


def _collect_outputs(job_name: str) -> tuple[dict[str, object], ...]:
    root = Path(os.environ.get("HARBOR_JOBS_PATH", "/harbor-jobs")) / job_name
    outputs: list[dict[str, object]] = []
    if not root.is_dir():
        return ()
    for path in sorted(root.rglob("*.json"))[:100]:
        if path.stat().st_size > 2_000_000:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        outputs.append({"path": str(path.relative_to(root)), "value": value})
    return tuple(outputs)


async def _execute_one(connector: DatabaseConnector, runner_url: str) -> bool:
    job = None
    try:
        async with connector.session() as session:
            job = await claim_research_evaluation_job(session)
            if job is None:
                return False
            job_name, config_yaml = await materialize_harbor_job(session, job)
        created = await asyncio.to_thread(
            _json_request,
            "POST",
            f"{runner_url}/v1/runs",
            {
                "taskType": "harbor_job",
                "payload": {
                    "jobName": job_name,
                    "configYaml": config_yaml,
                    "repoRoot": "/workspace",
                    "jobsDir": "jobs",
                    "env": {"PYTHONPATH": os.environ.get("HARBOR_PYTHONPATH", "")},
                },
            },
        )
        remote_id = str(created["id"])
        while True:
            detail = await asyncio.to_thread(
                _json_request, "GET", f"{runner_url}/v1/runs/{remote_id}"
            )
            if detail["status"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(5)
        if detail["status"] != "succeeded":
            raise RuntimeError(str(detail.get("error") or "Harbor job failed"))
        outputs = await asyncio.to_thread(_collect_outputs, job_name)
        trajectory = {"schema_version": "sandowl-harbor-trajectory/v1", "files": outputs}
        artifact = {"schema_version": "sandowl-harbor-artifact/v1", "files": outputs}
        verifier_files = tuple(
            item for item in outputs if "verifier" in str(item.get("path") or "")
        )
        verifier = {"schema_version": "sandowl-harbor-verifier/v1", "files": verifier_files}
        reward_value = 1.0 if verifier_files else 0.0
        reward = {
            "schema_version": "sandowl-harbor-reward/v1",
            "value": reward_value,
            "source": "task_owned_verifier",
        }
        async with connector.session() as session:
            await complete_research_evaluation_job(
                session,
                job.id,
                remote_run_id=remote_id,
                trajectory=trajectory,
                artifact=artifact,
                verifier=verifier,
                reward=reward,
                reward_value=reward_value,
            )
    except Exception as error:
        if job is None:
            raise
        async with connector.session() as session:
            await fail_research_evaluation_job(session, job.id, error)
    return True


async def run_worker(environment: dict[str, str]) -> None:
    settings = load_runtime_settings(environment)
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required for Harbor evaluation jobs")
    runner_url = environment.get("HARBOR_RUNNER_URL", "http://harbor-runner:9100").rstrip("/")
    connector = DatabaseConnector.create(settings.database_url)
    try:
        async with connector.session() as session:
            await fail_active_research_evaluation_jobs(
                session,
                RuntimeError("Harbor evaluation worker restarted before the job completed"),
            )
        while True:
            worked = await _execute_one(connector, runner_url)
            if not worked:
                await asyncio.sleep(2)
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(run_worker(dict(os.environ)))
