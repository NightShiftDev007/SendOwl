"""
OASIS模拟管理器
管理Twitter和Reddit双平台并行模拟
使用预设脚本 + LLM智能生成配置参数
"""

import os
import json
import shutil
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config import Config
from app.utils.logger import get_logger
from app.ontology.zep_entity_reader import ZepEntityReader, FilteredEntities, EntityNode
from app.world.oasis_profile_generator import OasisProfileGenerator, OasisAgentProfile
from app.engine.simulation_config_generator import SimulationConfigGenerator, SimulationParameters
from app.utils.locale import t

logger = get_logger('mirofish.simulation')


class SimulationStatus(str, Enum):
    """模拟状态"""
    CREATED = "created"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"      # 模拟被手动停止
    COMPLETED = "completed"  # 模拟自然完成
    FAILED = "failed"


class PlatformType(str, Enum):
    """平台类型"""
    TWITTER = "twitter"
    REDDIT = "reddit"


@dataclass
class SimulationState:
    """模拟状态"""
    simulation_id: str
    project_id: str
    graph_id: str
    
    # 平台启用状态
    enable_twitter: bool = True
    enable_reddit: bool = True
    
    # 状态
    status: SimulationStatus = SimulationStatus.CREATED
    
    # 准备阶段数据
    entities_count: int = 0
    profiles_count: int = 0
    entity_types: List[str] = field(default_factory=list)
    
    # 配置生成信息
    config_generated: bool = False
    config_reasoning: str = ""
    
    # 运行时数据
    current_round: int = 0
    twitter_status: str = "not_started"
    reddit_status: str = "not_started"
    
    # 时间戳
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # 错误信息
    error: Optional[str] = None

    # N=1 prepare 可恢复：刷新后续订 task SSE
    prepare_task_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """完整状态字典（内部使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "enable_twitter": self.enable_twitter,
            "enable_reddit": self.enable_reddit,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "config_reasoning": self.config_reasoning,
            "current_round": self.current_round,
            "twitter_status": self.twitter_status,
            "reddit_status": self.reddit_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "prepare_task_id": self.prepare_task_id,
        }
    
    def to_simple_dict(self) -> Dict[str, Any]:
        """简化状态字典（API返回使用）"""
        return {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "status": self.status.value,
            "entities_count": self.entities_count,
            "profiles_count": self.profiles_count,
            "entity_types": self.entity_types,
            "config_generated": self.config_generated,
            "error": self.error,
            "prepare_task_id": self.prepare_task_id,
        }


class SimulationManager:
    """
    模拟管理器
    
    核心功能：
    1. 从Zep图谱读取实体并过滤
    2. 生成OASIS Agent Profile
    3. 使用LLM智能生成模拟配置参数
    4. 准备预设脚本所需的所有文件
    """
    
    # 模拟数据存储目录（backend/uploads/runs）
    SIMULATION_DATA_DIR = Config.OASIS_SIMULATION_DATA_DIR
    
    def __init__(self):
        # 确保目录存在
        os.makedirs(self.SIMULATION_DATA_DIR, exist_ok=True)
        
        # 内存中的模拟状态缓存
        self._simulations: Dict[str, SimulationState] = {}
    
    def _get_simulation_dir(self, simulation_id: str) -> str:
        """获取模拟数据目录"""
        sim_dir = os.path.join(self.SIMULATION_DATA_DIR, simulation_id)
        os.makedirs(sim_dir, exist_ok=True)
        return sim_dir
    
    def _save_simulation_state(self, state: SimulationState):
        """保存模拟状态到文件"""
        sim_dir = self._get_simulation_dir(state.simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        state.updated_at = datetime.now().isoformat()
        
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        
        self._simulations[state.simulation_id] = state
    
    def _load_simulation_state(self, simulation_id: str) -> Optional[SimulationState]:
        """从文件加载模拟状态"""
        if simulation_id in self._simulations:
            return self._simulations[simulation_id]
        
        sim_dir = self._get_simulation_dir(simulation_id)
        state_file = os.path.join(sim_dir, "state.json")
        
        if not os.path.exists(state_file):
            return None
        
        with open(state_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=data.get("project_id", ""),
            graph_id=data.get("graph_id", ""),
            enable_twitter=data.get("enable_twitter", True),
            enable_reddit=data.get("enable_reddit", True),
            status=SimulationStatus(data.get("status", "created")),
            entities_count=data.get("entities_count", 0),
            profiles_count=data.get("profiles_count", 0),
            entity_types=data.get("entity_types", []),
            config_generated=data.get("config_generated", False),
            config_reasoning=data.get("config_reasoning", ""),
            current_round=data.get("current_round", 0),
            twitter_status=data.get("twitter_status", "not_started"),
            reddit_status=data.get("reddit_status", "not_started"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
            prepare_task_id=data.get("prepare_task_id"),
        )
        
        self._simulations[simulation_id] = state
        return state
    
    def create_simulation(
        self,
        project_id: str,
        graph_id: str,
        enable_twitter: bool = True,
        enable_reddit: bool = True,
    ) -> SimulationState:
        """
        创建新的模拟
        
        Args:
            project_id: 项目ID
            graph_id: Zep图谱ID
            enable_twitter: 是否启用Twitter模拟
            enable_reddit: 是否启用Reddit模拟
            
        Returns:
            SimulationState
        """
        import uuid
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=enable_twitter,
            enable_reddit=enable_reddit,
            status=SimulationStatus.CREATED,
        )
        
        self._save_simulation_state(state)
        logger.info(f"创建模拟: {simulation_id}, project={project_id}, graph={graph_id}")
        
        return state
    
    def prepare_simulation(
        self,
        simulation_id: str,
        simulation_requirement: str,
        document_text: str,
        defined_entity_types: Optional[List[str]] = None,
        use_llm_for_profiles: bool = True,
        progress_callback: Optional[callable] = None,
        parallel_profile_count: Optional[int] = None,
        stage: str = "all",
    ) -> SimulationState:
        """
        准备模拟环境（全程自动化）

        stage:
          - all: 人设 + 平台配置 + 事件配置
          - profiles: 仅人设
          - platform_config: 仅时间/Agent 活跃配置
          - event_config: 仅初始激活编排
        """
        stage = (stage or "all").strip().lower()
        if stage not in ("all", "profiles", "platform_config", "event_config"):
            raise ValueError(f"不支持的 prepare stage: {stage}")

        if parallel_profile_count is None or int(parallel_profile_count) <= 0:
            parallel_profile_count = Config.llm_parallel_workers()
        else:
            parallel_profile_count = max(1, int(parallel_profile_count))

        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        try:
            state.status = SimulationStatus.PREPARING
            state.error = None
            self._save_simulation_state(state)
            
            sim_dir = self._get_simulation_dir(simulation_id)

            # Phase C：stage=all 时按磁盘产物细化跳过（有多少跳多少）
            if stage == "all":
                profiles_path = os.path.join(sim_dir, "reddit_profiles.json")
                config_path_early = os.path.join(sim_dir, "simulation_config.json")
                profiles_n = 0
                if os.path.isfile(profiles_path):
                    try:
                        with open(profiles_path, encoding="utf-8") as f:
                            raw = json.load(f)
                        if isinstance(raw, list):
                            profiles_n = len(raw)
                    except Exception:
                        profiles_n = 0
                config_ready = False
                cfg0: Dict[str, Any] = {}
                if os.path.isfile(config_path_early):
                    try:
                        with open(config_path_early, encoding="utf-8") as f:
                            cfg0 = json.load(f) or {}
                        from app.engine.scenario_runner import _event_config_is_strong

                        # 弱 event_config 不算就绪，否则复用后又被 prepared 门槛打回，死循环
                        config_ready = bool(
                            cfg0.get("time_config")
                            and (cfg0.get("agent_configs") or [])
                            and _event_config_is_strong(cfg0.get("event_config"))
                        )
                    except Exception:
                        config_ready = False
                        cfg0 = {}
                agents_n = len(cfg0.get("agent_configs") or [])
                # 人设须达配置规模（禁止 1/19 残缺被当成可 resume）
                profiles_complete = profiles_n > 0 and (
                    agents_n <= 0 or profiles_n >= max(2, int(agents_n * 0.8))
                )
                if profiles_complete and config_ready:
                    logger.info(
                        f"resume prepare: profiles+config 已齐，直接 finalize sim={simulation_id}"
                    )
                    if progress_callback:
                        progress_callback("generating_config", 100, "复用已有配置", current=3, total=3)
                    return self.finalize_prepare(simulation_id)
                if profiles_complete and not config_ready:
                    logger.info(
                        f"resume prepare: 人设已有({profiles_n})，仅生成配置 sim={simulation_id}"
                    )
                    # 下面仍走 all，但跳过 profiles 段
                    stage = "all_skip_profiles"
                elif profiles_n > 0 and not profiles_complete:
                    logger.info(
                        f"resume prepare: 人设残缺({profiles_n}/{agents_n or '?'})，重新生成 "
                        f"sim={simulation_id}"
                    )

            # 补全 graph_id（多方案 sim 的 state 常为空）
            graph_id = self._resolve_graph_id(state)
            if graph_id and not state.graph_id:
                state.graph_id = graph_id
                self._save_simulation_state(state)

            # ========== 阶段1: 读取实体（Zep 或本地） ==========
            if progress_callback:
                progress_callback("reading", 0, t('progress.connectingZepGraph'))

            filtered = None
            # 分阶段重试 / resume 跳过人设：优先本地实体，避免空 graph_id 打 Zep
            if stage in ("event_config", "platform_config", "all_skip_profiles"):
                local_entities = self._entities_from_local(simulation_id)
                if local_entities:
                    types = {e.get_entity_type() or "Unknown" for e in local_entities}
                    filtered = FilteredEntities(
                        entities=local_entities,
                        entity_types=types,
                        total_count=len(local_entities),
                        filtered_count=len(local_entities),
                    )
                    logger.info(
                        f"分阶段重试使用本地实体: stage={stage}, count={len(local_entities)}"
                    )

            if filtered is None:
                if not graph_id:
                    raise RuntimeError(
                        "模拟缺少 graph_id，无法从 Zep 读取实体。"
                        "请从本体重新「进入环境搭建」，或先完成人设/配置后再分阶段重试。"
                    )
                reader = ZepEntityReader()
                if progress_callback:
                    progress_callback("reading", 30, t('progress.readingNodeData'))
                filtered = reader.filter_defined_entities(
                    graph_id=graph_id,
                    defined_entity_types=defined_entity_types,
                    enrich_with_edges=True,
                )
            
            state.entities_count = filtered.filtered_count
            state.entity_types = list(filtered.entity_types)
            # 尽早落盘，刷新/realtime 才能读到预期总数
            self._save_simulation_state(state)
            
            if progress_callback:
                progress_callback(
                    "reading", 100,
                    t('progress.readingComplete', count=filtered.filtered_count),
                    current=filtered.filtered_count,
                    total=filtered.filtered_count
                )
            
            if filtered.filtered_count == 0:
                state.status = SimulationStatus.FAILED
                state.error = "没有找到符合条件的实体，请检查图谱是否正确构建"
                self._save_simulation_state(state)
                return state
            
            # ========== 阶段2: 生成Agent Profile ==========
            if stage in ("all", "profiles"):
                total_entities = len(filtered.entities)
                
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 0,
                        t('progress.startGenerating'),
                        current=0,
                        total=total_entities
                    )
                
                # 传入graph_id以启用Zep检索功能，获取更丰富的上下文
                generator = OasisProfileGenerator(graph_id=graph_id or state.graph_id)
                
                def profile_progress(current, total, msg):
                    # Cast Sheet 后 total 可能下调：同步 entities_count 供 realtime/SSE
                    try:
                        t_int = int(total or 0)
                        if t_int > 0 and (
                            not state.entities_count or t_int < state.entities_count
                        ):
                            if state.entities_count != t_int:
                                state.entities_count = t_int
                                self._save_simulation_state(state)
                    except Exception:
                        pass
                    if progress_callback:
                        progress_callback(
                            "generating_profiles", 
                            int(current / total * 100) if total else 0, 
                            msg,
                            current=current,
                            total=total,
                            item_name=msg
                        )
                
                # 设置实时保存的文件路径（优先使用 Reddit JSON 格式）
                realtime_output_path = None
                realtime_platform = "reddit"
                if state.enable_reddit:
                    realtime_output_path = os.path.join(sim_dir, "reddit_profiles.json")
                    realtime_platform = "reddit"
                elif state.enable_twitter:
                    realtime_output_path = os.path.join(sim_dir, "twitter_profiles.csv")
                    realtime_platform = "twitter"
                
                profiles = generator.generate_profiles_from_entities(
                    entities=filtered.entities,
                    use_llm=use_llm_for_profiles,
                    progress_callback=profile_progress,
                    graph_id=graph_id or state.graph_id,
                    parallel_count=parallel_profile_count,
                    realtime_output_path=realtime_output_path,
                    output_platform=realtime_platform,
                    simulation_requirement=simulation_requirement,
                )

                # Cast Sheet 裁剪后，后续配置阶段只使用实际生成了人设的实体
                kept_uuids = {
                    p.source_entity_uuid for p in profiles if p.source_entity_uuid
                }
                if kept_uuids and len(kept_uuids) < len(filtered.entities):
                    filtered.entities = [
                        e for e in filtered.entities if e.uuid in kept_uuids
                    ]
                    filtered.filtered_count = len(filtered.entities)
                    filtered.entity_types = {
                        e.get_entity_type() or "Unknown" for e in filtered.entities
                    }
                    state.entities_count = filtered.filtered_count
                    state.entity_types = list(filtered.entity_types)
                    logger.info(
                        f"Cast Sheet 裁剪后实体数: {filtered.filtered_count} "
                        f"(excluded={len(getattr(generator, 'last_excluded', []) or [])})"
                    )

                # 落盘分角/裁剪元数据，供前端或排查
                try:
                    cast_meta = {
                        "cast_theme": (getattr(generator, "last_cast_sheet", None) or {}).get(
                            "cast_theme"
                        ),
                        "excluded": getattr(generator, "last_excluded", []) or [],
                        "profiles_count": len(profiles),
                    }
                    with open(
                        os.path.join(sim_dir, "cast_sheet_meta.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump(cast_meta, f, ensure_ascii=False, indent=2)
                except Exception as meta_err:
                    logger.warning(f"写入 cast_sheet_meta.json 失败: {meta_err}")
                
                state.profiles_count = len(profiles)
                
                # 保存Profile文件（注意：Twitter使用CSV格式，Reddit使用JSON格式）
                # Reddit 已经在生成过程中实时保存了，这里再保存一次确保完整性
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 95,
                        t('progress.savingProfiles'),
                        current=total_entities,
                        total=total_entities
                    )
                
                if state.enable_reddit:
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "reddit_profiles.json"),
                        platform="reddit"
                    )
                
                if state.enable_twitter:
                    # Twitter使用CSV格式！这是OASIS的要求
                    generator.save_profiles(
                        profiles=profiles,
                        file_path=os.path.join(sim_dir, "twitter_profiles.csv"),
                        platform="twitter"
                    )
                
                if progress_callback:
                    progress_callback(
                        "generating_profiles", 100,
                        t('progress.profilesComplete', count=len(profiles)),
                        current=len(profiles),
                        total=len(profiles)
                    )

                if stage == "profiles":
                    state = self.finalize_prepare(simulation_id)
                    # 仅人设阶段：finalize 不再因「有人设」升 READY，这里显式收口
                    if state.profiles_count > 0 and state.status == SimulationStatus.PREPARING:
                        state.status = SimulationStatus.READY
                        state.error = None
                        self._save_simulation_state(state)
                    return state
            
            # ========== 阶段3: LLM智能生成模拟配置 ==========
            config_generator = SimulationConfigGenerator()
            config_path = os.path.join(sim_dir, "simulation_config.json")

            if stage == "event_config":
                existing = self.get_simulation_config(simulation_id)
                if not existing or not existing.get("agent_configs"):
                    raise RuntimeError("请先完成双平台配置（时间/Agent），再单独重试初始激活编排")
                if progress_callback:
                    progress_callback(
                        "generating_config", 20,
                        t('progress.generatingEventConfig'),
                        current=1,
                        total=2,
                    )
                merged = config_generator.regenerate_event_config(
                    existing_config=existing,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    entities=filtered.entities,
                )
                if progress_callback:
                    progress_callback(
                        "generating_config", 90,
                        t('progress.savingConfigFiles'),
                        current=2,
                        total=2,
                    )
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                return self.finalize_prepare(simulation_id)

            if stage == "platform_config":
                existing = self.get_simulation_config(simulation_id) or {
                    "simulation_id": simulation_id,
                    "project_id": state.project_id,
                    "graph_id": state.graph_id,
                    "event_config": {"initial_posts": [], "hot_topics": [], "narrative_direction": ""},
                }
                if progress_callback:
                    progress_callback(
                        "generating_config", 10,
                        t('progress.callingLLMConfig'),
                        current=0,
                        total=2,
                    )

                def _plat_progress(step, total, message):
                    if progress_callback:
                        pct = int(10 + 80 * step / max(total, 1))
                        progress_callback(
                            "generating_config",
                            pct,
                            message,
                            current=step,
                            total=total,
                        )

                merged = config_generator.regenerate_platform_config(
                    existing_config=existing,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    entities=filtered.entities,
                    progress_callback=_plat_progress,
                )
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                if progress_callback:
                    progress_callback(
                        "generating_config", 100,
                        t('progress.configComplete'),
                        current=2,
                        total=2,
                    )
                return self.finalize_prepare(simulation_id)

            # stage == all
            if progress_callback:
                progress_callback(
                    "generating_config", 0,
                    t('progress.analyzingRequirements'),
                    current=0,
                    total=3
                )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 30,
                    t('progress.callingLLMConfig'),
                    current=1,
                    total=3
                )
            
            sim_params = config_generator.generate_config(
                simulation_id=simulation_id,
                project_id=state.project_id,
                graph_id=state.graph_id,
                simulation_requirement=simulation_requirement,
                document_text=document_text,
                entities=filtered.entities,
                enable_twitter=state.enable_twitter,
                enable_reddit=state.enable_reddit
            )
            
            if progress_callback:
                progress_callback(
                    "generating_config", 70,
                    t('progress.savingConfigFiles'),
                    current=2,
                    total=3
                )
            
            # 保存配置文件
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(sim_params.to_json())
            
            if progress_callback:
                progress_callback(
                    "generating_config", 100,
                    t('progress.configComplete'),
                    current=3,
                    total=3
                )
            
            # 注意：运行脚本保留在 backend/scripts/ 目录，不再复制到模拟目录
            # 启动模拟时，simulation_runner 会从 scripts/ 目录运行脚本
            
            state = self.finalize_prepare(simulation_id)
            logger.info(
                f"模拟准备完成: {simulation_id}, "
                f"entities={state.entities_count}, profiles={state.profiles_count}"
            )
            return state
            
        except Exception as e:
            logger.error(f"模拟准备失败: {simulation_id}, error={str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            state.status = SimulationStatus.FAILED
            state.error = str(e)
            self._save_simulation_state(state)
            raise
    def get_simulation(self, simulation_id: str) -> Optional[SimulationState]:
        """获取模拟状态"""
        return self._load_simulation_state(simulation_id)
    
    def list_simulations(self, project_id: Optional[str] = None) -> List[SimulationState]:
        """列出所有模拟"""
        simulations = []
        
        if os.path.exists(self.SIMULATION_DATA_DIR):
            for sim_id in os.listdir(self.SIMULATION_DATA_DIR):
                # 跳过隐藏文件（如 .DS_Store）和非目录文件
                sim_path = os.path.join(self.SIMULATION_DATA_DIR, sim_id)
                if sim_id.startswith('.') or not os.path.isdir(sim_path):
                    continue
                
                state = self._load_simulation_state(sim_id)
                if state:
                    if project_id is None or state.project_id == project_id:
                        simulations.append(state)
        
        return simulations
    
    def get_profiles(self, simulation_id: str, platform: str = "reddit") -> List[Dict[str, Any]]:
        """获取模拟的Agent Profile"""
        state = self._load_simulation_state(simulation_id)
        if not state:
            raise ValueError(f"模拟不存在: {simulation_id}")
        
        sim_dir = self._get_simulation_dir(simulation_id)
        profile_path = os.path.join(sim_dir, f"{platform}_profiles.json")
        
        if not os.path.exists(profile_path):
            return []
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_simulation_config(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """获取模拟配置"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return None
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_run_instructions(self, simulation_id: str) -> Dict[str, str]:
        """获取运行说明"""
        sim_dir = self._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        return {
            "simulation_dir": sim_dir,
            "scripts_dir": scripts_dir,
            "config_file": config_path,
            "commands": {
                "twitter": f"python {scripts_dir}/run_twitter_simulation.py --config {config_path}",
                "reddit": f"python {scripts_dir}/run_reddit_simulation.py --config {config_path}",
                "parallel": f"python {scripts_dir}/run_parallel_simulation.py --config {config_path}",
            },
            "instructions": (
                f"1. 激活conda环境: conda activate MiroFish\n"
                f"2. 运行模拟 (脚本位于 {scripts_dir}):\n"
                f"   - 单独运行Twitter: python {scripts_dir}/run_twitter_simulation.py --config {config_path}\n"
                f"   - 单独运行Reddit: python {scripts_dir}/run_reddit_simulation.py --config {config_path}\n"
                f"   - 并行运行双平台: python {scripts_dir}/run_parallel_simulation.py --config {config_path}"
            )
        }

    def _entities_from_local(
        self, simulation_id: str, existing_config: Optional[Dict[str, Any]] = None
    ) -> List[EntityNode]:
        """从本地 agent_configs / profiles 构造实体，供分阶段重试在无 graph_id 时使用。"""
        entities: List[EntityNode] = []
        cfg = existing_config if existing_config is not None else self.get_simulation_config(simulation_id)
        cfg = cfg or {}
        for row in cfg.get("agent_configs") or []:
            etype = row.get("entity_type") or "Unknown"
            name = row.get("entity_name") or f"agent_{row.get('agent_id', 0)}"
            uuid = row.get("entity_uuid") or f"local-{row.get('agent_id', 0)}"
            entities.append(
                EntityNode(
                    uuid=str(uuid),
                    name=str(name),
                    labels=[str(etype)],
                    summary=str(row.get("summary") or ""),
                    attributes={"entity_type": etype},
                )
            )
        if entities:
            return entities

        try:
            profiles = self.get_profiles(simulation_id, platform="reddit")
        except Exception:
            profiles = []
        for i, p in enumerate(profiles or []):
            etype = p.get("source_entity_type") or p.get("profession") or "Unknown"
            name = p.get("name") or p.get("username") or f"agent_{i}"
            uuid = p.get("source_entity_uuid") or f"local-profile-{i}"
            entities.append(
                EntityNode(
                    uuid=str(uuid),
                    name=str(name),
                    labels=[str(etype)],
                    summary=str(p.get("bio") or p.get("persona") or ""),
                    attributes={"entity_type": etype},
                )
            )
        return entities

    def _resolve_graph_id(self, state: SimulationState) -> str:
        """尽量补全 graph_id（多方案 materialize 常漏写）。"""
        gid = (state.graph_id or "").strip()
        if gid:
            return gid
        cfg = self.get_simulation_config(state.simulation_id) or {}
        gid = (cfg.get("graph_id") or "").strip()
        if gid:
            state.graph_id = gid
            return gid
        # 从决策/本体回填
        project_id = (state.project_id or cfg.get("project_id") or "").strip()
        if not project_id:
            # 用 sim_id 反查决策
            try:
                from app.ontology import registry

                registry.init_schema()
                for dec in registry.list_decisions() or []:
                    for run in registry.list_runs_for_decision(dec["id"]) or []:
                        if run.get("sim_id") == state.simulation_id:
                            project_id = dec["id"]
                            state.project_id = project_id
                            break
                    if project_id:
                        break
            except Exception as e:
                logger.warning(f"按 sim_id 反查决策失败: {e}")
        if project_id.startswith("dec_"):
            try:
                from app.ontology import registry

                registry.init_schema()
                dec = registry.get_decision(project_id) or {}
                ont_id = dec.get("ontology_id")
                if ont_id:
                    ont = registry.get_ontology(ont_id) or {}
                    gid = (ont.get("graph_id") or "").strip()
                    if gid:
                        state.graph_id = gid
                        state.project_id = project_id
                        return gid
            except Exception as e:
                logger.warning(f"从决策回填 graph_id 失败: {e}")
        elif project_id.startswith("ont_"):
            try:
                from app.ontology import registry

                registry.init_schema()
                ont = registry.get_ontology(project_id) or {}
                gid = (ont.get("graph_id") or "").strip()
                if gid:
                    state.graph_id = gid
                    return gid
            except Exception as e:
                logger.warning(f"从本体回填 graph_id 失败: {e}")
        return ""

    def finalize_prepare(self, simulation_id: str) -> SimulationState:
        """
        prepare 收口：以磁盘为准回写摘要字段到 state.json。

        覆盖 entities_count / profiles_count / config_generated / graph_id /
        project_id / entity_types / status，避免多路径各自漏写。
        """
        sim_dir = self._get_simulation_dir(simulation_id)
        cfg = self.get_simulation_config(simulation_id) or {}
        state = self._load_simulation_state(simulation_id)

        if not state:
            state = SimulationState(
                simulation_id=simulation_id,
                project_id=str(cfg.get("project_id") or ""),
                graph_id=str(cfg.get("graph_id") or ""),
                status=SimulationStatus.CREATED,
            )

        before = (
            state.entities_count,
            state.profiles_count,
            state.config_generated,
            state.graph_id,
            state.project_id,
            state.status,
            tuple(state.entity_types or []),
        )

        # ---- profiles / entities ----
        profiles_n = 0
        reddit_path = os.path.join(sim_dir, "reddit_profiles.json")
        twitter_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.isfile(reddit_path):
            try:
                with open(reddit_path, encoding="utf-8") as f:
                    plist = json.load(f)
                if isinstance(plist, list):
                    profiles_n = len(plist)
            except Exception as e:
                logger.warning(f"finalize_prepare 读取 reddit profiles 失败: {e}")
        if profiles_n == 0 and os.path.isfile(twitter_path):
            try:
                import csv

                with open(twitter_path, encoding="utf-8", newline="") as f:
                    profiles_n = max(0, sum(1 for _ in csv.DictReader(f)))
            except Exception as e:
                logger.warning(f"finalize_prepare 读取 twitter profiles 失败: {e}")

        if profiles_n > 0:
            state.profiles_count = profiles_n
            if not state.entities_count or state.entities_count < profiles_n:
                state.entities_count = profiles_n

        # ---- config 摘要 ----
        agents = cfg.get("agent_configs") or []
        if cfg.get("time_config") and agents:
            state.config_generated = True
            reasoning = cfg.get("generation_reasoning")
            if reasoning:
                state.config_reasoning = str(reasoning)
            if not state.entity_types:
                types = sorted(
                    {
                        str(a.get("entity_type") or "").strip()
                        for a in agents
                        if a.get("entity_type")
                    }
                )
                if types:
                    state.entity_types = types

        if cfg.get("project_id") and not (state.project_id or "").strip():
            state.project_id = str(cfg["project_id"])

        # ---- graph_id / project_id ----
        gid = self._resolve_graph_id(state)
        if gid:
            state.graph_id = gid

        # 回写到 config，避免下次再丢
        cfg_path = os.path.join(sim_dir, "simulation_config.json")
        if os.path.isfile(cfg_path) and (gid or state.project_id):
            try:
                dirty = False
                if gid and not (cfg.get("graph_id") or "").strip():
                    cfg["graph_id"] = gid
                    dirty = True
                if state.project_id and not (cfg.get("project_id") or "").strip():
                    cfg["project_id"] = state.project_id
                    dirty = True
                if dirty:
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"finalize_prepare 回写 config 失败: {e}")

        # ---- status ----
        # 仅配置齐套才从 PREPARING→READY；禁止「有 1 条人设就算完成」
        # （profiles-only 分阶段重试：config 尚未齐时保持 PREPARING，由上层继续跑配置）
        agents_n = len(agents)
        profiles_ok = profiles_n > 0 and (
            agents_n <= 0 or profiles_n >= max(2, int(agents_n * 0.8))
        )
        if state.config_generated and profiles_ok:
            if state.status in (
                SimulationStatus.CREATED,
                SimulationStatus.PREPARING,
                SimulationStatus.READY,
            ):
                state.status = SimulationStatus.READY
                state.error = None
        elif state.config_generated and not profiles_ok and profiles_n > 0:
            # 配置在、人设残缺：保持/回到 PREPARING，避免 already_prepared 误判
            if state.status == SimulationStatus.READY:
                state.status = SimulationStatus.PREPARING

        self._save_simulation_state(state)
        after = (
            state.entities_count,
            state.profiles_count,
            state.config_generated,
            state.graph_id,
            state.project_id,
            state.status,
            tuple(state.entity_types or []),
        )
        msg = (
            f"finalize_prepare: {simulation_id} status={state.status.value} "
            f"entities={state.entities_count} profiles={state.profiles_count} "
            f"config_generated={state.config_generated} graph_id={state.graph_id!r}"
        )
        if before != after:
            logger.info(msg)
        else:
            logger.debug(msg)
        return state

    def sync_prepare_to_registry(self, state: SimulationState) -> None:
        """将 prepare 摘要同步到 meta.db（runs / decisions）。"""
        try:
            from app.ontology import registry

            registry.init_schema()
        except Exception as e:
            logger.warning(f"sync_prepare_to_registry: registry 不可用: {e}")
            return

        sim_id = state.simulation_id
        run_dir = self._get_simulation_dir(sim_id)
        decision_id = None
        run_id = None

        try:
            for dec in registry.list_decisions() or []:
                for run in registry.list_runs_for_decision(dec["id"]) or []:
                    if run.get("sim_id") == sim_id:
                        decision_id = dec["id"]
                        run_id = run["id"]
                        break
                if run_id:
                    break
        except Exception as e:
            logger.warning(f"sync_prepare_to_registry: 反查 run 失败: {e}")
            return

        if not run_id:
            return

        try:
            # 仅在 prepare 成功（state=ready）时把 run 标为 ready；
            # 已 running/completed/stopped 的 run 只补 run_dir，避免冲掉终态。
            if state.status == SimulationStatus.READY:
                registry.update_run(run_id, status="ready", run_dir=run_dir)
            else:
                registry.update_run(run_id, run_dir=run_dir)
        except Exception as e:
            logger.warning(f"sync_prepare_to_registry: update_run 失败: {e}")
            return

        if not decision_id:
            return

        try:
            runs = registry.list_runs_for_decision(decision_id) or []
            done_statuses = {
                "ready",
                "running",
                "completed",
                "stopped",
                "failed",
                "done",
            }
            if runs and all((r.get("status") or "") in done_statuses for r in runs):
                # 弱初始激活不得解锁 Step3：与 scenario_runner 门槛一致
                try:
                    from app.engine.scenario_runner import (
                        _event_config_is_strong,
                        propagate_strong_event_config,
                    )

                    cfg = self.get_simulation_config(sim_id) or {}
                    if not _event_config_is_strong(cfg.get("event_config")):
                        registry.update_decision(decision_id, status="prepare_failed")
                        logger.warning(
                            f"sync_prepare_to_registry: decision {decision_id} "
                            f"event_config 弱 → prepare_failed"
                        )
                        return
                    # 单 sim 修好后，把强编排补到共享 base 与其余弱 sim，
                    # 否则多方案里只有当前 sim 达标
                    propagate_strong_event_config(
                        decision_id, cfg.get("event_config"), source_sim_id=sim_id
                    )
                except Exception as e:
                    logger.debug(f"sync_prepare_to_registry event check skip: {e}")
                registry.update_decision(decision_id, status="prepared")
                logger.info(
                    f"sync_prepare_to_registry: decision {decision_id} -> prepared"
                )
        except Exception as e:
            logger.warning(f"sync_prepare_to_registry: update_decision 失败: {e}")
