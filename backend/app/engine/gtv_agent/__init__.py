"""GTV 成交 Agent 轨：漏斗状态机 + 多角色逐轮推演（非 OASIS）。"""

from .runner import run_agent_track, agent_status_path

__all__ = ["run_agent_track", "agent_status_path"]
