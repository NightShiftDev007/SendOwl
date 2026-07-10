"""
决策场景编排：共享世界切片 + 多方案 × 多种子推演
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import Config
from app.engine.contract import run_engine
from app.engine.intervention import Intervention
from app.ontology import registry
from app.ontology.snapshot import load_snapshot
from app.utils.logger import get_logger
from app.world.network import write_network
from app.world.population import generate_profiles_from_slice
from app.world.slicer import slice_world

logger = get_logger("adc.engine.scenario_runner")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScenarioRunner:
    """多方案 × 多采样决策推演编排器。"""

    def __init__(self):
        registry.init_schema()
        Config.ensure_directories()

    def create_decision(
        self,
        ontology_id: str,
        version_id: Optional[str],
        title: str,
        scenarios: List[Dict[str, Any]],
        sample_count: int = 3,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """
        scenarios: [{name, intervention|initial_posts, kind?, color?}, ...]
        """
        ont = registry.get_ontology(ontology_id)
        if not ont:
            raise ValueError(f"本体不存在: {ontology_id}")

        if not version_id:
            latest = registry.get_latest_version(ontology_id)
            if not latest:
                raise ValueError("本体没有快照版本，请先导出 snapshot")
            version_id = latest["id"]

        dec = registry.create_decision_record(
            ontology_id=ontology_id,
            version_id=version_id,
            title=title,
            sample_count=sample_count,
            max_rounds=max_rounds,
        )
        decision_id = dec["id"]

        colors = ["#e74c3c", "#27ae60", "#7f8c8d", "#3498db", "#9b59b6"]
        created_scenarios = []
        for i, sc in enumerate(scenarios or []):
            name = sc.get("name") or f"方案{i + 1}"
            kind = sc.get("kind") or sc.get("id") or "custom"
            color = sc.get("color") or colors[i % len(colors)]
            intervention = sc.get("intervention")
            if intervention is None:
                intervention = {
                    "name": name,
                    "kind": kind,
                    "initial_posts": sc.get("initial_posts") or [],
                    "narrative_direction": sc.get("hypothesis") or "",
                    "preferred_poster_keywords": sc.get("preferred_poster_keywords")
                    or ["交管", "官方", "周明远", "公安", "交通警察"],
                }
            rec = registry.add_scenario(
                decision_id=decision_id,
                name=name,
                intervention=intervention,
                kind=kind,
                color=color,
            )
            created_scenarios.append(rec)

            # 预创建 run 记录
            for s in range(sample_count):
                registry.add_run(rec["id"], seed=42 + s, status="pending")

        return {
            "decision": registry.get_decision(decision_id),
            "scenarios": created_scenarios,
            "runs": registry.list_runs_for_decision(decision_id),
        }

    def _build_shared_world(
        self,
        decision_id: str,
        intervention_text: str,
    ) -> str:
        """切片 + 人口 + 网络，写入 DECISION_DIR/{id}/shared。"""
        dec = registry.get_decision(decision_id)
        # 取 version 快照路径
        from app.models.store import connection

        with connection() as conn:
            row = conn.execute(
                "SELECT * FROM ontology_versions WHERE id = ?",
                (dec["version_id"],),
            ).fetchone()
        if not row:
            latest = registry.get_latest_version(dec["ontology_id"])
            if not latest:
                raise ValueError("无可用本体快照")
            version = latest
        else:
            version = dict(row)

        snapshot = load_snapshot(version["snapshot_path"])
        world_slice = slice_world(
            snapshot,
            intervention_text=intervention_text,
            k=2,
            use_llm_filter=False,
        )

        shared_dir = os.path.join(Config.DECISION_DIR, decision_id, "shared")
        if os.path.exists(shared_dir):
            shutil.rmtree(shared_dir)
        os.makedirs(shared_dir, exist_ok=True)

        with open(
            os.path.join(shared_dir, "slice.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(world_slice, f, ensure_ascii=False, indent=2)

        # 先生成 profiles（无 network），再写 network，再二次注入 persona
        pop = generate_profiles_from_slice(
            world_slice,
            output_dir=shared_dir,
            max_agents=30,
            use_llm=False,
        )
        network = write_network(
            world_slice,
            pop["entity_to_agent"],
            os.path.join(shared_dir, "network.json"),
        )
        # 用 network 再写一遍 persona 关注注入
        generate_profiles_from_slice(
            world_slice,
            output_dir=shared_dir,
            max_agents=30,
            use_llm=False,
            network=network,
        )

        # 基础 config 模板
        base_cfg = {
            "time_config": {
                "total_simulation_hours": int(dec.get("max_rounds") or 10),
                "minutes_per_round": 60,
                "agents_per_hour_min": 2,
                "agents_per_hour_max": 12,
            },
            "event_config": {"initial_posts": [], "hot_topics": []},
            "platform": "twitter",
        }
        with open(
            os.path.join(shared_dir, "base_simulation_config.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(base_cfg, f, ensure_ascii=False, indent=2)

        registry.update_decision(decision_id, shared_world_dir=shared_dir)
        return shared_dir

    def start_decision(self, decision_id: str, background: bool = True) -> Dict[str, Any]:
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        registry.update_decision(decision_id, status="running")

        if background:
            t = threading.Thread(
                target=self._run_decision_worker,
                args=(decision_id,),
                daemon=True,
            )
            t.start()
            return {"decision_id": decision_id, "status": "running"}

        return self._run_decision_worker(decision_id)

    def _run_decision_worker(self, decision_id: str) -> Dict[str, Any]:
        try:
            scenarios = registry.list_scenarios(decision_id)
            # 合并干预文本用于切片
            texts = []
            for sc in scenarios:
                iv = Intervention.from_dict(sc.get("intervention"))
                texts.append(iv.intervention_text())
            intervention_text = "\n".join(texts)

            shared_dir = self._build_shared_world(decision_id, intervention_text)
            with open(
                os.path.join(shared_dir, "base_simulation_config.json"),
                encoding="utf-8",
            ) as f:
                base_cfg = json.load(f)
            with open(
                os.path.join(shared_dir, "network.json"), encoding="utf-8"
            ) as f:
                network = json.load(f)

            dec = registry.get_decision(decision_id)
            max_rounds = int(dec.get("max_rounds") or 10)

            for sc in scenarios:
                runs = registry.list_runs_for_scenario(sc["id"])
                for run in runs:
                    registry.update_run(
                        run["id"],
                        status="running",
                        started_at=_utc_now(),
                    )
                    try:
                        result = run_engine(
                            profiles_dir=shared_dir,
                            config=base_cfg,
                            network=network,
                            intervention=sc.get("intervention"),
                            seed=int(run.get("seed") or 42),
                            max_rounds=max_rounds,
                            platform="twitter",
                            run_id=run["id"],
                            wait=True,
                        )
                        run_dir = os.path.join(Config.RUN_DIR, run["id"])
                        metrics = None
                        try:
                            from app.decision.metrics_service import (
                                compute_run_metrics,
                            )

                            metrics = compute_run_metrics(
                                run_dir,
                                scenario_id=sc.get("kind") or sc["id"],
                                scenario_name=sc.get("name") or "",
                                color=sc.get("color") or "#333",
                            )
                        except Exception as me:
                            logger.warning(f"指标计算失败: {me}")

                        registry.update_run(
                            run["id"],
                            status=result.get("status") or "completed",
                            run_dir=run_dir,
                            metrics=metrics,
                            finished_at=_utc_now(),
                            error=result.get("error"),
                        )
                    except Exception as e:
                        logger.exception(f"run failed: {run['id']}")
                        registry.update_run(
                            run["id"],
                            status="failed",
                            finished_at=_utc_now(),
                            error=str(e),
                        )

            registry.update_decision(decision_id, status="completed")
            return self.get_status(decision_id)
        except Exception as e:
            logger.error(traceback.format_exc())
            registry.update_decision(decision_id, status="failed")
            return {"decision_id": decision_id, "status": "failed", "error": str(e)}

    def get_status(self, decision_id: str) -> Dict[str, Any]:
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")
        scenarios = registry.list_scenarios(decision_id)
        matrix = []
        for sc in scenarios:
            runs = registry.list_runs_for_scenario(sc["id"])
            matrix.append(
                {
                    "scenario_id": sc["id"],
                    "scenario_name": sc.get("name"),
                    "kind": sc.get("kind"),
                    "color": sc.get("color"),
                    "runs": [
                        {
                            "run_id": r["id"],
                            "seed": r.get("seed"),
                            "status": r.get("status"),
                            "error": r.get("error"),
                            "started_at": r.get("started_at"),
                            "finished_at": r.get("finished_at"),
                            "has_metrics": bool(r.get("metrics")),
                        }
                        for r in runs
                    ],
                }
            )
        total = sum(len(m["runs"]) for m in matrix)
        done = sum(
            1
            for m in matrix
            for r in m["runs"]
            if r["status"] in ("completed", "stalled", "failed", "timeout")
        )
        return {
            "decision": dec,
            "matrix": matrix,
            "progress": {"done": done, "total": total},
        }

    def get_decision_detail(self, decision_id: str) -> Dict[str, Any]:
        status = self.get_status(decision_id)
        status["scenarios"] = registry.list_scenarios(decision_id)
        return status
