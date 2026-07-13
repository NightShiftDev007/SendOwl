"""进度僵尸回收：惰性判定 + 定时扫双保险。

TTL（写入 design.md）：
- building / graph task: 2h → failed + task_lost
- preparing: 1h 无 progress 更新 → prepare_failed
- running 且 env 不存活：标 failed/stopped
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import Config
from app.utils.logger import get_logger

logger = get_logger("adc.progress.janitor")

BUILDING_TTL_SEC = int(os.environ.get("PROGRESS_TTL_BUILDING_SEC", str(2 * 3600)))
PREPARING_TTL_SEC = int(os.environ.get("PROGRESS_TTL_PREPARING_SEC", str(1 * 3600)))
RUNNING_CHECK_SEC = int(os.environ.get("PROGRESS_TTL_RUNNING_CHECK_SEC", str(5 * 60)))
JANITOR_INTERVAL_SEC = int(os.environ.get("PROGRESS_JANITOR_INTERVAL_SEC", str(5 * 60)))

_janitor_started = False
_janitor_lock = threading.Lock()


def _parse_ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        # 支持带 Z 的 ISO
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _age_sec(ts: Optional[float]) -> Optional[float]:
    if ts is None:
        return None
    return max(0.0, time.time() - ts)


def reclaim_stale_preparing(decision_id: str, *, force: bool = False) -> bool:
    """若 preparing 超时无进度，标 prepare_failed。返回是否回收。"""
    from app.ontology import registry

    registry.init_schema()
    dec = registry.get_decision(decision_id)
    if not dec:
        return False
    if str(dec.get("status") or "").lower() != "preparing":
        return False

    # 以 prepare_progress.updated_at 为准；无则用 decision.updated_at
    updated = None
    try:
        from app.engine.scenario_runner import _read_prepare_progress

        prep = _read_prepare_progress(decision_id) or {}
        updated = _parse_ts(prep.get("updated_at"))
    except Exception:
        prep = {}
        updated = None
    if updated is None:
        updated = _parse_ts(dec.get("updated_at") or dec.get("created_at"))

    age = _age_sec(updated)
    if not force and (age is None or age < PREPARING_TTL_SEC):
        return False

    msg = f"preparing 超时（>{PREPARING_TTL_SEC // 60}min 无进度），已自动标记失败"
    try:
        from app.engine.scenario_runner import _write_prepare_progress

        _write_prepare_progress(
            decision_id,
            status="failed",
            stage="timeout",
            message=msg,
        )
    except Exception:
        pass
    registry.update_decision(decision_id, status="prepare_failed")
    try:
        from app.api.stream import publish_decision_status

        publish_decision_status(decision_id)
    except Exception:
        pass
    logger.warning(f"[janitor] {decision_id}: {msg}")
    return True


def reclaim_stale_building(ontology_id: str, *, force: bool = False) -> bool:
    """building 超时 → failed，并 fail 关联 graph task。"""
    from app.ontology import registry
    from app.models.task import TaskManager

    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return False
    status = str(ont.get("status") or "").lower()
    if status not in ("building", "graph_building"):
        return False

    updated = _parse_ts(ont.get("updated_at") or ont.get("created_at"))
    age = _age_sec(updated)
    if not force and (age is None or age < BUILDING_TTL_SEC):
        return False

    tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
    msg = f"building 超时（>{BUILDING_TTL_SEC // 60}min），task_lost"
    if tid:
        try:
            TaskManager().fail_task(tid, msg)
        except Exception:
            pass
    registry.update_ontology(ontology_id, status="failed", build_task_id=None)
    logger.warning(f"[janitor] ontology {ontology_id}: {msg}")
    return True


def reclaim_dead_running(decision_id: str) -> bool:
    """running 但环境不存活 → failed。"""
    from app.ontology import registry
    from app.engine.simulation_runner import SimulationRunner

    registry.init_schema()
    dec = registry.get_decision(decision_id)
    if not dec or str(dec.get("status") or "").lower() != "running":
        return False

    runs = registry.list_runs_for_decision(decision_id) or []
    if not runs:
        return False

    any_alive = False
    any_running_run = False
    for r in runs:
        st = str((r or {}).get("status") or "").lower()
        if st == "running":
            any_running_run = True
        sim_id = (r or {}).get("sim_id")
        if not sim_id:
            continue
        try:
            if SimulationRunner.check_env_alive(sim_id):
                any_alive = True
                break
        except Exception:
            continue

    if any_alive:
        return False
    if not any_running_run:
        return False

    # 给启动留宽限，避免刚标 running 就误杀
    age = _age_sec(_parse_ts(dec.get("updated_at") or dec.get("created_at")))
    if age is not None and age < RUNNING_CHECK_SEC:
        return False

    # 全部 run 已终态则让 decision 自己收敛，不在此强制
    all_terminal = all(
        str((r or {}).get("status") or "").lower()
        in ("completed", "failed", "stalled", "timeout", "stopped")
        for r in runs
    )
    if all_terminal:
        return False

    registry.update_decision(decision_id, status="failed")
    for r in runs:
        if str((r or {}).get("status") or "").lower() == "running":
            try:
                registry.update_run(r["id"], status="failed", error="env_not_alive")
            except Exception:
                pass
    try:
        from app.api.stream import publish_decision_status

        publish_decision_status(decision_id)
    except Exception:
        pass
    logger.warning(f"[janitor] {decision_id}: running 但 env 不存活，已标 failed")
    return True


def sweep_once() -> Dict[str, int]:
    """全量扫一轮。"""
    from app.ontology import registry
    from app.models.task import TaskManager

    stats = {"preparing": 0, "building": 0, "running": 0, "tasks": 0}
    registry.init_schema()

    for dec in registry.list_decisions(include_trashed=False) or []:
        did = dec.get("id")
        if not did:
            continue
        st = str(dec.get("status") or "").lower()
        try:
            if st == "preparing" and reclaim_stale_preparing(did):
                stats["preparing"] += 1
            elif st == "running" and reclaim_dead_running(did):
                stats["running"] += 1
        except Exception as e:
            logger.debug(f"janitor decision {did}: {e}")

    for ont in registry.list_ontologies() or []:
        oid = ont.get("id")
        if not oid:
            continue
        try:
            if reclaim_stale_building(oid):
                stats["building"] += 1
        except Exception as e:
            logger.debug(f"janitor ontology {oid}: {e}")

    # 卡住的 processing task
    try:
        tm = TaskManager()
        for item in tm.list_tasks() or []:
            st = str(item.get("status") or "").lower()
            if st not in ("processing", "pending"):
                continue
            updated = _parse_ts(item.get("updated_at") or item.get("created_at"))
            age = _age_sec(updated)
            ttl = BUILDING_TTL_SEC if item.get("task_type") == "graph_build" else PREPARING_TTL_SEC
            if age is not None and age >= ttl:
                tid = item.get("task_id")
                if tid:
                    tm.fail_task(tid, f"task_lost: 超过 {ttl // 60}min 无更新")
                    stats["tasks"] += 1
    except Exception as e:
        logger.debug(f"janitor tasks: {e}")

    try:
        TaskManager().cleanup_old_tasks(max_age_hours=48)
    except Exception:
        pass

    return stats


def _janitor_loop() -> None:
    logger.info(
        f"progress_janitor 启动 interval={JANITOR_INTERVAL_SEC}s "
        f"preparing_ttl={PREPARING_TTL_SEC}s building_ttl={BUILDING_TTL_SEC}s"
    )
    while True:
        try:
            stats = sweep_once()
            if any(stats.values()):
                logger.info(f"progress_janitor sweep: {stats}")
        except Exception as e:
            logger.warning(f"progress_janitor sweep error: {e}")
        time.sleep(JANITOR_INTERVAL_SEC)


def start_progress_janitor() -> bool:
    """Flask debug reloader 下仅主进程启动。"""
    global _janitor_started
    with _janitor_lock:
        if _janitor_started:
            return False
        debug = str(os.environ.get("FLASK_DEBUG", "True")).lower() == "true"
        # 非 debug：直接启；debug：仅 WERKZEUG_RUN_MAIN=true
        if debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            return False
        t = threading.Thread(target=_janitor_loop, name="progress-janitor", daemon=True)
        t.start()
        _janitor_started = True
        return True


def maybe_reclaim_on_read(decision_id: str) -> None:
    """惰性：get_status / Envelope 构建时调用。"""
    try:
        reclaim_stale_preparing(decision_id)
    except Exception:
        pass
