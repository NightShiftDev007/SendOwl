"""推演运行 API"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from app.config import Config
from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.api.run")

run_bp = Blueprint("run", __name__, url_prefix="/api/run")

_SYSTEM_EVENTS = {
    "simulation_start",
    "simulation_end",
    "round_start",
    "round_end",
}

_TRACE_ACTION_MAP = {
    "create_post": "CREATE_POST",
    "quote_post": "QUOTE_POST",
    "repost": "REPOST",
    "like_post": "LIKE_POST",
    "dislike_post": "DISLIKE_POST",
    "create_comment": "CREATE_COMMENT",
    "follow": "FOLLOW",
    "mute": "MUTE",
}


def _resolve_run_context(run_id: str) -> Tuple[Dict[str, Any], str, str]:
    """
    返回 (run_record_or_stub, sim_id, run_dir)。
    终局：SimulationRunner 按 sim_id 操作；run_dir 指向 uploads/runs/<sim_id>。
    """
    registry.init_schema()
    run = registry.get_run(run_id)
    if run:
        sim_id = run.get("sim_id") or run_id
        run_dir = run.get("run_dir") or os.path.join(
            Config.OASIS_SIMULATION_DATA_DIR, sim_id
        )
        return run, sim_id, run_dir
    # 兼容：直接传 sim_id
    run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, run_id)
    if os.path.isdir(run_dir):
        return {"id": run_id, "sim_id": run_id, "run_dir": run_dir, "status": "unknown"}, run_id, run_dir
    # 旧 run_* 目录
    legacy = os.path.join(Config.RUN_DIR, run_id)
    if os.path.isdir(legacy):
        return {"id": run_id, "run_dir": legacy, "status": "unknown"}, run_id, legacy
    return {}, run_id, run_dir


@run_bp.get("/health")
def health():
    return jsonify({"status": "ok", "module": "run"})


@run_bp.get("/<run_id>")
def get_run(run_id: str):
    run, sim_id, run_dir = _resolve_run_context(run_id)
    if not run and not os.path.isdir(run_dir):
        return jsonify({"success": False, "error": "not found"}), 404
    if not run:
        run = {"id": run_id, "run_dir": run_dir, "status": "unknown"}

    try:
        from app.engine.simulation_runner import SimulationRunner

        state = SimulationRunner.get_run_state(sim_id)
        if state:
            run["runner"] = state.to_dict() if hasattr(state, "to_dict") else {
                "runner_status": getattr(state, "runner_status", None),
                "current_round": getattr(state, "current_round", None),
            }
    except Exception:
        pass

    run["run_dir"] = run_dir
    run["sim_id"] = sim_id
    return jsonify({"success": True, "data": run})


def _load_agents_for_run(run_dir: str) -> List[Dict[str, Any]]:
    """从 profiles / OASIS DB 列出可采访 Agent。"""
    agents: List[Dict[str, Any]] = []
    seen = set()

    reddit = Path(run_dir) / "reddit_profiles.json"
    if reddit.exists():
        try:
            rows = json.loads(reddit.read_text(encoding="utf-8"))
            for row in rows if isinstance(rows, list) else []:
                aid = row.get("user_id", row.get("agent_id"))
                if aid is None:
                    continue
                aid = int(aid)
                if aid in seen:
                    continue
                seen.add(aid)
                agents.append(
                    {
                        "agent_id": aid,
                        "name": row.get("name") or row.get("username") or f"Agent_{aid}",
                        "username": row.get("username") or "",
                        "entity_type": row.get("source_entity_type")
                        or row.get("profession")
                        or "",
                        "bio": (row.get("bio") or "")[:160],
                    }
                )
        except Exception as e:
            logger.warning(f"load reddit profiles failed: {e}")

    if not agents:
        csv_path = Path(run_dir) / "twitter_profiles.csv"
        if csv_path.exists():
            try:
                import csv

                with csv_path.open(encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        aid = row.get("user_id") or row.get("agent_id")
                        if aid is None or aid == "":
                            continue
                        aid = int(aid)
                        if aid in seen:
                            continue
                        seen.add(aid)
                        agents.append(
                            {
                                "agent_id": aid,
                                "name": row.get("name") or row.get("username") or f"Agent_{aid}",
                                "username": row.get("username") or "",
                                "entity_type": "",
                                "bio": (row.get("description") or row.get("user_char") or "")[
                                    :160
                                ],
                            }
                        )
            except Exception as e:
                logger.warning(f"load twitter profiles failed: {e}")

    if not agents:
        for db in _db_candidates(run_dir):
            if not db.exists():
                continue
            try:
                conn = sqlite3.connect(str(db))
                conn.row_factory = sqlite3.Row
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "user" in tables:
                    for r in conn.execute(
                        "SELECT user_id, agent_id, name, user_name, bio FROM user"
                    ):
                        aid = r["agent_id"] if r["agent_id"] is not None else r["user_id"]
                        aid = int(aid)
                        if aid in seen:
                            continue
                        seen.add(aid)
                        agents.append(
                            {
                                "agent_id": aid,
                                "name": r["name"] or r["user_name"] or f"Agent_{aid}",
                                "username": r["user_name"] or "",
                                "entity_type": "",
                                "bio": (r["bio"] or "")[:160],
                            }
                        )
                conn.close()
                if agents:
                    break
            except Exception as e:
                logger.warning(f"load agents from db failed: {e}")

    agents.sort(key=lambda a: a["agent_id"])
    return agents


@run_bp.get("/<run_id>/agents")
def list_agents(run_id: str):
    run, sim_id, run_dir = _resolve_run_context(run_id)
    if not os.path.isdir(run_dir):
        return jsonify({"success": False, "error": "run not found"}), 404
    agents = _load_agents_for_run(run_dir)
    return jsonify(
        {
            "success": True,
            "data": {
                "run_id": run_id,
                "sim_id": sim_id,
                "agents": agents,
                "count": len(agents),
            },
        }
    )


def _action_candidates(run_dir: str) -> List[Path]:
    return [
        Path(run_dir) / "actions.jsonl",
        Path(run_dir) / "twitter" / "actions.jsonl",
        Path(run_dir) / "reddit" / "actions.jsonl",
    ]


def _db_candidates(run_dir: str) -> List[Path]:
    return [
        Path(run_dir) / "twitter_simulation.db",
        Path(run_dir) / "reddit_simulation.db",
        Path(run_dir) / "twitter" / "twitter_simulation.db",
        Path(run_dir) / "reddit" / "reddit_simulation.db",
    ]


def _content_of(row: Dict[str, Any]) -> str:
    args = row.get("action_args") or {}
    if not isinstance(args, dict):
        args = {}
    return (
        row.get("content")
        or args.get("content")
        or args.get("quote_content")
        or args.get("post_content")
        or ""
    )


def _is_displayable_action(row: Dict[str, Any]) -> bool:
    """系统事件与空壳 LLM_ACTION 不进时间线。"""
    event = row.get("event_type")
    if event and event in _SYSTEM_EVENTS:
        return False

    action_type = str(row.get("action_type") or "").upper()
    if not action_type and not event:
        return bool(row.get("agent_id") is not None and _content_of(row))

    if action_type in ("LLM_ACTION", "DO_NOTHING", "REFRESH", "SIGN_UP"):
        return bool(_content_of(row).strip())

    if action_type in (
        "CREATE_POST",
        "QUOTE_POST",
        "REPOST",
        "CREATE_COMMENT",
        "LIKE_POST",
        "DISLIKE_POST",
        "FOLLOW",
        "MUTE",
    ):
        return True

    # 其它带正文的动作保留
    return bool(_content_of(row).strip())


def _normalize_action(row: Dict[str, Any], idx: int) -> Dict[str, Any]:
    content = _content_of(row)
    action_type = str(row.get("action_type") or row.get("event_type") or "ACTION").upper()
    agent_id = row.get("agent_id")
    agent_name = (
        row.get("agent_name")
        or row.get("name")
        or (f"Agent_{agent_id}" if agent_id is not None else "Unknown")
    )
    # LIKE / REPOST 无正文时给一句可读摘要
    if not content.strip():
        if action_type == "LIKE_POST":
            pid = (row.get("action_args") or {}).get("post_id") or row.get("post_id")
            content = f"点赞了帖子 #{pid}" if pid is not None else "点赞了一条帖子"
        elif action_type == "REPOST":
            pid = (row.get("action_args") or {}).get("reposted_id") or row.get("post_id")
            content = f"转发了帖子 #{pid}" if pid is not None else "转发了一条帖子"
        elif action_type == "FOLLOW":
            content = "关注了用户"
    # 保留稳定主键：优先 rowid，其次已有 id；不要用枚举下标覆盖 _rowid
    rowid = row.get("_rowid")
    if rowid is None and row.get("_idx") is not None and row.get("_source") == "oasis_db":
        rowid = row.get("_idx")
    stable_idx = rowid if rowid is not None else idx
    out = {
        **row,
        "action_type": action_type,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "content": content,
        "round": row.get("round", row.get("round_num")),
        "_idx": stable_idx,
    }
    if rowid is not None:
        out["_rowid"] = int(rowid)
    return out


def _actions_from_oasis_db(
    db_path: Path, limit: int = 500, newest_first: bool = False
) -> List[Dict[str, Any]]:
    """从 OASIS SQLite 还原带正文的动作（优于空壳 LLM_ACTION jsonl）。

    newest_first=True 时按最新优先截断，供 SSE 直播增量使用。
    """
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "trace" not in tables or "user" not in tables:
            conn.close()
            return []

        users = {
            int(r["user_id"]): {
                "agent_id": r["agent_id"] if r["agent_id"] is not None else r["user_id"],
                "name": r["name"] or f"Agent_{r['user_id']}",
            }
            for r in conn.execute("SELECT user_id, agent_id, name FROM user")
        }
        posts = {}
        if "post" in tables:
            for r in conn.execute(
                "SELECT post_id, user_id, content, quote_content, original_post_id, created_at FROM post"
            ):
                posts[int(r["post_id"])] = dict(r)

        order_sql = "DESC" if newest_first else "ASC"
        actions: List[Dict[str, Any]] = []
        for i, r in enumerate(
            conn.execute(
                f"SELECT rowid AS _rowid, user_id, created_at, action, info FROM trace "
                f"ORDER BY created_at {order_sql}, rowid {order_sql}"
            )
        ):
            raw_action = (r["action"] or "").lower()
            mapped = _TRACE_ACTION_MAP.get(raw_action)
            if not mapped:
                continue
            try:
                info = json.loads(r["info"] or "{}")
            except json.JSONDecodeError:
                info = {}

            user = users.get(int(r["user_id"]), {})
            agent_id = user.get("agent_id", r["user_id"])
            agent_name = user.get("name") or f"Agent_{agent_id}"
            round_num = int(r["created_at"] or 0)
            rowid = int(r["_rowid"])
            content = ""
            post_id = info.get("post_id") or info.get("new_post_id")
            parent_id = (
                info.get("quoted_id")
                or info.get("reposted_id")
                or info.get("original_post_id")
            )

            if mapped in ("CREATE_POST", "QUOTE_POST", "REPOST", "CREATE_COMMENT"):
                content = info.get("content") or info.get("quote_content") or ""
                if not content and post_id is not None and int(post_id) in posts:
                    p = posts[int(post_id)]
                    # quote 优先展示评论正文
                    content = (p.get("quote_content") or p.get("content") or "").strip()
                    if mapped == "QUOTE_POST" and p.get("quote_content"):
                        content = p["quote_content"]
                    elif mapped == "REPOST" and not content:
                        orig = posts.get(int(parent_id)) if parent_id is not None else None
                        content = (orig or {}).get("content") or ""
                        if content:
                            content = f"转发：{content[:120]}"
                if mapped == "QUOTE_POST" and not content and parent_id is not None:
                    orig = posts.get(int(parent_id))
                    if orig:
                        content = f"引用：{(orig.get('content') or '')[:120]}"

            # 对齐 MiroFish 时间线字段：quote_content / original_content / post_content
            enriched_args = dict(info) if isinstance(info, dict) else {}
            if mapped == "QUOTE_POST":
                new_post = posts.get(int(post_id)) if post_id is not None else None
                orig = posts.get(int(parent_id)) if parent_id is not None else None
                if new_post and new_post.get("quote_content"):
                    enriched_args["quote_content"] = new_post["quote_content"]
                    content = content or new_post["quote_content"]
                elif content:
                    enriched_args["quote_content"] = content
                if orig:
                    enriched_args["original_content"] = (orig.get("content") or "").strip()
                    author = users.get(int(orig.get("user_id") or -1), {})
                    if author.get("name"):
                        enriched_args["original_author_name"] = author["name"]
            elif mapped == "REPOST" and parent_id is not None:
                orig = posts.get(int(parent_id))
                if orig:
                    enriched_args["original_content"] = (orig.get("content") or "").strip()
                    author = users.get(int(orig.get("user_id") or -1), {})
                    if author.get("name"):
                        enriched_args["original_author_name"] = author["name"]
            elif mapped in ("LIKE_POST", "DISLIKE_POST"):
                liked_id = info.get("post_id") or info.get("like_id") or info.get("dislike_id")
                liked = posts.get(int(liked_id)) if liked_id is not None else None
                if liked:
                    enriched_args["post_content"] = (
                        liked.get("quote_content") or liked.get("content") or ""
                    ).strip()
                    author = users.get(int(liked.get("user_id") or -1), {})
                    if author.get("name"):
                        enriched_args["post_author_name"] = author["name"]
            elif mapped == "CREATE_POST" and content and not enriched_args.get("content"):
                enriched_args["content"] = content

            actions.append(
                {
                    "round": round_num,
                    "round_num": round_num,
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "action_type": mapped,
                    "action_args": enriched_args,
                    "content": content,
                    "post_id": post_id,
                    "parent_post_id": parent_id,
                    "timestamp": None,
                    "success": True,
                    # rowid 跨轮询稳定；枚举下标 i 仅作兜底
                    "_rowid": rowid,
                    "_idx": rowid,
                    "_enum": i,
                    "_source": "oasis_db",
                }
            )
            if len(actions) >= limit:
                break

        conn.close()
        return actions
    except Exception as e:
        logger.warning(f"从 OASIS DB 还原动作失败: {db_path}: {e}")
        return []


def _load_actions_from_jsonl(
    path: Path, limit: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    actions: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event_type") in _SYSTEM_EVENTS:
                events.append(row)
                continue
            if _is_displayable_action(row):
                actions.append(_normalize_action(row, i))
            else:
                events.append(row)
    return actions[:limit], events


@run_bp.get("/<run_id>/actions")
def get_actions(run_id: str):
    run, sim_id, run_dir = _resolve_run_context(run_id)
    limit = int(request.args.get("limit") or 500)
    include_events = str(request.args.get("include_events") or "").lower() in (
        "1",
        "true",
        "yes",
    )

    # 1) 优先 OASIS DB（有真实正文）
    db_actions: List[Dict[str, Any]] = []
    db_path_used: Optional[str] = None
    for db in _db_candidates(run_dir):
        rows = _actions_from_oasis_db(db, limit=limit)
        if len(rows) > len(db_actions):
            db_actions = rows
            db_path_used = str(db)

    # 2) jsonl 作为补充 / 无 DB 时的回退
    jsonl_actions: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    jsonl_path: Optional[str] = None
    for path in _action_candidates(run_dir):
        if not path.exists():
            continue
        acts, evs = _load_actions_from_jsonl(path, limit)
        if len(acts) > len(jsonl_actions) or jsonl_path is None:
            jsonl_actions, events, jsonl_path = acts, evs, str(path)

    # DB 有实质内容时用 DB；否则用 jsonl
    if db_actions and (
        sum(1 for a in db_actions if (a.get("content") or "").strip())
        >= max(1, sum(1 for a in jsonl_actions if (a.get("content") or "").strip()))
    ):
        best_actions = [_normalize_action(a, i) for i, a in enumerate(db_actions)]
        source = db_path_used
    else:
        best_actions = jsonl_actions
        source = jsonl_path

    if not best_actions and not events:
        return jsonify(
            {
                "success": True,
                "data": {"actions": [], "events": [], "path": None, "count": 0},
            }
        )

    payload: Dict[str, Any] = {
        "actions": best_actions[:limit],
        "path": source,
        "count": len(best_actions[:limit]),
        "event_count": len(events),
        "source": "oasis_db" if source == db_path_used else "jsonl",
    }
    if include_events:
        payload["events"] = events[-50:]
    else:
        payload["events_summary"] = [
            {
                "event_type": e.get("event_type"),
                "round": e.get("round"),
                "timestamp": e.get("timestamp"),
            }
            for e in events
            if e.get("event_type") in ("simulation_start", "simulation_end")
        ]
    return jsonify({"success": True, "data": payload})


@run_bp.post("/<run_id>/interview")
def interview(run_id: str):
    """代理到 SimulationRunner.interview（按 sim_id）；环境不可用时返回 stub。"""
    run, sim_id, run_dir = _resolve_run_context(run_id)
    body = request.get_json(silent=True) or {}
    agent_id = body.get("agent_id")
    prompt = body.get("prompt") or body.get("question") or "你怎么看当前政策？"

    try:
        from app.engine.simulation_runner import SimulationRunner

        state = SimulationRunner.get_run_state(sim_id)
        status = getattr(getattr(state, "runner_status", None), "value", None) or (
            str(getattr(state, "runner_status", "")) if state else ""
        )
        # 也检查 env alive
        alive = False
        try:
            alive = bool(SimulationRunner.check_env_alive(sim_id))
        except Exception:
            alive = False
        if state and (status in ("running", "completed", "paused", "alive") or alive):
            if agent_id is not None:
                result = SimulationRunner.interview_agent(
                    simulation_id=sim_id,
                    agent_id=int(agent_id),
                    prompt=prompt,
                )
            else:
                max_agents = int(body.get("max_agents") or 3)
                interviews = [
                    {"agent_id": i, "prompt": prompt} for i in range(max_agents)
                ]
                result = SimulationRunner.interview_agents_batch(
                    simulation_id=sim_id,
                    interviews=interviews,
                )
            return jsonify(
                {"success": True, "data": result, "mode": "live", "sim_id": sim_id}
            )
    except Exception as e:
        logger.warning(f"interview live failed: {e}")

    return jsonify(
        {
            "success": True,
            "mode": "stub",
            "data": {
                "reply": f"[stub] Agent {agent_id}：关于「{prompt}」，我需要更多上下文才能判断。",
                "agent_id": agent_id,
                "run_id": run_id,
                "sim_id": sim_id,
            },
        }
    )
