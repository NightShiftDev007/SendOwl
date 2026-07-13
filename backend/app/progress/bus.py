"""进度总线抽象：默认 memory；可选 redis（多 worker）。"""

from __future__ import annotations

from typing import Optional

from app.config import Config


class ProgressBus:
    """进程内 / Redis 统一接口。本期 Redis 仅配置位，实现仍走 memory hub。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._mode = (Config.PROGRESS_BUS or "memory").lower()
        return cls._instance

    @property
    def mode(self) -> str:
        return self._mode

    def publish_decision(self, decision_id: str, snapshot: Optional[dict] = None) -> None:
        from app.api.stream import publish_decision_status

        publish_decision_status(decision_id, snapshot)
        if self._mode == "redis":
            # 配置位预留：多 worker 时在此 publish Redis channel
            pass

    def publish_task(self, task_id: str, snapshot: dict) -> None:
        # TaskManager._publish 已是 memory；redis 模式同样预留
        if self._mode == "redis":
            pass
