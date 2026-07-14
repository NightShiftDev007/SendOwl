"""ProgressEnvelope：统一进度读模型。

所有进度类数据（decision prepare / run / task）映射到同一形状，
供 SSE 与 HTTP 快照共用。结果增量走 artifacts（digest / watermark），
避免把完整 persona / 整图塞进每一帧。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import Config

DIGEST_LIMIT = 20
BIO_TRUNCATE = 80


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_profiles(profiles: Optional[List[Any]], limit: int = DIGEST_LIMIT) -> List[Dict[str, Any]]:
    """裁剪人设摘要，供 SSE 帧使用。"""
    if not isinstance(profiles, list):
        return []
    out: List[Dict[str, Any]] = []
    for p in profiles[:limit]:
        if not isinstance(p, dict):
            continue
        bio = str(p.get("bio") or p.get("description") or "")
        if len(bio) > BIO_TRUNCATE:
            bio = bio[:BIO_TRUNCATE] + "…"
        topics = p.get("interested_topics") or p.get("topics") or []
        if isinstance(topics, str):
            topics = [topics]
        if not isinstance(topics, list):
            topics = []
        topics = [str(t) for t in topics[:6] if t]
        out.append(
            {
                "name": p.get("name") or p.get("username") or "",
                "username": p.get("username") or "",
                "entity_type": p.get("entity_type") or p.get("profession") or "",
                "bio": bio,
                "interested_topics": topics,
                "topics_count": len(topics),
            }
        )
    return out


def _load_profiles_list(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        if isinstance(raw, dict):
            items = raw.get("profiles") or raw.get("agents") or []
            return [x for x in items if isinstance(x, dict)]
    except Exception:
        pass
    return []


def resolve_sim_id_for_decision(decision_id: str) -> Optional[str]:
    """从 registry 解析 decision 下首个 run 的 sim_id。"""
    if not decision_id or not str(decision_id).startswith("dec_"):
        return None
    try:
        from app.ontology import registry as ont_registry

        ont_registry.init_schema()
        runs = ont_registry.list_runs_for_decision(decision_id) or []
        for r in runs:
            sid = (r or {}).get("sim_id")
            if sid:
                return str(sid)
    except Exception:
        pass
    return None


def load_profiles_digest_for_decision(
    decision_id: str,
    *,
    sim_id: Optional[str] = None,
    limit: int = DIGEST_LIMIT,
) -> Dict[str, Any]:
    """从 shared / sim 读 reddit_profiles，返回 count + digest。"""
    resolved = sim_id or resolve_sim_id_for_decision(decision_id)
    search_dirs: List[str] = []
    if resolved:
        search_dirs.append(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, resolved))
    if decision_id and str(decision_id).startswith("dec_"):
        search_dirs.append(os.path.join(Config.DECISION_DIR, decision_id, "shared"))

    profiles: List[Dict[str, Any]] = []
    for d in search_dirs:
        path = os.path.join(d, "reddit_profiles.json")
        profiles = _load_profiles_list(path)
        if profiles:
            break

    topics_total = 0
    for p in profiles:
        topics = p.get("interested_topics") or p.get("topics") or []
        if isinstance(topics, list):
            topics_total += len(topics)

    return {
        "profile_count": len(profiles),
        "profiles_digest": digest_profiles(profiles, limit=limit),
        "topics_count": topics_total,
        "sim_id": resolved,
    }


def load_profiles_digest_for_sim(
    simulation_id: str,
    *,
    limit: int = DIGEST_LIMIT,
) -> Dict[str, Any]:
    """从单个 sim 目录读人设 digest。"""
    if not simulation_id:
        return {"profile_count": 0, "profiles_digest": [], "topics_count": 0}
    path = os.path.join(
        Config.OASIS_SIMULATION_DATA_DIR, simulation_id, "reddit_profiles.json"
    )
    profiles = _load_profiles_list(path)
    topics_total = 0
    for p in profiles:
        topics = p.get("interested_topics") or p.get("topics") or []
        if isinstance(topics, list):
            topics_total += len(topics)
    return {
        "profile_count": len(profiles),
        "profiles_digest": digest_profiles(profiles, limit=limit),
        "topics_count": topics_total,
        "sim_id": simulation_id,
    }


def _config_ready_for_sim(simulation_id: Optional[str]) -> bool:
    if not simulation_id:
        return False
    path = os.path.join(
        Config.OASIS_SIMULATION_DATA_DIR, simulation_id, "simulation_config.json"
    )
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(
            isinstance(cfg, dict)
            and cfg.get("time_config")
            and cfg.get("agent_configs")
        )
    except Exception:
        return False


def _map_decision_status(raw: Optional[str]) -> str:
    s = str(raw or "").lower()
    if s in ("preparing", "pending", "created"):
        return "running" if s == "preparing" else "pending"
    if s in ("prepared", "ready", "completed", "done", "success"):
        return "completed"
    if s in ("prepare_failed", "failed", "error"):
        return "failed"
    if s in ("running",):
        return "running"
    if s in ("stopped", "cancelled"):
        return "failed"
    return s or "pending"


def build_decision_envelope(
    decision_id: str,
    status_snap: Optional[Dict[str, Any]] = None,
    *,
    include_profiles_digest: bool = True,
) -> Dict[str, Any]:
    """从 get_status 快照 / prepare_progress 构建 Envelope。"""
    snap = status_snap or {}
    dec = snap.get("decision") if isinstance(snap.get("decision"), dict) else {}
    raw_status = snap.get("status") or dec.get("status")
    prep = snap.get("prepare_progress") if isinstance(snap.get("prepare_progress"), dict) else {}

    status_l = str(raw_status or "").lower()
    is_preparing = status_l == "preparing"

    # 准备中优先细进度；推演中用矩阵粗进度
    if is_preparing or prep:
        stage = str(snap.get("stage") or prep.get("stage") or ("preparing" if is_preparing else "idle"))
        progress = snap.get("prepare_percent")
        if progress is None:
            progress = prep.get("progress")
        try:
            progress = int(progress) if progress is not None else 0
        except (TypeError, ValueError):
            progress = 0
        message = snap.get("message") or prep.get("message") or ""
        profile_count = snap.get("profile_count")
        if profile_count is None:
            profile_count = prep.get("profile_count") or 0
    else:
        stage = "running" if status_l == "running" else (status_l or "idle")
        prog = snap.get("progress") if isinstance(snap.get("progress"), dict) else {}
        done = int(prog.get("done") or 0)
        total = int(prog.get("total") or 0)
        progress = int(round(100.0 * done / total)) if total > 0 else (
            100 if status_l in ("completed", "done", "success") else 0
        )
        message = snap.get("message") or ""
        profile_count = snap.get("profile_count") or prep.get("profile_count") or 0

    artifacts: Dict[str, Any] = {
        "profile_count": int(profile_count or 0),
        "config_ready": bool(snap.get("config_ready")),
        "prepare_task_id": (
            dec.get("prepare_task_id")
            or snap.get("prepare_task_id")
            or prep.get("prepare_task_id")
        ),
        "report_task_id": snap.get("report_task_id") or dec.get("report_task_id"),
        "topics_count": int(snap.get("topics_count") or 0),
    }
    total_expected = prep.get("total_expected") or snap.get("total_expected")
    try:
        if total_expected is not None and int(total_expected) > 0:
            artifacts["total_expected"] = int(total_expected)
    except (TypeError, ValueError):
        pass

    if include_profiles_digest and is_preparing:
        sim_id = (
            snap.get("sim_id")
            or snap.get("simulation_id")
            or resolve_sim_id_for_decision(decision_id)
        )
        digest_info = load_profiles_digest_for_decision(decision_id, sim_id=sim_id)
        if digest_info["profile_count"] > 0:
            artifacts["profile_count"] = digest_info["profile_count"]
        artifacts["profiles_digest"] = digest_info["profiles_digest"]
        artifacts["topics_count"] = digest_info.get("topics_count") or 0
        if digest_info.get("sim_id"):
            artifacts["sim_id"] = digest_info["sim_id"]
            artifacts["config_ready"] = artifacts["config_ready"] or _config_ready_for_sim(
                digest_info["sim_id"]
            )
        if not message and artifacts["profile_count"]:
            message = f"已生成 {artifacts['profile_count']} 个人设"

    updated_at = (
        prep.get("updated_at")
        or snap.get("updated_at")
        or dec.get("updated_at")
        or _utc_now()
    )

    return {
        "scope": "decision",
        "id": decision_id,
        "status": _map_decision_status(raw_status),
        "raw_status": status_l,
        "stage": stage,
        "progress": max(0, min(100, int(progress or 0))),
        "message": message or "",
        "artifacts": artifacts,
        "updated_at": updated_at,
    }


def build_task_envelope(task_id: str, task_snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从 TaskManager 快照构建 Envelope；prepare 任务读盘补 profiles digest。"""
    snap = task_snap
    if snap is None:
        from app.models.task import TaskManager

        task = TaskManager().get_task(task_id)
        snap = task.to_dict() if task else None
    if not snap:
        return {
            "scope": "task",
            "id": task_id,
            "status": "failed",
            "stage": "missing",
            "progress": 0,
            "message": "task_not_found",
            "artifacts": {},
            "updated_at": _utc_now(),
        }

    status = str(snap.get("status") or "pending").lower()
    mapped = {
        "pending": "pending",
        "processing": "running",
        "completed": "completed",
        "failed": "failed",
    }.get(status, status)

    meta = snap.get("metadata") if isinstance(snap.get("metadata"), dict) else {}
    detail = snap.get("progress_detail") if isinstance(snap.get("progress_detail"), dict) else {}
    task_type = str(snap.get("task_type") or "")
    sim_id = meta.get("simulation_id") or detail.get("simulation_id")

    artifacts: Dict[str, Any] = {
        "prepare_task_id": task_id if task_type in ("prepare", "simulation_prepare") else None,
        "report_task_id": task_id if task_type == "report_generate" else meta.get("report_task_id"),
        "report_id": meta.get("report_id"),
        "simulation_id": sim_id,
        "ontology_id": meta.get("ontology_id") or meta.get("project_id"),
        "profile_count": detail.get("profile_count") or meta.get("profile_count"),
        "config_ready": bool(detail.get("config_ready")),
        "topics_count": int(detail.get("topics_count") or 0),
    }

    # N=1 prepare：读盘补人设增量（等价合并旧 preview SSE）
    if task_type in ("prepare", "simulation_prepare") and sim_id and mapped == "running":
        digest_info = load_profiles_digest_for_sim(str(sim_id))
        if digest_info["profile_count"] > 0:
            artifacts["profile_count"] = digest_info["profile_count"]
        artifacts["profiles_digest"] = digest_info["profiles_digest"]
        artifacts["topics_count"] = digest_info.get("topics_count") or 0
        artifacts["config_ready"] = artifacts["config_ready"] or _config_ready_for_sim(
            str(sim_id)
        )
        # 预期：progress_detail.total_items（含 Cast 下调）优先，其次 state.entities_count
        try:
            detail_total = detail.get("total_items")
            if detail_total is not None and int(detail_total) > 0:
                artifacts["total_expected"] = int(detail_total)
            else:
                state_path = os.path.join(
                    Config.OASIS_SIMULATION_DATA_DIR, str(sim_id), "state.json"
                )
                if os.path.isfile(state_path):
                    with open(state_path, encoding="utf-8") as f:
                        st = json.load(f) or {}
                    ec = st.get("entities_count") or 0
                    if ec:
                        artifacts["total_expected"] = int(ec)
        except Exception:
            pass
    elif task_type in ("prepare", "simulation_prepare") and sim_id and mapped == "completed":
        digest_info = load_profiles_digest_for_sim(str(sim_id))
        artifacts["profile_count"] = digest_info["profile_count"]
        artifacts["profiles_digest"] = digest_info["profiles_digest"]
        artifacts["topics_count"] = digest_info.get("topics_count") or 0
        artifacts["config_ready"] = True

    message = snap.get("message") or snap.get("error") or ""
    if (
        not message
        and artifacts.get("profile_count")
        and task_type in ("prepare", "simulation_prepare")
        and mapped == "running"
    ):
        message = f"已生成 {artifacts['profile_count']} 个人设"

    return {
        "scope": "task",
        "id": task_id,
        "status": mapped,
        "raw_status": status,
        "stage": str(detail.get("stage") or snap.get("task_type") or "task"),
        "progress": int(snap.get("progress") or 0),
        "message": message,
        "artifacts": artifacts,
        "updated_at": snap.get("updated_at") or _utc_now(),
    }
