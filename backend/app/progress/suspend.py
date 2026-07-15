"""任务入回收站 / 彻底删除时终止在途工作，并阻止 crash recovery 自动续跑。

语义说明：
- 不是可恢复的「暂停」：会 stop 推演、fail task、cancel 报告生成
- 进回收站：磁盘产物保留，恢复后须用户显式重试
- 彻底删除：再次终止 + 清磁盘/元数据
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Set

from app.utils.logger import get_logger

logger = get_logger("adc.progress.suspend")

TRASH_SUSPEND_REASON = "任务已移入回收站，已停止自动续跑"


def suspend_decision_work(
    decision_id: str,
    *,
    reason: str = TRASH_SUSPEND_REASON,
) -> Dict[str, Any]:
    """停止该决策关联的推演 / prepare / 报告，并 fail 相关 task。"""
    summary: Dict[str, Any] = {
        "decision_id": decision_id,
        "sims_stopped": [],
        "prepare_tasks_failed": [],
        "reports_cancelled": [],
        "errors": [],
    }
    if not decision_id:
        return summary

    sim_ids = _collect_sim_ids(decision_id)
    for sim_id in sim_ids:
        try:
            _stop_sim(sim_id, summary)
        except Exception as e:
            summary["errors"].append(f"stop {sim_id}: {e}")
            logger.warning(f"suspend stop sim failed sim={sim_id}: {e}")
        try:
            _fail_prepare_task(sim_id, reason, summary)
        except Exception as e:
            summary["errors"].append(f"prepare {sim_id}: {e}")
            logger.warning(f"suspend fail prepare failed sim={sim_id}: {e}")

    try:
        _cancel_reports_for_decision(decision_id, sim_ids, reason, summary)
    except Exception as e:
        summary["errors"].append(f"reports: {e}")
        logger.warning(f"suspend cancel reports failed decision={decision_id}: {e}")

    # 把决策状态从 preparing/running 挪走，避免恢复后被 crash recovery 自动续跑
    try:
        from app.ontology import registry

        dec = registry.get_decision(decision_id) or {}
        st = str(dec.get("status") or "").lower()
        if st == "preparing":
            registry.update_decision(decision_id, status="prepare_failed")
            summary["decision_status"] = "prepare_failed"
        elif st == "running":
            registry.update_decision(decision_id, status="failed")
            summary["decision_status"] = "failed"
    except Exception as e:
        summary["errors"].append(f"decision_status: {e}")
        logger.warning(f"suspend update decision status failed: {e}")

    try:
        from app.engine.scenario_runner import _write_prepare_progress

        _write_prepare_progress(
            decision_id,
            status="cancelled",
            stage="cancelled",
            message=reason,
            progress=0,
        )
    except Exception as e:
        logger.debug(f"suspend write prepare_progress: {e}")

    logger.info(
        "suspend decision=%s sims=%s reports=%s prepare=%s",
        decision_id,
        len(summary["sims_stopped"]),
        len(summary["reports_cancelled"]),
        len(summary["prepare_tasks_failed"]),
    )
    return summary


def suspend_ontology_work(
    ontology_id: str,
    *,
    reason: str = TRASH_SUSPEND_REASON,
) -> Dict[str, Any]:
    """挂起本体建图 task（若仍在 processing）。"""
    summary: Dict[str, Any] = {
        "ontology_id": ontology_id,
        "build_tasks_failed": [],
        "errors": [],
    }
    if not ontology_id:
        return summary
    try:
        from app.ontology import registry
        from app.models.task import TaskManager

        ont = registry.get_ontology(ontology_id)
        if not ont:
            return summary
        tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
        if not tid:
            return summary
        tm = TaskManager()
        task = tm.get_task(tid)
        if not task:
            return summary
        st = str(getattr(task.status, "value", task.status) or "").lower()
        if st in ("processing", "pending"):
            tm.fail_task(tid, reason)
            summary["build_tasks_failed"].append(tid)
            try:
                registry.update_ontology(ontology_id, status="failed", build_task_id=None)
            except Exception:
                pass
    except Exception as e:
        summary["errors"].append(str(e))
        logger.warning(f"suspend ontology build failed oid={ontology_id}: {e}")
    return summary


def is_decision_trashed(decision_id: Optional[str]) -> bool:
    if not decision_id:
        return False
    try:
        from app.ontology import registry

        dec = registry.get_decision(decision_id)
        if not dec:
            return True
        return bool(str(dec.get("trashed_at") or "").strip())
    except Exception:
        return False


def resolve_decision_id_for_sim(sim_id: Optional[str]) -> Optional[str]:
    """从 sim / runs / project_id 反查 decision_id。"""
    if not sim_id:
        return None
    try:
        from app.models.store import connection

        with connection() as conn:
            row = conn.execute(
                """
                SELECT s.decision_id
                FROM runs r
                JOIN scenarios s ON s.id = r.scenario_id
                WHERE r.sim_id = ?
                LIMIT 1
                """,
                (sim_id,),
            ).fetchone()
        if row:
            did = dict(row).get("decision_id")
            if did:
                return str(did)
    except Exception as e:
        logger.debug(f"resolve decision via runs failed sim={sim_id}: {e}")

    try:
        from app.engine.simulation_manager import SimulationManager

        state = SimulationManager().get_simulation(sim_id)
        pid = (getattr(state, "project_id", None) or "") if state else ""
        if str(pid).startswith("dec_"):
            return str(pid)
    except Exception as e:
        logger.debug(f"resolve decision via sim state failed sim={sim_id}: {e}")
    return None


def is_sim_owner_trashed(sim_id: Optional[str]) -> bool:
    did = resolve_decision_id_for_sim(sim_id)
    if did:
        return is_decision_trashed(did)
    return False


def collect_sim_ids(decision_id: str) -> Set[str]:
    """收集决策关联的所有 simulation_id。"""
    ids: Set[str] = set()
    try:
        from app.ontology import registry

        for run in registry.list_runs_for_decision(decision_id) or []:
            sid = run.get("sim_id")
            if sid:
                ids.add(str(sid))
    except Exception as e:
        logger.debug(f"list runs for suspend failed: {e}")

    try:
        from app.engine.simulation_manager import SimulationManager

        for state in SimulationManager().list_simulations(project_id=decision_id) or []:
            sid = getattr(state, "simulation_id", None) or getattr(state, "id", None)
            if sid:
                ids.add(str(sid))
    except Exception as e:
        logger.debug(f"list sims for suspend failed: {e}")
    return ids


def _collect_sim_ids(decision_id: str) -> Set[str]:
    return collect_sim_ids(decision_id)


def _stop_sim(sim_id: str, summary: Dict[str, Any]) -> None:
    from app.engine.simulation_runner import SimulationRunner

    try:
        SimulationRunner.stop_simulation(sim_id)
        summary["sims_stopped"].append(sim_id)
    except Exception as e:
        # 未在跑的 sim 会抛错，忽略
        logger.debug(f"stop_simulation {sim_id}: {e}")


def _fail_prepare_task(sim_id: str, reason: str, summary: Dict[str, Any]) -> None:
    from app.engine.simulation_manager import SimulationManager
    from app.models.task import TaskManager

    mgr = SimulationManager()
    state = mgr.get_simulation(sim_id)
    if not state:
        return
    tid = getattr(state, "prepare_task_id", None)
    if not tid:
        return
    tm = TaskManager()
    task = tm.get_task(tid)
    if not task:
        return
    st = str(getattr(task.status, "value", task.status) or "").lower()
    if st in ("processing", "pending"):
        tm.fail_task(tid, reason)
        summary["prepare_tasks_failed"].append(tid)


def _cancel_reports_for_decision(
    decision_id: str,
    sim_ids: Set[str],
    reason: str,
    summary: Dict[str, Any],
) -> None:
    from app.config import Config
    from app.decision.report_agent import ReportManager
    from app.models.task import TaskManager

    reports_root = getattr(Config, "REPORTS_DIR", None) or os.path.join(
        Config.UPLOAD_FOLDER, "reports"
    )
    if not os.path.isdir(reports_root):
        return

    tm = TaskManager()
    for name in os.listdir(reports_root):
        if not name.startswith("report_"):
            continue
        report_id = name
        meta = ReportManager.get_generate_task_meta(report_id) or {}
        meta_did = meta.get("decision_id")
        meta_sid = meta.get("simulation_id")
        linked = False
        if meta_did and str(meta_did) == decision_id:
            linked = True
        elif meta_sid and str(meta_sid) in sim_ids:
            linked = True
        elif meta_sid and resolve_decision_id_for_sim(str(meta_sid)) == decision_id:
            linked = True
        if not linked:
            continue

        ReportManager.cancel_generate(
            report_id, reason=reason, decision_id=decision_id
        )
        tid = meta.get("task_id")
        if tid:
            task = tm.get_task(tid)
            if task:
                st = str(getattr(task.status, "value", task.status) or "").lower()
                if st in ("processing", "pending"):
                    tm.fail_task(tid, reason)
        summary["reports_cancelled"].append(report_id)
