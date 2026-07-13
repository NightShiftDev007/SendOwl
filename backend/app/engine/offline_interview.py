"""
Interview 双轨：live（OASIS IPC）优先，失败/环境关闭时降级为 LLM 离线回顾采访。
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import Config
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

MISSING_RECORD_REPLY = (
    "（回顾采访）当前缺少该 Agent 的人设或推演动作记录，无法基于历史可靠作答。"
)

OFFLINE_SYSTEM = """你是社会模拟中的一个 Agent，正在接受事后回顾采访。
请严格以第一人称、符合人设与过往行为的方式回答。
只能依据给定的人设与动作记录推断；不要编造具体未出现的事实细节。
若信息不足，请坦诚说明不确定，但仍保持角色口吻。
回答简洁，2～6 句为宜，不要输出 Markdown 标题或 JSON。"""


def _sim_dir(simulation_id: str) -> str:
    return os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)


def load_agent_profiles(simulation_id: str) -> List[Dict[str, Any]]:
    """加载 Agent 人设（reddit JSON 优先，其次 twitter CSV）。"""
    sim_dir = _sim_dir(simulation_id)
    profiles: List[Dict[str, Any]] = []

    reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
    if os.path.exists(reddit_path):
        try:
            with open(reddit_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.warning(f"读取 reddit_profiles 失败: {e}")

    twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
    if os.path.exists(twitter_path):
        try:
            with open(twitter_path, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    profiles.append(
                        {
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "未知",
                        }
                    )
            return profiles
        except Exception as e:
            logger.warning(f"读取 twitter_profiles 失败: {e}")

    return profiles


def _available_platforms(simulation_id: str) -> List[str]:
    sim_dir = _sim_dir(simulation_id)
    platforms = []
    if os.path.exists(os.path.join(sim_dir, "twitter", "actions.jsonl")) or os.path.exists(
        os.path.join(sim_dir, "twitter_profiles.csv")
    ):
        platforms.append("twitter")
    if os.path.exists(os.path.join(sim_dir, "reddit", "actions.jsonl")) or os.path.exists(
        os.path.join(sim_dir, "reddit_profiles.json")
    ):
        platforms.append("reddit")
    if not platforms:
        # 根级 actions 视为 twitter 兼容
        if os.path.exists(os.path.join(sim_dir, "actions.jsonl")):
            platforms.append("twitter")
    return platforms or ["twitter"]


def _read_actions_for_agent(
    simulation_id: str,
    agent_id: int,
    limit: int = 24,
) -> List[Dict[str, Any]]:
    sim_dir = _sim_dir(simulation_id)
    paths = [
        os.path.join(sim_dir, "twitter", "actions.jsonl"),
        os.path.join(sim_dir, "reddit", "actions.jsonl"),
        os.path.join(sim_dir, "actions.jsonl"),
    ]
    collected: List[Dict[str, Any]] = []
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("event") or row.get("type") in (
                        "simulation_start",
                        "round_start",
                        "round_end",
                        "simulation_end",
                    ):
                        continue
                    aid = row.get("agent_id")
                    if aid is None:
                        continue
                    try:
                        if int(aid) != int(agent_id):
                            continue
                    except (TypeError, ValueError):
                        continue
                    collected.append(
                        {
                            "round": row.get("round"),
                            "action_type": row.get("action_type"),
                            "action_args": row.get("action_args"),
                            "result": row.get("result"),
                            "platform": "reddit" if "/reddit/" in path.replace("\\", "/") else "twitter",
                        }
                    )
        except OSError as e:
            logger.warning(f"读取 actions 失败 {path}: {e}")

    return collected[-limit:]


def _format_actions(actions: List[Dict[str, Any]]) -> str:
    if not actions:
        return "（无动作记录）"
    lines = []
    for a in actions:
        args = a.get("action_args") or {}
        if isinstance(args, dict):
            content = (
                args.get("content")
                or args.get("text")
                or args.get("prompt")
                or args.get("post_content")
                or json.dumps(args, ensure_ascii=False)[:120]
            )
        else:
            content = str(args)[:120]
        lines.append(
            f"- [r{a.get('round')}][{a.get('platform')}] {a.get('action_type')}: {content}"
        )
    return "\n".join(lines)


def _format_history(history: List[Dict[str, Any]], limit: int = 4) -> str:
    if not history:
        return "（无）"
    lines = []
    for h in history[-limit:]:
        prompt = h.get("prompt") or h.get("question") or ""
        resp = h.get("response") or h.get("answer") or ""
        if isinstance(h.get("info"), dict):
            prompt = prompt or h["info"].get("prompt", "")
            resp = resp or h["info"].get("response", "")
        lines.append(f"Q: {str(prompt)[:200]}\nA: {str(resp)[:300]}")
    return "\n\n".join(lines)


def _profile_for_agent(profiles: List[Dict[str, Any]], agent_id: int) -> Optional[Dict[str, Any]]:
    if 0 <= agent_id < len(profiles):
        return profiles[agent_id]
    return None


def _generate_offline_reply(
    llm: LLMClient,
    profile: Optional[Dict[str, Any]],
    agent_id: int,
    prompt: str,
    actions: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
) -> str:
    if not profile and not actions:
        return MISSING_RECORD_REPLY

    name = "未知"
    profession = "未知"
    bio = ""
    persona = ""
    if profile:
        name = profile.get("realname") or profile.get("username") or f"Agent_{agent_id}"
        profession = profile.get("profession") or "未知"
        bio = (profile.get("bio") or "")[:800]
        persona = (profile.get("persona") or profile.get("user_char") or "")[:800]

    user_prompt = f"""你的身份：
