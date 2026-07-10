"""
本体高层服务：创建、建图、追加文档、快照
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Dict, List, Optional, Union

from werkzeug.datastructures import FileStorage

from app.config import Config
from app.models.task import TaskManager, TaskStatus
from app.ontology import registry
from app.ontology.snapshot import export_snapshot
from app.ontology.templates import get_template
from app.ontology.text_processor import TextProcessor
from app.utils.file_parser import FileParser
from app.utils.logger import get_logger

logger = get_logger("adc.ontology.service")

MAX_AGENTS_NOTE = 30  # world 层上限，此处仅文档说明


def _read_uploaded_text(file_storage: FileStorage) -> tuple[str, str]:
    """返回 (filename, text)。"""
    filename = file_storage.filename or f"upload_{uuid.uuid4().hex[:8]}.txt"
    raw = file_storage.read()
    # FileParser 可能需要路径；先落盘再解析
    return filename, raw


def _save_document_bytes(
    ontology_id: str, filename: str, raw: bytes
) -> tuple[str, str, int]:
    """保存文档到 ONTOLOGY_DIR，返回 (path, text, char_count)。"""
    safe_name = os.path.basename(filename).replace(" ", "_")
    dest_dir = os.path.join(Config.ONTOLOGY_DIR, ontology_id, "docs")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
    with open(path, "wb") as f:
        f.write(raw)

    try:
        text = FileParser.extract_text(path)
    except Exception:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
    return path, text, len(text)


def create_from_files(
    name: str,
    files: List[Union[FileStorage, tuple]],
    simulation_requirement: str = "",
    template: str = "opinion",
    use_llm_ontology: bool = True,
    lock_schema: bool = False,
) -> Dict[str, Any]:
    """
    创建本体记录、保存文档、生成或加载 schema。

    files: FileStorage 列表，或 (filename, bytes) 元组列表。
    """
    schema: Optional[Dict[str, Any]] = None
    document_texts: List[str] = []

    # 先创建记录拿到 id
    ont = registry.create_ontology(
        name=name,
        template=template,
        schema=None,
        schema_locked=False,
        status="created",
    )
    ontology_id = ont["id"]

    for item in files or []:
        if isinstance(item, tuple):
            filename, raw = item[0], item[1]
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
        else:
            filename = item.filename or "upload.txt"
            raw = item.read()
            if hasattr(item, "seek"):
                item.seek(0)

        path, text, char_count = _save_document_bytes(ontology_id, filename, raw)
        registry.add_document(ontology_id, filename, path, char_count)
        document_texts.append(text)

    if use_llm_ontology and document_texts:
        try:
            from app.ontology.ontology_generator import OntologyGenerator

            gen = OntologyGenerator()
            schema = gen.generate(
                document_texts=document_texts,
                simulation_requirement=simulation_requirement
                or "构建适合社交媒体舆论模拟的本体",
            )
        except Exception as e:
            logger.warning(f"LLM 本体生成失败，回退模板: {e}")
            schema = get_template(template)
    else:
        schema = get_template(template)

    registry.update_ontology(
        ontology_id,
        schema=schema,
        schema_locked=lock_schema,
        status="created",
    )
    return registry.get_ontology(ontology_id)


def _combined_document_text(ontology_id: str) -> str:
    docs = registry.list_documents(ontology_id)
    parts = []
    for d in docs:
        path = d.get("path")
        if path and os.path.exists(path):
            try:
                parts.append(FileParser.extract_text(path))
            except Exception:
                with open(path, encoding="utf-8", errors="replace") as f:
                    parts.append(f.read())
    return "\n\n---\n\n".join(parts)


def build_graph(
    ontology_id: str,
    use_existing_schema: bool = True,
    async_mode: bool = True,
) -> Dict[str, Any]:
    """
    调用 GraphBuilderService 建图。
    返回 {task_id} 或同步结果 {graph_id, ...}。
    """
    ont = registry.get_ontology(ontology_id)
    if not ont:
        raise ValueError(f"本体不存在: {ontology_id}")

    schema = ont.get("schema")
    if not schema or not use_existing_schema:
        schema = get_template(ont.get("template") or "opinion")
        registry.update_ontology(ontology_id, schema=schema)

    text = _combined_document_text(ontology_id)
    if not text.strip():
        raise ValueError("没有可建图的文档内容")

    registry.update_ontology(ontology_id, status="building")

    from app.ontology.graph_builder import GraphBuilderService

    builder = GraphBuilderService()

    if async_mode:
        task_id = builder.build_graph_async(
            text=text,
            ontology=schema,
            graph_name=ont.get("name") or ontology_id,
            chunk_size=Config.DEFAULT_CHUNK_SIZE,
            chunk_overlap=Config.DEFAULT_CHUNK_OVERLAP,
        )
        # 后台监视任务完成，回写 graph_id / status
        thread = threading.Thread(
            target=_watch_build_task,
            args=(ontology_id, task_id),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "ontology_id": ontology_id, "status": "building"}

    # 同步：复用 async worker 逻辑较重，这里直接走 create + set + add
    task_id = builder.build_graph_async(
        text=text,
        ontology=schema,
        graph_name=ont.get("name") or ontology_id,
    )
    tm = TaskManager()
    import time

    for _ in range(600):
        task = tm.get_task(task_id)
        if not task:
            break
        if task.status == TaskStatus.COMPLETED:
            graph_id = (task.result or {}).get("graph_id")
            registry.update_ontology(
                ontology_id, graph_id=graph_id, status="ready"
            )
            return {
                "task_id": task_id,
                "ontology_id": ontology_id,
                "graph_id": graph_id,
                "status": "ready",
                "result": task.result,
            }
        if task.status == TaskStatus.FAILED:
            registry.update_ontology(ontology_id, status="failed")
            raise RuntimeError(task.error or "建图失败")
        time.sleep(2)
    raise TimeoutError("建图超时")


def _watch_build_task(ontology_id: str, task_id: str) -> None:
    import time

    tm = TaskManager()
    while True:
        task = tm.get_task(task_id)
        if not task:
            return
        if task.status == TaskStatus.COMPLETED:
            graph_id = (task.result or {}).get("graph_id")
            registry.update_ontology(
                ontology_id, graph_id=graph_id, status="ready"
            )
            try:
                export_snapshot(ontology_id, graph_id)
            except Exception as e:
                logger.warning(f"建图后自动快照失败: {e}")
            return
        if task.status == TaskStatus.FAILED:
            registry.update_ontology(ontology_id, status="failed")
            return
        time.sleep(2)


def get_build_status(ontology_id: str, task_id: Optional[str] = None) -> Dict[str, Any]:
    ont = registry.get_ontology(ontology_id)
    result: Dict[str, Any] = {
        "ontology_id": ontology_id,
        "status": ont.get("status") if ont else "unknown",
        "graph_id": ont.get("graph_id") if ont else None,
    }
    if task_id:
        task = TaskManager().get_task(task_id)
        if task:
            result["task"] = task.to_dict()
    return result


def append_documents(
    ontology_id: str,
    files: List[Union[FileStorage, tuple]],
) -> Dict[str, Any]:
    """追加文档；若已有 graph_id，则向 Zep 追加 episodes。"""
    ont = registry.get_ontology(ontology_id)
    if not ont:
        raise ValueError(f"本体不存在: {ontology_id}")

    new_texts: List[str] = []
    docs = []
    for item in files or []:
        if isinstance(item, tuple):
            filename, raw = item[0], item[1]
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
        else:
            filename = item.filename or "upload.txt"
            raw = item.read()

        path, text, char_count = _save_document_bytes(ontology_id, filename, raw)
        doc = registry.add_document(ontology_id, filename, path, char_count)
        docs.append(doc)
        new_texts.append(text)

    graph_id = ont.get("graph_id")
    if graph_id and new_texts and Config.ZEP_API_KEY:
        try:
            from app.ontology.graph_builder import GraphBuilderService

            builder = GraphBuilderService()
            combined = "\n\n---\n\n".join(new_texts)
            chunks = TextProcessor.split_text(
                combined, Config.DEFAULT_CHUNK_SIZE, Config.DEFAULT_CHUNK_OVERLAP
            )
            episode_uuids = builder.add_text_batches(graph_id, chunks)
            builder._wait_for_episodes(episode_uuids)
            registry.update_ontology(ontology_id, status="ready")
        except Exception as e:
            logger.warning(f"追加文档到图谱失败: {e}")

    return {
        "ontology_id": ontology_id,
        "documents": docs,
        "graph_id": graph_id,
    }


def create_snapshot(ontology_id: str) -> Dict[str, Any]:
    ont = registry.get_ontology(ontology_id)
    if not ont:
        raise ValueError(f"本体不存在: {ontology_id}")
    graph_id = ont.get("graph_id")
    if not graph_id:
        raise ValueError("本体尚未关联 graph_id，请先建图")
    return export_snapshot(ontology_id, graph_id)


def update_schema(
    ontology_id: str,
    schema: Dict[str, Any],
    lock: bool = True,
) -> Dict[str, Any]:
    ont = registry.get_ontology(ontology_id)
    if not ont:
        raise ValueError(f"本体不存在: {ontology_id}")
    if ont.get("schema_locked") and not lock:
        # 已锁定时仍允许显式更新并保持锁定
        pass
    return registry.update_ontology(
        ontology_id, schema=schema, schema_locked=lock
    )
