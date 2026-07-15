"""决策活动摘要：供任务库卡片 / 弹窗展示「是否在跑、当前步骤、阶段」。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger("adc.progress.activity")

STEP_KEYS = {
    1: "graph",
    2: "environment",
    3: "simulation",
    4: "report",
    5: "interaction",
}

ACTIVE_ONTOLOGY_STATUSES = frozenset({"building", "graph_building"})


def summarize_decision_activity(
    decision_id: str,
    *,
    dec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """返回轻量活动摘要（不做完整 envelope / 不扫全部 report 内容）。"""
    from app.ontology import registry
    from app.engine.scenario_runner import _read_prepare_progress
    from app.engine.simulation_runner import SimulationRunner

    registry.init_schema()
    if dec is None:
        dec = registry.get_decision(decision_id) or {}
    status = str(dec.get("status") or "").lower()
    ontology_id = dec.get("ontology_id") or ""

    ont_status = ""
    if ontology_id:
        try:
            ont = registry.get_ontology(ontology_id) or {}
            ont_status = str(ont.get("status") or "").lower()
        except Exception:
            ont_status = ""

    # --- 报告生成中？ ---
    report_info = _peek_report_generating(decision_id, dec)

    # --- 推演轮次 ---
    rounds = {"current": 0, "total": 0, "done_runs": 0, "total_runs": 0}
    any_run_running = False
    try:
        runs = registry.list_runs_for_decision(decision_id) or []
        rounds["total_runs"] = len(runs)
        for r in runs:
            st = str(r.get("status") or "").lower()
            if st in ("completed", "stalled", "failed", "timeout", "stopped"):
                rounds["done_runs"] += 1
            if st == "running":
                any_run_running = True
            sid = r.get("sim_id")
            if sid and (st == "running" or status == "running"):
                try:
                    rs = SimulationRunner.get_run_state(sid)
                    if rs:
                        rounds["current"] = max(
                            rounds["current"], int(getattr(rs, "current_round", 0) or 0)
                        )
                        rounds["total"] = max(
                            rounds["total"], int(getattr(rs, "total_rounds", 0) or 0)
                        )
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"activity rounds peek failed: {e}")

    # --- prepare 细进度 ---
    prep = None
    try:
        prep = _read_prepare_progress(decision_id)
    except Exception:
        prep = None

    # --- 判定当前步骤 / 是否在跑 ---
    workflow_step = 2
    stage = status or "idle"
    message = ""
    progress = 0
    is_running = False

    if ont_status in ACTIVE_ONTOLOGY_STATUSES:
        workflow_step = 1
        stage = ont_status
        message = "图谱构建中"
        is_running = True
        progress = _ontology_build_progress(ontology_id)
    elif status == "preparing":
        # 仅以决策状态为准，避免残留 prepare_progress.json 误标「运行中」
        workflow_step = 2
        stage = str((prep or {}).get("stage") or "preparing")
        message = str((prep or {}).get("message") or "环境准备中")
        try:
            progress = int((prep or {}).get("progress") or 0)
        except (TypeError, ValueError):
            progress = 0
        is_running = True
    elif status == "running" or any_run_running:
        workflow_step = 3
        stage = "running"
        is_running = True
        if rounds["total"] > 0:
            message = f"推演中 {rounds['current']}/{rounds['total']} 轮"
            progress = int(round(100.0 * rounds["current"] / rounds["total"]))
        elif rounds["total_runs"] > 0:
            message = f"推演中 {rounds['done_runs']}/{rounds['total_runs']} 组"
            progress = int(
                round(100.0 * rounds["done_runs"] / max(rounds["total_runs"], 1))
            )
        else:
            message = "推演运行中"
            progress = 5
    elif report_info.get("generating"):
        workflow_step = 4
        stage = "report_generating"
        message = report_info.get("message") or "报告生成中"
        progress = int(report_info.get("progress") or 0)
        is_running = True
    elif status == "completed":
        workflow_step = 5 if report_info.get("has_report") else 4
        stage = "completed"
        message = "已完成"
        progress = 100
    elif status == "prepared":
        workflow_step = 2
        stage = "prepared"
        message = "环境已就绪"
        progress = 100
    elif status == "prepare_failed":
        workflow_step = 2
        stage = status
        message = "环境准备失败，可进入任务重试"
    elif status == "failed":
        workflow_step = 3
        stage = status
        message = "推演失败，可进入任务重试"
    elif status == "created":
        workflow_step = 1 if ont_status not in ("ready",) else 2
        stage = status
        message = "待继续"
    else:
        workflow_step = 2 if ontology_id else 1
        stage = status or ont_status or "idle"
        message = ""

    return {
        "is_running": bool(is_running),
        "workflow_step": int(workflow_step),
        "workflow_step_key": STEP_KEYS.get(int(workflow_step), "graph"),
        "status": status,
        "ontology_status": ont_status,
        "stage": stage,
        "message": message,
        "progress": max(0, min(100, int(progress or 0))),
        "rounds": rounds,
        "report_generating": bool(report_info.get("generating")),
    }


def enrich_decisions_with_activity(
    decisions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in decisions or []:
        row = dict(d)
        did = row.get("id")
        try:
            row["activity"] = summarize_decision_activity(did, dec=row) if did else {}
        except Exception as e:
            logger.debug(f"activity enrich failed {did}: {e}")
            row["activity"] = {
                "is_running": False,
                "workflow_step": 1,
                "workflow_step_key": "graph",
                "status": str(row.get("status") or ""),
                "stage": "idle",
                "message": "",
                "progress": 0,
            }
        out.append(row)
    return out


def _ontology_build_progress(ontology_id: str) -> int:
    try:
        from app.ontology import registry
        from app.models.task import TaskManager

        ont = registry.get_ontology(ontology_id) or {}
        tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
        if not tid:
            return 5
        task = TaskManager().get_task(tid)
        if not task:
            return 5
        return max(0, min(100, int(getattr(task, "progress", 0) or 0)))
    except Exception:
        return 5


def _peek_report_generating(
    decision_id: str, dec: Dict[str, Any]
) -> Dict[str, Any]:
    """粗查：关联 sim 的 report generate_task 是否 processing。"""
    from app.config import Config
    from app.ontology import registry
    from app.decision.report_agent import ReportManager
    from app.models.task import TaskManager

    result = {"generating": False, "has_report": False, "progress": 0, "message": ""}
    sim_ids = set()
    try:
        for r in registry.list_runs_for_decision(decision_id) or []:
            if r.get("sim_id"):
                sim_ids.add(str(r["sim_id"]))
    except Exception:
        pass

    reports_root = getattr(Config, "REPORTS_DIR", None) or os.path.join(
        Config.UPLOAD_FOLDER, "reports"
    )
    if not os.path.isdir(reports_root):
        return result

    tm = TaskManager()
    for name in os.listdir(reports_root):
        if not name.startswith("report_"):
            continue
        meta = ReportManager.get_generate_task_meta(name) or {}
        if meta.get("cancelled"):
            continue
        linked = str(meta.get("decision_id") or "") == decision_id or (
            meta.get("simulation_id") and str(meta.get("simulation_id")) in sim_ids
        )
        if not linked:
            continue

        # 已有完整报告？
        try:
            full_path = ReportManager._get_report_markdown_path(name)
            if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
                result["has_report"] = True
        except Exception:
            pass

        tid = meta.get("task_id")
        if not tid:
            continue
        task = tm.get_task(tid)
        if not task:
            continue
        st = str(getattr(task.status, "value", task.status) or "").lower()
        if st in ("processing", "pending"):
            result["generating"] = True
            result["progress"] = max(0, min(100, int(getattr(task, "progress", 0) or 0)))
            result["message"] = str(getattr(task, "message", None) or "报告生成中")
            break
    return result
