"""
本体图谱快照导出 / 加载

展示 Source of Truth：日常读图只读本地快照；
仅在建图完成 / 追加文档 / 显式同步时从 Zep 导出。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from zep_cloud.client import Zep

from app.config import Config
from app.ontology import registry
from app.utils.logger import get_logger
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

logger = get_logger("adc.ontology.snapshot")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def heal_missing_edge_endpoints(client: Zep, nodes: list, edges: list) -> list:
    """Zep 列表分页常漏掉边两端节点；按边引用补拉，保证快照自洽。"""
    by_id = {
        getattr(n, "uuid_", None) or getattr(n, "uuid", None): n
        for n in nodes
        if getattr(n, "uuid_", None) or getattr(n, "uuid", None)
    }
    missing = set()
    for edge in edges:
        src = getattr(edge, "source_node_uuid", None) or getattr(
            edge, "source_node_id", None
        )
        tgt = getattr(edge, "target_node_uuid", None) or getattr(
            edge, "target_node_id", None
        )
        if src and src not in by_id:
            missing.add(src)
        if tgt and tgt not in by_id:
            missing.add(tgt)
    if not missing:
        return nodes

    healed = 0
    for uid in missing:
        try:
            node = client.graph.node.get(uuid_=uid)
            nid = getattr(node, "uuid_", None) if node else None
            if nid:
                by_id[nid] = node
                healed += 1
        except Exception as e:
            logger.debug(f"heal node {str(uid)[:8]}… skip: {e}")
    if healed:
        logger.info(
            f"快照导出补全边端点: 列表 {len(nodes)} → {len(by_id)} "
            f"(补拉 {healed}/{len(missing)})"
        )
    return list(by_id.values())


def _serialize_node(node: Any) -> Dict[str, Any]:
    labels = list(getattr(node, "labels", None) or [])
    attrs = getattr(node, "attributes", None) or {}
    if hasattr(attrs, "model_dump"):
        attrs = attrs.model_dump()
    elif not isinstance(attrs, dict):
        attrs = dict(attrs) if attrs else {}
    created_at = getattr(node, "created_at", None)
    return {
        "uuid": getattr(node, "uuid_", None) or getattr(node, "uuid", None) or "",
        "name": getattr(node, "name", "") or "",
        "labels": labels,
        "summary": getattr(node, "summary", "") or "",
        "attributes": attrs,
        "created_at": str(created_at) if created_at else None,
    }


def _serialize_edge(edge: Any, node_map: Dict[str, str]) -> Dict[str, Any]:
    src = (
        getattr(edge, "source_node_uuid", None)
        or getattr(edge, "source_node_id", None)
        or ""
    )
    tgt = (
        getattr(edge, "target_node_uuid", None)
        or getattr(edge, "target_node_id", None)
        or ""
    )
    created_at = getattr(edge, "created_at", None)
    valid_at = getattr(edge, "valid_at", None)
    invalid_at = getattr(edge, "invalid_at", None)
    expired_at = getattr(edge, "expired_at", None)
    episodes = getattr(edge, "episodes", None) or getattr(edge, "episode_ids", None)
    if episodes and not isinstance(episodes, list):
        episodes = [str(episodes)]
    elif episodes:
        episodes = [str(e) for e in episodes]
    name = getattr(edge, "name", "") or ""
    fact_type = getattr(edge, "fact_type", None) or name or ""
    attrs = getattr(edge, "attributes", None) or {}
    if hasattr(attrs, "model_dump"):
        attrs = attrs.model_dump()
    elif not isinstance(attrs, dict):
        attrs = dict(attrs) if attrs else {}

    return {
        "uuid": getattr(edge, "uuid_", None) or getattr(edge, "uuid", None) or "",
        "name": name,
        "fact": getattr(edge, "fact", "") or "",
        "fact_type": fact_type,
        "source_node_uuid": src,
        "target_node_uuid": tgt,
        "source_node_name": node_map.get(src, ""),
        "target_node_name": node_map.get(tgt, ""),
        "attributes": attrs,
        "created_at": str(created_at) if created_at else None,
        "valid_at": str(valid_at) if valid_at else None,
        "invalid_at": str(invalid_at) if invalid_at else None,
        "expired_at": str(expired_at) if expired_at else None,
        "episodes": episodes or [],
        "label": name or getattr(edge, "label", "") or "",
    }


def _fetch_and_serialize(client: Zep, graph_id: str) -> tuple[List[Dict], List[Dict]]:
    nodes_raw = fetch_all_nodes(client, graph_id)
    edges_raw = fetch_all_edges(client, graph_id)
    nodes_raw = heal_missing_edge_endpoints(client, nodes_raw, edges_raw)
    node_map = {
        (getattr(n, "uuid_", None) or getattr(n, "uuid", None) or ""): (
            getattr(n, "name", "") or ""
        )
        for n in nodes_raw
    }
    nodes = [_serialize_node(n) for n in nodes_raw]
    edges = [_serialize_edge(e, node_map) for e in edges_raw]
    return nodes, edges


def export_snapshot(ontology_id: str, graph_id: str) -> Dict[str, Any]:
    """
    从 Zep 拉取全量节点/边（含端点补全），写入 SNAPSHOT_DIR/{ontology_id}/v{N}.json，
    并在 registry 登记版本。

    去重：同 graph_id 且 node/edge 计数与最新版本一致时不升版，返回现有 latest。
    """
    if not Config.ZEP_API_KEY:
        raise ValueError("ZEP_API_KEY 未配置，无法导出快照")
    if not graph_id:
        raise ValueError("graph_id 为空")

    client = Zep(api_key=Config.ZEP_API_KEY)
    nodes, edges = _fetch_and_serialize(client, graph_id)

    latest = registry.get_latest_version(ontology_id)
    if latest and latest.get("snapshot_path"):
        try:
            prev = load_snapshot(latest["snapshot_path"])
            same_graph = (prev.get("graph_id") or latest.get("graph_id")) == graph_id
            prev_nodes = prev.get("nodes") or []
            prev_edges = prev.get("edges") or []
            same_counts = len(prev_nodes) == len(nodes) and len(prev_edges) == len(edges)
            # 旧快照缺 live 对齐字段时必须重写，不能只凭计数跳过
            sample_edge = prev_edges[0] if prev_edges else {}
            sample_node = prev_nodes[0] if prev_nodes else {}
            shape_ok = (
                (not prev_edges or "fact_type" in sample_edge)
                and (not prev_edges or "source_node_name" in sample_edge)
                and (not prev_nodes or "created_at" in sample_node)
            )
            if same_graph and same_counts and shape_ok:
                logger.info(
                    f"快照未变化，跳过升版: {ontology_id} "
                    f"v{latest.get('version')} nodes={len(nodes)} edges={len(edges)}"
                )
                return latest
        except Exception as e:
            logger.debug(f"快照去重比对失败，继续升版: {e}")

    version = (latest["version"] + 1) if latest else 1

    out_dir = os.path.join(Config.SNAPSHOT_DIR, ontology_id)
    os.makedirs(out_dir, exist_ok=True)
    snapshot_path = os.path.join(out_dir, f"v{version}.json")

    payload = {
        "ontology_id": ontology_id,
        "graph_id": graph_id,
        "version": version,
        "exported_at": _utc_now(),
        "nodes": nodes,
        "edges": edges,
    }
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    record = registry.add_version(
        ontology_id=ontology_id,
        version=version,
        snapshot_path=snapshot_path,
        node_count=len(nodes),
        edge_count=len(edges),
    )
    logger.info(
        f"快照已导出: {snapshot_path} nodes={len(nodes)} edges={len(edges)}"
    )
    return record


def load_snapshot(path: str) -> Dict[str, Any]:
    """加载快照 JSON。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def register_local_snapshot(
    ontology_id: str,
    snapshot: Dict[str, Any],
    graph_id: Optional[str] = None,
) -> Dict[str, Any]:
    """离线/测试：直接写入本地快照并登记版本（不访问 Zep）。"""
    latest = registry.get_latest_version(ontology_id)
    version = (latest["version"] + 1) if latest else 1
    out_dir = os.path.join(Config.SNAPSHOT_DIR, ontology_id)
    os.makedirs(out_dir, exist_ok=True)
    snapshot_path = os.path.join(out_dir, f"v{version}.json")

    payload = {
        "ontology_id": ontology_id,
        "graph_id": graph_id or snapshot.get("graph_id") or "local",
        "version": version,
        "exported_at": _utc_now(),
        "nodes": snapshot.get("nodes") or [],
        "edges": snapshot.get("edges") or [],
    }
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return registry.add_version(
        ontology_id=ontology_id,
        version=version,
        snapshot_path=snapshot_path,
        node_count=len(payload["nodes"]),
        edge_count=len(payload["edges"]),
    )
