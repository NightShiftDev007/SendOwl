"""Materialize bounded MatrAIx Harbor jobs from immutable SandOwl targets."""

# ruff: noqa: E501

import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.populations.repository import get_cohort
from app.research_evaluations.models import (
    ResearchEvaluationJobRecord,
    ResearchEvaluationTargetRecord,
)
from app.research_evaluations.targets import research_evaluation_target_detail


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _runner_path(workspace: Path, path: Path) -> PurePosixPath:
    relative = path.relative_to(workspace)
    runner_workspace = PurePosixPath(os.environ.get("HARBOR_RUNNER_WORKSPACE_PATH", "/workspace"))
    return runner_workspace / PurePosixPath(relative.as_posix())


def _generic_verifier(criteria: tuple[str, ...]) -> str:
    return f"""import json, os
from pathlib import Path
output = Path('/app/output/result.json')
if not output.is_file():
    raise SystemExit('result.json is missing')
payload = json.loads(output.read_text())
if not isinstance(payload, dict) or not str(payload.get('summary') or '').strip():
    raise SystemExit('result.summary is required')
evidence = payload.get('criteriaEvidence')
if not isinstance(evidence, list) or len(evidence) != {len(criteria)}:
    raise SystemExit('criteriaEvidence count must match the frozen criteria')
verifier = Path(os.environ.get('HARBOR_VERIFIER_DIR') or '/logs/verifier')
verifier.mkdir(parents=True, exist_ok=True)
(verifier / 'structured_output.json').write_text(json.dumps({{'criteria': {json.dumps(criteria, ensure_ascii=False)}, 'result': payload}}, ensure_ascii=False))
(verifier / 'reward.txt').write_text('1')
"""


def _materialize_dynamic_task(workspace: Path, job: ResearchEvaluationJobRecord, target) -> Path:
    task_path = workspace / "sandowl_tasks" / job.job_sha256
    payload = target.payload
    metadata_type = "chatbot" if payload.kind == "chat" else "web"
    environment = (
        "application/shared-chat-persona"
        if payload.kind == "chat"
        else "application/shared-web-playwright"
    )
    network = '\nnetwork_mode = "public"' if payload.kind == "web" else ""
    _write(
        task_path / "task.toml",
        f'''version = "1.0"\nartifacts = ["/app/output"]\n\n[task]\nname = "sandowl/{payload.kind}-{job.job_sha256[:12]}"\n\n[metadata]\ndifficulty = "medium"\ntype = "{metadata_type}"\ndomain = "research"\ntags = ["sandowl", "project-bound"]\n\n[verifier]\ntimeout_sec = 300.0\n\n[agent]\ntimeout_sec = 900.0{network}\n\n[environment]\ndefinition = "{environment}"\ncpus = 2\nmemory_mb = 4096\nstorage_mb = 10240{network}\n''',
    )
    criteria = "\n".join(f"- {item}" for item in payload.success_criteria)
    _write(task_path / "input" / "context.md", payload.task_goal)
    _write(
        task_path / "instruction.md",
        f"""# {payload.title}

Complete the task at {payload.target_url}. Use the frozen persona profile and the context in `input/context.md`.

Success criteria:
{criteria}

Write `/app/output/result.json` with `summary` and one `criteriaEvidence` item per criterion. Do not claim evidence you did not observe.
""",
    )
    if payload.kind == "chat" and payload.target_url is not None:
        parsed = urlsplit(payload.target_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/v1/messages"
        _write(
            task_path / "input" / "chatbot.yaml",
            f"""transport: sidecar_http
runtimeDefaults:
  applicationId: sandowl_project_target
  applicationContext: research
  domain: research
capabilities: [text_chat]
connection:
  baseUrl: {base_url}
  healthPath: /
protocol:
  sendMessage:
    method: POST
    path: {path}
    sessionIdField: ""
    messageField: message
    titleField: ""
    botTypeField: ""
    staticBody: {{}}
  response:
    sessionIdField: ""
    replyField: reply
artifacts:
  transcript: transcript.json
  applicationResult: result.json
  feedback: user_feedback.json
""",
        )
    _write(task_path / "tests" / "test_state.py", _generic_verifier(payload.success_criteria))
    _write(
        task_path / "tests" / "test.sh",
        "#!/bin/sh\nset -eu\npython /tests/test_state.py\n",
    )
    return task_path


async def materialize_harbor_job(
    session: AsyncSession,
    job: ResearchEvaluationJobRecord,
) -> tuple[str, str]:
    workspace = Path(os.environ.get("HARBOR_WORKSPACE_PATH", "/harbor-workspace"))
    target_record = await session.get(ResearchEvaluationTargetRecord, job.target_id)
    if target_record is None:
        raise RuntimeError("evaluation target disappeared before Harbor dispatch")
    target = research_evaluation_target_detail(target_record)
    cohort = await get_cohort(session, job.cohort_id)
    persona_dir = workspace / "sandowl_personas" / job.job_sha256
    persona_paths: list[Path] = []
    for member in cohort.members:
        path = persona_dir / f"persona_{member.position:04d}.yaml"
        _write(
            path,
            yaml.safe_dump(
                {
                    "persona_id": member.persona.persona_id,
                    "display_name": member.persona.display_name,
                    "dimensions": {item.name: item.value for item in member.persona.attributes},
                },
                allow_unicode=True,
                sort_keys=True,
            ),
        )
        persona_paths.append(path)
    if target.payload.kind == "app":
        if target.payload.task_package is None:
            raise RuntimeError("App target has no Harbor task package")
        task_path = workspace / target.payload.task_package
        if not task_path.is_dir() or workspace not in task_path.resolve().parents:
            raise RuntimeError("App Harbor task package is unavailable in the pinned runtime")
    else:
        task_path = _materialize_dynamic_task(workspace, job, target)
    runner_task_path = _runner_path(workspace, task_path)
    runner_persona_paths = tuple(_runner_path(workspace, path) for path in persona_paths)
    agent_name = {
        "chat": "persona-user-sim",
        "web": "persona-openhands-sdk",
        "app": "persona-computer-1",
    }[target.payload.kind]
    model_name = os.environ.get("HARBOR_MODEL_NAME", "dashscope/qwen3.7-plus")
    config = {
        "job_name": f"sandowl-{job.id}",
        "jobs_dir": "jobs",
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "quiet": True,
        "environment": {"type": "docker", "delete": True},
        "agents": [
            {
                "name": agent_name,
                "model_name": model_name,
                "kwargs": {"persona_path": str(path)},
            }
            for path in runner_persona_paths
        ],
        "tasks": [{"path": str(runner_task_path)}],
    }
    return config["job_name"], yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
