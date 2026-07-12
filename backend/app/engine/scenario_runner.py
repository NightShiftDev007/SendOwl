"""
决策场景编排：共享世界切片 + 多方案 × 多种子推演

终局：每个 Run = 一个真正的 Simulation（SimulationManager / SimulationRunner）。
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
from app.engine.contract import materialize_run_dir, wait_for_simulation
from app.engine.intervention import Intervention
from app.engine.simulation_manager import SimulationManager, SimulationStatus
from app.engine.simulation_runner import SimulationRunner
from app.ontology import registry
from app.ontology.service import _combined_document_text
from app.ontology.snapshot import load_snapshot
from app.utils.logger import get_logger
from app.world.network import write_network
from app.world.population import generate_profiles_from_slice
from app.world.slicer import slice_world

logger = get_logger("adc.engine.scenario_runner")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_config_is_strong(event_config: Optional[Dict[str, Any]]) -> bool:
    """LLM 生成的初始激活通常 ≥2 帖 + ≥1 话题 + 叙事；干预 stub 往往只有 1 帖。"""
    if not isinstance(event_config, dict):
        return False
    posts = event_config.get("initial_posts") or []
    topics = event_config.get("hot_topics") or []
    narrative = str(event_config.get("narrative_direction") or "").strip()
    return len(posts) >= 2 and len(topics) >= 1 and bool(narrative)


def _sim_dir_looks_prepared(sim_id: str) -> bool:
    run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
    cfg_path = os.path.join(run_dir, "simulation_config.json")
    if not os.path.isfile(cfg_path):
        return False
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        return bool(cfg.get("time_config") and (cfg.get("agent_configs") or []))
    except Exception:
        return False


class ScenarioRunner:
    """多方案 × 多采样决策推演编排器（底层全部是真 Simulation）。"""

    def __init__(self):
        registry.init_schema()
        Config.ensure_directories()
        self.sim_manager = SimulationManager()

    def _ontology_graph_id(self, ontology_id: str) -> str:
        ont = registry.get_ontology(ontology_id)
        if not ont:
            raise ValueError(f"本体不存在: {ontology_id}")
        graph_id = ont.get("graph_id")
        if not graph_id:
            latest = registry.get_latest_version(ontology_id)
            if latest and latest.get("snapshot_path"):
                try:
                    snap = load_snapshot(latest["snapshot_path"])
                    graph_id = snap.get("graph_id")
                except Exception:
                    pass
        if not graph_id:
            raise ValueError("本体尚未建图，缺少 graph_id")
        return graph_id

    def create_decision(
        self,
        ontology_id: str,
        version_id: Optional[str],
        title: str,
        scenarios: List[Dict[str, Any]],
        sample_count: int = 1,
        max_rounds: int = 10,
    ) -> Dict[str, Any]:
        """
        scenarios: [{name, intervention|initial_posts|content, kind?, color?}, ...]
        默认 N=1 M=1；每个 Run 经 SimulationManager 创建真 simulation。
        """
        ont = registry.get_ontology(ontology_id)
        if not ont:
            raise ValueError(f"本体不存在: {ontology_id}")

        if not version_id:
            latest = registry.get_latest_version(ontology_id)
            # 允许尚无快照（任务可在建图前创建）；prepare 阶段再绑定最新版本
            version_id = latest["id"] if latest else ""

        sample_count = max(1, int(sample_count or 1))
        max_rounds = max(1, int(max_rounds or 10))

        # 默认单方案（N=1）
        if not scenarios:
            scenarios = [
                {
                    "name": title or "默认方案",
                    "kind": "default",
                    "color": "#3498db",
                    "intervention": {
                        "name": title or "默认方案",
                        "kind": "default",
                        "initial_posts": [],
                        "narrative_direction": title or "",
                    },
                }
            ]

        graph_id = None
        try:
            graph_id = self._ontology_graph_id(ontology_id)
        except ValueError:
            # 建图前即可建任务：先落 Decision，prepare 时再补建 sim
            graph_id = None

        # 一本体一活跃决策：旧活跃任务进回收站（不级联软删本体，避免新建失败）
        for old in registry.list_decisions(include_trashed=False):
            if old.get("ontology_id") == ontology_id:
                registry.trash_decision(old["id"], cascade_ontology=False)

        dec = registry.create_decision_record(
            ontology_id=ontology_id,
            version_id=version_id,
            title=title,
            sample_count=sample_count,
            max_rounds=max_rounds,
        )
        decision_id = dec["id"]

        created_scenarios = self._build_scenarios_and_runs(
            decision_id=decision_id,
            ontology_id=ontology_id,
            title=title,
            scenarios=scenarios,
            sample_count=sample_count,
            graph_id=graph_id,
        )

        detail = {
            "decision": registry.get_decision(decision_id),
            "scenarios": created_scenarios,
            "runs": registry.list_runs_for_decision(decision_id),
        }
        # 便捷字段：N=1 时前端可直接拿首个 sim_id 进 Step2
        runs = detail["runs"]
        if runs:
            detail["sim_id"] = runs[0].get("sim_id")
            detail["simulation_id"] = runs[0].get("sim_id")
        return detail

    def _clear_decision_scenarios_and_runs(self, decision_id: str) -> None:
        """清除决策下旧方案/runs 及 sim 磁盘，保留 decision 行本身。"""
        from app.models.store import connection

        runs = registry.list_runs_for_decision(decision_id)
        scenarios = registry.list_scenarios(decision_id)
        for r in runs:
            registry._rm_path(r.get("run_dir"))
            sim_id = r.get("sim_id")
            if sim_id:
                registry._rm_path(os.path.join(Config.RUN_DIR, sim_id))
                registry._rm_path(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id))
        with connection() as conn:
            for r in runs:
                conn.execute("DELETE FROM runs WHERE id = ?", (r["id"],))
            for s in scenarios:
                conn.execute("DELETE FROM scenarios WHERE id = ?", (s["id"],))
        # 共享世界需随方案重建
        dec = registry.get_decision(decision_id) or {}
        shared = dec.get("shared_world_dir")
        if shared:
            registry._rm_path(shared)
            registry.update_decision(decision_id, shared_world_dir="")

    def _build_scenarios_and_runs(
        self,
        decision_id: str,
        ontology_id: str,
        title: str,
        scenarios: List[Dict[str, Any]],
        sample_count: int,
        graph_id: Optional[str],
    ) -> List[Dict[str, Any]]:
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
                    "narrative_direction": sc.get("hypothesis") or sc.get("content") or "",
                    "preferred_poster_keywords": sc.get("preferred_poster_keywords")
                    or ["交管", "官方", "周明远", "公安", "交通警察"],
                }
                if sc.get("content") and not intervention["initial_posts"]:
                    intervention["initial_posts"] = [
                        {
                            "content": sc.get("content"),
                            "poster_hint": sc.get("poster_hint") or "official",
                        }
                    ]
            rec = registry.add_scenario(
                decision_id=decision_id,
                name=name,
                intervention=intervention,
                kind=kind,
                color=color,
            )
            created_scenarios.append(rec)

            for s in range(sample_count):
                sim_id = None
                run_dir = ""
                if graph_id:
                    state = self.sim_manager.create_simulation(
                        project_id=decision_id,
                        graph_id=graph_id,
                        enable_twitter=True,
                        enable_reddit=True,
                    )
                    sim_id = state.simulation_id
                    run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
                    ont_req = ""
                    try:
                        ont = registry.get_ontology(ontology_id) or {}
                        ont_req = (ont.get("simulation_requirement") or "").strip()
                    except Exception:
                        pass
                    req = (
                        ont_req
                        or Intervention.from_dict(intervention).intervention_text()
                        or title
                    )
                    cfg_path = os.path.join(run_dir, "simulation_config.json")
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(
                            {"simulation_requirement": req, "seed": 42 + s},
                            f,
                            ensure_ascii=False,
                            indent=2,
                        )
                registry.add_run(
                    rec["id"],
                    seed=42 + s,
                    status="pending",
                    sim_id=sim_id or "",
                    run_dir=run_dir,
                )
        return created_scenarios

    def replace_scenarios(
        self,
        decision_id: str,
        scenarios: List[Dict[str, Any]],
        sample_count: int = 1,
        max_rounds: int = 10,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """原地替换方案与 runs（不新建 Decision、不进回收站）。"""
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        ontology_id = dec.get("ontology_id") or ""
        sample_count = max(1, int(sample_count or 1))
        max_rounds = max(1, int(max_rounds or 10))
        title = (title or "").strip() or dec.get("title") or decision_id

        if not scenarios:
            scenarios = [
                {
                    "name": title or "默认方案",
                    "kind": "default",
                    "color": "#3498db",
                    "intervention": {
                        "name": title or "默认方案",
                        "kind": "default",
                        "initial_posts": [],
                        "narrative_direction": title or "",
                    },
                }
            ]

        # 绑定最新快照
        if not (dec.get("version_id") or "").strip():
            latest = registry.get_latest_version(ontology_id)
            if latest:
                registry.update_decision(decision_id, version_id=latest["id"])

        graph_id = None
        try:
            graph_id = self._ontology_graph_id(ontology_id)
        except ValueError:
            graph_id = None

        self._clear_decision_scenarios_and_runs(decision_id)
        registry.update_decision(
            decision_id,
            sample_count=sample_count,
            max_rounds=max_rounds,
            title=title,
            status="created",
        )
        self._build_scenarios_and_runs(
            decision_id=decision_id,
            ontology_id=ontology_id,
            title=title,
            scenarios=scenarios,
            sample_count=sample_count,
            graph_id=graph_id,
        )
        return self.get_decision_detail(decision_id)

    def ensure_sims(self, decision_id: str) -> Dict[str, Any]:
        """为尚无 sim_id 的 runs 补建空壳（不跑 LLM）。

        用于「点启动引擎即建任务」后、建图完成再进入 Step2 的衔接。
        """
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        ontology_id = dec.get("ontology_id") or ""
        # 绑定最新快照（建图前创建的任务 version_id 可能为空）
        if not (dec.get("version_id") or "").strip():
            latest = registry.get_latest_version(ontology_id)
            if latest:
                registry.update_decision(decision_id, version_id=latest["id"])

        graph_id = self._ontology_graph_id(ontology_id)
        runs = registry.list_runs_for_decision(decision_id)
        for run in runs:
            if run.get("sim_id"):
                continue
            state = self.sim_manager.create_simulation(
                project_id=decision_id,
                graph_id=graph_id,
                enable_twitter=True,
                enable_reddit=True,
            )
            sim_id = state.simulation_id
            run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
            ont_req = ""
            try:
                ont = registry.get_ontology(ontology_id) or {}
                ont_req = (ont.get("simulation_requirement") or "").strip()
            except Exception:
                pass
            req = ont_req or (dec.get("title") or decision_id)
            os.makedirs(run_dir, exist_ok=True)
            cfg_path = os.path.join(run_dir, "simulation_config.json")
            if not os.path.isfile(cfg_path):
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "simulation_requirement": req,
                            "seed": int(run.get("seed") or 42),
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            registry.update_run(run["id"], sim_id=sim_id, run_dir=run_dir)

        return self.get_decision_detail(decision_id)

    def _build_shared_world(
        self,
        decision_id: str,
        intervention_text: str,
        use_llm_profiles: Optional[bool] = None,
    ) -> str:
        """切片 + 人口 + 网络，写入 DECISION_DIR/{id}/shared。"""
        dec = registry.get_decision(decision_id)
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

        if use_llm_profiles is None:
            use_llm_profiles = bool(Config.LLM_API_KEY)

        # 第一次生成人设（可走 LLM）；第二次仅注入关注关系，复用结果避免 LLM 跑两遍
        pop = generate_profiles_from_slice(
            world_slice,
            output_dir=shared_dir,
            max_agents=30,
            use_llm=use_llm_profiles,
        )
        network = write_network(
            world_slice,
            pop["entity_to_agent"],
            os.path.join(shared_dir, "network.json"),
        )
        generate_profiles_from_slice(
            world_slice,
            output_dir=shared_dir,
            max_agents=30,
            use_llm=False,
            network=network,
            existing_profiles=pop.get("profiles"),
            existing_entity_to_agent=pop.get("entity_to_agent"),
        )

        from app.engine.contract import default_time_config

        base_cfg = {
            "time_config": default_time_config(
                total_hours=int(dec.get("max_rounds") or 10),
                minutes_per_round=60,
                agents_per_hour_min=2,
                agents_per_hour_max=12,
            ),
            "event_config": {"initial_posts": [], "hot_topics": [], "narrative_direction": ""},
            "agent_configs": [],
            "twitter_config": {
                "platform": "twitter",
                "recency_weight": 0.4,
                "popularity_weight": 0.3,
                "relevance_weight": 0.3,
                "viral_threshold": 10,
                "echo_chamber_strength": 0.5,
            },
            "reddit_config": {
                "platform": "reddit",
                "recency_weight": 0.3,
                "popularity_weight": 0.4,
                "relevance_weight": 0.3,
                "viral_threshold": 15,
                "echo_chamber_strength": 0.6,
            },
            "platform": "parallel",
            "simulation_requirement": intervention_text or (dec.get("title") or ""),
        }
        with open(
            os.path.join(shared_dir, "base_simulation_config.json"),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(base_cfg, f, ensure_ascii=False, indent=2)

        registry.update_decision(decision_id, shared_world_dir=shared_dir)
        return shared_dir

    def _inject_shared_world_into_sim(
        self,
        sim_id: str,
        shared_dir: str,
        base_cfg: Dict[str, Any],
        intervention: Any,
        seed: int,
        max_rounds: int,
        decision_id: str = "",
        graph_id: str = "",
    ) -> str:
        """把共享世界 profiles + 方案干预注入到真 simulation 目录。"""
        # 保留已有的强 event_config，避免刷新/重挂载 prepare 用干预 stub 冲掉 LLM 结果
        existing_event = None
        existing_cfg_path = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id, "simulation_config.json")
        if os.path.isfile(existing_cfg_path):
            try:
                with open(existing_cfg_path, encoding="utf-8") as f:
                    old_cfg = json.load(f)
                if _event_config_is_strong(old_cfg.get("event_config")):
                    existing_event = old_cfg.get("event_config")
            except Exception:
                pass

        # materialize_run_dir 以 sim_id 为目录名写入 OASIS_SIMULATION_DATA_DIR(=RUN_DIR)
        run_dir = materialize_run_dir(
            run_id=sim_id,
            profiles_dir=shared_dir,
            config=base_cfg,
            intervention=intervention,
            seed=seed,
            max_rounds=max_rounds,
        )

        cfg_path = os.path.join(run_dir, "simulation_config.json")
        if os.path.isfile(cfg_path) and (graph_id or decision_id or existing_event):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                if graph_id:
                    cfg["graph_id"] = graph_id
                if decision_id:
                    cfg["project_id"] = decision_id
                # 干预 stub 弱于已有 LLM 编排时，保留后者
                if existing_event and not _event_config_is_strong(cfg.get("event_config")):
                    cfg["event_config"] = existing_event
                    logger.info(f"保留已有强 event_config: sim_id={sim_id}")
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # 统一收口：以磁盘为准回写 state.json，并同步 meta.db
        state = self.sim_manager.finalize_prepare(sim_id)
        self.sim_manager.sync_prepare_to_registry(state)
        return run_dir

    def prepare_decision(self, decision_id: str) -> Dict[str, Any]:
        """
        准备推演环境。
        - N=1 M=1：走 SimulationManager.prepare_simulation（LLM 人设，MiroFish 原体验）
        - N>1 或 M>1：共享世界建一次，注入到各 sim
        """
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        scenarios = registry.list_scenarios(decision_id)
        runs = registry.list_runs_for_decision(decision_id)
        n = len(scenarios)
        m = int(dec.get("sample_count") or 1)

        texts = []
        for sc in scenarios:
            iv = Intervention.from_dict(sc.get("intervention"))
            texts.append(iv.intervention_text())
        intervention_text = "\n".join(texts) or (dec.get("title") or decision_id)

        # 已准备且各 sim 配置齐全：直接返回，避免刷新冲掉 LLM event_config
        if runs and all(r.get("sim_id") and _sim_dir_looks_prepared(r["sim_id"]) for r in runs):
            prefer = runs[0].get("sim_id") if len(runs) == 1 else None
            world = self.get_world_assets(decision_id, prefer_sim_id=prefer)
            logger.info(f"决策已准备，跳过重建: decision_id={decision_id}, sims={len(runs)}")
            return {
                "decision_id": decision_id,
                "status": "completed",
                "progress": 100,
                "stage": "ready",
                "message": "模拟环境已准备完成（缓存）",
                "sim_id": prefer,
                "profile_count": len(world.get("profiles") or []),
                "config": world.get("config"),
                "already_prepared": True,
                "mode": "cached",
            }

        # ---- N=1 M=1：经典 MiroFish prepare ----
        if n <= 1 and m <= 1 and runs:
            run = runs[0]
            sim_id = run.get("sim_id")
            if not sim_id:
                # 建图前创建的任务：此时补建 sim
                graph_id = self._ontology_graph_id(dec["ontology_id"])
                state = self.sim_manager.create_simulation(
                    project_id=decision_id,
                    graph_id=graph_id,
                    enable_twitter=True,
                    enable_reddit=True,
                )
                sim_id = state.simulation_id
                run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
                registry.update_run(run["id"], sim_id=sim_id, run_dir=run_dir)
            document_text = _combined_document_text(dec["ontology_id"]) or ""
            sc0 = scenarios[0] if scenarios else {}
            req = (
                Intervention.from_dict(sc0.get("intervention")).intervention_text()
                or intervention_text
            )
            state = self.sim_manager.prepare_simulation(
                simulation_id=sim_id,
                simulation_requirement=req,
                document_text=document_text,
                use_llm_for_profiles=True,
                parallel_profile_count=3,
            )
            # 若有干预，再 patch 到 config
            # N=1 默认方案的 initial_posts 往往是创建时塞入的需求原文 stub，
            # 不能覆盖 LLM 生成的 event_config；仅多方案/显式干预才注入。
            if sc0.get("intervention"):
                iv = Intervention.from_dict(sc0.get("intervention"))
                kind = (iv.kind or sc0.get("kind") or "default").lower()
                substantive = (
                    kind not in ("default", "")
                    or len(iv.initial_posts) > 1
                    or bool(iv.hot_topics)
                )
                if substantive:
                    cfg_path = os.path.join(
                        Config.OASIS_SIMULATION_DATA_DIR, sim_id, "simulation_config.json"
                    )
                    if os.path.isfile(cfg_path):
                        with open(cfg_path, encoding="utf-8") as f:
                            cfg = json.load(f)
                        from app.engine.contract import ensure_agent_configs, _load_profiles_from_dir
                        from app.engine.intervention import apply_to_config, load_agents_index

                        agents = load_agents_index(
                            _load_profiles_from_dir(
                                os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
                            )
                        )
                        cfg = apply_to_config(cfg, sc0.get("intervention"), agents)
                        cfg = ensure_agent_configs(cfg, agents)
                        cfg["simulation_requirement"] = req
                        with open(cfg_path, "w", encoding="utf-8") as f:
                            json.dump(cfg, f, ensure_ascii=False, indent=2)
                else:
                    # 仍写回完整需求，避免 stub 污染
                    cfg_path = os.path.join(
                        Config.OASIS_SIMULATION_DATA_DIR, sim_id, "simulation_config.json"
                    )
                    if os.path.isfile(cfg_path):
                        with open(cfg_path, encoding="utf-8") as f:
                            cfg = json.load(f)
                        cfg["simulation_requirement"] = req
                        with open(cfg_path, "w", encoding="utf-8") as f:
                            json.dump(cfg, f, ensure_ascii=False, indent=2)

            registry.update_run(
                run["id"],
                status="ready",
                run_dir=os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id),
            )
            registry.update_decision(decision_id, status="prepared")
            world = self.get_world_assets(decision_id, prefer_sim_id=sim_id)
            return {
                "decision_id": decision_id,
                "status": "completed",
                "progress": 100,
                "stage": "ready",
                "message": "模拟环境已准备完成（LLM 人设）",
                "sim_id": sim_id,
                "profile_count": state.profiles_count if state else len(world.get("profiles") or []),
                "config": world.get("config"),
                "mode": "single_sim",
            }

        # ---- N>1：共享世界 + 注入 ----
        shared_dir = self._build_shared_world(decision_id, intervention_text)
        with open(
            os.path.join(shared_dir, "base_simulation_config.json"),
            encoding="utf-8",
        ) as f:
            base_cfg = json.load(f)

        max_rounds = int(dec.get("max_rounds") or 10)
        graph_id = self._ontology_graph_id(dec["ontology_id"])
        for sc in scenarios:
            for run in registry.list_runs_for_scenario(sc["id"]):
                sim_id = run.get("sim_id")
                if not sim_id:
                    # 兼容旧数据：补建 sim
                    state = self.sim_manager.create_simulation(
                        project_id=decision_id, graph_id=graph_id
                    )
                    sim_id = state.simulation_id
                    registry.update_run(run["id"], sim_id=sim_id)

                run_dir = self._inject_shared_world_into_sim(
                    sim_id=sim_id,
                    shared_dir=shared_dir,
                    base_cfg=base_cfg,
                    intervention=sc.get("intervention"),
                    seed=int(run.get("seed") or 42),
                    max_rounds=max_rounds,
                    decision_id=decision_id,
                    graph_id=graph_id,
                )
                registry.update_run(run["id"], status="ready", run_dir=run_dir)

        registry.update_decision(decision_id, status="prepared")
        world = self.get_world_assets(decision_id)
        return {
            "decision_id": decision_id,
            "status": "completed",
            "progress": 100,
            "stage": "ready",
            "message": "共享世界已准备完成",
            "shared_world_dir": shared_dir,
            "profile_count": len(world.get("profiles") or []),
            "config": world.get("config"),
            "mode": "shared_world",
        }

    def get_world_assets(
        self, decision_id: str, prefer_sim_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """读取 profiles / config：优先单 sim，其次共享世界。"""
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        sim_id = prefer_sim_id
        if not sim_id:
            runs = registry.list_runs_for_decision(decision_id)
            if len(runs) == 1:
                sim_id = runs[0].get("sim_id")

        search_dirs: List[str] = []
        if sim_id:
            search_dirs.append(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id))
        shared_dir = dec.get("shared_world_dir") or os.path.join(
            Config.DECISION_DIR, decision_id, "shared"
        )
        search_dirs.append(shared_dir)

        profiles: List[Dict[str, Any]] = []
        config: Dict[str, Any] = {}
        used_dir = None

        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            reddit_path = os.path.join(d, "reddit_profiles.json")
            csv_path = os.path.join(d, "twitter_profiles.csv")
            cfg_path = os.path.join(d, "simulation_config.json")
            if not os.path.isfile(cfg_path):
                cfg_path = os.path.join(d, "base_simulation_config.json")

            local_profiles: List[Dict[str, Any]] = []
            if os.path.isfile(reddit_path):
                with open(reddit_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    local_profiles = raw
                elif isinstance(raw, dict):
                    local_profiles = raw.get("profiles") or raw.get("agents") or []
            elif os.path.isfile(csv_path):
                import csv

                with open(csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        local_profiles.append(
                            {
                                "agent_id": i,
                                "username": row.get("username") or row.get("name") or f"agent_{i}",
                                "name": row.get("name") or row.get("username") or f"agent_{i}",
                                "bio": row.get("bio") or row.get("description") or "",
                                "persona": row.get("persona") or row.get("user_char") or "",
                                "interested_topics": [],
                            }
                        )

            local_cfg: Dict[str, Any] = {}
            if os.path.isfile(cfg_path):
                with open(cfg_path, encoding="utf-8") as f:
                    local_cfg = json.load(f)

            if local_profiles or local_cfg:
                profiles = local_profiles
                config = local_cfg
                used_dir = d
                break

        normalized: List[Dict[str, Any]] = []
        for i, p in enumerate(profiles):
            if not isinstance(p, dict):
                continue
            item = dict(p)
            if item.get("agent_id") is None:
                item["agent_id"] = item.get("user_id", i)
            if not item.get("entity_type"):
                item["entity_type"] = (
                    item.get("source_entity_type") or item.get("profession") or "Agent"
                )
            if not item.get("interested_topics"):
                item["interested_topics"] = []
            normalized.append(item)

        return {
            "decision_id": decision_id,
            "sim_id": sim_id,
            "shared_world_dir": shared_dir if os.path.isdir(shared_dir) else None,
            "assets_dir": used_dir,
            "profiles": normalized,
            "config": config,
            "ready": bool(normalized or config),
        }

    def start_decision(self, decision_id: str, background: bool = True) -> Dict[str, Any]:
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        registry.update_decision(decision_id, status="running")
        try:
            from app.api.stream import publish_decision_status

            publish_decision_status(decision_id)
        except Exception:
            pass

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
        """串行启动各 Run 对应的真 Simulation。"""
        try:
            dec = registry.get_decision(decision_id)
            max_rounds = int(dec.get("max_rounds") or 10)
            scenarios = registry.list_scenarios(decision_id)

            # 若尚未 prepare，先 prepare
            runs_all = registry.list_runs_for_decision(decision_id)
            need_prepare = any(
                not r.get("sim_id")
                or not os.path.isfile(
                    os.path.join(
                        Config.OASIS_SIMULATION_DATA_DIR,
                        r.get("sim_id") or "",
                        "simulation_config.json",
                    )
                )
                for r in runs_all
            )
            if need_prepare or (dec.get("status") in (None, "", "created", "pending")):
                self.prepare_decision(decision_id)

            last_alive_sim: Optional[str] = None
            for sc in scenarios:
                runs = registry.list_runs_for_scenario(sc["id"])
                for run in runs:
                    st = (run.get("status") or "").lower()
                    if st in ("completed", "done", "success"):
                        continue
                    if st == "failed" and run.get("error") and "服务器关闭" not in (
                        run.get("error") or ""
                    ):
                        continue

                    sim_id = run.get("sim_id")
                    if not sim_id:
                        registry.update_run(
                            run["id"],
                            status="failed",
                            finished_at=_utc_now(),
                            error="缺少 sim_id",
                        )
                        continue

                    # 关闭上一个活跃 env（N>1 资源策略）
                    if last_alive_sim and last_alive_sim != sim_id:
                        try:
                            SimulationRunner.close_simulation_env(last_alive_sim)
                        except Exception as e:
                            logger.warning(f"close-env {last_alive_sim}: {e}")

                    registry.update_run(
                        run["id"],
                        status="running",
                        started_at=run.get("started_at") or _utc_now(),
                        error=None,
                    )
                    try:
                        from app.api.stream import publish_decision_status

                        publish_decision_status(decision_id)
                    except Exception:
                        pass
                    try:
                        # 确保 state ready
                        state = self.sim_manager.get_simulation(sim_id)
                        if state and state.status != SimulationStatus.READY:
                            # 若文件已齐，强制 ready
                            cfg = os.path.join(
                                Config.OASIS_SIMULATION_DATA_DIR,
                                sim_id,
                                "simulation_config.json",
                            )
                            if os.path.isfile(cfg):
                                state.status = SimulationStatus.READY
                                self.sim_manager._save_simulation_state(state)

                        SimulationRunner.start_simulation(
                            simulation_id=sim_id,
                            platform="twitter",
                            max_rounds=max_rounds,
                            enable_graph_memory_update=False,
                            no_wait=False,  # wait 模式：跑完可采访
                        )
                        result = wait_for_simulation(
                            run_id=sim_id,
                            max_rounds=max_rounds,
                        )
                        run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
                        metrics = None
                        try:
                            from app.decision.metrics_service import compute_run_metrics

                            metrics = compute_run_metrics(
                                run_dir,
                                scenario_id=sc.get("kind") or sc["id"],
                                scenario_name=sc.get("name") or "",
                                color=sc.get("color") or "#333",
                            )
                        except Exception as me:
                            logger.warning(f"指标计算失败: {me}")

                        final_status = result.get("status") or "completed"
                        if final_status in ("stopped", "error", "timeout", "stalled"):
                            # stalled/timeout 仍记 metrics，状态映射
                            if final_status in ("timeout", "stalled"):
                                pass
                            else:
                                final_status = "failed"

                        # 映射 runner 状态到 run 状态
                        status_map = {
                            "completed": "completed",
                            "idle": "completed",
                            "timeout": "timeout",
                            "stalled": "stalled",
                            "failed": "failed",
                            "error": "failed",
                            "stopped": "failed",
                        }
                        final_status = status_map.get(final_status, final_status)

                        registry.update_run(
                            run["id"],
                            status=final_status,
                            run_dir=run_dir,
                            sim_id=sim_id,
                            metrics=metrics,
                            finished_at=_utc_now(),
                            error=result.get("error"),
                        )
                        last_alive_sim = sim_id
                    except Exception as e:
                        logger.exception(f"run failed: {run['id']} sim={sim_id}")
                        registry.update_run(
                            run["id"],
                            status="failed",
                            finished_at=_utc_now(),
                            error=str(e),
                        )

            leftover = []
            for sc in registry.list_scenarios(decision_id):
                for run in registry.list_runs_for_scenario(sc["id"]):
                    if (run.get("status") or "").lower() in (
                        "pending",
                        "running",
                        "created",
                        "ready",
                    ):
                        leftover.append(run["id"])
            registry.update_decision(
                decision_id,
                status="running" if leftover else "completed",
            )
            status = self.get_status(decision_id)
            try:
                from app.api.stream import publish_decision_status

                publish_decision_status(decision_id, status)
            except Exception:
                pass
            return status
        except Exception as e:
            logger.error(traceback.format_exc())
            registry.update_decision(decision_id, status="failed")
            failed = {"decision_id": decision_id, "status": "failed", "error": str(e)}
            try:
                from app.api.stream import publish_decision_status

                publish_decision_status(decision_id, failed)
            except Exception:
                pass
            return failed

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
                            "sim_id": r.get("sim_id"),
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
            "status": dec.get("status"),
            "matrix": matrix,
            "progress": {"done": done, "total": total},
        }

    def get_decision_detail(self, decision_id: str) -> Dict[str, Any]:
        status = self.get_status(decision_id)
        scenarios = []
        for sc in registry.list_scenarios(decision_id):
            scenarios.append(
                {
                    **sc,
                    "runs": registry.list_runs_for_scenario(sc["id"]),
                }
            )
        status["scenarios"] = scenarios
        runs = registry.list_runs_for_decision(decision_id)
        if runs:
            status["sim_id"] = runs[0].get("sim_id")
            status["simulation_id"] = runs[0].get("sim_id")
        return status
