"""决策层 API"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.decision.metrics_service import build_compare_payload
from app.decision.report_service import generate_report
from app.engine.scenario_runner import ScenarioRunner, _sim_dir_looks_prepared
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
            # 终局默认 N=1 M=1（单次推演）
            sample_count=int(body.get("sample_count") if body.get("sample_count") is not None else 1),
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


@decision_bp.delete("/<decision_id>")
def delete_decision(decision_id: str):
    """移入回收站（软删除），不立即清磁盘。"""
    registry.init_schema()
    try:
        ok = registry.trash_decision(decision_id)
        if not ok:
            return jsonify({"success": False, "error": f"决策不存在: {decision_id}"}), 404
        return jsonify({"success": True, "data": {"id": decision_id, "trashed": True}})
    except Exception as e:
        logger.exception("trash decision failed")
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.get("/<decision_id>")
def get_decision(decision_id: str):
    registry.init_schema()
    try:
        data = ScenarioRunner().get_decision_detail(decision_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@decision_bp.post("/<decision_id>/ensure-sims")
def ensure_decision_sims(decision_id: str):
    """建图完成后为任务补建 sim 空壳（不跑 LLM prepare）。"""
    registry.init_schema()
    try:
        data = ScenarioRunner().ensure_sims(decision_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.exception("ensure sims failed")
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.post("/<decision_id>/scenarios")
def replace_decision_scenarios(decision_id: str):
    """原地替换方案与 runs，不新建 Decision、不进回收站。"""
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    try:
        data = ScenarioRunner().replace_scenarios(
            decision_id=decision_id,
            scenarios=body.get("scenarios") or [],
            sample_count=int(
                body.get("sample_count") if body.get("sample_count") is not None else 1
            ),
            max_rounds=int(body.get("max_rounds") or 10),
            title=body.get("title"),
        )
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.exception("replace scenarios failed")
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.post("/<decision_id>/prepare")
def prepare_decision(decision_id: str):
    """构建共享世界（切片/人口/网络），对应 MiroFish Step2 prepare。

    N>1 LLM 人设可能超过前端 HTTP 超时，改为后台线程执行；
    前端通过 decision.status=preparing + profiles/realtime（含 shared 回退）跟踪进度。
    """
    import threading

    registry.init_schema()
    try:
        body = request.get_json(silent=True) or {}
        force = bool(body.get("force_regenerate"))

        dec = registry.get_decision(decision_id)
        if not dec:
            return jsonify({"success": False, "error": f"决策不存在: {decision_id}"}), 404

        status = str(dec.get("status") or "").lower()
        if status == "preparing" and not force:
            return jsonify({
                "success": True,
                "data": {
                    "decision_id": decision_id,
                    "status": "preparing",
                    "already_prepared": False,
                    "message": "环境准备进行中",
                },
            })

        runner = ScenarioRunner()
        # 已完整准备：同步返回缓存，避免无意义后台任务
        try:
            runs = registry.list_runs_for_decision(decision_id) or []

            if (
                not force
                and runs
                and all(r.get("sim_id") and _sim_dir_looks_prepared(r["sim_id"]) for r in runs)
            ):
                data = runner.prepare_decision(decision_id, force=force)
                return jsonify({"success": True, "data": data})
        except Exception:
            pass

        registry.update_decision(decision_id, status="preparing")

        def _worker():
            try:
                ScenarioRunner().prepare_decision(decision_id, force=force)
            except Exception as exc:
                logger.exception("prepare decision background failed: %s", exc)
                try:
                    registry.update_decision(decision_id, status="prepare_failed")
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True, name=f"prepare-{decision_id}").start()
        return jsonify({
            "success": True,
            "data": {
                "decision_id": decision_id,
                "status": "preparing",
                "already_prepared": False,
                "progress": 0,
                "message": "环境准备已在后台启动",
            },
        })
    except Exception as e:
        logger.exception("prepare decision failed")
        try:
            registry.update_decision(decision_id, status="prepare_failed")
        except Exception:
            pass
        return jsonify({"success": False, "error": str(e)}), 500


@decision_bp.get("/<decision_id>/world")
def decision_world(decision_id: str):
    """返回共享世界 profiles / config，供 Step2 展示。"""
    registry.init_schema()
    try:
        data = ScenarioRunner().get_world_assets(decision_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404


@decision_bp.post("/<decision_id>/start")
def start_decision(decision_id: str):
    registry.init_schema()
    body = request.get_json(silent=True) or {}
    background = body.get("background", True)
    force = bool(body.get("force", False))
    try:
        data = ScenarioRunner().start_decision(
            decision_id,
            background=bool(background),
            force=force,
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
            force = request.args.get("force", "false").lower() in ("1", "true", "yes")
            report = generate_report(payload, decision_id=decision_id, force=force)
            payload["report"] = {
                "path": report["path"],
                "source": report["source"],
                "markdown": report.get("markdown") or "",
            }
        return jsonify({"success": True, "data": payload})
    except Exception as e:
        logger.exception("compare failed")
        return jsonify({"success": False, "error": str(e)}), 500
