"""
SQLite 元数据存储
meta.db 位于 backend/uploads/meta.db
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import Config

META_DB_PATH = os.path.join(Config.UPLOAD_FOLDER, 'meta.db')


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """打开 meta.db 连接（row_factory=sqlite3.Row）。"""
    path = db_path or META_DB_PATH
    _ensure_parent_dir(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


@contextmanager
def connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """上下文管理的 meta.db 连接。"""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
