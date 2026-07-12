"""
本体元数据注册表（meta.db）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models.store import connection, get_connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    return dict(row)


def init_schema(db_path: str | None = None) -> None:
    """创建本体 / 决策相关表。"""
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ontologies (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              template TEXT DEFAULT 'opinion',
              graph_id TEXT,
              schema_json TEXT,
              schema_locked INTEGER DEFAULT 0,
              status TEXT DEFAULT 'created',
              build_task_id TEXT,
              simulation_requirement TEXT,
              trashed_at TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS ontology_documents (
              id TEXT PRIMARY KEY,
              ontology_id TEXT,
              filename TEXT,
              path TEXT,
              char_count INTEGER,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS ontology_versions (
              id TEXT PRIMARY KEY,
              ontology_id TEXT,
              version INTEGER,
              snapshot_path TEXT,
              node_count INTEGER,
              edge_count INTEGER,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS decisions (
              id TEXT PRIMARY KEY,
              ontology_id TEXT,
              version_id TEXT,
              title TEXT,
              status TEXT DEFAULT 'created',
              sample_count INTEGER DEFAULT 3,
              max_rounds INTEGER DEFAULT 10,
              shared_world_dir TEXT,
              trashed_at TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS scenarios (
              id TEXT PRIMARY KEY,
              decision_id TEXT,
              name TEXT,
              kind TEXT,
              intervention_json TEXT,
              color TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              scenario_id TEXT,
              seed INTEGER,
              status TEXT DEFAULT 'pending',
              run_dir TEXT,
              sim_id TEXT,
              metrics_json TEXT,
              started_at TEXT,
              finished_at TEXT,
              error TEXT
            );
            """
        )
        # 兼容旧库：补列
        try:
            run_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "sim_id" not in run_cols:
                conn.execute("ALTER TABLE runs ADD COLUMN sim_id TEXT")
            ont_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(ontologies)").fetchall()
            }
            if "build_task_id" not in ont_cols:
                conn.execute("ALTER TABLE ontologies ADD COLUMN build_task_id TEXT")
            if "simulation_requirement" not in ont_cols:
                conn.execute(
                    "ALTER TABLE ontologies ADD COLUMN simulation_requirement TEXT"
                )
            if "trashed_at" not in ont_cols:
                conn.execute("ALTER TABLE ontologies ADD COLUMN trashed_at TEXT")
            dec_cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(decisions)").fetchall()
            }
            if "trashed_at" not in dec_cols:
                conn.execute("ALTER TABLE decisions ADD COLUMN trashed_at TEXT")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def create_ontology(
    name: str,
    template: str = "opinion",
    schema: Optional[Dict[str, Any]] = None,
    schema_locked: bool = False,
    status: str = "created",
    graph_id: Optional[str] = None,
    simulation_requirement: str = "",
) -> Dict[str, Any]:
    oid = f"ont_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    schema_json = json.dumps(schema, ensure_ascii=False) if schema else None
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO ontologies
              (id, name, template, graph_id, schema_json, schema_locked, status,
               simulation_requirement, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                name,
                template,
                graph_id,
                schema_json,
                1 if schema_locked else 0,
                status,
                simulation_requirement or "",
                now,
                now,
            ),
        )
    return get_ontology(oid)


def list_documents_by_ontology_ids(
    ontology_ids: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """批量按本体 ID 拉取文档，避免列表接口 N+1。"""
    if not ontology_ids:
        return {}
    placeholders = ",".join("?" * len(ontology_ids))
    with connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM ontology_documents
            WHERE ontology_id IN ({placeholders})
            ORDER BY created_at
            """,
            list(ontology_ids),
        ).fetchall()
    result: Dict[str, List[Dict[str, Any]]] = {oid: [] for oid in ontology_ids}
    for row in rows:
        doc = _row_to_dict(row)
        result.setdefault(doc["ontology_id"], []).append(doc)
    return result


def list_ontologies(include_trashed: bool = False) -> List[Dict[str, Any]]:
    with connection() as conn:
        if include_trashed:
            rows = conn.execute(
                "SELECT * FROM ontologies ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM ontologies
                WHERE trashed_at IS NULL OR trashed_at = ''
                ORDER BY created_at DESC
                """
            ).fetchall()
    items = [_enrich_ontology(_row_to_dict(r)) for r in rows]
    docs_map = list_documents_by_ontology_ids([o["id"] for o in items if o.get("id")])
    for item in items:
        item["documents"] = docs_map.get(item["id"], [])
    return items


def get_ontology(ontology_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM ontologies WHERE id = ?", (ontology_id,)
        ).fetchone()
    if not row:
        return None
    return _enrich_ontology(_row_to_dict(row))


