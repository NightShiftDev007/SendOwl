"""Phase C：启动恢复扫描。

后端重启后扫描在途工作并自动续跑；无法续则立即标 failed（不等 TTL）。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger("adc.progress.recovery")

RECOVERY_DELAY_SEC = float(os.environ.get("PROGRESS_RECOVERY_DELAY_SEC", "3"))
_recovery_started = False
_recovery_lock = threading.Lock()


def start_crash_recovery(*, delay_sec: Optional[float] = None) -> bool:
    """在后台延迟启动恢复扫描（debug reloader 仅主进程）。"""
    global _recovery_started
    with _recovery_lock:
        if _recovery_started:
            return False
        is_reloader = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
        is_debug = (
            os.environ.get("FLASK_DEBUG") == "1"
            or os.environ.get("WERKZEUG_RUN_MAIN") is not None
        )
        if is_debug and not is_reloader:
            return False
        _recovery_started = True

    wait = RECOVERY_DELAY_SEC if delay_sec is None else float(delay_sec)

    def _runner():
        if wait > 0:
            time.sleep(wait)
        try:
            summary = run_recovery_scan()
            logger.info(f"crash recovery 完成: {summary}")
        except Exception as e:
            logger.error(f"crash recovery 异常: {e}", exc_info=True)

    threading.Thread(target=_runner, daemon=True, name="crash-recovery").start()
    return True


def run_recovery_scan() -> Dict[str, int]:
    """同步扫描并恢复；返回计数摘要。"""
    summary = {
        "decisions_preparing": 0,
        "decisions_running": 0,
        "ontologies_building": 0,
        "reports_resumed": 0,
        "failed_fast": 0,
        "adopted": 0,
    }

    summary["decisions_preparing"] = _recover_preparing_decisions()
    summary["decisions_running"] = _recover_running_decisions(summary)
    summary["ontologies_building"] = _recover_building_ontologies()
    summary["reports_resumed"] = _recover_report_tasks()
    summary["n1_prepare"] = _recover_n1_prepare_sims()
    return summary


def _fail_decision(decision_id: str, message: str) -> None:
    from app.ontology import registry

    try:
        registry.update_decision(decision_id, status="failed")
    except Exception:
        try:
            registry.update_decision(decision_id, status="prepare_failed")
        except Exception:
            pass
    try:
        from app.api.stream import publish_decision_status

        publish_decision_status(decision_id)
    except Exception:
        pass
    logger.warning(f"recovery fail-fast decision={decision_id}: {message}")


def _recover_preparing_decisions() -> int:
    from app.ontology import registry
    from app.engine.scenario_runner import ScenarioRunner

    registry.init_schema()
    count = 0
    for dec in registry.list_decisions(include_trashed=False) or []:
        did = dec.get("id")
        if not did:
            continue
        if str(dec.get("status") or "").lower() != "preparing":
            continue
        count += 1
        logger.info(f"recovery: 重入 prepare decision={did}")
        try:

            def _worker(decision_id=did):
                try:
                    ScenarioRunner().prepare_decision(decision_id)
                    try:
                        from app.api.stream import publish_decision_status

                        publish_decision_status(decision_id)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"recovery prepare failed {decision_id}: {e}")
                    _fail_decision(decision_id, f"prepare resume failed: {e}")

            threading.Thread(
                target=_worker, daemon=True, name=f"recovery-prepare-{did}"
            ).start()
        except Exception as e:
            _fail_decision(did, str(e))
    return count


def _recover_running_decisions(summary: Dict[str, int]) -> int:
    """running decision：先 reconcile，再 adopt / 复活 worker。

    N=1 旁路启动（/api/simulation/start 已回写 registry=running）时：
    env 已死会重启该 run——这是预期行为。
    """
    from app.ontology import registry
    from app.engine.scenario_runner import ScenarioRunner
    from app.engine.simulation_runner import SimulationRunner

    registry.init_schema()
    count = 0
    runner = ScenarioRunner()

    for dec in registry.list_decisions(include_trashed=False) or []:
        did = dec.get("id")
        if not did:
            continue
        if str(dec.get("status") or "").lower() != "running":
            continue
        count += 1
        try:
            runner.reconcile_runs_with_run_state(did)
        except Exception as e:
            logger.debug(f"reconcile before recovery: {e}")

        # 尝试收养各 run 对应子进程
        runs = registry.list_runs_for_decision(did) or []
        any_alive = False
        for run in runs:
            sim_id = run.get("sim_id")
            if not sim_id:
                continue
            st = str(run.get("status") or "").lower()
            if st in ("completed", "done", "success", "failed"):
                continue
            adopted = SimulationRunner.try_adopt(sim_id)
            if adopted:
                any_alive = True
                summary["adopted"] = summary.get("adopted", 0) + 1
                logger.info(f"recovery: adopted sim={sim_id} for decision={did}")

        # 复活 decision worker（内部会 skip completed / attach 活 sim）
        try:
            logger.info(f"recovery: 复活 decision worker decision={did}")
            runner.start_decision(did, background=True, force=False, revive_worker=True)
        except Exception as e:
            if any_alive:
                logger.warning(
                    f"recovery: worker 启动失败但已 adopt，保持 running decision={did}: {e}"
                )
            else:
                _fail_decision(did, f"running resume failed: {e}")
                summary["failed_fast"] = summary.get("failed_fast", 0) + 1
    return count


def _recover_building_ontologies() -> int:
    from app.ontology import registry
    from app.ontology.service import (
        _combined_document_text,
        _watch_build_task,
    )
    from app.ontology.snapshot import export_snapshot
    from app.ontology.graph_builder import GraphBuilderService
    from app.models.task import TaskManager, TaskStatus
    from app.config import Config

    registry.init_schema()
    count = 0
    tm = TaskManager()

    for ont in registry.list_ontologies() or []:
        oid = ont.get("id")
        if not oid:
            continue
        st = str(ont.get("status") or "").lower()
        if st not in ("building", "graph_building"):
            continue
        count += 1
        tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
        task = tm.get_task(tid) if tid else None
        detail = (getattr(task, "progress_detail", None) or {}) if task else {}
        result = (getattr(task, "result", None) or {}) if task else {}
        has_cp = bool(detail.get("graph_id") or result.get("graph_id"))

        if not tid or not task:
            logger.warning(f"recovery: ontology building 无 task，标 failed oid={oid}")
            registry.update_ontology(oid, status="failed", build_task_id=None)
            continue

        task_st = str(getattr(task.status, "value", task.status) or "").lower()
        if task_st == "completed":
            gid = result.get("graph_id")
            registry.update_ontology(
                oid, graph_id=gid, status="ready", build_task_id=None
            )
            try:
                export_snapshot(oid, gid)
            except Exception:
                pass
            continue
        if task_st == "failed":
            registry.update_ontology(oid, status="failed", build_task_id=None)
            continue

        if not has_cp:
            logger.warning(
                f"recovery: 建图无检查点，标 failed oid={oid} task={tid}"
            )
            tm.fail_task(tid, "recovery: 无 graph 检查点，请重新建图")
            registry.update_ontology(oid, status="failed", build_task_id=None)
            continue

        schema = ont.get("schema")
        text = _combined_document_text(oid)
        if not schema or not (text or "").strip():
            tm.fail_task(tid, "recovery: 缺少 schema/文档，无法续传")
            registry.update_ontology(oid, status="failed", build_task_id=None)
            continue

        builder = GraphBuilderService()
        ok = builder.resume_graph_build(
            task_id=tid,
            text=text,
            ontology=schema,
            graph_name=ont.get("name") or oid,
            chunk_size=Config.DEFAULT_CHUNK_SIZE,
            chunk_overlap=Config.DEFAULT_CHUNK_OVERLAP,
        )
        if ok:
            threading.Thread(
                target=_watch_build_task,
                args=(oid, tid),
                daemon=True,
                name=f"recovery-watch-{oid}",
            ).start()
            logger.info(f"recovery: 续传建图 oid={oid} task={tid}")
        else:
            tm.fail_task(tid, "recovery: resume_graph_build 失败")
            registry.update_ontology(oid, status="failed", build_task_id=None)
    return count


def _recover_report_tasks() -> int:
    from app.models.task import TaskManager, TaskStatus
    from app.decision.report_agent import ReportManager
    from app.engine.simulation_manager import SimulationManager
    from app.config import Config
    from app.progress.suspend import (
        is_decision_trashed,
        is_sim_owner_trashed,
        resolve_decision_id_for_sim,
        TRASH_SUSPEND_REASON,
    )

    tm = TaskManager()
    count = 0
    skipped_trash = 0
    reports_root = getattr(Config, "REPORTS_DIR", None) or os.path.join(
        Config.UPLOAD_FOLDER, "reports"
    )
    if not os.path.isdir(reports_root):
        return 0

    for name in os.listdir(reports_root):
        if not name.startswith("report_"):
            continue
        report_id = name
        meta = ReportManager.get_generate_task_meta(report_id)
        if not meta:
            continue
        tid = meta.get("task_id")
        if not tid:
            continue
        task = tm.get_task(tid)
        if not task:
            continue
        st = str(getattr(task.status, "value", task.status) or "").lower()
        if st not in ("processing", "pending"):
            continue

        sim_id = meta.get("simulation_id") or (task.metadata or {}).get(
            "simulation_id"
        )
        decision_id = meta.get("decision_id") or resolve_decision_id_for_sim(sim_id)

        # 仅当归属到「未入回收站」的决策时才自动续跑。
        # 已 trash / 决策已删 / 无法归属 → fail task，等用户进任务显式重试。
        owner_ok = bool(decision_id) and not is_decision_trashed(decision_id)
        if not owner_ok or meta.get("cancelled") or (
            sim_id and is_sim_owner_trashed(sim_id)
        ):
            ReportManager.cancel_generate(
                report_id,
                reason=TRASH_SUSPEND_REASON,
                decision_id=decision_id,
            )
            tm.fail_task(tid, TRASH_SUSPEND_REASON)
            skipped_trash += 1
            logger.info(
                f"recovery: 跳过无活跃归属的报告 report={report_id} "
                f"decision={decision_id} cancelled={bool(meta.get('cancelled'))}"
            )
            continue

        # 已有完整报告则直接 complete
        full_path = ReportManager._get_report_markdown_path(report_id)
        if os.path.isfile(full_path) and os.path.getsize(full_path) > 0:
            tm.complete_task(
                tid,
                result={"report_id": report_id, "status": "completed", "recovered": True},
            )
            continue

        graph_id = (task.metadata or {}).get("graph_id")
        requirement = ""
        if sim_id:
            try:
                mgr = SimulationManager()
                state = mgr.get_simulation(sim_id)
                if state:
                    graph_id = graph_id or state.graph_id
                    cfg = mgr.get_simulation_config(sim_id) or {}
                    requirement = (
                        cfg.get("simulation_requirement")
                        or getattr(state, "simulation_requirement", None)
                        or ""
                    )
            except Exception as e:
                logger.debug(f"recover report resolve sim: {e}")

        if not graph_id or not sim_id:
            tm.fail_task(tid, "recovery: 缺少 graph_id/simulation_id，无法续跑报告")
            count += 1
            continue

        ok = ReportManager.resume_generate_in_background(
            report_id,
            tid,
            simulation_id=sim_id,
            graph_id=graph_id,
            simulation_requirement=str(requirement or ""),
        )
        if ok:
            count += 1
            logger.info(f"recovery: 续跑报告 report={report_id} task={tid}")
        else:
            tm.fail_task(tid, "recovery: resume_generate 失败")
    if skipped_trash:
        logger.info(f"recovery: 因回收站跳过报告 {skipped_trash} 个")
    return count


def _recover_n1_prepare_sims() -> int:
    """N=1：sim state=preparing 且有 prepare_task_id → 复用 task_id 重开 worker。"""
    from app.engine.simulation_manager import SimulationManager, SimulationStatus
    from app.models.task import TaskManager, TaskStatus
    from app.config import Config
    from app.ontology import registry
    from app.progress.suspend import is_decision_trashed, TRASH_SUSPEND_REASON

    mgr = SimulationManager()
    tm = TaskManager()
    count = 0
    root = Config.OASIS_SIMULATION_DATA_DIR
    if not os.path.isdir(root):
        return 0

    for sim_id in os.listdir(root):
        if not str(sim_id).startswith("sim_"):
            continue
        state = mgr.get_simulation(sim_id)
        if not state:
            continue
        if state.status != SimulationStatus.PREPARING:
            continue
        tid = getattr(state, "prepare_task_id", None)
        if not tid:
            # 无 task 句柄：若有 decision 在 preparing，已由 _recover_preparing 覆盖
            continue
        task = tm.get_task(tid)
        if not task:
            continue
        st = str(getattr(task.status, "value", task.status) or "").lower()
        if st not in ("processing", "pending"):
            continue

        document_text = ""
        requirement = ""
        project_id = state.project_id or ""
        if project_id and str(project_id).startswith("dec_") and is_decision_trashed(
            project_id
        ):
            tm.fail_task(tid, TRASH_SUSPEND_REASON)
            logger.info(
                f"recovery: 跳过回收站 N=1 prepare sim={sim_id} decision={project_id}"
            )
            continue
        try:
            cfg = mgr.get_simulation_config(sim_id) or {}
            requirement = cfg.get("simulation_requirement") or ""
        except Exception:
            pass
        if project_id and str(project_id).startswith("dec_"):
            try:
                from app.ontology.service import _combined_document_text

                dec = registry.get_decision(project_id)
                if dec:
                    document_text = _combined_document_text(dec["ontology_id"]) or ""
                    if not requirement:
                        requirement = dec.get("title") or project_id
            except Exception:
                pass

        tm.update_task(
            tid,
            status=TaskStatus.PROCESSING,
            message="recovery: 从断点续跑 prepare",
        )

        def _worker(
            simulation_id=sim_id,
            task_id=tid,
            req=requirement,
            doc=document_text,
            pid=project_id,
        ):
            try:
                def progress_callback(stage, progress, message, **kwargs):
                    tm.update_task(
                        task_id,
                        progress=int(progress or 0),
                        message=f"[{stage}] {message}",
                    )

                mgr.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=req or simulation_id,
                    document_text=doc or "",
                    use_llm_for_profiles=True,
                    progress_callback=progress_callback,
                    parallel_profile_count=3,
                    stage="all",
                )
                tm.complete_task(
                    task_id,
                    result={"simulation_id": simulation_id, "resumed": True},
                )
                if pid and str(pid).startswith("dec_"):
                    try:
                        registry.update_decision(pid, status="prepared")
                        from app.api.stream import publish_decision_status

                        publish_decision_status(pid)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"recovery N=1 prepare failed {simulation_id}: {e}")
                tm.fail_task(task_id, str(e))
                if pid and str(pid).startswith("dec_"):
                    try:
                        registry.update_decision(pid, status="prepare_failed")
                    except Exception:
                        pass

        threading.Thread(
            target=_worker, daemon=True, name=f"recovery-n1-prepare-{sim_id}"
        ).start()
        count += 1
        logger.info(f"recovery: N=1 prepare 续跑 sim={sim_id} task={tid}")
    return count
