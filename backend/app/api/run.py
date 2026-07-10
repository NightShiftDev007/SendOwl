"""推演运行 API"""

from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.config import Config
from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.api.run")

run_bp = Blueprint("run", __name__, url_prefix="/api/run")


@run_bp.get("/health")
def health():
    return jsonify({"status": "ok", "module": "run"})


@run_bp.get("/<run_id>")
def get_run(run_id: str):
    registry.init_schema()
    run = registry.get_run(run_id)
    if not run:
        # 也可能是纯文件系统 run
        run_dir = os.path.join(Config.RUN_DIR, run_id)
        if not os.path.isdir(run_dir):
            return jsonify({"success": False, "error": "not found"}), 404
        run = {"id": run_id, "run_dir": run_dir, "status": "unknown"}
    else:
        run_dir = run.get("run_dir") or os.path.join(Config.RUN_DIR, run_id)

    # 附加 runner 状态
    try:
        from app.engine.simulation_runner import SimulationRunner

        state = SimulationRunner.get_run_state(run_id)
        if state:
            run["runner"] = state.to_dict() if hasattr(state, "to_dict") else {
                "runner_status": getattr(state, "runner_status", None),
                "current_round": getattr(state, "current_round", None),
            }
    except Exception:
        pass

    run["run_dir"] = run_dir
    return jsonify({"success": True, "data": run})


@run_bp.get("/<run_id>/actions")
def get_actions(run_id: str):
    registry.init_schema()
    run = registry.get_run(run_id)
    run_dir = (run or {}).get("run_dir") or os.path.join(Config.RUN_DIR, run_id)
    candidates = [
        Path(run_dir) / "actions.jsonl",
        Path(run_dir) / "twitter" / "actions.jsonl",
        Path(run_dir) / "reddit" / "actions.jsonl",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if not path:
        return jsonify({"success": True, "data": {"actions": [], "path": None}})

    limit = int(request.args.get("limit") or 500)
    actions = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                actions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return jsonify(
        {
            "success": True,
            "data": {"actions": actions, "path": str(path), "count": len(actions)},
        }
    )


@run_bp.post("/<run_id>/interview")
def interview(run_id: str):
    """代理到 SimulationRunner.interview；环境不可用时返回 stub。"""
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    prompt = body.get("prompt") or body.get("question") or "你怎么看当前政策？"

    try:
        from app.engine.simulation_runner import SimulationRunner

        state = SimulationRunner.get_run_state(run_id)
        status = getattr(getattr(state, "runner_status", None), "value", None) or (
            str(getattr(state, "runner_status", "")) if state else ""
        )
        # 环境存活时尝试采访
        if state and status in ("running", "completed", "paused", "alive"):
            if agent_id is not None:
                result = SimulationRunner.interview_agent(
                    simulation_id=run_id,
                    agent_id=int(agent_id),
                    prompt=prompt,
                )
            else:
                max_agents = int(body.get("max_agents") or 3)
                interviews = [
                    {"agent_id": i, "prompt": prompt} for i in range(max_agents)
                ]
                result = SimulationRunner.interview_agents_batch(
                    simulation_id=run_id,
                    interviews=interviews,
                )
            return jsonify({"success": True, "data": result, "mode": "live"})
    except Exception as e:
        logger.warning(f"interview live failed: {e}")

    # stub
    return jsonify(
        {
            "success": True,
            "mode": "stub",
            "data": {
                "run_id": run_id,
                "agent_id": agent_id,
                "prompt": prompt,
                "reply": "（离线 stub）模拟环境未存活，无法进行实时采访。",
            },
        }
    )
