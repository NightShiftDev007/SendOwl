"""
从切片边映射初始关注网络
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.logger import get_logger

logger = get_logger("adc.world.network")

# 优先视为「关注」的边类型
FOLLOWISH_LABELS = {
    "FOLLOWS",
    "FOLLOW",
    "INFLUENCES",
    "SUPPORTS",
    "WORKS_FOR",
    "REPRESENTS",
    "REPORTS_ON",
    "SERVES",
}


def _edge_label(e: Dict[str, Any]) -> str:
    return str(
        e.get("label") or e.get("name") or e.get("fact") or e.get("type") or ""
    ).upper()


def build_follow_pairs(
    world_slice: Dict[str, Any],
    entity_to_agent: Dict[str, int],
    max_follows_per_agent: int = 8,
) -> List[List[int]]:
    """
    将切片边映射为 [src_agent_id, dst_agent_id]。
    仅保留两端都在 profiles 中的边。
    """
    agent_ids: Set[int] = set(entity_to_agent.values())
    follows: List[List[int]] = []
    seen: Set[Tuple[int, int]] = set()
    per_src: Dict[int, int] = {}

    # 先处理 followish 边
    edges = list(world_slice.get("edges") or [])
    prioritized = sorted(
        edges,
        key=lambda e: (0 if any(x in _edge_label(e) for x in FOLLOWISH_LABELS) else 1),
    )

    for e in prioritized:
        src_e = str(e.get("source_node_uuid") or e.get("source") or "")
        tgt_e = str(e.get("target_node_uuid") or e.get("target") or "")
        if src_e not in entity_to_agent or tgt_e not in entity_to_agent:
            continue
        src_a = int(entity_to_agent[src_e])
        dst_a = int(entity_to_agent[tgt_e])
        if src_a == dst_a:
            continue
        if src_a not in agent_ids or dst_a not in agent_ids:
            continue
        if per_src.get(src_a, 0) >= max_follows_per_agent:
            continue
        key = (src_a, dst_a)
        if key in seen:
            continue
        seen.add(key)
        follows.append([src_a, dst_a])
        per_src[src_a] = per_src.get(src_a, 0) + 1

    return follows


def write_network(
    world_slice: Dict[str, Any],
    entity_to_agent: Dict[str, int],
    output_path: str,
    max_follows_per_agent: int = 8,
) -> Dict[str, Any]:
    """写入 network.json，返回网络对象。"""
    follows = build_follow_pairs(
        world_slice, entity_to_agent, max_follows_per_agent=max_follows_per_agent
    )
    payload = {
        "follows": follows,
        "note": (
            "OASIS 未必能直接注入关注边；population 会把关注名单写入 persona："
            "「你关注了: ...」"
        ),
        "agent_count": len(set(entity_to_agent.values())),
        "follow_count": len(follows),
    }
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logger.info(f"network.json 已写入: {output_path} follows={len(follows)}")
    return payload


def load_network(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
