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
    """读图谱数据。

    - building：读 Zep live（不 heal），供 Step1 建图 SSE 增量刷图
    - ready：默认本地最新快照；无快照则 bootstrap 导出后再读
    """
    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return None

    graph_id = resolve_ontology_graph_id(ontology_id)
    status = str(ont.get("status") or "").lower()
    building = status == "building" or bool(
        ont.get("build_task_id") or ont.get("graph_build_task_id")
    )

    def _from_snapshot(*, allow_empty: bool = True):
        latest = registry.get_latest_version(ontology_id)
        if latest and latest.get("snapshot_path"):
            try:
                snap = load_snapshot(latest["snapshot_path"])
                nodes = snap.get("nodes") or []
                edges = snap.get("edges") or []
                if not allow_empty and not nodes and not edges:
                    return None
                return {
                    "version": latest,
                    "graph_id": snap.get("graph_id") or latest.get("graph_id") or graph_id,
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                    "source": "snapshot",
                }
            except Exception as e:
                logger.warning(f"read snapshot graph failed for {ontology_id}: {e}")
        return None

    def _from_live(gid: str):
        try:
            from app.config import Config
            from app.ontology.graph_builder import GraphBuilderService

            builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
            data = builder.get_graph_data(gid, heal=False)
            nodes = data.get("nodes") or []
            edges = data.get("edges") or []
            return {
                "graph_id": gid,
                "nodes": nodes,
                "edges": edges,
                "node_count": data.get("node_count") or len(nodes),
                "edge_count": data.get("edge_count") or len(edges),
                "source": "zep",
            }
        except Exception as e:
            logger.warning(f"read zep graph failed for {ontology_id}: {e}")
            return None

    def _refresh_snapshot_from_live(gid: str):
        """空快照时从 Zep 重导，避免 ready 后永久空白。"""
        try:
            from app.ontology.snapshot import export_snapshot

            export_snapshot(ontology_id, gid)
            return _from_snapshot(allow_empty=True)
        except Exception as e:
            logger.warning(f"refresh empty snapshot failed for {ontology_id}: {e}")
            return None

    # 建图期：live（不 heal、不 bootstrap）
    if building and graph_id:
        live = _from_live(graph_id)
        if live:
            return live
        return _from_snapshot()

    # ready：优先非空快照；空快照则回退 Zep live 并尝试重导
    snap = _from_snapshot(allow_empty=False)
    if snap:
        return snap

    if graph_id and not building:
        live = _from_live(graph_id)
        if live and (live.get("node_count") or live.get("edge_count")):
            refreshed = _refresh_snapshot_from_live(graph_id)
            return refreshed or live
        # live 也空：仍返回空快照/空 live，供前端继续补拉
        empty_snap = _from_snapshot(allow_empty=True)
        if empty_snap:
            return empty_snap
        if live:
            return live
        try:
            from app.ontology.snapshot import export_snapshot

            export_snapshot(ontology_id, graph_id)
            return _from_snapshot(allow_empty=True) or _from_live(graph_id)
        except Exception as e:
            logger.warning(f"bootstrap snapshot failed for {ontology_id}: {e}")
            return _from_live(graph_id)

    return None


@ontology_bp.get("/<ontology_id>/graph")
def graph(ontology_id: str):
    """读图：默认本地快照；建图中读 Zep live。"""
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
