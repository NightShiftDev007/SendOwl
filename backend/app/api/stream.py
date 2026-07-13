"""SSE 流式进度推送

一阶段一 SSE：同连接推进度 + 结果增量，终态 done 关闭。

- GET /api/tasks/<task_id>/events  → 建图 / N=1 prepare / 报告（帧内可含 graph / profiles / logs）
- GET /api/decision/<decision_id>/events → N>1 prepare / 推演（帧内可含 profiles / 平台进度 / actions）

以下端点保留作降级，正常路径前端不再订阅：
- prepare/preview、actions、report logs、ontology graph events
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


def _task_snap_with_envelope(snap: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(snap, dict):
        return snap
    try:
        from app.progress.envelope import build_task_envelope

        tid = snap.get("task_id")
        if tid:
            out = dict(snap)
            env = build_task_envelope(tid, snap)
            out["envelope"] = env
            # 方便前端不拆 envelope 也能读到人设增量
            arts = env.get("artifacts") if isinstance(env, dict) else {}
            if isinstance(arts, dict):
                if arts.get("profiles_digest") is not None:
                    out["profiles_digest"] = arts["profiles_digest"]
                if arts.get("profile_count") is not None:
                    out["profile_count"] = arts["profile_count"]
                if arts.get("topics_count") is not None:
                    out["topics_count"] = arts["topics_count"]
                if arts.get("config_ready") is not None:
                    out["config_ready"] = arts["config_ready"]

            # Step1 建图：同帧附带 graph 快照（按规模变化推送）
            meta = snap.get("metadata") if isinstance(snap.get("metadata"), dict) else {}
            ont_id = (
                arts.get("ontology_id")
                if isinstance(arts, dict)
                else None
            ) or meta.get("ontology_id") or meta.get("project_id")
            task_type = str(snap.get("task_type") or "")
            if ont_id and (
                "graph" in task_type
                or "build" in task_type
                or meta.get("ontology_id")
                or meta.get("project_id")
            ):
                try:
                    from app.api.ontology import read_ontology_graph

                    g = read_ontology_graph(str(ont_id)) or {}
                    node_count = int(g.get("node_count") or len(g.get("nodes") or []) or 0)
                    edge_count = int(g.get("edge_count") or len(g.get("edges") or []) or 0)
                    out["graph"] = {
                        "ontology_id": ont_id,
                        "graph_id": g.get("graph_id"),
                        "nodes": g.get("nodes") or [],
                        "edges": g.get("edges") or [],
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "source": g.get("source"),
                    }
                    if isinstance(arts, dict):
                        arts = dict(arts)
                        arts["node_count"] = node_count
                        arts["edge_count"] = edge_count
                        arts["graph_id"] = g.get("graph_id")
                        env = dict(env)
                        env["artifacts"] = arts
                        out["envelope"] = env
                except Exception as e:
                    logger.debug(f"task graph enrich skip: {e}")

            # Step4 报告：同帧附带 agent/console 日志增量
            report_id = (arts.get("report_id") if isinstance(arts, dict) else None) or meta.get(
                "report_id"
            )
            if report_id and (
                task_type == "report_generate" or "report" in task_type
            ):
                try:
                    from app.decision.report_agent import ReportManager

                    agent_from = int(
                        (arts or {}).get("agent_log_line")
                        or meta.get("agent_log_line")
                        or 0
                    )
                    console_from = int(
                        (arts or {}).get("console_log_line")
                        or meta.get("console_log_line")
                        or 0
                    )
                    agent = ReportManager.get_agent_log(str(report_id), from_line=agent_from)
                    console = ReportManager.get_console_log(
                        str(report_id), from_line=console_from
                    )
                    agent_logs = agent.get("logs") or []
                    console_logs = console.get("logs") or []
                    agent_next = int(
                        agent.get("total_lines")
                        or agent_from + len(agent_logs)
                    )
                    console_next = int(
                        console.get("total_lines")
                        or console_from + len(console_logs)
                    )
                    out["agent_logs"] = agent_logs
                    out["console_logs"] = console_logs
                    out["agent_log_line"] = agent_next
                    out["console_log_line"] = console_next
                    if isinstance(arts, dict):
                        arts = dict(arts)
                        arts["agent_log_line"] = agent_next
                        arts["console_log_line"] = console_next
                        env = dict(env)
                        env["artifacts"] = arts
                        out["envelope"] = env
                except Exception as e:
                    logger.debug(f"task report logs enrich skip: {e}")
            return out
    except Exception:
        pass
    return snap


def _task_dedupe_key(snap: Dict[str, Any]) -> str:
    """含 profile_count / graph 规模 / 日志水位，避免只指纹进度导致结果增量被吞。"""
    env = snap.get("envelope") if isinstance(snap, dict) else None
    arts = (env or {}).get("artifacts") if isinstance(env, dict) else {}
    graph = snap.get("graph") if isinstance(snap, dict) else None
    return _fingerprint(
        {
            "status": snap.get("status") if isinstance(snap, dict) else None,
            "progress": snap.get("progress") if isinstance(snap, dict) else None,
            "message": snap.get("message") if isinstance(snap, dict) else None,
            "profile_count": (arts or {}).get("profile_count")
            or (snap.get("profile_count") if isinstance(snap, dict) else None),
            "topics_count": (arts or {}).get("topics_count"),
            "config_ready": (arts or {}).get("config_ready"),
            "node_count": (arts or {}).get("node_count")
            or ((graph or {}).get("node_count") if isinstance(graph, dict) else None),
            "edge_count": (arts or {}).get("edge_count")
            or ((graph or {}).get("edge_count") if isinstance(graph, dict) else None),
            "agent_log_line": (arts or {}).get("agent_log_line")
            or (snap.get("agent_log_line") if isinstance(snap, dict) else None),
            "console_log_line": (arts or {}).get("console_log_line")
            or (snap.get("console_log_line") if isinstance(snap, dict) else None),
            "stage": (env or {}).get("stage") if isinstance(env, dict) else None,
        }
    )


@stream_bp.get("/tasks/<task_id>/events")
def task_events(task_id: str):
    """TaskManager 任务进度 SSE。"""
    tm = TaskManager()
    task = tm.get_task(task_id)
    if not task:
        # 刚创建竞态 / 进程重启后短暂等待 DB 回源；仍没有则发可重试错误
        def missing():
            for _ in range(10):
                found = tm.get_task(task_id)
                if found:
                    break
                time.sleep(0.5)
            else:
                yield _sse_format(
                    "task_error",
                    {
                        "task_id": task_id,
                        "error": "task_not_found",
                        "status": "pending",
                        "retryable": True,
                    },
                )
                return

            # 任务已出现：推首包后进入正常订阅循环
            q = tm.subscribe(task_id)
            last_heartbeat = time.time()
            last_key: Optional[str] = None
            try:
                current = tm.get_task(task_id)
                if current:
                    snap = _task_snap_with_envelope(current.to_dict())
                    last_key = _task_dedupe_key(snap)
                    yield _sse_format("progress", snap)
                    if current.status in TERMINAL_STATUSES:
                        yield _sse_format("done", snap)
                        return
                while True:
                    try:
                        snap = _task_snap_with_envelope(q.get(timeout=POLL_WAIT_SEC))
                        key = _task_dedupe_key(snap)
                        if key != last_key:
                            last_key = key
                            yield _sse_format("progress", snap)
                        status = str(snap.get("status") or "")
                        if status in ("completed", "failed"):
                            yield _sse_format("done", snap)
                            return
                        last_heartbeat = time.time()
                    except queue.Empty:
                        current = tm.get_task(task_id)
                        if current:
                            snap = _task_snap_with_envelope(current.to_dict())
                            key = _task_dedupe_key(snap)
                            if key != last_key:
                                last_key = key
                                yield _sse_format("progress", snap)
                            if current.status in TERMINAL_STATUSES:
                                yield _sse_format("done", snap)
                                return
                        if time.time() - last_heartbeat >= HEARTBEAT_SEC:
                            yield ": ping\n\n"
                            last_heartbeat = time.time()
            except GeneratorExit:
                pass
            finally:
                tm.unsubscribe(task_id, q)

        return _sse_response(missing())

    def generate():
        q = tm.subscribe(task_id)
        last_heartbeat = time.time()
        last_key: Optional[str] = None
        try:
            # 首包：当前快照
            current = tm.get_task(task_id)
            if current:
                snap = _task_snap_with_envelope(current.to_dict())
                last_key = _task_dedupe_key(snap)
                yield _sse_format("progress", snap)
                if current.status in TERMINAL_STATUSES:
                    yield _sse_format("done", snap)
                    return

            while True:
                try:
                    snap = _task_snap_with_envelope(q.get(timeout=POLL_WAIT_SEC))
                    key = _task_dedupe_key(snap)
                    if key != last_key:
                        last_key = key
                        yield _sse_format("progress", snap)
                    status = str(snap.get("status") or "")
                    if status in ("completed", "failed"):
                        yield _sse_format("done", snap)
                        return
                    last_heartbeat = time.time()
                except queue.Empty:
                    # 再读一次：prepare 人设落盘后即使无 task publish 也能推进
                    current = tm.get_task(task_id)
                    if current:
                        snap = _task_snap_with_envelope(current.to_dict())
                        key = _task_dedupe_key(snap)
                        if key != last_key:
                            last_key = key
                            yield _sse_format("progress", snap)
                        if current.status in TERMINAL_STATUSES:
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


def _decision_terminal(status: str) -> bool:
    # prepared 不关流：Step3 可能继续订同一 decision；由前端在 prepare 完成时自行 close
    return status in (
        "completed",
        "failed",
        "done",
        "success",
        "prepare_failed",
    )


def _decision_dedupe_key(snap: Dict[str, Any]) -> str:
    """指纹含 profile_count / 平台进度 / actions watermark，避免吞增量。"""
    env = snap.get("envelope") if isinstance(snap, dict) else None
    arts = (env or {}).get("artifacts") if isinstance(env, dict) else {}
    return _fingerprint(
        {
            "status": snap.get("status"),
            "stage": snap.get("stage") or ((env or {}).get("stage") if isinstance(env, dict) else None),
            "prepare_percent": snap.get("prepare_percent")
            or ((env or {}).get("progress") if isinstance(env, dict) else None),
            "message": snap.get("message")
            or ((env or {}).get("message") if isinstance(env, dict) else None),
            "profile_count": snap.get("profile_count")
            or (arts or {}).get("profile_count"),
            "topics_count": (arts or {}).get("topics_count"),
            "progress": snap.get("progress"),
            "twitter_current_round": snap.get("twitter_current_round")
            or (arts or {}).get("twitter_current_round"),
            "reddit_current_round": snap.get("reddit_current_round")
            or (arts or {}).get("reddit_current_round"),
            "twitter_actions_count": snap.get("twitter_actions_count")
            or (arts or {}).get("twitter_actions_count"),
            "reddit_actions_count": snap.get("reddit_actions_count")
            or (arts or {}).get("reddit_actions_count"),
            "actions_watermark": snap.get("actions_watermark")
            or (arts or {}).get("actions_watermark"),
            "runner_status": snap.get("runner_status")
            or (arts or {}).get("runner_status"),
        }
    )


def _pick_sim_from_snap(snap: Dict[str, Any], preferred_sim: Optional[str] = None) -> Optional[str]:
    if preferred_sim:
        return preferred_sim
    if snap.get("sim_id"):
        return str(snap["sim_id"])
    for m in snap.get("matrix") or []:
        for r in m.get("runs") or []:
            sid = (r or {}).get("sim_id")
            if sid:
                return str(sid)
    return None


def _enrich_decision_run_snap(
    snap: Dict[str, Any],
    *,
    sim_id: Optional[str] = None,
    actions_from: int = 0,
    actions_limit: int = 80,
) -> Dict[str, Any]:
    """为 Step3 同帧附带平台进度 + actions 增量。"""
    if not isinstance(snap, dict):
        return snap
    out = dict(snap)
    status_l = str(out.get("status") or "").lower()
    # preparing 阶段不塞动作
    if status_l == "preparing":
        return out

    sid = _pick_sim_from_snap(out, sim_id)
    if not sid:
        return out

    out["sim_id"] = sid
    try:
        from app.engine.simulation_runner import SimulationRunner

        rs = SimulationRunner.get_run_state(sid)
        if rs:
            rd = rs.to_dict() if hasattr(rs, "to_dict") else {}
            for k in (
                "runner_status",
                "current_round",
                "total_rounds",
                "twitter_current_round",
                "reddit_current_round",
                "twitter_actions_count",
                "reddit_actions_count",
                "twitter_running",
                "reddit_running",
                "twitter_completed",
                "reddit_completed",
                "twitter_simulated_hours",
                "reddit_simulated_hours",
                "progress_percent",
                "simulated_hours",
            ):
                if k in rd:
                    out[k] = rd[k]
            # 写入 envelope artifacts 供去重/前端
            env = out.get("envelope")
            if isinstance(env, dict):
                arts = dict(env.get("artifacts") or {})
                for k in (
                    "twitter_current_round",
                    "reddit_current_round",
                    "twitter_actions_count",
                    "reddit_actions_count",
                    "runner_status",
                ):
                    if k in out:
                        arts[k] = out[k]
                arts["sim_id"] = sid
                env = dict(env)
                env["artifacts"] = arts
                # 推演中 envelope status
                rv = str(out.get("runner_status") or "").lower()
                if rv == "completed":
                    env["status"] = "completed"
                    env["raw_status"] = "completed"
                    env["progress"] = 100
                elif rv in ("running", "starting"):
                    env["status"] = "running"
                    env["raw_status"] = out.get("status") or "running"
                out["envelope"] = env
    except Exception as e:
        logger.debug(f"enrich run_state skip: {e}")

    # actions 增量
    try:
        from app.api.simulation import read_simulation_actions

        # 取较新窗口再按 watermark 切
        pack = read_simulation_actions(sid, limit=max(actions_limit, 50), offset=0, newest=True)
        actions = pack.get("actions") or []
        # watermark：用稳定 id 列表长度语义 —— 传 actions_from 为已收条数时取 tail
        if actions_from > 0 and len(actions) >= actions_from:
            # newest 窗口是尾部；前端用 id 去重更稳，这里仍推窗口内全部供 merge
            pass
        out["actions"] = actions
        out["actions_watermark"] = len(actions)
        env = out.get("envelope")
        if isinstance(env, dict):
            arts = dict(env.get("artifacts") or {})
            arts["actions_watermark"] = out["actions_watermark"]
            arts["action_count"] = len(actions)
            env = dict(env)
            env["artifacts"] = arts
            out["envelope"] = env
    except Exception as e:
        logger.debug(f"enrich actions skip: {e}")

    return out


@stream_bp.get("/decision/<decision_id>/events")
def decision_events(decision_id: str):
    """Decision / Run 推演进度 SSE（帧内含 ProgressEnvelope + 平台进度/动作增量）。"""
    hub = DecisionEventHub()
    preferred_sim = (request.args.get("sim_id") or "").strip() or None
    try:
        actions_from = int(request.args.get("actions_from") or 0)
    except (TypeError, ValueError):
        actions_from = 0

    def generate():
        q = hub.subscribe(decision_id)
        last_heartbeat = time.time()
        last_key: Optional[str] = None
        try:
            try:
                snap = _enrich_decision_run_snap(
                    ScenarioRunner().get_status(decision_id),
                    sim_id=preferred_sim,
                    actions_from=actions_from,
                )
                last_key = _decision_dedupe_key(snap)
                yield _sse_format("progress", snap)
                status = str(snap.get("status") or "").lower()
                runner = str(snap.get("runner_status") or "").lower()
                if _decision_terminal(status) or (
                    runner in ("completed", "stopped", "failed")
                    and status != "preparing"
                ):
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
                    if "envelope" not in snap or preferred_sim:
                        try:
                            snap = ScenarioRunner().get_status(decision_id)
                        except Exception:
                            pass
                    snap = _enrich_decision_run_snap(
                        snap, sim_id=preferred_sim, actions_from=actions_from
                    )
                    key = _decision_dedupe_key(snap)
                    if key != last_key:
                        last_key = key
                        yield _sse_format("progress", snap)
                    status = str(snap.get("status") or "").lower()
                    runner = str(snap.get("runner_status") or "").lower()
                    if _decision_terminal(status) or (
                        runner in ("completed", "stopped", "failed")
                        and status != "preparing"
                    ):
                        yield _sse_format("done", snap)
                        return
                    last_heartbeat = time.time()
                except queue.Empty:
                    try:
                        snap = _enrich_decision_run_snap(
                            ScenarioRunner().get_status(decision_id),
                            sim_id=preferred_sim,
                            actions_from=actions_from,
                        )
                        key = _decision_dedupe_key(snap)
                        if key != last_key:
                            last_key = key
                            yield _sse_format("progress", snap)
                        status = str(snap.get("status") or "").lower()
                        runner = str(snap.get("runner_status") or "").lower()
                        if _decision_terminal(status) or (
                            runner in ("completed", "stopped", "failed")
                            and status != "preparing"
                        ):
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
        # profiles 侧 is_generating 不会被完整旧 config 覆盖
        if profiles.get("is_generating"):
            return False
        stage = str(config.get("generation_stage") or "")
        if "generating" in stage:
            return False
        cfg = config.get("config") if isinstance(config.get("config"), dict) else None
        has_cfg = bool(cfg and cfg.get("time_config") and cfg.get("agent_configs"))
        return has_cfg and (
            stage == "completed" or bool(config.get("config_generated"))
        )

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

    limit = request.args.get("limit", 200, type=int)
    last_count = {"n": 0}
    seen_ids: set = set()

    def _action_id(a: dict) -> str:
        if a.get("id") is not None:
            return str(a["id"])
        if a.get("_uniqueId"):
            return str(a["_uniqueId"])
        # 稳定主键：platform + sqlite rowid
        rowid = a.get("_rowid")
        if rowid is not None:
            return f"{a.get('platform')}:{int(rowid)}"
        content = str(a.get("content") or "")[:48]
        return (
            f"{a.get('platform')}:{a.get('agent_id')}:{a.get('round')}:"
            f"{a.get('action_type')}:{a.get('_idx')}:"
            f"{a.get('timestamp') or a.get('created_at') or ''}:"
            f"{content}"
        )

    def fetch():
        data = read_simulation_actions(sim_id, limit=limit, offset=0, newest=True)
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
        if not new_actions:
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
                # 无 state 时保持 watch（多进程/尚未落盘）；由前端卸载关闭
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
    """Step4：agent + console 日志增量 SSE。

    兼容传入 dec_* / sim_*：尽量解析为真实 report_*；解析不到则立即 done
   （对比报告模式无 agent-log）。
    """
    from app.decision.report_agent import ReportManager, ReportStatus

    resolved = report_id
    if not str(report_id).startswith("report_"):
        try:
            # dec_ → 首个 sim → by-simulation
            sim_id = None
            if str(report_id).startswith("dec_"):
                from app.ontology import registry as ont_registry

                ont_registry.init_schema()
                runs = ont_registry.list_runs_for_decision(report_id) or []
                for r in runs:
                    sid = (r or {}).get("sim_id")
                    if sid:
                        sim_id = sid
                        break
            elif str(report_id).startswith("sim_"):
                sim_id = report_id

            if sim_id:
                report_obj = ReportManager.get_report_by_simulation(sim_id)
                if report_obj:
                    resolved = report_obj.report_id
        except Exception as e:
            logger.warning(f"report logs resolve id failed: {e}")

    # 无真实报告且输入不是 report_*：对比模式 → 立即结束
    # 若已是 report_* 但元数据尚未落盘：进入 watch，等待创建
    existing = None
    try:
        existing = ReportManager.get_report(resolved)
    except Exception:
        existing = None
    if not existing and not str(resolved).startswith("report_"):
        def missing():
            yield _sse_format(
                "done",
                {
                    "report_id": report_id,
                    "resolved_report_id": resolved,
                    "status": "completed",
                    "mode": "compare_or_missing",
                    "agent": {"logs": [], "next_line": 0, "from_line": 0},
                    "console": {"logs": [], "next_line": 0, "from_line": 0},
                },
            )

        return _sse_response(missing())

    agent_from = request.args.get("agent_from", 0, type=int)
    console_from = request.args.get("console_from", 0, type=int)
    if agent_from is None:
        agent_from = 0
    if console_from is None:
        console_from = 0
    cursors = {"agent": int(agent_from), "console": int(console_from)}
    missing_ticks = {"n": 0}
    # ~90s：报告元数据尚未写入时继续等
    MAX_MISSING_TICKS = 60

    def fetch():
        agent = ReportManager.get_agent_log(resolved, from_line=cursors["agent"])
        console = ReportManager.get_console_log(resolved, from_line=cursors["console"])
        agent_logs = agent.get("logs") or []
        console_logs = console.get("logs") or []
        # 用 total_lines 推进，避免 JSON 坏行导致 cursor 回退重复
        agent_total = int(agent.get("total_lines") or cursors["agent"])
        console_total = int(console.get("total_lines") or cursors["console"])
        agent_next = max(agent_total, cursors["agent"] + len(agent_logs))
        console_next = max(console_total, cursors["console"] + len(console_logs))
        if not agent_logs and not console_logs:
            return {
                "report_id": resolved,
                "agent": {
                    "logs": [],
                    "next_line": cursors["agent"],
                    "from_line": cursors["agent"],
                },
                "console": {
                    "logs": [],
                    "next_line": cursors["console"],
                    "from_line": cursors["console"],
                },
                "_stable": True,
            }
        payload = {
            "report_id": resolved,
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
            report = ReportManager.get_report(resolved)
            if not report:
                missing_ticks["n"] += 1
                return missing_ticks["n"] >= MAX_MISSING_TICKS
            missing_ticks["n"] = 0
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


@stream_bp.get("/ontology/<ontology_id>/graph/events")
def ontology_graph_events(ontology_id: str):
    """建图期图谱 SSE：对齐 MiroFish data 读图，指纹用 node/edge count。"""
    from app.api.ontology import read_ontology_graph, resolve_ontology_graph_id
    from app.models.task import TaskManager
    from app.ontology import registry as ont_registry

    def fetch():
        data = read_ontology_graph(ontology_id)
        if not data:
            return {
                "ontology_id": ontology_id,
                "graph_id": None,
                "nodes": [],
                "edges": [],
                "node_count": 0,
                "edge_count": 0,
                "_stable": True,
            }
        # 指纹只看规模，避免对全图 JSON 做 MD5
        return {
            "ontology_id": ontology_id,
            "graph_id": data.get("graph_id"),
            "nodes": data.get("nodes") or [],
            "edges": data.get("edges") or [],
            "node_count": int(data.get("node_count") or 0),
            "edge_count": int(data.get("edge_count") or 0),
            "source": data.get("source"),
            "_fp": (
                f"{data.get('graph_id') or ''}:"
                f"{int(data.get('node_count') or 0)}:"
                f"{int(data.get('edge_count') or 0)}"
            ),
        }

    def done(snap: Any) -> bool:
        try:
            ont_registry.init_schema()
            ont = ont_registry.get_ontology(ontology_id)
            if not ont:
                return False
            status = str(ont.get("status") or "").lower()
            if status in ("ready", "graph_completed", "failed", "error"):
                return True
            tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
            if tid:
                task = TaskManager().get_task(tid)
                if task and task.status in TERMINAL_STATUSES:
                    return True
            # 无进行中任务且已有图：视为可结束（避免永久挂起）
            if resolve_ontology_graph_id(ontology_id) and status in (
                "ready",
                "graph_completed",
            ):
                return True
        except Exception:
            return False
        return False

    def generate():
        """自定义 watch：用 _fp 字段做指纹，变化才推全量 nodes/edges。"""
        last_fp: Optional[str] = None
        last_heartbeat = time.time()
        last_snap: Any = None
        send_initial = True
        try:
            while True:
                try:
                    snap = fetch()
                except Exception as e:
                    yield _sse_format(
                        "task_error",
                        {"error": str(e), "status": "failed"},
                    )
                    yield _sse_format("done", {"status": "failed", "error": str(e)})
                    return

                fp = (
                    snap.get("_fp")
                    if isinstance(snap, dict) and snap.get("_fp") is not None
                    else _fingerprint(
                        {
                            "graph_id": (snap or {}).get("graph_id"),
                            "node_count": (snap or {}).get("node_count"),
                            "edge_count": (snap or {}).get("edge_count"),
                        }
                        if isinstance(snap, dict)
                        else snap
                    )
                )
                # _stable 空快照：仅首包或指纹变化时推
                if send_initial or fp != last_fp:
                    if fp != last_fp or (send_initial and last_fp is None):
                        last_fp = fp
                        last_snap = snap
                        out = dict(snap) if isinstance(snap, dict) else snap
                        if isinstance(out, dict):
                            out.pop("_fp", None)
                            out.pop("_stable", None)
                        yield _sse_format("graph", out)
                        send_initial = False
                        last_heartbeat = time.time()

                if done(snap if snap is not None else last_snap):
                    out = dict(last_snap) if isinstance(last_snap, dict) else (last_snap or {})
                    if isinstance(out, dict):
                        out.pop("_fp", None)
                        out.pop("_stable", None)
                    yield _sse_format("done", out)
                    return

                time.sleep(WATCH_INTERVAL_SEC)
                if time.time() - last_heartbeat >= HEARTBEAT_SEC:
                    yield ": ping\n\n"
                    last_heartbeat = time.time()
        except GeneratorExit:
            pass

    return _sse_response(generate())
