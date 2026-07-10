"""
推演引擎契约：物化 run 目录并启动 / 等待 SimulationRunner
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from app.config import Config
from app.engine.intervention import (
    Intervention,
    apply_to_config,
    load_agents_index,
)
from app.utils.logger import get_logger

logger = get_logger("adc.engine.contract")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_config(
    run_id: str,
    max_rounds: int = 10,
    seed: int = 42,
) -> Dict[str, Any]:
    hours = max(1, max_rounds)  # minutes_per_round=60 → rounds ≈ hours
    return {
        "simulation_id": run_id,
        "time_config": {
            "total_simulation_hours": hours,
            "minutes_per_round": 60,
            "agents_per_hour_min": 2,
            "agents_per_hour_max": 12,
        },
        "event_config": {
            "initial_posts": [],
            "hot_topics": [],
        },
        "platform": "twitter",
        "seed": seed,
    }


def _copy_profiles(profiles_dir: str, run_dir: str) -> None:
    for name in (
        "twitter_profiles.csv",
        "reddit_profiles.json",
        "network.json",
        "entity_agent_mapping.json",
    ):
        src = os.path.join(profiles_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(run_dir, name))


def _load_profiles_from_dir(profiles_dir: str) -> List[Dict[str, Any]]:
    reddit = os.path.join(profiles_dir, "reddit_profiles.json")
    if os.path.exists(reddit):
        with open(reddit, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    # 最小回退：从 twitter csv
    csv_path = os.path.join(profiles_dir, "twitter_profiles.csv")
    if os.path.exists(csv_path):
        import csv

        rows = []
        with open(csv_path, encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f)):
                rows.append(
                    {
                        "user_id": int(row.get("user_id", i)),
                        "name": row.get("name", f"agent_{i}"),
                        "username": row.get("username", ""),
                        "bio": row.get("description") or row.get("user_char") or "",
                        "persona": row.get("user_char") or "",
                    }
                )
        return rows
    return []


def _db_post_count(run_dir: str) -> int:
    import sqlite3

    for root, _, files in os.walk(run_dir):
        for name in files:
            if name.endswith(".db"):
                path = os.path.join(root, name)
                try:
                    conn = sqlite3.connect(path)
                    n = conn.execute("SELECT COUNT(*) FROM post").fetchone()[0]
                    conn.close()
                    return int(n)
                except Exception:
                    continue
    return 0


def _find_actions_path(run_dir: str) -> Optional[str]:
    candidates = [
        os.path.join(run_dir, "actions.jsonl"),
        os.path.join(run_dir, "twitter", "actions.jsonl"),
        os.path.join(run_dir, "reddit", "actions.jsonl"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _find_db_path(run_dir: str) -> Optional[str]:
    for root, _, files in os.walk(run_dir):
        for name in files:
            if name.endswith(".db"):
                return os.path.join(root, name)
    return None


def materialize_run_dir(
    run_id: str,
    profiles_dir: str,
    config: Optional[Dict[str, Any]] = None,
    intervention: Union[Intervention, Dict, List, None] = None,
    seed: int = 42,
    max_rounds: int = 10,
) -> str:
    """创建 Config.RUN_DIR/{run_id} 并写入配置与 profiles。"""
    run_dir = os.path.join(Config.RUN_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    _copy_profiles(profiles_dir, run_dir)

    cfg = deepcopy(config) if config else _default_config(run_id, max_rounds, seed)
    cfg["simulation_id"] = run_id
    cfg["seed"] = seed
    if "time_config" in cfg:
        cfg["time_config"]["total_simulation_hours"] = min(
            int(cfg["time_config"].get("total_simulation_hours", max_rounds)),
            max(1, max_rounds),
        )

    profiles = _load_profiles_from_dir(run_dir)
    agents = load_agents_index(profiles)
    cfg = apply_to_config(cfg, intervention, agents)

    config_path = os.path.join(run_dir, "simulation_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    state = {
        "simulation_id": run_id,
        "status": "ready",
        "seed": seed,
        "created_at": _utc_now(),
    }
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return run_dir


def wait_for_simulation(
    run_id: str,
    max_rounds: int = 10,
    poll_sec: float = 5.0,
    stall_sec: float = 180.0,
    timeout_sec: float = 45 * 60,
) -> Dict[str, Any]:
    """轮询 SimulationRunner 状态直到完成/卡住/超时。"""
    from app.engine.simulation_runner import RunnerStatus, SimulationRunner

    t0 = time.time()
    last_progress_at = t0
    last_round = -1
    last_posts = -1
    runner = "starting"
    run_dir = os.path.join(Config.RUN_DIR, run_id)

    while True:
        state = SimulationRunner.get_run_state(run_id)
        runner = (
            state.runner_status.value
            if state and hasattr(state.runner_status, "value")
            else (str(state.runner_status) if state else "unknown")
        )
        current_round = getattr(state, "current_round", None) if state else None
        if current_round is None and state:
            current_round = getattr(state, "twitter_current_round", None)
        posts = _db_post_count(run_dir)

        try:
            cr = int(current_round) if current_round is not None else -1
        except (TypeError, ValueError):
            cr = -1
        if cr > last_round or posts > last_posts:
            last_round = max(last_round, cr)
            last_posts = max(last_posts, posts)
            last_progress_at = time.time()

        if runner in (
            RunnerStatus.COMPLETED.value,
            RunnerStatus.STOPPED.value,
            RunnerStatus.FAILED.value,
            "completed",
            "stopped",
            "failed",
            "error",
        ):
            break

        if runner in ("idle", RunnerStatus.IDLE.value) and (
            posts > 0 or _find_actions_path(run_dir)
        ):
            runner = "completed"
            break

        if time.time() - last_progress_at > stall_sec and (time.time() - t0) > 60:
            try:
                SimulationRunner.stop_simulation(run_id)
            except Exception:
                pass
            runner = "stalled"
            break

        if time.time() - t0 > timeout_sec:
            try:
                SimulationRunner.stop_simulation(run_id)
            except Exception:
                pass
            runner = "timeout"
            break

        time.sleep(poll_sec)

    return {
        "run_id": run_id,
        "status": runner,
        "db_path": _find_db_path(run_dir),
        "actions_path": _find_actions_path(run_dir),
        "posts_count": _db_post_count(run_dir),
        "elapsed_sec": int(time.time() - t0),
    }


def run_engine(
    run_dir: Optional[str] = None,
    profiles_dir: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    network: Optional[Dict[str, Any]] = None,
    intervention: Union[Intervention, Dict, List, None] = None,
    seed: int = 42,
    max_rounds: int = 10,
    platform: str = "twitter",
    run_id: Optional[str] = None,
    wait: bool = True,
) -> Dict[str, Any]:
    """
    物化 run 目录并启动模拟。

    若 run_dir 已存在且含 simulation_config.json，可跳过 profiles_dir。
    """
    Config.ensure_directories()
    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"

    if profiles_dir:
        materialized = materialize_run_dir(
            run_id=run_id,
            profiles_dir=profiles_dir,
            config=config,
            intervention=intervention,
            seed=seed,
            max_rounds=max_rounds,
        )
    elif run_dir:
        materialized = run_dir
        # 仍可 patch intervention
        cfg_path = os.path.join(materialized, "simulation_config.json")
        if os.path.exists(cfg_path) and intervention is not None:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            profiles = _load_profiles_from_dir(materialized)
            cfg = apply_to_config(cfg, intervention, load_agents_index(profiles))
            cfg["seed"] = seed
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    else:
        raise ValueError("需要 profiles_dir 或 run_dir")

    # 可选写入 network
    if network:
        with open(
            os.path.join(materialized, "network.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(network, f, ensure_ascii=False, indent=2)

    # 确保 run 落在 Config.RUN_DIR 下（SimulationRunner 约定）
    expected = os.path.join(Config.RUN_DIR, run_id)
    if os.path.abspath(materialized) != os.path.abspath(expected):
        if os.path.exists(expected):
            shutil.rmtree(expected)
        shutil.copytree(materialized, expected)
        materialized = expected

    from app.engine.simulation_runner import SimulationRunner

    try:
        SimulationRunner.start_simulation(
            simulation_id=run_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=False,
            no_wait=True,
        )
    except Exception as e:
        logger.exception(f"启动模拟失败: {run_id}")
        return {
            "run_id": run_id,
            "status": "failed",
            "db_path": None,
            "actions_path": None,
            "posts_count": 0,
            "error": str(e),
        }

    if not wait:
        return {
            "run_id": run_id,
            "status": "running",
            "db_path": None,
            "actions_path": None,
            "posts_count": 0,
        }

    result = wait_for_simulation(run_id, max_rounds=max_rounds)
    return result
