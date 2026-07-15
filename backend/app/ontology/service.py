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

def _export_snapshot_with_retry(ontology_id: str, graph_id: str, attempts: int = 4, delay_sec: float = 3.0) -> None:
    """建图完成后 Zep 实体可能尚未可查；空快照时短暂重试，避免永久 0 节点。"""
    import time

    last_err: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            record = export_snapshot(ontology_id, graph_id)
            # add_version 返回含 node_count；无则读文件
            n = int(record.get("node_count") or 0)
            e = int(record.get("edge_count") or 0)
            if n > 0 or e > 0:
                return
            logger.info(
                f"建图后快照仍为空，重试 {i+1}/{attempts}: {ontology_id}"
            )
        except Exception as ex:
            last_err = ex
            logger.warning(f"建图后快照失败 ({i+1}/{attempts}): {ex}")
        if i + 1 < attempts:
            time.sleep(delay_sec)
    if last_err:
        logger.warning(f"建图后快照最终失败: {last_err}")


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


def _extracted_text_path(ontology_id: str) -> str:
    return os.path.join(Config.ONTOLOGY_DIR, ontology_id, "extracted_text.txt")


def save_extracted_text(ontology_id: str, text: str) -> None:
    path = _extracted_text_path(ontology_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def get_extracted_text(ontology_id: str) -> Optional[str]:
    path = _extracted_text_path(ontology_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def create_from_files(
    name: str,
    files: List[Union[FileStorage, tuple]],
    simulation_requirement: str = "",
    template: str = "opinion",
    use_llm_ontology: bool = True,
    lock_schema: bool = False,
) -> Dict[str, Any]:
    """
    创建本体记录、保存文档，并用 LLM 生成 schema（始终 LLM，与 MiroFish 一致；失败不回退模板）。

    files: FileStorage 列表，或 (filename, bytes) 元组列表。
    use_llm_ontology 保留兼容，创建路径强制走 LLM。
    """
    document_texts: List[str] = []
    all_text_parts: List[str] = []

    # 先创建记录拿到 id
    ont = registry.create_ontology(
        name=name,
        template=template,
        schema=None,
        schema_locked=False,
        status="created",
        simulation_requirement=simulation_requirement or "",
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
        text = TextProcessor.preprocess_text(text)
        registry.add_document(ontology_id, filename, path, len(text))
        document_texts.append(text)
        display_name = os.path.basename(filename)
        all_text_parts.append(f"\n\n=== {display_name} ===\n{text}")

    all_text = "".join(all_text_parts)
    if all_text.strip():
        save_extracted_text(ontology_id, all_text)

    if not document_texts:
        raise ValueError("没有可用文档，无法用 LLM 生成 SCHEMA")

    from app.ontology.ontology_generator import OntologyGenerator

    gen = OntologyGenerator()
    schema = gen.generate(
        document_texts=document_texts,
        simulation_requirement=simulation_requirement
        or "构建适合社交媒体舆论模拟的本体",
    )

    registry.update_ontology(
        ontology_id,
        schema=schema,
        schema_locked=lock_schema,
        simulation_requirement=simulation_requirement or "",
        status="ontology_generated",
    )
    return registry.get_ontology(ontology_id)


def _combined_document_text(ontology_id: str) -> str:
    """优先读落盘的 extracted_text（与 MiroFish 建图同源）；否则重提取并 preprocess。"""
    cached = get_extracted_text(ontology_id)
    if cached and cached.strip():
        return cached

    docs = registry.list_documents(ontology_id)
    parts = []
    for d in docs:
        path = d.get("path")
        filename = d.get("filename") or os.path.basename(path or "doc")
        if path and os.path.exists(path):
            try:
                text = FileParser.extract_text(path)
            except Exception:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            text = TextProcessor.preprocess_text(text)
            parts.append(f"\n\n=== {filename} ===\n{text}")
    all_text = "".join(parts)
    if all_text.strip():
        try:
            save_extracted_text(ontology_id, all_text)
        except Exception:
            pass
    return all_text


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
        # 与 MiroFish 一致：缺 schema / 强制重建时用 LLM，不回退模板
        text_for_schema = _combined_document_text(ontology_id)
        if not text_for_schema.strip():
            raise ValueError("没有可建图的文档内容，无法用 LLM 生成 SCHEMA")
        from app.ontology.ontology_generator import OntologyGenerator

        gen = OntologyGenerator()
        schema = gen.generate(
            document_texts=[text_for_schema],
            simulation_requirement=ont.get("simulation_requirement")
            or "构建适合社交媒体舆论模拟的本体",
        )
        registry.update_ontology(ontology_id, schema=schema)

    text = _combined_document_text(ontology_id)
    if not text.strip():
        raise ValueError("没有可建图的文档内容")

    from app.ontology.graph_builder import GraphBuilderService

    builder = GraphBuilderService()

    if async_mode:
        task_id = builder.build_graph_async(
            text=text,
            ontology=schema,
            graph_name=ont.get("name") or ontology_id,
            chunk_size=Config.DEFAULT_CHUNK_SIZE,
            chunk_overlap=Config.DEFAULT_CHUNK_OVERLAP,
            extra_metadata={"ontology_id": ontology_id},
        )
        registry.update_ontology(
            ontology_id, status="building", build_task_id=task_id
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
        extra_metadata={"ontology_id": ontology_id},
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
        # 建图早期就把 graph_id 回写，live 端点才能在 Zep 处理中刷图
        early_gid = (task.result or {}).get("graph_id")
        if early_gid:
            ont = registry.get_ontology(ontology_id)
            if ont and not ont.get("graph_id"):
                try:
                    registry.update_ontology(ontology_id, graph_id=early_gid)
                except Exception:
                    pass
        if task.status == TaskStatus.COMPLETED:
            graph_id = (task.result or {}).get("graph_id")
            registry.update_ontology(
                ontology_id,
                graph_id=graph_id,
                status="ready",
                build_task_id=None,
            )
            try:
                _export_snapshot_with_retry(ontology_id, graph_id)
            except Exception as e:
                logger.warning(f"建图后自动快照失败: {e}")
            return
        if task.status == TaskStatus.FAILED:
            registry.update_ontology(
                ontology_id, status="failed", build_task_id=None
            )
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
            # 用任务状态覆盖本体状态，便于前端判断完成/失败
            result["status"] = task.status.value
            result["progress"] = task.progress
            result["message"] = task.message
            if task.result and task.result.get("graph_id"):
                result["graph_id"] = task.result.get("graph_id")
            if task.error:
                result["error"] = task.error

            # 任务已完成时，在 status 查询里同步落库 + 快照，避免前端抢跑 404
            if task.status == TaskStatus.COMPLETED:
                gid = (task.result or {}).get("graph_id") or result.get("graph_id")
                if gid:
                    try:
                        registry.update_ontology(
                            ontology_id,
                            graph_id=gid,
                            status="ready",
                            build_task_id=None,
                        )
                        result["graph_id"] = gid
                        latest = registry.get_latest_version(ontology_id)
                        need = (not latest) or int(latest.get("node_count") or 0) <= 0
                        if need:
                            _export_snapshot_with_retry(ontology_id, gid, attempts=2, delay_sec=2.0)
                    except Exception as e:
                        logger.warning(f"完成态同步落库/快照失败: {e}")

            # 建图中途提前回写 graph_id，供 live 刷图
            elif (
                task.result
                and task.result.get("graph_id")
                and ont
                and not ont.get("graph_id")
            ):
                try:
                    registry.update_ontology(
                        ontology_id, graph_id=task.result["graph_id"]
                    )
                except Exception:
                    pass

            # 若曾被旧 task 误标 failed，但当前任务仍在跑，纠正回 building
            if (
                ont
                and ont.get("status") == "failed"
                and task.status
                not in (TaskStatus.FAILED, TaskStatus.COMPLETED)
                and not ont.get("graph_id")
            ):
                try:
                    registry.update_ontology(
                        ontology_id, status="building", build_task_id=task_id
                    )
                    result["status"] = task.status.value
                except Exception:
                    pass
        else:
            # 进程重启后 TaskManager 内存任务会丢失。
            # 仅当轮询的是「当前」build_task_id 时才标失败，避免旧 task_id 误杀新建图。
            current_tid = (ont or {}).get("build_task_id")
            is_current = (not current_tid) or (task_id == current_tid)
            if (
                is_current
                and ont
                and ont.get("status") == "building"
                and not ont.get("graph_id")
            ):
                result["status"] = "failed"
                result["error"] = "建图任务已丢失（服务可能重启过），请重新点击建图"
                result["task_lost"] = True
                try:
                    registry.update_ontology(
                        ontology_id, status="failed", build_task_id=None
                    )
                except Exception:
                    pass
            elif not is_current:
                result["status"] = "stale"
                result["error"] = "该任务已过期，请使用最新建图任务"
                result["task_lost"] = True
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
        text = TextProcessor.preprocess_text(text)
        doc = registry.add_document(ontology_id, filename, path, len(text))
        docs.append(doc)
        new_texts.append(text)

    # 追加后重建 extracted_text，保证后续建图/prepare 同源
    try:
        cached_path = _extracted_text_path(ontology_id)
        if os.path.exists(cached_path):
            os.remove(cached_path)
        _combined_document_text(ontology_id)
    except Exception as e:
        logger.warning(f"更新 extracted_text 失败: {e}")

    graph_id = ont.get("graph_id")
    if graph_id and new_texts and Config.ZEP_API_KEY:
        try:
            from app.ontology.graph_builder import GraphBuilderService

            builder = GraphBuilderService()
            combined = "\n\n".join(
                f"=== {d.get('filename')} ===\n{t}"
                for d, t in zip(docs, new_texts)
            )
            chunks = TextProcessor.split_text(
                combined, Config.DEFAULT_CHUNK_SIZE, Config.DEFAULT_CHUNK_OVERLAP
            )
            episode_uuids = builder.add_text_batches(graph_id, chunks)
            builder._wait_for_episodes(episode_uuids)
            registry.update_ontology(ontology_id, status="ready")
            try:
                export_snapshot(ontology_id, graph_id)
            except Exception as se:
                logger.warning(f"追加文档后自动快照失败: {se}")
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
