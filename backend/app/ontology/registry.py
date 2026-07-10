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
              metrics_json TEXT,
              started_at TEXT,
              finished_at TEXT,
              error TEXT
            );
            """
        )
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
) -> Dict[str, Any]:
    oid = f"ont_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    schema_json = json.dumps(schema, ensure_ascii=False) if schema else None
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO ontologies
              (id, name, template, graph_id, schema_json, schema_locked, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                oid,
                name,
                template,
                graph_id,
                schema_json,
                1 if schema_locked else 0,
                status,
                now,
                now,
            ),
        )
    return get_ontology(oid)


def list_ontologies() -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ontologies ORDER BY created_at DESC"
        ).fetchall()
    return [_enrich_ontology(_row_to_dict(r)) for r in rows]


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


def list_decisions() -> List[Dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM decisions ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_decision(decision_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {"status", "shared_world_dir", "title", "sample_count", "max_rounds"}
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
) -> Dict[str, Any]:
    rid = f"run_{uuid.uuid4().hex[:12]}"
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, scenario_id, seed, status, run_dir)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rid, scenario_id, seed, status, run_dir),
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
