"""
本体图谱快照导出 / 加载
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from zep_cloud.client import Zep

from app.config import Config
from app.ontology import registry
from app.utils.logger import get_logger
from app.utils.zep_paging import fetch_all_edges, fetch_all_nodes

logger = get_logger("adc.ontology.snapshot")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_node(node: Any) -> Dict[str, Any]:
    labels = list(getattr(node, "labels", None) or [])
    attrs = getattr(node, "attributes", None) or {}
    if hasattr(attrs, "model_dump"):
        attrs = attrs.model_dump()
    elif not isinstance(attrs, dict):
        attrs = dict(attrs) if attrs else {}
    return {
        "uuid": getattr(node, "uuid_", None) or getattr(node, "uuid", None) or "",
        "name": getattr(node, "name", "") or "",
        "labels": labels,
        "summary": getattr(node, "summary", "") or "",
        "attributes": attrs,
    }


def _serialize_edge(edge: Any) -> Dict[str, Any]:
    return {
        "uuid": getattr(edge, "uuid_", None) or getattr(edge, "uuid", None) or "",
        "name": getattr(edge, "name", "") or getattr(edge, "fact", "") or "",
        "fact": getattr(edge, "fact", "") or "",
        "source_node_uuid": (
            getattr(edge, "source_node_uuid", None)
            or getattr(edge, "source_node_id", None)
            or ""
        ),
        "target_node_uuid": (
            getattr(edge, "target_node_uuid", None)
            or getattr(edge, "target_node_id", None)
            or ""
        ),
        "label": getattr(edge, "name", None) or getattr(edge, "label", "") or "",
    }


def export_snapshot(ontology_id: str, graph_id: str) -> Dict[str, Any]:
    """
    从 Zep 拉取全量节点/边，写入 SNAPSHOT_DIR/{ontology_id}/v{N}.json，
    并在 registry 登记版本。
    """
    if not Config.ZEP_API_KEY:
        raise ValueError("ZEP_API_KEY 未配置，无法导出快照")
    if not graph_id:
        raise ValueError("graph_id 为空")

    client = Zep(api_key=Config.ZEP_API_KEY)
    nodes_raw = fetch_all_nodes(client, graph_id)
    edges_raw = fetch_all_edges(client, graph_id)
    nodes = [_serialize_node(n) for n in nodes_raw]
    edges = [_serialize_edge(e) for e in edges_raw]

    latest = registry.get_latest_version(ontology_id)
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
