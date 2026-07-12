"""SSE 流式进度推送

- GET /api/tasks/<task_id>/events  → TaskManager 任务进度
- GET /api/decision/<decision_id>/events → Decision/Run 推演进度
- GET /api/simulation/<sim_id>/prepare/preview/events → Step2 profiles+config 预览
- GET /api/simulation/<sim_id>/actions/events → Step3 动作增量
- GET /api/report/<report_id>/logs/events → Step4 agent/console 日志增量

事件为全量状态快照或增量；终态发 event: done 后关闭；心跳 : ping。
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from typing import Any, Callable, Dict, Generator, List, Optional

from flask import Blueprint, Response, request, stream_with_context

from app.engine.scenario_runner import ScenarioRunner
from app.models.task import TERMINAL_STATUSES, TaskManager
from app.utils.logger import get_logger

logger = get_logger("adc.api.stream")

stream_bp = Blueprint("stream", __name__, url_prefix="/api")

HEARTBEAT_SEC = 20
POLL_WAIT_SEC = 1.0
WATCH_INTERVAL_SEC = 1.5


class DecisionEventHub:
    """decision_id 级轻量 pub/sub（与 TaskManager 解耦）。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._subscribers: Dict[str, List[queue.Queue]] = {}
                    cls._instance._sub_lock = threading.Lock()
        return cls._instance

    def subscribe(self, decision_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._sub_lock:
            self._subscribers.setdefault(decision_id, []).append(q)
        return q

    def unsubscribe(self, decision_id: str, q: queue.Queue) -> None:
        with self._sub_lock:
            subs = self._subscribers.get(decision_id) or []
            if q in subs:
                subs.remove(q)
            if not subs and decision_id in self._subscribers:
                del self._subscribers[decision_id]

    def publish(self, decision_id: str, snapshot: Dict[str, Any]) -> None:
        with self._sub_lock:
            subs = list(self._subscribers.get(decision_id) or [])
        for q in subs:
            try:
                q.put_nowait(snapshot)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(snapshot)
                except queue.Full:
                    pass


def publish_decision_status(decision_id: str, snapshot: Optional[Dict[str, Any]] = None) -> None:
    """供 ScenarioRunner 在状态变更时调用。"""
    if not decision_id:
        return
    if snapshot is None:
        try:
            snapshot = ScenarioRunner().get_status(decision_id)
        except Exception as e:
            logger.debug(f"publish_decision_status skip: {e}")
            return
    DecisionEventHub().publish(decision_id, snapshot)


def _sse_format(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _sse_response(gen: Generator[str, None, None]) -> Response:
    return Response(
        stream_with_context(gen),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _fingerprint(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _watch_stream(
    *,
    event_name: str,
    fetch_snapshot: Callable[[], Any],
    is_done: Optional[Callable[[Any], bool]] = None,
    interval: float = WATCH_INTERVAL_SEC,
    send_initial: bool = True,
) -> Generator[str, None, None]:
    """通用 watch：仅在快照指纹变化时推送，穿插心跳，终态发 done。"""
    last_fp: Optional[str] = None
    last_heartbeat = time.time()
    last_snap: Any = None
    try:
        while True:
            try:
                snap = fetch_snapshot()
            except Exception as e:
                yield _sse_format(
                    "task_error",
                    {"error": str(e), "status": "failed"},
                )
                yield _sse_format("done", {"status": "failed", "error": str(e)})
                return

            fp = _fingerprint(snap)
            if send_initial or fp != last_fp:
                if fp != last_fp or (send_initial and last_fp is None):
                    last_fp = fp
                    last_snap = snap
                    yield _sse_format(event_name, snap)
                    send_initial = False
                    last_heartbeat = time.time()

            if is_done and is_done(snap if snap is not None else last_snap):
                yield _sse_format("done", snap if snap is not None else last_snap or {})
                return

            time.sleep(interval)
            if time.time() - last_heartbeat >= HEARTBEAT_SEC:
                yield ": ping\n\n"
                last_heartbeat = time.time()
    except GeneratorExit:
        pass


@stream_bp.get("/tasks/<task_id>/events")
def task_events(task_id: str):
    """TaskManager 任务进度 SSE。"""
    tm = TaskManager()
    task = tm.get_task(task_id)
    if not task:
        # 仍允许订阅：可能刚创建竞态；首包发 not_found 后由前端走快照降级
        def missing():
            yield _sse_format(
                "task_error",
                {"task_id": task_id, "error": "task_not_found", "status": "failed"},
            )
            yield _sse_format("done", {"task_id": task_id, "status": "failed"})

        return _sse_response(missing())

    def generate():
        q = tm.subscribe(task_id)
        last_heartbeat = time.time()
        try:
            # 首包：当前快照
            current = tm.get_task(task_id)
            if current:
                snap = current.to_dict()
                yield _sse_format("progress", snap)
                if current.status in TERMINAL_STATUSES:
                    yield _sse_format("done", snap)
                    return

            while True:
                try:
                    snap = q.get(timeout=POLL_WAIT_SEC)
                    yield _sse_format("progress", snap)
                    status = str(snap.get("status") or "")
                    if status in ("completed", "failed"):
                        yield _sse_format("done", snap)
                        return
                    last_heartbeat = time.time()
                except queue.Empty:
                    # 再读一次内存态（避免错过 publish）
                    current = tm.get_task(task_id)
                    if current and current.status in TERMINAL_STATUSES:
                        snap = current.to_dict()
                        yield _sse_format("progress", snap)
                        yield _sse_format("done", snap)
                        return
                    if time.time() - last_heartbeat >= HEARTBEAT_SEC:
                        yield ": ping\n\n"
                        last_heartbeat = time.time()
        except GeneratorExit:
            pass
        finally:
            tm.unsubscribe(task_id, q)

    return _sse_response(generate())


@stream_bp.get("/decision/<decision_id>/events")
def decision_events(decision_id: str):
    """Decision / Run 推演进度 SSE。"""
    hub = DecisionEventHub()

    def generate():
        q = hub.subscribe(decision_id)
        last_heartbeat = time.time()
        last_payload: Optional[str] = None
        try:
            try:
                snap = ScenarioRunner().get_status(decision_id)
                last_payload = json.dumps(snap, ensure_ascii=False, default=str)
                yield _sse_format("progress", snap)
                status = str(snap.get("status") or "").lower()
                if status in ("completed", "failed", "done", "success"):
                    yield _sse_format("done", snap)
                    return
            except Exception as e:
                yield _sse_format(
                    "task_error",
                    {"decision_id": decision_id, "error": str(e), "status": "failed"},
                )

            while True:
                try:
                    snap = q.get(timeout=POLL_WAIT_SEC)
                    payload = json.dumps(snap, ensure_ascii=False, default=str)
                    if payload != last_payload:
                        last_payload = payload
                        yield _sse_format("progress", snap)
                    status = str(snap.get("status") or "").lower()
                    if status in ("completed", "failed", "done", "success"):
                        yield _sse_format("done", snap)
                        return
                    last_heartbeat = time.time()
                except queue.Empty:
                    # 兜底轮询快照，保证无 publish 时也能推进
                    try:
                        snap = ScenarioRunner().get_status(decision_id)
                        payload = json.dumps(snap, ensure_ascii=False, default=str)
                        if payload != last_payload:
                            last_payload = payload
                            yield _sse_format("progress", snap)
                        status = str(snap.get("status") or "").lower()
                        if status in ("completed", "failed", "done", "success"):
                            yield _sse_format("done", snap)
                            return
                    except Exception:
                        pass
                    if time.time() - last_heartbeat >= HEARTBEAT_SEC:
                        yield ": ping\n\n"
                        last_heartbeat = time.time()
        except GeneratorExit:
            pass
        finally:
            hub.unsubscribe(decision_id, q)

    return _sse_response(generate())


@stream_bp.get("/simulation/<sim_id>/prepare/preview/events")
def prepare_preview_events(sim_id: str):
    """Step2：profiles + config 实时预览 SSE。

    兼容传入 dec_*：解析为首个关联 sim_id 后再 watch 磁盘。
    """
    from app.api.simulation import read_config_realtime, read_profiles_realtime

    platform = request.args.get("platform", "reddit")
    resolved_sim = sim_id

    if str(sim_id).startswith("dec_"):
        try:
            from app.ontology import registry as ont_registry

            ont_registry.init_schema()
            runs = ont_registry.list_runs_for_decision(sim_id) or []
            for r in runs:
                sid = (r or {}).get("sim_id")
                if sid:
                    resolved_sim = sid
                    break
            if resolved_sim == sim_id:
                detail = ScenarioRunner().get_decision_detail(sim_id)
                resolved_sim = (
                    detail.get("sim_id")
                    or detail.get("simulation_id")
                    or sim_id
                )
        except Exception as e:
            logger.warning(f"prepare preview resolve dec→sim failed: {e}")

    def fetch():
        profiles = read_profiles_realtime(resolved_sim, platform)
        config = read_config_realtime(resolved_sim)
        return {
            "simulation_id": resolved_sim,
            "decision_id": sim_id if str(sim_id).startswith("dec_") else None,
            "profiles": {k: v for k, v in profiles.items() if k != "not_found"},
            "config": {k: v for k, v in config.items() if k != "not_found"},
        }

    def done(snap: Any) -> bool:
        if not isinstance(snap, dict):
            return False
        profiles = snap.get("profiles") or {}
        config = snap.get("config") or {}
        if profiles.get("is_generating") or config.get("is_generating"):
            return False
        stage = str(config.get("generation_stage") or "")
        cfg = config.get("config") if isinstance(config.get("config"), dict) else None
        has_cfg = bool(cfg and cfg.get("time_config") and cfg.get("agent_configs"))
        return has_cfg or stage == "completed" or bool(config.get("config_generated"))

    return _sse_response(
        _watch_stream(
            event_name="preview",
            fetch_snapshot=fetch,
            is_done=done,
            interval=WATCH_INTERVAL_SEC,
        )
    )


@stream_bp.get("/simulation/<sim_id>/actions/events")
def simulation_actions_events(sim_id: str):
    """Step3：动作增量 SSE。"""
    from app.api.simulation import read_simulation_actions
    from app.engine.simulation_runner import RunnerStatus, SimulationRunner

    limit = request.args.get("limit", 120, type=int)
    last_count = {"n": 0}
    seen_ids: set = set()

    def _action_id(a: dict) -> str:
        return str(
            a.get("id")
            or a.get("_uniqueId")
            or f"{a.get('platform')}:{a.get('agent_id')}:{a.get('round')}:{a.get('action_type')}:{a.get('timestamp') or a.get('created_at') or ''}"
        )

    def fetch():
        data = read_simulation_actions(sim_id, limit=limit, offset=0)
        actions = data.get("actions") or []
        new_actions = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            aid = _action_id(a)
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            new_actions.append(a)
        last_count["n"] = len(seen_ids)
        # 无新增时返回稳定指纹（避免空增量反复推送）
        if not new_actions and last_count["n"] > 0:
            return {
                "simulation_id": sim_id,
                "actions": [],
                "total_seen": last_count["n"],
                "source": data.get("source"),
                "_stable": True,
            }
        return {
            "simulation_id": sim_id,
            "actions": new_actions,
            "total_seen": last_count["n"],
            "source": data.get("source"),
        }

    def done(_snap: Any) -> bool:
        try:
            state = SimulationRunner.get_run_state(sim_id)
            if not state:
                return False
            return state.runner_status in (
                RunnerStatus.COMPLETED,
                RunnerStatus.FAILED,
                RunnerStatus.STOPPED,
            )
        except Exception:
            return False

    return _sse_response(
        _watch_stream(
            event_name="actions",
            fetch_snapshot=fetch,
            is_done=done,
            interval=WATCH_INTERVAL_SEC,
        )
    )


@stream_bp.get("/report/<report_id>/logs/events")
def report_logs_events(report_id: str):
    """Step4：agent + console 日志增量 SSE。"""
    from app.decision.report_agent import ReportManager, ReportStatus

    agent_from = request.args.get("agent_from", 0, type=int) or 0
    console_from = request.args.get("console_from", 0, type=int) or 0
    cursors = {"agent": agent_from, "console": console_from}

    def fetch():
        agent = ReportManager.get_agent_log(report_id, from_line=cursors["agent"])
        console = ReportManager.get_console_log(report_id, from_line=cursors["console"])
        agent_logs = agent.get("logs") or []
        console_logs = console.get("logs") or []
        agent_next = int(agent.get("from_line") or cursors["agent"]) + len(agent_logs)
        console_next = int(console.get("from_line") or cursors["console"]) + len(console_logs)
        if not agent_logs and not console_logs:
            # 稳定空快照，指纹不变则不推送
            return {
                "report_id": report_id,
                "agent": {"logs": [], "next_line": cursors["agent"], "from_line": cursors["agent"]},
                "console": {
                    "logs": [],
                    "next_line": cursors["console"],
                    "from_line": cursors["console"],
                },
                "_stable": True,
            }
        payload = {
            "report_id": report_id,
            "agent": {
                "logs": agent_logs,
                "next_line": agent_next,
                "from_line": cursors["agent"],
            },
            "console": {
                "logs": console_logs,
                "next_line": console_next,
                "from_line": cursors["console"],
            },
        }
        cursors["agent"] = agent_next
        cursors["console"] = console_next
        return payload

    def done(_snap: Any) -> bool:
        try:
            report = ReportManager.get_report(report_id)
            if not report:
                return False
            return report.status in (ReportStatus.COMPLETED, ReportStatus.FAILED)
        except Exception:
            return False

    return _sse_response(
        _watch_stream(
            event_name="logs",
            fetch_snapshot=fetch,
            is_done=done,
            interval=WATCH_INTERVAL_SEC,
        )
    )
