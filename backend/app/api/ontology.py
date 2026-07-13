"""本体层 API"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.ontology import registry, service as ontology_service
from app.ontology.snapshot import load_snapshot
from app.utils.logger import get_logger

logger = get_logger("adc.api.ontology")

ontology_bp = Blueprint("ontology", __name__, url_prefix="/api/ontology")


@ontology_bp.get("/health")
def health():
    return jsonify({"status": "ok", "module": "ontology"})


@ontology_bp.get("/list")
def list_ontologies():
    registry.init_schema()
    return jsonify({"success": True, "data": registry.list_ontologies()})


@ontology_bp.delete("/<ontology_id>")
def delete_ontology(ontology_id: str):
    """移入回收站（软删除，级联其下决策），不立即清磁盘。"""
    registry.init_schema()
    try:
        ok = registry.trash_ontology(ontology_id)
        if not ok:
            return jsonify({"success": False, "error": f"本体不存在: {ontology_id}"}), 404
        return jsonify({"success": True, "data": {"id": ontology_id, "trashed": True}})
    except Exception as e:
        logger.exception("trash ontology failed")
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.post("/create")
def create_ontology():
    registry.init_schema()
    name = request.form.get("name") or (request.json or {}).get("name")
    if not name:
        return jsonify({"success": False, "error": "name 必填"}), 400

    template = request.form.get("template") or (request.json or {}).get(
        "template", "opinion"
    )
    simulation_requirement = request.form.get(
        "simulation_requirement"
    ) or (request.json or {}).get("simulation_requirement", "")
    use_llm = request.form.get("use_llm_ontology", "true")
    # 兼容旧参数；SCHEMA 始终 LLM，忽略关闭开关
    _ = use_llm
    use_llm_ontology = True

    files = request.files.getlist("files") if request.files else []
    try:
        ont = ontology_service.create_from_files(
            name=name,
            files=files,
            simulation_requirement=simulation_requirement,
            template=template,
            use_llm_ontology=use_llm_ontology and bool(files),
        )
        return jsonify({"success": True, "data": ont})
    except Exception as e:
        logger.exception("create ontology failed")
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.get("/<ontology_id>")
def get_ontology(ontology_id: str):
    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return jsonify({"success": False, "error": "not found"}), 404
    ont["documents"] = registry.list_documents(ontology_id)
    ont["versions"] = registry.list_versions(ontology_id)
    return jsonify({"success": True, "data": ont})


@ontology_bp.post("/<ontology_id>/build")
def build_ontology(ontology_id: str):
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    use_existing = body.get("use_existing_schema", True)
    async_mode = body.get("async", True)
    try:
        result = ontology_service.build_graph(
            ontology_id,
            use_existing_schema=use_existing,
            async_mode=async_mode,
        )
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.exception("build failed")
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.get("/<ontology_id>/build/status")
def build_status(ontology_id: str):
    registry.init_schema()
    task_id = request.args.get("task_id")
    data = ontology_service.get_build_status(ontology_id, task_id)
    return jsonify({"success": True, "data": data})


@ontology_bp.post("/<ontology_id>/documents")
def append_documents(ontology_id: str):
    registry.init_schema()
    files = request.files.getlist("files") if request.files else []
    if not files:
        return jsonify({"success": False, "error": "files 必填"}), 400
    try:
        data = ontology_service.append_documents(ontology_id, files)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.post("/<ontology_id>/snapshot")
def snapshot(ontology_id: str):
    registry.init_schema()
    try:
        record = ontology_service.create_snapshot(ontology_id)
        return jsonify({"success": True, "data": record})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.get("/<ontology_id>/versions")
def versions(ontology_id: str):
    registry.init_schema()
    return jsonify(
        {"success": True, "data": registry.list_versions(ontology_id)}
    )


def resolve_ontology_graph_id(ontology_id: str) -> str | None:
    """解析可用 graph_id：ontology 字段 → 进行中的 build task.result。"""
    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return None
    graph_id = ont.get("graph_id")
    if graph_id:
        return graph_id
    tid = ont.get("build_task_id") or ont.get("graph_build_task_id")
    if not tid:
        return None
    try:
        from app.models.task import TaskManager

        task = TaskManager().get_task(tid)
        if task and task.result:
            graph_id = task.result.get("graph_id")
            if graph_id and not ont.get("graph_id"):
                try:
                    registry.update_ontology(ontology_id, graph_id=graph_id)
                except Exception:
                    pass
            return graph_id
    except Exception:
        pass
    return None


def read_ontology_graph(ontology_id: str) -> dict | None:
    """读图谱数据（对齐 MiroFish /api/graph/data/{graph_id}）。

    优先 Zep live；无 graph_id 或 live 连线率过低时回退最新快照。
    """
    registry.init_schema()
    graph_id = resolve_ontology_graph_id(ontology_id)

    def _from_snapshot():
        latest = registry.get_latest_version(ontology_id)
        if latest and latest.get("snapshot_path"):
            try:
                snap = load_snapshot(latest["snapshot_path"])
                nodes = snap.get("nodes") or []
                edges = snap.get("edges") or []
                return {
                    "version": latest,
                    "graph_id": snap.get("graph_id") or latest.get("graph_id"),
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "source": "snapshot",
                }
            except Exception as e:
                logger.warning(f"read snapshot graph failed for {ontology_id}: {e}")
        return None

    def _match_rate(nodes, edges) -> float:
        if not edges:
            return 1.0
        ids = {n.get("uuid") for n in nodes if n.get("uuid")}
        ok = sum(
            1
            for e in edges
            if e.get("source_node_uuid") in ids and e.get("target_node_uuid") in ids
        )
        return ok / max(len(edges), 1)

    if graph_id:
        try:
            from app.config import Config
            from app.ontology.graph_builder import GraphBuilderService

            builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
            data = builder.get_graph_data(graph_id)
            nodes = data.get("nodes") or []
            edges = data.get("edges") or []
            live = {
                "graph_id": graph_id,
                "nodes": nodes,
                "edges": edges,
                "node_count": data.get("node_count") or len(nodes),
                "edge_count": data.get("edge_count") or len(edges),
                "source": "zep",
            }
            # 推演写入后 Zep 列表常漏节点；补拉后若仍几乎无连线，用快照保底
            if edges and _match_rate(nodes, edges) < 0.25:
                snap = _from_snapshot()
                if snap and _match_rate(snap["nodes"], snap["edges"]) > _match_rate(
                    nodes, edges
                ):
                    logger.warning(
                        f"live graph connectivity low for {ontology_id}, "
                        f"fallback to snapshot (live={_match_rate(nodes, edges):.0%} "
                        f"snap={_match_rate(snap['nodes'], snap['edges']):.0%})"
                    )
                    return snap
            return live
        except Exception as e:
            logger.warning(f"read zep graph failed for {ontology_id}: {e}")

    return _from_snapshot()

@ontology_bp.get("/<ontology_id>/graph")
def graph(ontology_id: str):
    """一次性拉图（有 graph_id 读 Zep；否则快照）。"""
    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return jsonify({"success": False, "error": "not found"}), 404
    data = read_ontology_graph(ontology_id)
    if not data:
        return jsonify({"success": False, "error": "图谱尚未创建"}), 404
    return jsonify({"success": True, "data": data})


@ontology_bp.put("/<ontology_id>/schema")
def put_schema(ontology_id: str):
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    schema = body.get("schema")
    if not schema:
        return jsonify({"success": False, "error": "schema 必填"}), 400
    lock = body.get("lock", True)
    try:
        ont = ontology_service.update_schema(ontology_id, schema, lock=lock)
        return jsonify({"success": True, "data": ont})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
