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
from app.world.population import (
    expected_agent_count_from_slice,
    generate_profiles_from_slice,
)
from app.world.slicer import slice_world

logger = get_logger("adc.engine.scenario_runner")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prepare_progress_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "prepare_progress.json")


def _write_prepare_progress(decision_id: str, **fields) -> Dict[str, Any]:
    """写入 N>1 prepare 细进度（侧车 JSON，形状对齐 ProgressEnvelope 子集）。"""
    path = _prepare_progress_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "scope": "decision",
        "id": decision_id,
        "status": "running",
        "stage": "preparing",
        "progress": 0,
        "message": "",
        "profile_count": 0,
        "updated_at": _utc_now(),
    }
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                payload.update(json.load(f) or {})
        except Exception:
            pass
    payload.update({k: v for k, v in fields.items() if v is not None})
    payload["updated_at"] = _utc_now()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        from app.api.stream import publish_decision_status

        publish_decision_status(decision_id)
    except Exception:
        pass
    return payload


def _read_prepare_progress(decision_id: str) -> Optional[Dict[str, Any]]:
    path = _prepare_progress_path(decision_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _event_config_is_strong(event_config: Optional[Dict[str, Any]]) -> bool:
    """LLM 生成的初始激活通常 ≥2 帖 + ≥1 话题 + 叙事；干预 stub 往往只有 1 帖。"""
    if not isinstance(event_config, dict):
        return False
    posts = [
        p
        for p in (event_config.get("initial_posts") or [])
        if isinstance(p, dict) and str(p.get("content") or "").strip()
    ]
    topics = [
        t for t in (event_config.get("hot_topics") or []) if str(t or "").strip()
    ]
    narrative = str(event_config.get("narrative_direction") or "").strip()
    return len(posts) >= 2 and len(topics) >= 1 and bool(narrative)



def _entities_from_shared_profiles(shared_dir: str) -> List[Any]:
    """从 shared reddit_profiles 构造 EntityNode，供多方案 LLM 配置生成。"""
    from app.ontology.zep_entity_reader import EntityNode

    path = os.path.join(shared_dir, "reddit_profiles.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            profiles = json.load(f) or []
    except Exception:
        return []
    if not isinstance(profiles, list):
        return []

    entities = []
    for i, p in enumerate(profiles):
        if not isinstance(p, dict):
            continue
        etype = p.get("source_entity_type") or p.get("profession") or "Unknown"
        name = p.get("name") or p.get("username") or f"agent_{i}"
        uuid = p.get("source_entity_uuid") or f"local-profile-{i}"
        entities.append(
            EntityNode(
                uuid=str(uuid),
                name=str(name),
                labels=[str(etype)],
                summary=str(p.get("bio") or p.get("persona") or "")[:500],
                attributes={"entity_type": etype},
            )
        )
    return entities


def _generate_shared_base_config(
    *,
    decision_id: str,
    shared_dir: str,
    intervention_text: str,
    max_rounds: int,
    graph_id: str = "",
) -> Dict[str, Any]:
    """多方案共享世界：用人设 + 文档跑一遍 LLM 配置（含强 event_config）。"""
    from app.engine.contract import default_time_config, ensure_agent_configs
    from app.engine.simulation_config_generator import SimulationConfigGenerator

    entities = _entities_from_shared_profiles(shared_dir)
    if not entities:
        raise RuntimeError("共享世界无人设，无法生成初始激活编排")

    dec = registry.get_decision(decision_id) or {}
    ontology_id = dec.get("ontology_id") or ""
    document_text = _combined_document_text(ontology_id) if ontology_id else ""
    graph_id = graph_id or ""
    if not graph_id and ontology_id:
        try:
            ont = registry.get_ontology(ontology_id) or {}
            graph_id = ont.get("graph_id") or ""
        except Exception:
            pass

    _write_prepare_progress(
        decision_id,
        stage="config",
        progress=78,
        message="正在生成双平台配置与初始激活编排…",
        profile_count=len(entities),
        status="running",
    )

    generator = SimulationConfigGenerator()

    def _progress(step, total, message):
        pct = 78 + int(10 * step / max(total, 1))
        _write_prepare_progress(
            decision_id,
            stage="config",
            progress=min(pct, 88),
            message=message or "生成模拟配置…",
            profile_count=len(entities),
            status="running",
        )

    params = generator.generate_config(
        simulation_id=f"shared_{decision_id}",
        project_id=decision_id,
        graph_id=graph_id,
        simulation_requirement=intervention_text or (dec.get("title") or decision_id),
        document_text=document_text or "",
        entities=entities,
        enable_twitter=True,
        enable_reddit=True,
        progress_callback=_progress,
    )
    cfg = params.to_dict()
    # 与单 sim 一致：补齐 agent_configs 兜底
    try:
        from app.engine.contract import _load_profiles_from_dir
        from app.engine.intervention import load_agents_index

        agents = load_agents_index(_load_profiles_from_dir(shared_dir))
        cfg = ensure_agent_configs(cfg, agents)
    except Exception as e:
        logger.warning(f"shared base ensure_agent_configs 失败: {e}")

    # 覆盖时间总长为决策 max_rounds（小时）
    if isinstance(cfg.get("time_config"), dict) and max_rounds:
        cfg["time_config"]["total_simulation_hours"] = int(max_rounds)

    cfg["platform"] = cfg.get("platform") or "parallel"
    cfg["simulation_requirement"] = intervention_text or cfg.get("simulation_requirement") or ""

    # 首轮弱结果：单独重跑一次事件编排，再判死刑
    if not _event_config_is_strong(cfg.get("event_config")):
        logger.warning(
            f"shared event_config 首轮偏弱，重试初始激活编排 decision={decision_id}"
        )
        try:
            cfg = generator.regenerate_event_config(
                existing_config=cfg,
                simulation_requirement=intervention_text or (dec.get("title") or decision_id),
                document_text=document_text or "",
                entities=entities,
            )
        except Exception as e:
            logger.warning(f"shared event_config 重试失败: {e}")
    if not _event_config_is_strong(cfg.get("event_config")):
        raise RuntimeError(
            "LLM 初始激活编排结果无效（需≥2条初始帖、≥1个热点、非空叙事）"
        )
    return cfg


def propagate_strong_event_config(
    decision_id: str,
    event_config: Dict[str, Any],
    source_sim_id: str = "",
) -> int:
    """单 sim 分阶段重试修好 event_config 后，补齐共享 base 与其余弱 sim。

    合并策略与注入一致：保留目标 sim 自己的干预帖在前，热点/叙事取强配置。
    返回修补的 sim 数。
    """
    if not _event_config_is_strong(event_config):
        return 0
    fixed = 0

    shared_base = os.path.join(
        Config.DECISION_DIR, decision_id, "shared", "base_simulation_config.json"
    )
    if os.path.isfile(shared_base):
        try:
            with open(shared_base, encoding="utf-8") as f:
                base = json.load(f) or {}
            if not _event_config_is_strong(base.get("event_config")):
                base["event_config"] = event_config
                with open(shared_base, "w", encoding="utf-8") as f:
                    json.dump(base, f, ensure_ascii=False, indent=2)
                logger.info(f"propagate event_config → shared base: {decision_id}")
        except Exception as e:
            logger.warning(f"propagate 到 shared base 失败: {e}")

    try:
        runs = registry.list_runs_for_decision(decision_id) or []
    except Exception:
        runs = []
    for run in runs:
        sim_id = run.get("sim_id")
        if not sim_id or sim_id == source_sim_id:
            continue
        cfg_path = os.path.join(
            Config.OASIS_SIMULATION_DATA_DIR, sim_id, "simulation_config.json"
        )
        if not os.path.isfile(cfg_path):
            continue
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f) or {}
            cur = cfg.get("event_config") if isinstance(cfg.get("event_config"), dict) else {}
            if _event_config_is_strong(cur):
                continue
            merged = dict(event_config)
            own_posts = [
                p
                for p in (cur.get("initial_posts") or [])
                if isinstance(p, dict) and str(p.get("content") or "").strip()
            ]
            if own_posts:
                seen = {str(p.get("content") or "").strip() for p in own_posts}
                padded = list(own_posts)
                posts_min = max(2, int(getattr(Config, "EVENT_INITIAL_POSTS_MIN", 4) or 4))
                source_posts = [
                    p
                    for p in (merged.get("initial_posts") or [])
                    if isinstance(p, dict) and str(p.get("content") or "").strip()
                ]
                pad_target = min(posts_min, len(own_posts) + len(source_posts))
                for p in source_posts:
                    if len(padded) >= pad_target:
                        break
                    c = str(p.get("content") or "").strip()
                    if c and c not in seen:
                        padded.append(p)
                        seen.add(c)
                merged["initial_posts"] = padded
            cfg["event_config"] = merged
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            fixed += 1
        except Exception as e:
            logger.warning(f"propagate 到 sim={sim_id} 失败: {e}")
    if fixed:
        logger.info(
            f"propagate event_config: decision={decision_id} 修补 {fixed} 个弱 sim"
        )
    return fixed


def _read_event_config_from_sim(sim_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sim_id:
        return None
    path = os.path.join(
        Config.OASIS_SIMULATION_DATA_DIR, sim_id, "simulation_config.json"
    )
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f) or {}
        ec = cfg.get("event_config")
        return ec if isinstance(ec, dict) else None
    except Exception:
        return None


def _assert_event_config_ready_for_prepare(
    decision_id: str, *, sim_id: Optional[str] = None, cfg: Optional[Dict[str, Any]] = None
) -> None:
    """prepared 前硬门槛：弱初始激活不得解锁 Step3。"""
    event_config = None
    if isinstance(cfg, dict):
        event_config = cfg.get("event_config") if isinstance(cfg.get("event_config"), dict) else cfg
    if not _event_config_is_strong(event_config):
        event_config = _read_event_config_from_sim(sim_id)
    if not _event_config_is_strong(event_config):
        # 尝试 shared base
        shared = os.path.join(
            Config.DECISION_DIR, decision_id, "shared", "base_simulation_config.json"
        )
        if os.path.isfile(shared):
            try:
                with open(shared, encoding="utf-8") as f:
                    base = json.load(f) or {}
                event_config = base.get("event_config")
            except Exception:
                pass
    if not _event_config_is_strong(event_config):
        raise RuntimeError(
            "初始激活编排未完成或结果无效（需≥2条初始帖、≥1个热点、非空叙事），"
            "不能标记为 prepared"
        )


def _sim_dir_looks_prepared(sim_id: str) -> bool:
    run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
    # GTV 商业模板：轻量 stub 即视为已准备
    if os.path.isfile(os.path.join(run_dir, "gtv_engine.json")):
        return True
    cfg_path = os.path.join(run_dir, "simulation_config.json")
    if not os.path.isfile(cfg_path):
        return False
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        # 弱 event_config 不算已准备，否则缓存路径会永久跳过修复
        if not (
            cfg.get("time_config")
            and (cfg.get("agent_configs") or [])
            and _event_config_is_strong(cfg.get("event_config"))
        ):
            return False
        # 人设也要齐：禁止「只有配置、人设残缺」被当成已准备
        agents_n = len(cfg.get("agent_configs") or [])
        profiles_n = 0
        reddit = os.path.join(run_dir, "reddit_profiles.json")
        if os.path.isfile(reddit):
            with open(reddit, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                profiles_n = len(raw)
        if profiles_n <= 0:
            return False
        if agents_n > 0 and profiles_n < max(2, int(agents_n * 0.8)):
            return False
        return True
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
                if sc.get("gtv"):
                    intervention["gtv"] = sc.get("gtv")
            elif isinstance(intervention, dict) and sc.get("gtv") and not intervention.get("gtv"):
                intervention = {**intervention, "gtv": sc.get("gtv")}
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
        force: bool = False,
    ) -> str:
        """切片 + 人口 + 网络，写入 DECISION_DIR/{id}/shared。

        Phase C：默认重入——已有 slice/profiles/base_config 则跳过；
        仅 force=True 时清空 shared/ 重做。
        """
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
        world_slice = None
        shared_dir = os.path.join(Config.DECISION_DIR, decision_id, "shared")
        slice_path = os.path.join(shared_dir, "slice.json")
        profiles_path = os.path.join(shared_dir, "reddit_profiles.json")
        base_cfg_path = os.path.join(shared_dir, "base_simulation_config.json")

        if force and os.path.exists(shared_dir):
            shutil.rmtree(shared_dir)
        os.makedirs(shared_dir, exist_ok=True)

        if os.path.isfile(slice_path) and not force:
            try:
                with open(slice_path, encoding="utf-8") as f:
                    world_slice = json.load(f)
                if not (world_slice or {}).get("nodes"):
                    world_slice = None
                else:
                    logger.info(f"resume shared: 复用 slice.json decision={decision_id}")
            except Exception:
                world_slice = None

        if world_slice is None:
            _write_prepare_progress(
                decision_id,
                stage="slice",
                progress=10,
                message="正在切片世界图谱…",
                status="running",
            )
            world_slice = slice_world(
                snapshot,
                intervention_text=intervention_text,
                k=2,
                use_llm_filter=False,
            )
            with open(slice_path, "w", encoding="utf-8") as f:
                json.dump(world_slice, f, ensure_ascii=False, indent=2)
        else:
            _write_prepare_progress(
                decision_id,
                stage="slice",
                progress=10,
                message="复用已有世界切片…",
                status="running",
            )

        node_count = len(world_slice.get("nodes") or [])
        total_expected = expected_agent_count_from_slice(world_slice)
        _write_prepare_progress(
            decision_id,
            stage="profiles",
            progress=25,
            message=f"切片完成（{node_count} 实体），正在生成 Agent 人设…",
            profile_count=0,
            total_expected=total_expected or None,
            status="running",
        )

        if use_llm_profiles is None:
            use_llm_profiles = bool(Config.LLM_API_KEY)

        # resume：人设已达标则跳过 LLM
        existing_profiles = None
        if os.path.isfile(profiles_path) and not force:
            try:
                with open(profiles_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list) and len(raw) > 0:
                    existing_profiles = raw
                elif isinstance(raw, dict):
                    existing_profiles = raw.get("profiles") or []
            except Exception:
                existing_profiles = None

        if existing_profiles and len(existing_profiles) >= max(1, min(5, max(node_count // 2, 1))):
            pop = {
                "profiles": existing_profiles,
                "entity_to_agent": {},
            }
            eta_path = os.path.join(shared_dir, "entity_to_agent.json")
            if os.path.isfile(eta_path):
                try:
                    with open(eta_path, encoding="utf-8") as f:
                        pop["entity_to_agent"] = json.load(f) or {}
                except Exception:
                    pass
            logger.info(
                f"resume shared: 复用 {len(existing_profiles)} 人设 decision={decision_id}"
            )
            profile_count = len(existing_profiles)
            _write_prepare_progress(
                decision_id,
                stage="profiles",
                progress=70,
                message=f"复用已有 {profile_count} 个人设，注入关注网络…",
                profile_count=profile_count,
                status="running",
            )
            network = write_network(
                world_slice,
                pop.get("entity_to_agent") or {},
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
        else:
            pop = generate_profiles_from_slice(
                world_slice,
                output_dir=shared_dir,
                max_agents=30,
                use_llm=use_llm_profiles,
            )
            profile_count = len(pop.get("profiles") or [])
            _write_prepare_progress(
                decision_id,
                stage="profiles",
                progress=70,
                message=f"已生成 {profile_count} 个人设，注入关注网络…",
                profile_count=profile_count,
                status="running",
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

        _write_prepare_progress(
            decision_id,
            stage="inject",
            progress=85,
            message="正在写入基础配置…",
            profile_count=profile_count,
            status="running",
        )

        base_cfg = None
        if os.path.isfile(base_cfg_path) and not force:
            try:
                with open(base_cfg_path, encoding="utf-8") as f:
                    base_cfg = json.load(f)
                # 弱/空初始激活不能复用（否则多方案永远 prepare_failed）
                if not (base_cfg or {}).get("time_config") or not _event_config_is_strong(
                    (base_cfg or {}).get("event_config")
                ):
                    logger.info(
                        f"resume shared: base_config 缺失或 event_config 弱，重新生成 "
                        f"decision={decision_id}"
                    )
                    base_cfg = None
                else:
                    logger.info(
                        f"resume shared: 复用 base_simulation_config decision={decision_id}"
                    )
            except Exception:
                base_cfg = None

        if base_cfg is None:
            graph_id = ""
            try:
                ont = registry.get_ontology(dec.get("ontology_id") or "") or {}
                graph_id = ont.get("graph_id") or ""
            except Exception:
                pass
            base_cfg = _generate_shared_base_config(
                decision_id=decision_id,
                shared_dir=shared_dir,
                intervention_text=intervention_text,
                max_rounds=int(dec.get("max_rounds") or 10),
                graph_id=graph_id,
            )
            with open(base_cfg_path, "w", encoding="utf-8") as f:
                json.dump(base_cfg, f, ensure_ascii=False, indent=2)
            logger.info(
                f"shared LLM 配置已写入: decision={decision_id} "
                f"agents={len(base_cfg.get('agent_configs') or [])} "
                f"posts={len((base_cfg.get('event_config') or {}).get('initial_posts') or [])}"
            )

        registry.update_decision(decision_id, shared_world_dir=shared_dir)
        _write_prepare_progress(
            decision_id,
            stage="inject",
            progress=90,
            message="共享世界已就绪，注入各方案…",
            profile_count=profile_count,
            status="running",
        )
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
        if os.path.isfile(cfg_path) and (graph_id or decision_id or existing_event or base_cfg):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                if graph_id:
                    cfg["graph_id"] = graph_id
                if decision_id:
                    cfg["project_id"] = decision_id

                # materialize 的 apply_to_config 会用方案干预帖覆盖整份 event_config，
                # 常把 LLM 热点/叙事冲成弱编排。合并：方案帖优先，缺口用 base/已有强编排补齐。
                base_event = (
                    existing_event
                    if _event_config_is_strong(existing_event)
                    else (
                        (base_cfg or {}).get("event_config")
                        if _event_config_is_strong((base_cfg or {}).get("event_config"))
                        else None
                    )
                )
                cur_event = cfg.get("event_config") if isinstance(cfg.get("event_config"), dict) else {}
                if base_event and not _event_config_is_strong(cur_event):
                    merged = dict(base_event)
                    iv_posts = [
                        p
                        for p in (cur_event.get("initial_posts") or [])
                        if isinstance(p, dict) and str(p.get("content") or "").strip()
                    ]
                    base_posts = [
                        p
                        for p in (base_event.get("initial_posts") or [])
                        if isinstance(p, dict) and str(p.get("content") or "").strip()
                    ]
                    if iv_posts:
                        # 方案差异帖在前，再用 base 帖补到 EVENT_INITIAL_POSTS_MIN
                        seen = {str(p.get("content") or "").strip() for p in iv_posts}
                        padded = list(iv_posts)
                        posts_min = max(2, int(getattr(Config, "EVENT_INITIAL_POSTS_MIN", 4) or 4))
                        pad_target = min(posts_min, len(iv_posts) + len(base_posts))
                        for p in base_posts:
                            if len(padded) >= pad_target:
                                break
                            c = str(p.get("content") or "").strip()
                            if c and c not in seen:
                                padded.append(p)
                                seen.add(c)
                        merged["initial_posts"] = padded
                    cfg["event_config"] = merged
                    logger.info(
                        f"合并强 event_config 与方案干预: sim_id={sim_id} "
                        f"posts={len(merged.get('initial_posts') or [])}"
                    )
                elif existing_event and not _event_config_is_strong(cur_event):
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

    def prepare_decision(self, decision_id: str, force: bool = False) -> Dict[str, Any]:
        """
        准备推演环境。
        - N=1 M=1：走 SimulationManager.prepare_simulation（LLM 人设，MiroFish 原体验）
        - N>1 或 M>1：共享世界建一次，注入到各 sim
        - force=True：N>1 清空 shared/ 重做
        - template=gtv_deal：轻量 prepare（跳过社媒人设/OASIS）
        """
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        from app.engine.gtv_adapter import is_gtv_deal, prepare_gtv_deal

        if is_gtv_deal(decision_id):
            return prepare_gtv_deal(self, decision_id, force=force)

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
        if (
            not force
            and runs
            and all(r.get("sim_id") and _sim_dir_looks_prepared(r["sim_id"]) for r in runs)
        ):
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
                parallel_profile_count=Config.llm_parallel_workers(),
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
            _assert_event_config_ready_for_prepare(decision_id, sim_id=sim_id)
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
        _write_prepare_progress(
            decision_id,
            stage="slice",
            progress=5,
            message="开始构建共享世界…",
            status="running",
        )
        shared_dir = self._build_shared_world(
            decision_id, intervention_text, force=force
        )
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

        _assert_event_config_ready_for_prepare(decision_id, cfg=base_cfg)
        registry.update_decision(decision_id, status="prepared")
        world = self.get_world_assets(decision_id)
        _write_prepare_progress(
            decision_id,
            stage="ready",
            progress=100,
            message="共享世界已准备完成",
            profile_count=len(world.get("profiles") or []),
            status="completed",
        )
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
        """读取 profiles / config：合并 sim 与 shared，取更完整的一份。

        禁止「sim 有 1 条残缺人设 / stub config 就 break」，否则会盖过 shared 全量。
        """
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        sim_id = prefer_sim_id
        if not sim_id:
            runs = registry.list_runs_for_decision(decision_id)
            if len(runs) == 1:
                sim_id = runs[0].get("sim_id")

        shared_dir = dec.get("shared_world_dir") or os.path.join(
            Config.DECISION_DIR, decision_id, "shared"
        )
        # shared 优先扫描，再补 sim（最终仍按完整度择优）
        search_dirs: List[str] = [shared_dir]
        if sim_id:
            search_dirs.append(os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id))

        profiles: List[Dict[str, Any]] = []
        config: Dict[str, Any] = {}
        used_dir = None

        def _cfg_score(cfg: Dict[str, Any]) -> int:
            if not isinstance(cfg, dict) or not cfg:
                return 0
            score = 0
            if cfg.get("time_config"):
                score += 2
            agents = cfg.get("agent_configs") or []
            if agents:
                score += min(len(agents), 50)
            if _event_config_is_strong(cfg.get("event_config")):
                score += 10
            return score

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

            if len(local_profiles) > len(profiles):
                profiles = local_profiles
                used_dir = d
            if _cfg_score(local_cfg) > _cfg_score(config):
                config = local_cfg
                if not used_dir:
                    used_dir = d

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
                # 旧人设常缺话题字段：读盘时轻量回填，避免 UI「关联话题数」恒为 0
                try:
                    from app.world.oasis_profile_generator import OasisProfileGenerator

                    item["interested_topics"] = OasisProfileGenerator._normalize_interested_topics(
                        item.get("interested_topics"),
                        profession=item.get("profession"),
                        entity_type=item.get("source_entity_type")
                        or item.get("entity_type"),
                        entity_summary=item.get("persona") or item.get("bio"),
                        bio=item.get("bio"),
                    )
                except Exception:
                    item["interested_topics"] = []
            normalized.append(item)

        slice_node_count = 0
        slice_path = os.path.join(shared_dir, "slice.json") if shared_dir else ""
        if slice_path and os.path.isfile(slice_path):
            try:
                with open(slice_path, encoding="utf-8") as f:
                    slice_data = json.load(f)
                slice_node_count = len(slice_data.get("nodes") or [])
            except Exception:
                slice_node_count = 0

        return {
            "decision_id": decision_id,
            "sim_id": sim_id,
            "shared_world_dir": shared_dir if os.path.isdir(shared_dir) else None,
            "assets_dir": used_dir,
            "profiles": normalized,
            "config": config,
            "ready": bool(
                normalized
                and config.get("time_config")
                and (config.get("agent_configs") or [])
                and _event_config_is_strong(config.get("event_config"))
            ),
            "slice_node_count": slice_node_count,
            "has_slice": bool(slice_node_count),
        }

    def start_decision(
        self,
        decision_id: str,
        background: bool = True,
        force: bool = False,
        revive_worker: bool = False,
        only_sim_id: Optional[str] = None,
        only_run_id: Optional[str] = None,
        max_rounds_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """启动决策推演。

        revive_worker=True（Phase C）：即便 status=running 也重起 worker 线程
        （进程重启后 daemon 线程已丢；内部会 skip completed / attach 活 sim）。
        N=1 旁路启动后 registry 已是 running：env 已死时 worker 会重启该 run——预期行为。

        force + only_sim_id/only_run_id：只重置并重跑指定 Run；其余 completed 保持不动。
        force 且未指定：重置全部 Run。
        max_rounds_override：Step2 自定义轮数（可高于 time_config 自动上限）。
        """
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")

        from app.engine.gtv_adapter import is_gtv_deal, start_gtv_deal

        if is_gtv_deal(decision_id):
            return start_gtv_deal(self, decision_id, force=force)

        status = str(dec.get("status") or "").lower()
        target_sim = (only_sim_id or "").strip() or None
        target_run = (only_run_id or "").strip() or None
        scoped = bool(target_sim or target_run)
        rounds_override = (
            int(max_rounds_override)
            if max_rounds_override is not None and int(max_rounds_override) > 0
            else None
        )

        # 已在推演且非 force：默认 attach；revive 时继续往下起 worker
        if status == "running" and not force and not revive_worker:
            snap = self.get_status(decision_id)
            snap["attached"] = True
            snap["decision_id"] = decision_id
            snap["message"] = "推演进行中，已附着现有运行"
            return snap

        # force：停掉目标 run / env，清理日志，重置为 ready
        if force:
            runs = registry.list_runs_for_decision(decision_id) or []
            reset_ids: List[str] = []
            for run in runs:
                if target_sim and str(run.get("sim_id") or "") != target_sim:
                    continue
                if target_run and str(run.get("id") or "") != target_run:
                    continue
                sim_id = run.get("sim_id")
                st = str(run.get("status") or "").lower()
                if sim_id:
                    if st in ("running", "starting"):
                        try:
                            SimulationRunner.stop_simulation(sim_id)
                        except Exception as e:
                            logger.warning(f"force stop {sim_id}: {e}")
                    try:
                        SimulationRunner.close_simulation_env(sim_id)
                    except Exception as e:
                        logger.warning(f"force close-env {sim_id}: {e}")
                    try:
                        SimulationRunner.cleanup_simulation_logs(sim_id)
                    except Exception as e:
                        logger.warning(f"force cleanup logs {sim_id}: {e}")
                registry.update_run(
                    run["id"],
                    status="ready",
                    error=None,
                    started_at=None,
                    finished_at=None,
                    metrics_json=None,
                )
                reset_ids.append(run["id"])
            if scoped and not reset_ids:
                raise ValueError(
                    f"未找到要重跑的 Run（sim_id={target_sim} run_id={target_run}）"
                )
            logger.info(
                f"force restart decision={decision_id}: "
                f"已重置 {len(reset_ids)} 个 run 为 ready"
                + (f" (scoped sim={target_sim} run={target_run})" if scoped else " (全部)")
            )

        registry.update_decision(decision_id, status="running")
        try:
            from app.api.stream import publish_decision_status

            publish_decision_status(decision_id)
        except Exception:
            pass

        if background:
            t = threading.Thread(
                target=self._run_decision_worker,
                args=(decision_id, rounds_override),
                daemon=True,
            )
            t.start()
            return {
                "decision_id": decision_id,
                "status": "running",
                "force_restarted": bool(force),
                "restart_scope": "run" if scoped else "all",
                "only_sim_id": target_sim,
                "only_run_id": target_run,
                "max_rounds": rounds_override,
                "attached": False,
            }

        return self._run_decision_worker(decision_id, rounds_override)

    def _run_decision_worker(
        self,
        decision_id: str,
        max_rounds_override: Optional[int] = None,
    ) -> Dict[str, Any]:
        """串行启动各 Run 对应的真 Simulation。"""
        try:
            dec = registry.get_decision(decision_id)
            max_rounds = int(
                max_rounds_override
                if max_rounds_override is not None
                else (dec.get("max_rounds") or 10)
            )
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

                    # 已在跑且 env 仍活：attach 并等待结束（Phase C revive 不能直接 skip）
                    if st == "running" and SimulationRunner.check_env_alive(sim_id):
                        logger.info(
                            f"run 已在推演，附着等待: run={run['id']} sim={sim_id}"
                        )
                        last_alive_sim = sim_id
                        # 确保 monitor/adopt 已挂上
                        try:
                            SimulationRunner.try_adopt(sim_id)
                        except Exception:
                            pass
                        try:
                            from app.api.stream import publish_decision_status

                            publish_decision_status(decision_id)
                        except Exception:
                            pass
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
                        # fall through to update_run below via duplicated logic — use shared path
                        registry.update_run(
                            run["id"],
                            status=(
                                "completed"
                                if final_status in ("completed", "done", "success", "stopped")
                                else "failed"
                            ),
                            finished_at=_utc_now(),
                            metrics=metrics,
                            error=result.get("error"),
                        )
                        try:
                            from app.api.stream import publish_decision_status

                            publish_decision_status(decision_id)
                        except Exception:
                            pass
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
                            platform="parallel",
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
                    st = (run.get("status") or "").lower()
                    # ready/pending 等均视为未跑完（force 重开后会落到 ready）
                    if st in ("pending", "running", "created", "ready", "starting"):
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

    def reconcile_runs_with_run_state(self, decision_id: str) -> bool:
        """用各 sim 的 run_state.json 校正 registry（N=1 旁路启动也会生效）。

        Returns True 若有写入。
        """
        from app.engine.simulation_runner import SimulationRunner

        changed = False
        try:
            scenarios = registry.list_scenarios(decision_id) or []
        except Exception:
            return False

        any_running = False
        any_incomplete = False
        all_terminal = True
        saw_run = False

        for sc in scenarios:
            for run in registry.list_runs_for_scenario(sc["id"]) or []:
                saw_run = True
                sim_id = run.get("sim_id")
                st = (run.get("status") or "").lower()
                if not sim_id:
                    if st not in ("completed", "failed", "timeout", "stalled"):
                        all_terminal = False
                        any_incomplete = True
                    continue

                rs = SimulationRunner.get_run_state(sim_id)
                if not rs:
                    if st in ("pending", "running", "created"):
                        any_incomplete = True
                        all_terminal = False
                    elif st == "ready":
                        # 未开跑：不算推演进行中
                        all_terminal = False
                    continue

                rv = (
                    rs.runner_status.value
                    if hasattr(rs.runner_status, "value")
                    else str(rs.runner_status)
                ).lower()

                if rv == "running" or rv == "starting":
                    any_running = True
                    all_terminal = False
                    if st != "running":
                        try:
                            registry.update_run(
                                run["id"],
                                status="running",
                                started_at=run.get("started_at") or _utc_now(),
                                error=None,
                            )
                            changed = True
                        except Exception as e:
                            logger.debug(f"reconcile running skip: {e}")
                elif rv in ("completed", "stopped", "failed"):
                    # ready 且从未 started：通常是上次推演残留；但 N=1 旁路可能没写 started_at
                    if st == "ready" and not run.get("started_at"):
                        rounds_done = int(getattr(rs, "current_round", 0) or 0)
                        rounds_total = int(getattr(rs, "total_rounds", 0) or 0)
                        if not (
                            rv in ("completed", "stopped")
                            and rounds_total > 0
                            and rounds_done >= rounds_total
                        ):
                            all_terminal = False
                            continue
                    rounds_done = int(getattr(rs, "current_round", 0) or 0)
                    rounds_total = int(getattr(rs, "total_rounds", 0) or 0)
                    # 轮次跑满后的 stopped 视为 completed（用户停或进程收尾）
                    if (
                        rv == "stopped"
                        and rounds_total > 0
                        and rounds_done >= rounds_total
                    ):
                        mapped = "completed"
                    else:
                        mapped = {
                            "completed": "completed",
                            "stopped": "failed",
                            "failed": "failed",
                        }.get(rv, "completed")
                    if st != mapped:
                        try:
                            registry.update_run(
                                run["id"],
                                status=mapped,
                                finished_at=run.get("finished_at") or _utc_now(),
                            )
                            changed = True
                        except Exception as e:
                            logger.debug(f"reconcile terminal skip: {e}")
                else:
                    if st in ("pending", "running", "created"):
                        any_incomplete = True
                        all_terminal = False
                    elif st == "ready":
                        all_terminal = False

        if not saw_run:
            return changed

        dec = registry.get_decision(decision_id) or {}
        cur = str(dec.get("status") or "").lower()
        want = None
        if any_running:
            want = "running"
        elif all_terminal and not any_incomplete:
            # 全部终态
            want = "completed"
        elif cur == "prepared" and any_running:
            want = "running"

        # 已 prepared 且所有 run_state completed → completed
        if cur in ("prepared", "running", "ready") and all_terminal and not any_running:
            # 确认每个有 sim 的 run 都终态
            all_done = True
            for sc in registry.list_scenarios(decision_id) or []:
                for run in registry.list_runs_for_scenario(sc["id"]) or []:
                    st = (run.get("status") or "").lower()
                    if st in ("pending", "running", "created"):
                        all_done = False
                        break
                    if st == "ready":
                        sid = run.get("sim_id")
                        rs = SimulationRunner.get_run_state(sid) if sid else None
                        if rs and (
                            (
                                rs.runner_status.value
                                if hasattr(rs.runner_status, "value")
                                else str(rs.runner_status)
                            ).lower()
                            in ("completed", "stopped", "failed")
                        ):
                            continue
                        # ready 且无终态 run_state：仍算未完成推演（未开跑）
                        all_done = False
                        break
                if not all_done:
                    break
            if all_done:
                want = "completed"

        if want and want != cur:
            try:
                registry.update_decision(decision_id, status=want)
                changed = True
            except Exception as e:
                logger.debug(f"reconcile decision status skip: {e}")

        return changed

    def get_status(self, decision_id: str) -> Dict[str, Any]:
        # 惰性回收僵尸 preparing
        try:
            from app.progress.janitor import maybe_reclaim_on_read

            maybe_reclaim_on_read(decision_id)
        except Exception:
            pass
        # 用 run_state 校正 registry（修复 N=1 旁路启动不回写）
        try:
            self.reconcile_runs_with_run_state(decision_id)
        except Exception as e:
            logger.debug(f"reconcile_runs_with_run_state: {e}")
        dec = registry.get_decision(decision_id)
        if not dec:
            raise ValueError(f"决策不存在: {decision_id}")
        scenarios = registry.list_scenarios(decision_id)
        matrix = []
        for sc in scenarios:
            runs = registry.list_runs_for_scenario(sc["id"])
            run_rows = []
            for r in runs:
                row = {
                    "run_id": r["id"],
                    "sim_id": r.get("sim_id"),
                    "seed": r.get("seed"),
                    "status": r.get("status"),
                    "error": r.get("error"),
                    "started_at": r.get("started_at"),
                    "finished_at": r.get("finished_at"),
                    "has_metrics": bool(r.get("metrics")),
                    "current_round": 0,
                    "total_rounds": 0,
                }
                sid = r.get("sim_id")
                if sid:
                    try:
                        rs = SimulationRunner.get_run_state(sid)
                        if rs:
                            row["current_round"] = int(
                                getattr(rs, "current_round", 0) or 0
                            )
                            row["total_rounds"] = int(
                                getattr(rs, "total_rounds", 0) or 0
                            )
                    except Exception:
                        pass
                run_rows.append(row)
            matrix.append(
                {
                    "scenario_id": sc["id"],
                    "scenario_name": sc.get("name"),
                    "kind": sc.get("kind"),
                    "color": sc.get("color"),
                    "runs": run_rows,
                }
            )
        total = sum(len(m["runs"]) for m in matrix)
        done = sum(
            1
            for m in matrix
            for r in m["runs"]
            if r["status"] in ("completed", "stalled", "failed", "timeout")
        )
        out = {
            "decision": dec,
            "status": dec.get("status"),
            "matrix": matrix,
            "progress": {"done": done, "total": total},
        }
        prep = _read_prepare_progress(decision_id)
        if prep:
            out["prepare_progress"] = prep
            # 准备中时用细进度覆盖粗矩阵进度展示
            if str(dec.get("status") or "").lower() == "preparing":
                out["stage"] = prep.get("stage")
                out["prepare_percent"] = prep.get("progress")
                out["message"] = prep.get("message")
                out["profile_count"] = prep.get("profile_count")
        # 统一 ProgressEnvelope（含 preparing 时的 profiles_digest）
        try:
            from app.progress.envelope import build_decision_envelope

            out["envelope"] = build_decision_envelope(decision_id, out)
            env_art = (out["envelope"] or {}).get("artifacts") or {}
            if out.get("profile_count") is None and env_art.get("profile_count"):
                out["profile_count"] = env_art["profile_count"]
        except Exception as e:
            logger.debug(f"build_decision_envelope skip: {e}")
        return out

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
        # 场景模板挂到 decision，供前端 Step2/3 分支
        try:
            from app.engine.gtv_adapter import (
                decision_template,
                enrich_gtv_status,
                load_deal_timeline,
            )

            tmpl = decision_template(decision_id)
            if isinstance(status.get("decision"), dict):
                status["decision"]["template"] = tmpl
            status["template"] = tmpl
            if tmpl == "gtv_deal":
                # 双轨：Agent 时间线只读真实产物，禁止用统计剧本回填冒充过程
                timeline = load_deal_timeline(decision_id)
                if timeline:
                    status["deal_timeline"] = timeline
                enrich_gtv_status(decision_id, status)
        except Exception:
            pass
        return status
