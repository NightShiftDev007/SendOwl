"""
图谱构建服务
接口2：使用Zep API构建Standalone Graph
"""

import os
import uuid
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from zep_cloud.client import Zep
from zep_cloud import EpisodeData, EntityEdgeSourceTarget

from app.config import Config
from app.models.task import TaskManager, TaskStatus
from app.utils.zep_paging import fetch_all_nodes, fetch_all_edges
from app.ontology.text_processor import TextProcessor
from app.utils.locale import t, get_locale, set_locale
from app.utils.logger import get_logger

logger = get_logger("mirofish.graph_builder")


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    图谱构建服务
    负责调用Zep API构建知识图谱
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        
        self.client = Zep(api_key=self.api_key)
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        异步构建图谱
        
        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量
            
        Returns:
            任务ID
        """
        # 创建任务（metadata 带 ontology_id，供 SSE 同帧附带 graph 快照）
        metadata = {
            "graph_name": graph_name,
            "chunk_size": chunk_size,
            "text_length": len(text),
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata=metadata,
        )
        
        # Capture locale before spawning background thread
        current_locale = get_locale()

        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size, current_locale)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        locale: str = 'zh',
        *,
        resume: bool = False,
    ):
        """图谱构建工作线程（支持 Phase C 断点续传）。"""
        set_locale(locale)
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message=t('progress.startBuildingGraph')
            )

            detail = {}
            existing = self.task_manager.get_task(task_id)
            if existing and isinstance(getattr(existing, "progress_detail", None), dict):
                detail = dict(existing.progress_detail or {})
            result0 = (getattr(existing, "result", None) or {}) if existing else {}

            graph_id = None
            start_chunk = 0
            episode_uuids: List[str] = []
            phase = "appending"

            if resume:
                graph_id = (
                    detail.get("graph_id")
                    or result0.get("graph_id")
                )
                phase = str(detail.get("phase") or "appending")
                start_chunk = int(detail.get("next_chunk_index") or 0)
                episode_uuids = list(detail.get("episode_uuids") or [])
                if not graph_id:
                    self.task_manager.fail_task(
                        task_id,
                        "recovery: 无 graph 检查点，请重新建图",
                    )
                    return
                logger.info(
                    f"resume graph: task={task_id} graph={graph_id} "
                    f"phase={phase} next_chunk={start_chunk}"
                )
            
            # 1. 创建图谱（resume 复用）
            if not graph_id:
                graph_id = self.create_graph(graph_name)
                self.task_manager.update_task(
                    task_id,
                    progress=10,
                    message=t('progress.graphCreated', graphId=graph_id),
                    result={"graph_id": graph_id},
                    progress_detail={
                        "graph_id": graph_id,
                        "phase": "appending",
                        "next_chunk_index": 0,
                        "total_chunks": 0,
                        "episode_uuids": [],
                    },
                )
                # 2. 设置本体
                self.set_ontology(graph_id, ontology)
                self.task_manager.update_task(
                    task_id,
                    progress=15,
                    message=t('progress.ontologySet')
                )
            else:
                self.task_manager.update_task(
                    task_id,
                    progress=15,
                    message=t('progress.graphCreated', graphId=graph_id),
                    result={"graph_id": graph_id},
                )
            
            # 3. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=t('progress.textSplit', count=total_chunks)
            )

            def _save_checkpoint(cp: Dict[str, Any]):
                self.task_manager.update_task(
                    task_id,
                    progress_detail=cp,
                    result={"graph_id": cp.get("graph_id") or graph_id},
                )

            # 4. 分批发送（waiting 阶段 resume：跳过 append）
            if phase != "waiting":
                episode_uuids = self.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size,
                    lambda msg, prog: self.task_manager.update_task(
                        task_id,
                        progress=20 + int(prog * 0.4),  # 20-60%
                        message=msg
                    ),
                    start_chunk_index=start_chunk,
                    existing_episode_uuids=episode_uuids,
                    checkpoint_callback=_save_checkpoint,
                )
            
            # 进入 waiting 阶段检查点
            _save_checkpoint({
                "graph_id": graph_id,
                "phase": "waiting",
                "next_chunk_index": total_chunks,
                "total_chunks": total_chunks,
                "episode_uuids": list(episode_uuids),
            })

            # 5. 等待Zep处理完成
            self.task_manager.update_task(
                task_id,
                progress=60,
                message=t('progress.waitingZepProcess')
            )
            
            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg
                )
            )
            
            # 6. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message=t('progress.fetchingGraphInfo')
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)

    def resume_graph_build(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
    ) -> bool:
        """Phase C：复用原 task_id，从检查点续传建图。"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return False
        detail = getattr(task, "progress_detail", None) or {}
        result = getattr(task, "result", None) or {}
        if not (detail.get("graph_id") or result.get("graph_id")):
            return False

        self.task_manager.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            message="recovery: 从断点续传建图",
        )
        current_locale = get_locale()
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(
                task_id,
                text,
                ontology,
                graph_name,
                chunk_size,
                chunk_overlap,
                batch_size,
                current_locale,
            ),
            kwargs={"resume": True},
            daemon=True,
            name=f"resume-graph-{task_id}",
        )
        thread.start()
        return True
    
    def create_graph(self, name: str) -> str:
        """创建Zep图谱（公开方法）"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        
        self.client.graph.create(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph"
        )
        
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        import warnings
        from typing import Optional
        from pydantic import Field
        from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel
        
        # 抑制 Pydantic v2 关于 Field(default=None) 的警告
        # 这是 Zep SDK 要求的用法，警告来自动态类创建，可以安全忽略
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        # Zep 保留名称，不能作为属性名
        RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}
        
        def safe_attr_name(attr_name: str) -> str:
            """将保留名称转换为安全名称"""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # 动态创建实体类型
        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            
            # 创建属性字典和类型注解（Pydantic v2 需要）
            attrs = {"__doc__": description}
            annotations = {}
            
            for attr_def in entity_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # 使用安全名称
                attr_desc = attr_def.get("description", attr_name)
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[EntityText]  # 类型注解
            
            attrs["__annotations__"] = annotations
            
            # 动态创建类
            entity_class = type(name, (EntityModel,), attrs)
            entity_class.__doc__ = description
            entity_types[name] = entity_class
        
        # 动态创建边类型
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            
            # 创建属性字典和类型注解
            attrs = {"__doc__": description}
            annotations = {}
            
            for attr_def in edge_def.get("attributes", []):
                attr_name = safe_attr_name(attr_def["name"])  # 使用安全名称
                attr_desc = attr_def.get("description", attr_name)
                # Zep API 需要 Field 的 description，这是必需的
                attrs[attr_name] = Field(description=attr_desc, default=None)
                annotations[attr_name] = Optional[str]  # 边属性用str类型
            
            attrs["__annotations__"] = annotations
            
            # 动态创建类
            class_name = ''.join(word.capitalize() for word in name.split('_'))
            edge_class = type(class_name, (EdgeModel,), attrs)
            edge_class.__doc__ = description
            
            # 构建source_targets
            source_targets = []
            for st in edge_def.get("source_targets", []):
                source_targets.append(
                    EntityEdgeSourceTarget(
                        source=st.get("source", "Entity"),
                        target=st.get("target", "Entity")
                    )
                )
            
            if source_targets:
                edge_definitions[name] = (edge_class, source_targets)
        
        # 调用Zep API设置本体
        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
        *,
        start_chunk_index: int = 0,
        existing_episode_uuids: Optional[List[str]] = None,
        checkpoint_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[str]:
        """分批添加文本到图谱，返回所有 episode 的 uuid 列表。

        Phase C：支持从 start_chunk_index 续传；每批后经 checkpoint_callback 落盘。
        """
        episode_uuids = list(existing_episode_uuids or [])
        total_chunks = len(chunks)
        start_i = max(0, int(start_chunk_index or 0))
        
        for i in range(start_i, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            
            if progress_callback:
                progress = (i + len(batch_chunks)) / total_chunks
                progress_callback(
                    t('progress.sendingBatch', current=batch_num, total=total_batches, chunks=len(batch_chunks)),
                    progress
                )
            
            # 构建episode数据
            episodes = [
                EpisodeData(data=chunk, type="text")
                for chunk in batch_chunks
            ]
            
            # 发送到Zep
            try:
                batch_result = self.client.graph.add_batch(
                    graph_id=graph_id,
                    episodes=episodes
                )
                
                # 收集返回的 episode uuid
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)
                
                next_index = i + len(batch_chunks)
                if checkpoint_callback:
                    try:
                        checkpoint_callback({
                            "graph_id": graph_id,
                            "phase": "appending",
                            "next_chunk_index": next_index,
                            "total_chunks": total_chunks,
                            "episode_uuids": list(episode_uuids),
                        })
                    except Exception as ce:
                        logger.debug(f"graph checkpoint skip: {ce}")

                # 避免请求过快
                time.sleep(1)
                
            except Exception as e:
                if progress_callback:
                    progress_callback(t('progress.batchFailed', batch=batch_num, error=str(e)), 0)
                raise
        
        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ):
        """等待所有 episode 处理完成（通过查询每个 episode 的 processed 状态）"""
        if not episode_uuids:
            if progress_callback:
                progress_callback(t('progress.noEpisodesWait'), 1.0)
            return
        
        start_time = time.time()
        pending_episodes = set(episode_uuids)
        completed_count = 0
        total_episodes = len(episode_uuids)
        
        if progress_callback:
            progress_callback(t('progress.waitingEpisodes', count=total_episodes), 0)
        
        while pending_episodes:
            if time.time() - start_time > timeout:
                if progress_callback:
                    progress_callback(
                        t('progress.episodesTimeout', completed=completed_count, total=total_episodes),
                        completed_count / total_episodes
                    )
                break
            
            # 检查每个 episode 的处理状态
            for ep_uuid in list(pending_episodes):
                try:
                    episode = self.client.graph.episode.get(uuid_=ep_uuid)
                    is_processed = getattr(episode, 'processed', False)
                    
                    if is_processed:
                        pending_episodes.remove(ep_uuid)
                        completed_count += 1
                        
                except Exception as e:
                    # 忽略单个查询错误，继续
                    pass
            
            # 耗时秒数不再拼进 message，由前端本地计时展示，避免依赖推帧节奏一卡一卡
            if progress_callback:
                progress_callback(
                    t('progress.zepProcessing', completed=completed_count, total=total_episodes, pending=len(pending_episodes)),
                    completed_count / total_episodes if total_episodes > 0 else 0
                )
            
            if pending_episodes:
                time.sleep(3)  # 每3秒检查一次
        
        if progress_callback:
            progress_callback(t('progress.processingComplete', completed=completed_count, total=total_episodes), 1.0)
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = fetch_all_nodes(self.client, graph_id)

        # 获取边（分页）
        edges = fetch_all_edges(self.client, graph_id)

        # 统计实体类型
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )
    
    def _serialize_node(self, node) -> Dict[str, Any]:
        created_at = getattr(node, "created_at", None)
        return {
            "uuid": node.uuid_,
            "name": node.name,
            "labels": node.labels or [],
            "summary": node.summary or "",
            "attributes": node.attributes or {},
            "created_at": str(created_at) if created_at else None,
        }

    def get_graph_data(self, graph_id: str, heal: bool = False) -> Dict[str, Any]:
        """
        获取完整图谱数据（包含详细信息）。

        展示主路径应读本地快照；本方法仅用于建图期 live 刷图等场景。
        heal 默认关闭（补全仅在 export_snapshot 导出时做一次）。
        """
        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)
        if heal:
            from app.ontology.snapshot import heal_missing_edge_endpoints

            nodes = heal_missing_edge_endpoints(self.client, nodes, edges)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = [self._serialize_node(node) for node in nodes]

        edges_data = []
        for edge in edges:
            created_at = getattr(edge, "created_at", None)
            valid_at = getattr(edge, "valid_at", None)
            invalid_at = getattr(edge, "invalid_at", None)
            expired_at = getattr(edge, "expired_at", None)

            episodes = getattr(edge, "episodes", None) or getattr(
                edge, "episode_ids", None
            )
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]

            fact_type = getattr(edge, "fact_type", None) or edge.name or ""

            edges_data.append(
                {
                    "uuid": edge.uuid_,
                    "name": edge.name or "",
                    "fact": edge.fact or "",
                    "fact_type": fact_type,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "source_node_name": node_map.get(edge.source_node_uuid, ""),
                    "target_node_name": node_map.get(edge.target_node_uuid, ""),
                    "attributes": edge.attributes or {},
                    "created_at": str(created_at) if created_at else None,
                    "valid_at": str(valid_at) if valid_at else None,
                    "invalid_at": str(invalid_at) if invalid_at else None,
                    "expired_at": str(expired_at) if expired_at else None,
                    "episodes": episodes or [],
                }
            )

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
    
    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.graph.delete(graph_id=graph_id)

