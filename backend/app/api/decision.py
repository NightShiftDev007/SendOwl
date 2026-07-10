"""决策层 API"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.decision.metrics_service import build_compare_payload
from app.decision.report_service import generate_report
from app.engine.scenario_runner import ScenarioRunner
from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.api.decision")

decision_bp = Blueprint("decision", __name__, url_prefix="/api/decision")


@decision_bp.get("/health")
def health():
    return jsonify({"status": "ok", "module": "decision"})


@decision_bp.post("/create")
def create_decision():
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    ontology_id = body.get("ontology_id")
    title = body.get("title") or "未命名决策"
    if not ontology_id:
        return jsonify({"success": False, "error": "ontology_id 必填"}), 400
    try:
        runner = ScenarioRunner()
        data = runner.create_decision(
            ontology_id=ontology_id,
            version_id=body.get("version_id"),
            title=title,
            scenarios=body.get("scenarios") or [],
            sample_count=int(body.get("sample_count") or 3),
            max_rounds=int(body.get("max_rounds") or 10),
        )
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.exception("create decision failed")
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.get("/list")
def list_decisions():
    registry.init_schema()
    return jsonify({"success": True, "data": registry.list_decisions()})


@decision_bp.get("/<decision_id>")
def get_decision(decision_id: str):
    registry.init_schema()
    try:
        data = ScenarioRunner().get_decision_detail(decision_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@decision_bp.post("/<decision_id>/start")
def start_decision(decision_id: str):
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    background = body.get("background", True)
    try:
        data = ScenarioRunner().start_decision(
            decision_id, background=bool(background)
        )
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.exception("start decision failed")
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.get("/<decision_id>/status")
def decision_status(decision_id: str):
    registry.init_schema()
    try:
        data = ScenarioRunner().get_status(decision_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@decision_bp.get("/<decision_id>/compare")
def decision_compare(decision_id: str):
    registry.init_schema()
    try:
        payload = build_compare_payload(decision_id)
        # 可选生成报告
        if request.args.get("report", "false").lower() in ("1", "true", "yes"):
            report = generate_report(payload, decision_id=decision_id)
            payload["report"] = {
                "path": report["path"],
                "source": report["source"],
                "markdown": report.get("markdown") or "",
            }
        return jsonify({"success": True, "data": payload})
    except Exception as e:
        logger.exception("compare failed")
        return jsonify({"success": False, "error": str(e)}), 500