- 名称：{name}
- 职业/角色：{profession}
- 简介：{bio}
- 人设：{persona}

你在推演中的近期行为：
{_format_actions(actions)}

既往采访（如有）：
{_format_history(history)}

采访者现在问：
{prompt}

请以该 Agent 第一人称回答。"""

    try:
        return llm.chat(
            messages=[
                {"role": "system", "content": OFFLINE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=800,
        ).strip() or MISSING_RECORD_REPLY
    except Exception as e:
        logger.warning(f"离线 Interview LLM 失败 agent={agent_id}: {e}")
        return f"（回顾采访失败）生成回答时出错：{e}"


def interview_offline(
    simulation_id: str,
    interviews: List[Dict[str, Any]],
    platform: Optional[str] = None,
    llm: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """
    LLM 离线回顾采访，输出与 live batch 对齐的 results 字典。

    Returns:
        {
          success, interviews_count, mode: "offline",
          result: { interviews_count, results: {twitter_0: {...}, ...} },
          timestamp
        }
    """
    sim_dir = _sim_dir(simulation_id)
    if not os.path.exists(sim_dir):
        return {
            "success": False,
            "mode": "offline",
            "interviews_count": len(interviews),
            "error": f"模拟不存在: {simulation_id}",
            "timestamp": datetime.now().isoformat(),
        }

    profiles = load_agent_profiles(simulation_id)
    platforms = _available_platforms(simulation_id)
    if platform in ("twitter", "reddit"):
        platforms = [platform]

    try:
        client = llm or LLMClient()
    except Exception as e:
        logger.warning(f"离线 Interview 无法初始化 LLM: {e}")
        results: Dict[str, Any] = {}
        for item in interviews:
            agent_id = int(item.get("agent_id", 0))
            msg = f"（回顾采访）LLM 未配置或不可用：{e}"
            for p in platforms:
                results[f"{p}_{agent_id}"] = {
                    "agent_id": agent_id,
                    "response": msg,
                    "platform": p,
                    "mode": "offline",
                }
        return {
            "success": True,
            "mode": "offline",
            "interviews_count": len(interviews),
            "result": {"interviews_count": len(results), "results": results},
            "timestamp": datetime.now().isoformat(),
            "warning": str(e),
        }

    # 可选历史：按 agent 懒加载
    history_cache: Dict[int, List[Dict[str, Any]]] = {}

    def _history(agent_id: int) -> List[Dict[str, Any]]:
        if agent_id not in history_cache:
            try:
                from app.engine.simulation_runner import SimulationRunner

                history_cache[agent_id] = SimulationRunner.get_interview_history(
                    simulation_id=simulation_id,
                    agent_id=agent_id,
                    limit=8,
                ) or []
            except Exception:
                history_cache[agent_id] = []
        return history_cache[agent_id]

    results = {}
    for item in interviews:
        agent_id = int(item["agent_id"])
        prompt = item.get("prompt") or ""
        item_platform = item.get("platform") or platform
        target_platforms = (
            [item_platform] if item_platform in ("twitter", "reddit") else list(platforms)
        )

        profile = _profile_for_agent(profiles, agent_id)
        actions = _read_actions_for_agent(simulation_id, agent_id)
        reply = _generate_offline_reply(
            client, profile, agent_id, prompt, actions, _history(agent_id)
        )

        for p in target_platforms:
            results[f"{p}_{agent_id}"] = {
                "agent_id": agent_id,
                "response": reply,
                "platform": p,
                "mode": "offline",
                "prompt": prompt,
            }

    return {
        "success": True,
        "mode": "offline",
        "interviews_count": len(interviews),
        "result": {"interviews_count": len(results), "results": results},
        "timestamp": datetime.now().isoformat(),
    }


def interview_with_fallback(
    simulation_id: str,
    interviews: List[Dict[str, Any]],
    platform: Optional[str] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """
    统一入口：环境存活走 live IPC；否则或 live 失败/超时 → offline LLM。
    """
    from app.engine.simulation_runner import SimulationRunner

    if not interviews:
        return {
            "success": False,
            "mode": "offline",
            "error": "interviews 为空",
            "interviews_count": 0,
            "timestamp": datetime.now().isoformat(),
        }

    alive = False
    try:
        alive = bool(SimulationRunner.check_env_alive(simulation_id))
    except Exception as e:
        logger.warning(f"check_env_alive 失败: {e}")

    if alive:
        try:
            live = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews,
                platform=platform,
                timeout=timeout,
            )
            if live.get("success"):
                live = dict(live)
                live["mode"] = "live"
                return live
            logger.warning(
                f"live interview 返回失败，降级 offline: {live.get('error')}"
            )
        except (ValueError, TimeoutError) as e:
            logger.warning(f"live interview 异常，降级 offline: {e}")
        except Exception as e:
            logger.warning(f"live interview 未知异常，降级 offline: {e}")

    return interview_offline(
        simulation_id=simulation_id,
        interviews=interviews,
        platform=platform,
    )


def interview_agent_with_fallback(
    simulation_id: str,
    agent_id: int,
    prompt: str,
    platform: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """单 Agent 采访：live 优先，失败降级 offline（结果形状兼容单条 API）。"""
    from app.engine.simulation_runner import SimulationRunner

    alive = False
    try:
        alive = bool(SimulationRunner.check_env_alive(simulation_id))
    except Exception:
        alive = False

    if alive:
        try:
            live = SimulationRunner.interview_agent(
                simulation_id=simulation_id,
                agent_id=agent_id,
                prompt=prompt,
                platform=platform,
                timeout=timeout,
            )
            if live.get("success"):
                live = dict(live)
                live["mode"] = "live"
                return live
        except (ValueError, TimeoutError) as e:
            logger.warning(f"live single interview 降级: {e}")
        except Exception as e:
            logger.warning(f"live single interview 异常降级: {e}")

    batch = interview_offline(
        simulation_id=simulation_id,
        interviews=[{"agent_id": agent_id, "prompt": prompt}],
        platform=platform,
    )
    results = (batch.get("result") or {}).get("results") or {}
    # 拼成单条 API 兼容结构
    if platform in ("twitter", "reddit"):
        key = f"{platform}_{agent_id}"
        one = results.get(key) or {}
        return {
            "success": batch.get("success", True),
            "mode": "offline",
            "agent_id": agent_id,
            "prompt": prompt,
            "result": one,
            "timestamp": batch.get("timestamp"),
        }

    platforms_map = {}
    for key, val in results.items():
        if key.endswith(f"_{agent_id}"):
            p = val.get("platform") or key.split("_", 1)[0]
            platforms_map[p] = val
    return {
        "success": batch.get("success", True),
        "mode": "offline",
        "agent_id": agent_id,
        "prompt": prompt,
        "result": {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": platforms_map,
        },
        "timestamp": batch.get("timestamp"),
    }


def interview_all_with_fallback(
    simulation_id: str,
    prompt: str,
    platform: Optional[str] = None,
    timeout: float = 180.0,
) -> Dict[str, Any]:
    """全局同题采访，走双轨。"""
    sim_dir = _sim_dir(simulation_id)
    config_path = os.path.join(sim_dir, "simulation_config.json")
    interviews: List[Dict[str, Any]] = []

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            for agent_config in config.get("agent_configs") or []:
                aid = agent_config.get("agent_id")
                if aid is not None:
                    interviews.append({"agent_id": int(aid), "prompt": prompt})
        except Exception as e:
            logger.warning(f"读取 simulation_config 失败: {e}")

    if not interviews:
        profiles = load_agent_profiles(simulation_id)
        interviews = [{"agent_id": i, "prompt": prompt} for i in range(len(profiles))]

    if not interviews:
        return {
            "success": False,
            "mode": "offline",
            "error": f"模拟配置中没有 Agent: {simulation_id}",
            "timestamp": datetime.now().isoformat(),
        }

    return interview_with_fallback(
        simulation_id=simulation_id,
        interviews=interviews,
        platform=platform,
        timeout=timeout,
    )
