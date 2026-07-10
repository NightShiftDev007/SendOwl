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
    if isinstance(use_llm, str):
        use_llm_ontology = use_llm.lower() in ("1", "true", "yes")
    else:
        use_llm_ontology = bool(use_llm)

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


@ontology_bp.get("/<ontology_id>/graph")
def graph(ontology_id: str):
    registry.init_schema()
    latest = registry.get_latest_version(ontology_id)
    if latest and latest.get("snapshot_path"):
        try:
            snap = load_snapshot(latest["snapshot_path"])
            return jsonify(
                {
                    "success": True,
                    "data": {
                        "version": latest,
                        "nodes": snap.get("nodes") or [],
                        "edges": snap.get("edges") or [],
                        "graph_id": snap.get("graph_id"),
                    },
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # 无快照时回退 live（建图刚完成、快照尚未写出的竞态窗口）
    ont = registry.get_ontology(ontology_id)
    graph_id = (ont or {}).get("graph_id")
    if not graph_id:
        return jsonify({"success": False, "error": "无可用快照"}), 404
    try:
        from app.config import Config
        from app.ontology.graph_builder import GraphBuilderService

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        data = builder.get_graph_data(graph_id)
        return jsonify(
            {
                "success": True,
                "data": {
                    "graph_id": graph_id,
                    "nodes": data.get("nodes") or [],
                    "edges": data.get("edges") or [],
                    "node_count": data.get("node_count"),
                    "edge_count": data.get("edge_count"),
                    "live": True,
                },
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@ontology_bp.get("/<ontology_id>/graph/live")
def graph_live(ontology_id: str):
    """直读 Zep 当前图谱（建图过程中可实时刷图）。"""
    registry.init_schema()
    ont = registry.get_ontology(ontology_id)
    if not ont:
        return jsonify({"success": False, "error": "not found"}), 404
    graph_id = ont.get("graph_id")
    # 建图中途：本体尚未回写时，从进行中的 task.result 取 graph_id
    if not graph_id:
        tid = ont.get("build_task_id")
        if tid:
            from app.models.task import TaskManager

            task = TaskManager().get_task(tid)
            if task and task.result:
                graph_id = task.result.get("graph_id")
                if graph_id and not ont.get("graph_id"):
                    try:
                        registry.update_ontology(ontology_id, graph_id=graph_id)
                    except Exception:
                        pass
    if not graph_id:
        return jsonify({"success": False, "error": "图谱尚未创建"}), 404
    try:
        from app.config import Config
        from app.ontology.graph_builder import GraphBuilderService

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        data = builder.get_graph_data(graph_id)
        return jsonify(
            {
                "success": True,
                "data": {
                    "graph_id": graph_id,
                    "nodes": data.get("nodes") or [],
                    "edges": data.get("edges") or [],
                    "node_count": data.get("node_count"),
                    "edge_count": data.get("edge_count"),
                    "live": True,
                },
            }
        )
    except Exception as e:
        logger.exception("live graph fetch failed")
        return jsonify({"success": False, "error": str(e)}), 500


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
