"""
世界切片器：从本体快照按干预文本切出相关子图
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from app.utils.logger import get_logger

logger = get_logger("adc.world.slicer")

DEFAULT_K = 2
LLM_FILTER_THRESHOLD = 80
MAX_KEEP_AFTER_FILTER = 60


def _node_id(n: Dict[str, Any]) -> str:
    return str(n.get("uuid") or n.get("id") or n.get("name") or "")


def _node_text(n: Dict[str, Any]) -> str:
    parts = [
        str(n.get("name") or ""),
        str(n.get("summary") or ""),
        " ".join(n.get("labels") or []),
    ]
    attrs = n.get("attributes") or {}
    if isinstance(attrs, dict):
        parts.extend(str(v) for v in attrs.values() if v)
    return " ".join(parts).lower()


def _tokenize_intervention(text: str) -> List[str]:
    text = text or ""
    # 中英关键词：连续汉字块 + 英文词
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text)
    # 去重保序
    seen = set()
    out = []
    for t in tokens:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            out.append(tl)
    return out


def _build_graph(nodes: List[Dict], edges: List[Dict]) -> nx.Graph:
    g = nx.Graph()
    for n in nodes:
        nid = _node_id(n)
        if nid:
            g.add_node(nid, data=n)
    for e in edges:
        src = str(e.get("source_node_uuid") or e.get("source") or "")
        tgt = str(e.get("target_node_uuid") or e.get("target") or "")
        if src and tgt and src in g and tgt in g:
            g.add_edge(src, tgt, data=e)
    return g


def _seed_by_keywords(
    nodes: List[Dict[str, Any]], keywords: List[str]
) -> List[str]:
    if not keywords:
        # 无关键词时取前若干节点
        return [_node_id(n) for n in nodes[:10] if _node_id(n)]

    scored = []
    for n in nodes:
        nid = _node_id(n)
        if not nid:
            continue
        text = _node_text(n)
        score = sum(1 for kw in keywords if kw in text)
        # 名称完全命中加权
        name = str(n.get("name") or "").lower()
        for kw in keywords:
            if kw == name or kw in name:
                score += 3
        if score > 0:
            scored.append((score, nid))
    scored.sort(key=lambda x: -x[0])
    seeds = [nid for _, nid in scored]
    if not seeds:
        seeds = [_node_id(n) for n in nodes[:5] if _node_id(n)]
    return seeds


def _k_hop_expand(g: nx.Graph, seed_ids: List[str], k: int) -> Set[str]:
    keep: Set[str] = set()
    for sid in seed_ids:
        if sid not in g:
            continue
        keep.add(sid)
        try:
            lengths = nx.single_source_shortest_path_length(g, sid, cutoff=k)
            keep.update(lengths.keys())
        except Exception:
            keep.add(sid)
    return keep


def _llm_filter_names(
    nodes: List[Dict[str, Any]],
    intervention_text: str,
    max_keep: int = MAX_KEEP_AFTER_FILTER,
) -> List[str]:
    """请 LLM 保留与干预最相关的实体名。失败则按原顺序截断。"""
    names = [str(n.get("name") or "") for n in nodes if n.get("name")]
    try:
        from app.utils.llm_client import LLMClient

        client = LLMClient()
        prompt = (
            "你是舆情图谱裁剪助手。给定干预文本与实体名列表，"
            f"请选出最多 {max_keep} 个与干预最相关的实体名，"
            "返回 JSON：{\"keep\": [\"名称\", ...]}。\n\n"
            f"干预文本：\n{intervention_text[:2000]}\n\n"
            f"实体名：\n{json.dumps(names, ensure_ascii=False)}"
        )
        result = client.chat_json(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        keep = result.get("keep") or []
        if isinstance(keep, list) and keep:
            return [str(x) for x in keep][:max_keep]
    except Exception as e:
        logger.warning(f"LLM 切片过滤失败，回退截断: {e}")
    return names[:max_keep]


def slice_world(
    snapshot: Dict[str, Any],
    intervention_text: str = "",
    k: int = DEFAULT_K,
    use_llm_filter: bool = True,
    llm_threshold: int = LLM_FILTER_THRESHOLD,
) -> Dict[str, Any]:
    """
    从快照切出相关子图。

    Returns:
        {nodes, edges, seed_ids}
    """
    nodes = list(snapshot.get("nodes") or [])
    edges = list(snapshot.get("edges") or [])
    g = _build_graph(nodes, edges)

    keywords = _tokenize_intervention(intervention_text)
    seed_ids = _seed_by_keywords(nodes, keywords)
    keep_ids = _k_hop_expand(g, seed_ids, k)

    sliced_nodes = [g.nodes[nid]["data"] for nid in keep_ids if nid in g]
    sliced_edges = []
    for u, v, data in g.edges(data=True):
        if u in keep_ids and v in keep_ids:
            sliced_edges.append(data.get("data") or {"source_node_uuid": u, "target_node_uuid": v})

    if use_llm_filter and len(sliced_nodes) > llm_threshold:
        keep_names = set(_llm_filter_names(sliced_nodes, intervention_text))
        # 种子强制保留
        seed_names = {
            str(g.nodes[s]["data"].get("name") or "")
            for s in seed_ids
            if s in g
        }
        keep_names |= seed_names
        sliced_nodes = [
            n for n in sliced_nodes if str(n.get("name") or "") in keep_names
        ]
        keep_ids = {_node_id(n) for n in sliced_nodes}
        sliced_edges = [
            e
            for e in sliced_edges
            if str(e.get("source_node_uuid") or e.get("source") or "") in keep_ids
            and str(e.get("target_node_uuid") or e.get("target") or "") in keep_ids
        ]

    return {
        "nodes": sliced_nodes,
        "edges": sliced_edges,
        "seed_ids": seed_ids,
        "meta": {
            "k": k,
            "keyword_count": len(keywords),
            "node_count": len(sliced_nodes),
            "edge_count": len(sliced_edges),
        },
    }


def slice_from_path(
    snapshot_path: str,
    intervention_text: str = "",
    **kwargs,
) -> Dict[str, Any]:
    with open(snapshot_path, encoding="utf-8") as f:
        snapshot = json.load(f)
    return slice_world(snapshot, intervention_text, **kwargs)
