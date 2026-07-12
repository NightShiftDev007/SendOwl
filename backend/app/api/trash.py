"""回收站 API：列表 / 恢复 / 彻底删除。"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.api.trash")

trash_bp = Blueprint("trash", __name__, url_prefix="/api/trash")


@trash_bp.get("")
@trash_bp.get("/")
def list_trash():
    registry.init_schema()
    items = registry.list_trash()
    return jsonify({"success": True, "data": items, "count": len(items)})


@trash_bp.post("/<kind>/<item_id>/restore")
def restore_trash_item(kind: str, item_id: str):
    registry.init_schema()
    kind = (kind or "").strip().lower()
    try:
        if kind == "decision":
            ok = registry.restore_decision(item_id)
        elif kind == "ontology":
            ok = registry.restore_ontology(item_id)
        else:
            return jsonify({"success": False, "error": "kind 须为 decision 或 ontology"}), 400
        if not ok:
            return jsonify({"success": False, "error": f"回收站中不存在: {kind}/{item_id}"}), 404
        return jsonify({"success": True, "data": {"kind": kind, "id": item_id, "restored": True}})
    except Exception as e:
        logger.exception("restore trash failed")
        return jsonify({"success": False, "error": str(e)}), 500


@trash_bp.delete("/<kind>/<item_id>")
def purge_trash_item(kind: str, item_id: str):
    """从回收站彻底清除（磁盘 + 元数据）。"""
    registry.init_schema()
    kind = (kind or "").strip().lower()
    try:
        if kind == "decision":
            row = registry.get_decision(item_id)
            if not row or not str(row.get("trashed_at") or "").strip():
                return jsonify({"success": False, "error": f"回收站中不存在决策: {item_id}"}), 404
            ok = registry.purge_decision(item_id)
        elif kind == "ontology":
            row = registry.get_ontology(item_id)
            if not row or not str(row.get("trashed_at") or "").strip():
                return jsonify({"success": False, "error": f"回收站中不存在本体: {item_id}"}), 404
            ok = registry.purge_ontology(item_id)
        else:
            return jsonify({"success": False, "error": "kind 须为 decision 或 ontology"}), 400
        if not ok:
            return jsonify({"success": False, "error": f"彻底删除失败: {kind}/{item_id}"}), 500
        return jsonify({"success": True, "data": {"kind": kind, "id": item_id, "purged": True}})
    except Exception as e:
        logger.exception("purge trash failed")
        return jsonify({"success": False, "error": str(e)}), 500
