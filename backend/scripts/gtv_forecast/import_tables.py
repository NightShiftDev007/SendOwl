"""Import required dump tables into Parquet (PII stripped)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .config import (
    DB_PATH,
    DEFAULT_DATA_PARENT,
    DEFAULT_DUMP_ROOT,
    DEFAULT_MID_ROOT,
    OPTIONAL_TABLES,
    PARQUET_DIR,
    PII_OR_BULKY,
    REQUIRED_TABLES,
    TABLE_DUMP_DB,
)
from .ids import as_str_id
from .sql_dump import find_part_files, iter_insert_rows

BATCH_SIZE = 5000

_ID_COLS = {
    "id",
    "user_id",
    "dept_id",
    "post_id",
    "plant_id",
    "warehouse_id",
    "room_id",
    "office_id",
    "park_id",
    "project_id",
    "project_sign_id",
    "housing_resource_id",
    "maintain_person_id",
    "submit_user",
    "submit_user_id",
    "create_by",
    "update_by",
    "project_manager",
    "clue_id",
    "carrier_id",
    "intent_area_id",
}


def _dump_root() -> Path:
    return Path(os.environ.get("GTV_DATA_ROOT", DEFAULT_DUMP_ROOT))


def _data_parent() -> Path:
    env = os.environ.get("GTV_DATA_PARENT")
    if env:
        return Path(env)
    root = _dump_root()
    # .../lyy_manage → .../data
    return root.parent if root.name in {"lyy_manage", "lyy_mid"} else DEFAULT_DATA_PARENT


def _dump_root_for_table(table: str) -> Path:
    db = TABLE_DUMP_DB.get(table, "lyy_manage")
    if db == "lyy_mid":
        mid = os.environ.get("GTV_MID_ROOT")
        if mid:
            return Path(mid)
        return DEFAULT_MID_ROOT if DEFAULT_MID_ROOT.is_dir() else _data_parent() / "lyy_mid"
    return _dump_root()


def _drop_pii(table: str, cols: list[str], row: list[Any]) -> dict[str, Any]:
    drop = PII_OR_BULKY.get(table, set())
    out: dict[str, Any] = {}
    for c, v in zip(cols, row, strict=True):
        if c in drop:
            continue
        if c in _ID_COLS or c.endswith("_id"):
            out[c] = as_str_id(v)
        else:
            out[c] = v
    return out


def import_table(table: str, dump_root: Path | None = None, force: bool = False) -> dict[str, Any]:
    dump_root = dump_root or _dump_root()
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PARQUET_DIR / f"{table}.parquet"
    meta_path = PARQUET_DIR / f"{table}.meta.json"
    if out_path.exists() and not force:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        return {"table": table, "skipped": True, "rows": meta.get("rows"), "path": str(out_path)}

    parts = find_part_files(dump_root, table)
    if not parts:
        return {"table": table, "skipped": True, "error": "no_data_files", "path": None}

    batches: list[pd.DataFrame] = []
    buffer: list[dict[str, Any]] = []
    rows = 0
    columns: list[str] | None = None

    for part in parts:
        for _t, cols, vals in iter_insert_rows(part):
            if columns is None:
                columns = [c for c in cols if c not in PII_OR_BULKY.get(table, set())]
            buffer.append(_drop_pii(table, cols, vals))
            rows += 1
            if len(buffer) >= BATCH_SIZE:
                batches.append(pd.DataFrame(buffer))
                buffer.clear()
    if buffer:
        batches.append(pd.DataFrame(buffer))

    if not batches:
        return {"table": table, "skipped": True, "error": "empty", "rows": 0}

    df = pd.concat(batches, ignore_index=True)
    for col in df.columns:
        if col in _ID_COLS or col.endswith("_id"):
            df[col] = df[col].map(as_str_id).astype("string")
    df.to_parquet(out_path, index=False)
    meta = {
        "table": table,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "dropped": sorted(PII_OR_BULKY.get(table, set())),
        "parts": [p.name for p in parts],
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"table": table, "skipped": False, "rows": meta["rows"], "path": str(out_path)}


def build_duckdb(tables: list[str] | None = None) -> Path:
    """Register parquet files as views/tables in a local DuckDB file."""
    DATA_DIR = DB_PATH.parent
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = duckdb.connect(str(DB_PATH))
    tables = tables or [t for t in REQUIRED_TABLES + OPTIONAL_TABLES if (PARQUET_DIR / f"{t}.parquet").exists()]
    for table in tables:
        pq = PARQUET_DIR / f"{table}.parquet"
        if not pq.exists():
            continue
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_parquet(?)",
            [str(pq)],
        )
    con.close()
    return DB_PATH


def import_all(force: bool = False) -> list[dict[str, Any]]:
    results = []
    for table in REQUIRED_TABLES + OPTIONAL_TABLES:
        dump_root = _dump_root_for_table(table)
        print(f"[import] {table} @ {dump_root.name} ...", flush=True)
        results.append(import_table(table, dump_root=dump_root, force=force))
        r = results[-1]
        print(f"  -> rows={r.get('rows')} skipped={r.get('skipped')} err={r.get('error')}", flush=True)
    build_duckdb()
    return results
