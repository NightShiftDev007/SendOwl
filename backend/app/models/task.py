"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
持久化到 meta.db tasks 表；内存为热点缓存，进程重启可回源。
"""

import json
import queue
import uuid
import threading
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from app.utils.locale import t


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return datetime.now()


def _json_dumps(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return None


def _json_loads(raw: Any, default=None):
    if raw is None or raw == "":
        return default if default is not None else None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default if default is not None else None


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0
    message: str = ""
    result: Optional[Dict] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    progress_detail: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: Any) -> "Task":
        status_raw = str(row["status"] if hasattr(row, "keys") else row[2])
        try:
            status = TaskStatus(status_raw)
        except Exception:
            status = TaskStatus.FAILED
        get = row.__getitem__
        return cls(
            task_id=get("id"),
            task_type=get("type"),
            status=status,
            created_at=_parse_dt(get("created_at")),
            updated_at=_parse_dt(get("updated_at")),
            progress=int(get("progress") or 0),
            message=get("message") or "",
            result=_json_loads(get("result_json")),
            error=get("error"),
            metadata=_json_loads(get("metadata_json"), default={}) or {},
            progress_detail=_json_loads(get("detail_json"), default={}) or {},
        )


class TaskManager:
    """线程安全的任务状态管理（单例）+ 轻量 pub/sub（供 SSE）+ SQLite 持久化"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, Task] = {}
                    cls._instance._task_lock = threading.Lock()
                    # task_id -> list[queue.Queue]
                    cls._instance._subscribers: Dict[str, List[queue.Queue]] = {}
                    cls._instance._sub_lock = threading.Lock()
                    cls._instance._db_ready = False
                    cls._instance._ensure_db()
        return cls._instance

    def _ensure_db(self) -> None:
        if self._db_ready:
            return
        try:
            from app.models.store import init_tasks_schema

            init_tasks_schema()
            self._db_ready = True
        except Exception:
            # 启动早期可能目录未就绪；后续写操作再试
            self._db_ready = False

    def _persist(self, task: Task) -> None:
        self._ensure_db()
        try:
            from app.models.store import connection

            with connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tasks (
                      id, type, status, progress, message, detail_json,
                      result_json, error, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      type=excluded.type,
                      status=excluded.status,
                      progress=excluded.progress,
                      message=excluded.message,
                      detail_json=excluded.detail_json,
                      result_json=excluded.result_json,
                      error=excluded.error,
                      metadata_json=excluded.metadata_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        task.task_id,
                        task.task_type,
                        task.status.value,
                        int(task.progress or 0),
                        task.message or "",
                        _json_dumps(task.progress_detail or {}),
                        _json_dumps(task.result),
                        task.error,
                        _json_dumps(task.metadata or {}),
                        task.created_at.isoformat(),
                        task.updated_at.isoformat(),
                    ),
                )
            self._db_ready = True
        except Exception:
            pass

    def _load_from_db(self, task_id: str) -> Optional[Task]:
        self._ensure_db()
        try:
            from app.models.store import connection

            with connection() as conn:
                row = conn.execute(
                    "SELECT * FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
            if not row:
                return None
            return Task.from_row(row)
        except Exception:
            return None

    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        # 前缀 task_：前端用此前缀区分真实异步任务与 dec_/sim_ 误传
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now = datetime.now()

        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        with self._task_lock:
            self._tasks[task_id] = task

        self._persist(task)
        self._publish(task_id, task.to_dict())
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._task_lock:
            hit = self._tasks.get(task_id)
            if hit:
                return hit
        loaded = self._load_from_db(task_id)
        if loaded:
            with self._task_lock:
                # 双检：避免并发重复装载
                existing = self._tasks.get(task_id)
                if existing:
                    return existing
                self._tasks[task_id] = loaded
            return loaded
        return None

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None,
    ):
        snapshot = None
        task_obj = None
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task is None:
                # 尝试回源后再更新
                pass
            else:
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                snapshot = task.to_dict()
                task_obj = task

        if task_obj is None:
            loaded = self._load_from_db(task_id)
            if not loaded:
                return
            with self._task_lock:
                self._tasks[task_id] = loaded
                task = loaded
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                snapshot = task.to_dict()
                task_obj = task

        if task_obj is not None:
            self._persist(task_obj)
        if snapshot is not None:
            self._publish(task_id, snapshot)

    def complete_task(self, task_id: str, result: Dict):
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t('progress.taskComplete'),
            result=result,
        )

    def fail_task(self, task_id: str, error: str):
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t('progress.taskFailed'),
            error=error,
        )

    def list_tasks(self, task_type: Optional[str] = None) -> list:
        self._ensure_db()
        # 合并 DB + 内存，以内存为准
        by_id: Dict[str, Dict[str, Any]] = {}
        try:
            from app.models.store import connection

            with connection() as conn:
                if task_type:
                    rows = conn.execute(
                        "SELECT * FROM tasks WHERE type = ? ORDER BY created_at DESC",
                        (task_type,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM tasks ORDER BY created_at DESC"
                    ).fetchall()
            for row in rows:
                task = Task.from_row(row)
                by_id[task.task_id] = task.to_dict()
        except Exception:
            pass

        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t for t in tasks if t.task_type == task_type]
            for t in tasks:
                by_id[t.task_id] = t.to_dict()

        return sorted(
            by_id.values(),
            key=lambda x: x.get("created_at") or "",
            reverse=True,
        )

    def find_latest_by_metadata(
        self,
        *,
        task_type: Optional[str] = None,
        metadata_key: str,
        metadata_value: str,
    ) -> Optional[Dict[str, Any]]:
        """按 metadata 字段找回最近任务（如 report_id → report_task_id）。"""
        for item in self.list_tasks(task_type=task_type):
            meta = item.get("metadata") or {}
            if str(meta.get(metadata_key) or "") == str(metadata_value):
                return item
        return None

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        cutoff_iso = cutoff.isoformat()

        with self._task_lock:
            old_ids = [
                tid
                for tid, task in self._tasks.items()
                if task.created_at < cutoff
                and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]

        self._ensure_db()
        try:
            from app.models.store import connection

            with connection() as conn:
                conn.execute(
                    """
                    DELETE FROM tasks
                    WHERE created_at < ?
                      AND status IN ('completed', 'failed')
                    """,
                    (cutoff_iso,),
                )
        except Exception:
            pass

    # ---- pub/sub for SSE ----

    def subscribe(self, task_id: str) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._sub_lock:
            self._subscribers.setdefault(task_id, []).append(q)
        return q

    def unsubscribe(self, task_id: str, q: queue.Queue) -> None:
        with self._sub_lock:
            subs = self._subscribers.get(task_id) or []
            if q in subs:
                subs.remove(q)
            if not subs and task_id in self._subscribers:
                del self._subscribers[task_id]

    def _publish(self, task_id: str, snapshot: Dict[str, Any]) -> None:
        with self._sub_lock:
            subs = list(self._subscribers.get(task_id) or [])
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