def _enrich_ontology(d: Dict[str, Any]) -> Dict[str, Any]:
    if not d:
        return d
    raw = d.get("schema_json")
    if raw:
        try:
            d["schema"] = json.loads(raw)
        except json.JSONDecodeError:
            d["schema"] = None
    else:
        d["schema"] = None
    d["schema_locked"] = bool(d.get("schema_locked"))
    return d


def update_ontology(ontology_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {
        "name",
        "template",
        "graph_id",
        "schema_json",
        "schema_locked",
        "status",
        "build_task_id",
        "simulation_requirement",
    }
    updates = {}
    for k, v in fields.items():
        if k == "schema" and v is not None:
            updates["schema_json"] = json.dumps(v, ensure_ascii=False)
        elif k in allowed:
            if k == "schema_locked":
                updates[k] = 1 if v else 0
            else:
                updates[k] = v
    if not updates:
        return get_ontology(ontology_id)
    updates["updated_at"] = _utc_now()
    cols = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [ontology_id]
    with connection() as conn:
        conn.execute(f"UPDATE ontologies SET {cols} WHERE id = ?", vals)
    return get_ontology(ontology_id)


def add_document(
    ontology_id: str,
    filename: str,
    path: str,
    char_count: int = 0,
) -> Dict[str, Any]:
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO ontology_documents
              (id, ontology_id, filename, path, char_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (doc_id, ontology_id, filename, path, char_count, now),
        )
    return {
        "id": doc_id,
        "ontology_id": ontology_id,
        "filename": filename,
        "path": path,
        "char_count": char_count,
        "created_at": now,
    }


def list_documents(ontology_id: str) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ontology_documents WHERE ontology_id = ? ORDER BY created_at",
            (ontology_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_version(
    ontology_id: str,
    version: int,
    snapshot_path: str,
    node_count: int = 0,
    edge_count: int = 0,
) -> Dict[str, Any]:
    vid = f"ver_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO ontology_versions
              (id, ontology_id, version, snapshot_path, node_count, edge_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (vid, ontology_id, version, snapshot_path, node_count, edge_count, now),
        )
    return {
        "id": vid,
        "ontology_id": ontology_id,
        "version": version,
        "snapshot_path": snapshot_path,
        "node_count": node_count,
        "edge_count": edge_count,
        "created_at": now,
    }


def list_versions(ontology_id: str) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM ontology_versions
            WHERE ontology_id = ?
            ORDER BY version DESC
            """,
            (ontology_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_latest_version(ontology_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM ontology_versions
            WHERE ontology_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (ontology_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


# ---- decision / scenario / run helpers ----

def create_decision_record(
    ontology_id: str,
    version_id: str,
    title: str,
    sample_count: int = 3,
    max_rounds: int = 10,
) -> Dict[str, Any]:
    did = f"dec_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO decisions
              (id, ontology_id, version_id, title, status, sample_count, max_rounds, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'created', ?, ?, ?, ?)
            """,
            (did, ontology_id, version_id, title, sample_count, max_rounds, now, now),
        )
    return get_decision(did)


def get_decision(decision_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (decision_id,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_decisions(include_trashed: bool = False) -> List[Dict[str, Any]]:
    with connection() as conn:
        if include_trashed:
            rows = conn.execute(
                "SELECT * FROM decisions ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM decisions
                WHERE trashed_at IS NULL OR trashed_at = ''
                ORDER BY created_at DESC
                """
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_decision(decision_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {
        "status",
        "shared_world_dir",
        "title",
        "sample_count",
        "max_rounds",
        "version_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_decision(decision_id)
    updates["updated_at"] = _utc_now()
    cols = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [decision_id]
    with connection() as conn:
        conn.execute(f"UPDATE decisions SET {cols} WHERE id = ?", vals)
    return get_decision(decision_id)


def add_scenario(
    decision_id: str,
    name: str,
    intervention: Any,
    kind: str = "custom",
    color: str = "#333333",
) -> Dict[str, Any]:
    sid = f"scn_{uuid.uuid4().hex[:12]}"
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO scenarios (id, decision_id, name, kind, intervention_json, color)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sid,
                decision_id,
                name,
                kind,
                json.dumps(intervention, ensure_ascii=False),
                color,
            ),
        )
    return get_scenario(sid)


def get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    try:
        d["intervention"] = json.loads(d.get("intervention_json") or "null")
    except json.JSONDecodeError:
        d["intervention"] = None
    return d


def list_scenarios(decision_id: str) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM scenarios WHERE decision_id = ?", (decision_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        try:
            d["intervention"] = json.loads(d.get("intervention_json") or "null")
        except json.JSONDecodeError:
            d["intervention"] = None
        out.append(d)
    return out


def add_run(
    scenario_id: str,
    seed: int,
    run_dir: str = "",
    status: str = "pending",
    sim_id: str = "",
) -> Dict[str, Any]:
    rid = f"run_{uuid.uuid4().hex[:12]}"
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, scenario_id, seed, status, run_dir, sim_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (rid, scenario_id, seed, status, run_dir, sim_id or None),
        )
    return get_run(rid)


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    with connection() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    raw = d.get("metrics_json")
    if raw:
        try:
            d["metrics"] = json.loads(raw)
        except json.JSONDecodeError:
            d["metrics"] = None
    else:
        d["metrics"] = None
    return d


def update_run(run_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {
        "status",
        "run_dir",
        "sim_id",
        "metrics_json",
        "started_at",
        "finished_at",
        "error",
        "seed",
    }
    updates = {}
    for k, v in fields.items():
        if k == "metrics" and v is not None:
            updates["metrics_json"] = json.dumps(v, ensure_ascii=False)
        elif k in allowed:
            updates[k] = v
    if not updates:
        return get_run(run_id)
    cols = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [run_id]
    with connection() as conn:
        conn.execute(f"UPDATE runs SET {cols} WHERE id = ?", vals)
    return get_run(run_id)


def list_runs_for_decision(decision_id: str) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT r.* FROM runs r
            JOIN scenarios s ON s.id = r.scenario_id
            WHERE s.decision_id = ?
            ORDER BY s.name, r.seed
            """,
            (decision_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        raw = d.get("metrics_json")
        if raw:
            try:
                d["metrics"] = json.loads(raw)
            except json.JSONDecodeError:
                d["metrics"] = None
        else:
            d["metrics"] = None
        out.append(d)
    return out


def list_runs_for_scenario(scenario_id: str) -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM runs WHERE scenario_id = ? ORDER BY seed",
            (scenario_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        raw = d.get("metrics_json")
        if raw:
            try:
                d["metrics"] = json.loads(raw)
            except json.JSONDecodeError:
                d["metrics"] = None
        else:
            d["metrics"] = None
        out.append(d)
    return out


def _rm_path(path: Optional[str]) -> None:
    import os
    import shutil

    if not path:
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def _is_trashed(row: Optional[Dict[str, Any]]) -> bool:
    if not row:
        return False
    return bool(str(row.get("trashed_at") or "").strip())


def trash_decision(decision_id: str, *, cascade_ontology: bool = True) -> bool:
    """移入回收站（软删除），保留磁盘产物。

    cascade_ontology=True（用户删任务）时：若该本体已无其它活跃决策，连同本体一起软删。
    cascade_ontology=False 用于「一本体一活跃决策」替换流程，避免本体被误软删。
    """
    dec = get_decision(decision_id)
    if not dec:
        return False
    if _is_trashed(dec):
        return True
    now = _utc_now()
    ontology_id = dec.get("ontology_id") or ""
    with connection() as conn:
        conn.execute(
            "UPDATE decisions SET trashed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, decision_id),
        )
    if cascade_ontology and ontology_id:
        still_active = [
            d
            for d in list_decisions(include_trashed=False)
            if d.get("ontology_id") == ontology_id and d["id"] != decision_id
        ]
        if not still_active:
            ont = get_ontology(ontology_id)
            if ont and not _is_trashed(ont):
                with connection() as conn:
                    conn.execute(
                        "UPDATE ontologies SET trashed_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, ontology_id),
                    )
    return True


def trash_ontology(ontology_id: str) -> bool:
    """本体移入回收站，并级联软删其下决策。"""
    ont = get_ontology(ontology_id)
    if not ont:
        return False
    now = _utc_now()
    with connection() as conn:
        if not _is_trashed(ont):
            conn.execute(
                "UPDATE ontologies SET trashed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, ontology_id),
            )
        conn.execute(
            """
            UPDATE decisions
            SET trashed_at = ?, updated_at = ?
            WHERE ontology_id = ? AND (trashed_at IS NULL OR trashed_at = '')
            """,
            (now, now, ontology_id),
        )
    return True


def restore_decision(decision_id: str) -> bool:
    """恢复任务。若同本体已有其它活跃决策，先将其入回收站（保持一活跃）。"""
    dec = get_decision(decision_id)
    if not dec or not _is_trashed(dec):
        return False
    ontology_id = dec.get("ontology_id") or ""
    # 恢复前顶掉同本体其它活跃决策
    if ontology_id:
        for other in list_decisions(include_trashed=False):
            if other.get("ontology_id") == ontology_id and other["id"] != decision_id:
                trash_decision(other["id"], cascade_ontology=False)
    ont = get_ontology(ontology_id) if ontology_id else None
    now = _utc_now()
    with connection() as conn:
        if ont and _is_trashed(ont):
            conn.execute(
                "UPDATE ontologies SET trashed_at = NULL, updated_at = ? WHERE id = ?",
                (now, ont["id"]),
            )
        conn.execute(
            "UPDATE decisions SET trashed_at = NULL, updated_at = ? WHERE id = ?",
            (now, decision_id),
        )
    return True


def restore_ontology(ontology_id: str) -> bool:
    ont = get_ontology(ontology_id)
    if not ont or not _is_trashed(ont):
        return False
    now = _utc_now()
    with connection() as conn:
        conn.execute(
            "UPDATE ontologies SET trashed_at = NULL, updated_at = ? WHERE id = ?",
            (now, ontology_id),
        )
        conn.execute(
            """
            UPDATE decisions
            SET trashed_at = NULL, updated_at = ?
            WHERE ontology_id = ? AND trashed_at IS NOT NULL AND trashed_at != ''
            """,
            (now, ontology_id),
        )
    return True


def list_trash() -> List[Dict[str, Any]]:
    """回收站：一条 = 一个任务（决策），对齐历史库 / MiroFish 语义。

    不展示本体行：本体是任务资源，不作为用户可见的回收站条目。
    """
    decisions = [
        d for d in list_decisions(include_trashed=True) if _is_trashed(d)
    ]
    items: List[Dict[str, Any]] = []
    for d in decisions:
        items.append(
            {
                "kind": "decision",
                "id": d["id"],
                "ontology_id": d.get("ontology_id"),
                "title": d.get("title") or d["id"],
                "trashed_at": d.get("trashed_at"),
                "created_at": d.get("created_at"),
                "status": d.get("status"),
            }
        )
    items.sort(key=lambda x: x.get("trashed_at") or "", reverse=True)
    return items


def purge_decision(decision_id: str) -> bool:
    """彻底删除决策及其 runs / 场景 / 磁盘产物。

    若本体已无任何决策引用（含回收站），一并 purge_ontology 清除孤儿本体。
    """
    import os

    from app.config import Config

    dec = get_decision(decision_id)
    if not dec:
        return False

    ontology_id = dec.get("ontology_id") or ""
    runs = list_runs_for_decision(decision_id)
    scenarios = list_scenarios(decision_id)

    for r in runs:
        _rm_path(r.get("run_dir"))
        sim_id = r.get("sim_id")
        if sim_id:
            _rm_path(os.path.join(Config.RUN_DIR, sim_id))
            _rm_path(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id))

    _rm_path(dec.get("shared_world_dir"))
    _rm_path(os.path.join(Config.DECISION_DIR, decision_id))
    _rm_path(os.path.join(Config.REPORTS_DIR, decision_id))
    for name in (f"{decision_id}.json", f"{decision_id}.md"):
        _rm_path(os.path.join(Config.REPORTS_DIR, name))

    with connection() as conn:
        for r in runs:
            conn.execute("DELETE FROM runs WHERE id = ?", (r["id"],))
        for s in scenarios:
            conn.execute("DELETE FROM scenarios WHERE id = ?", (s["id"],))
        conn.execute("DELETE FROM decisions WHERE id = ?", (decision_id,))

    if ontology_id:
        remaining = [
            d
            for d in list_decisions(include_trashed=True)
            if d.get("ontology_id") == ontology_id
        ]
        if not remaining:
            purge_ontology(ontology_id)
    return True


def purge_ontology(ontology_id: str) -> bool:
    """彻底删除本体及其文档/版本/磁盘产物。

    不级联硬删决策：回收站里每条独立清除，避免点本体一条把下属决策全清掉。
    若仍有关联决策，仅删除本体元数据与本体磁盘产物；决策条目继续留在回收站自行处理。
    """
    import os

    from app.config import Config

    ont = get_ontology(ontology_id)
    if not ont:
        return False

    docs = list_documents(ontology_id)
    versions = list_versions(ontology_id)

    for doc in docs:
        _rm_path(doc.get("path"))
    for ver in versions:
        _rm_path(ver.get("snapshot_path"))

    _rm_path(os.path.join(Config.ONTOLOGY_DIR, ontology_id))
    _rm_path(os.path.join(Config.SNAPSHOT_DIR, ontology_id))
    _rm_path(os.path.join(Config.UPLOAD_FOLDER, "ontologies", ontology_id))

    with connection() as conn:
        conn.execute(
            "DELETE FROM ontology_documents WHERE ontology_id = ?", (ontology_id,)
        )
        conn.execute(
            "DELETE FROM ontology_versions WHERE ontology_id = ?", (ontology_id,)
        )
        conn.execute("DELETE FROM ontologies WHERE id = ?", (ontology_id,))
    return True


# 兼容旧名：默认改为进回收站
def delete_decision(decision_id: str) -> bool:
    return trash_decision(decision_id)


def delete_ontology(ontology_id: str) -> bool:
    return trash_ontology(ontology_id)
