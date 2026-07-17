"""
从世界切片生成 OASIS Agent 人口（profiles）
"""

from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Dict, List, Optional, Set

from app.config import Config
from app.ontology.zep_entity_reader import EntityNode
from app.utils.logger import get_logger

logger = get_logger("adc.world.population")

MAX_AGENTS = 30

# 视为可发声 Agent 的实体类型（小写匹配）
PERSON_LIKE_TYPES = {
    "person",
    "governmentofficial",
    "deliveryrider",
    "commutercitizen",
    "selfmedia",
    "journalist",
    "streetmerchant",
    "studentparent",
    "expertscholar",
    "publicfigure",
    "student",
    "professor",
    "official",
    "activist",
    "alumni",
    "faculty",
    "expert",
}

ORG_LIKE_TYPES = {
    "organization",
    "company",
    "university",
    "governmentagency",
    "mediaoutlet",
    "ngo",
    "institution",
    "group",
    "community",
}


def _labels_of(node: Dict[str, Any]) -> List[str]:
    return [str(x) for x in (node.get("labels") or [])]


def _entity_type(node: Dict[str, Any]) -> str:
    for lab in _labels_of(node):
        if lab not in ("Entity", "Node"):
            return lab
    return "Person"


def _is_agent_candidate(node: Dict[str, Any]) -> bool:
    et = _entity_type(node).lower().replace("_", "").replace(" ", "")
    if et in PERSON_LIKE_TYPES or et in ORG_LIKE_TYPES:
        return True
    # 兜底：有人名式名称
    name = str(node.get("name") or "")
    return bool(name) and len(name) <= 40


def slice_nodes_to_entities(nodes: List[Dict[str, Any]]) -> List[EntityNode]:
    entities = []
    for n in nodes:
        if not _is_agent_candidate(n):
            continue
        uuid = str(n.get("uuid") or n.get("id") or "")
        name = str(n.get("name") or "").strip()
        if not name:
            continue
        entities.append(
            EntityNode(
                uuid=uuid or name,
                name=name,
                labels=_labels_of(n) or ["Person"],
                summary=str(n.get("summary") or ""),
                attributes=n.get("attributes") or {},
            )
        )
    return entities


def expected_agent_count_from_slice(
    world_slice: Optional[Dict[str, Any]],
    max_agents: int = MAX_AGENTS,
) -> int:
    """切片中可转为人设的实体数（上限 max_agents），供准备中进度展示。"""
    if not isinstance(world_slice, dict):
        return 0
    return min(len(slice_nodes_to_entities(world_slice.get("nodes") or [])), max_agents)


def _rule_based_profile(entity: EntityNode, user_id: int) -> Dict[str, Any]:
    from app.world.china_location import format_location_label, resolve_location

    et = entity.get_entity_type() or "Person"
    bio = (entity.summary or f"{et}: {entity.name}")[:200]
    loc = resolve_location(
        text=f"{entity.name} {et} {entity.summary or ''} {entity.attributes or ''}",
        entity_type=et,
        seed=entity.uuid or user_id,
    )
    place = format_location_label(loc)
    persona = (
        f"你是{entity.name}，身份类型为{et}，活动于{place}。"
        f"{entity.summary or '你关注本地公共政策与城市生活话题。'}"
        f"你会在社交媒体上表达与自身利益相关的观点。"
    )
    username = re.sub(r"[^\w\u4e00-\u9fff]+", "_", entity.name)[:24] or f"user_{user_id}"
    return {
        "user_id": user_id,
        "user_name": username,
        "name": entity.name,
        "bio": bio,
        "persona": persona,
        "source_entity_uuid": entity.uuid,
        "source_entity_type": et,
        "age": random.randint(22, 55),
        "gender": "other",
        "mbti": random.choice(["ISTJ", "ENFP", "INTJ", "ESFJ", "ISTP"]),
        "country": loc["country"],
        "province": loc["province"],
        "city": loc["city"],
        "district": loc.get("district") or "",
        "province_adcode": loc.get("province_adcode") or "",
        "city_adcode": loc.get("city_adcode") or "",
        "district_adcode": loc.get("district_adcode") or "",
        "profession": et,
        "karma": random.randint(500, 3000),
        "friend_count": random.randint(50, 400),
        "follower_count": random.randint(80, 800),
        "statuses_count": random.randint(100, 1500),
    }


def _enrich_persona_with_follows(
    persona: str, follow_names: List[str]
) -> str:
    if not follow_names:
        return persona
    names = "、".join(follow_names[:8])
    extra = f" 你关注了: {names}。"
    if extra.strip() in persona:
        return persona
    return (persona or "") + extra


def generate_profiles_from_slice(
    world_slice: Dict[str, Any],
    output_dir: str,
    max_agents: int = MAX_AGENTS,
    use_llm: bool = False,
    network: Optional[Dict[str, Any]] = None,
    entity_id_to_agent: Optional[Dict[str, int]] = None,
    existing_profiles: Optional[List[Dict[str, Any]]] = None,
    existing_entity_to_agent: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """
    从切片生成 twitter CSV + reddit JSON。

    Returns:
        {
          profiles: [...],
          twitter_path, reddit_path,
          entity_to_agent: {entity_uuid: user_id}
        }
    """
    os.makedirs(output_dir, exist_ok=True)
    entities = slice_nodes_to_entities(world_slice.get("nodes") or [])
    entities = entities[:max_agents]

    profiles_data: List[Dict[str, Any]] = []
    entity_to_agent: Dict[str, int] = {}

    if existing_profiles:
        profiles_data = [dict(p) for p in existing_profiles]
        entity_to_agent = dict(existing_entity_to_agent or {})
        if not entity_to_agent:
            for p in profiles_data:
                uuid = p.get("source_entity_uuid")
                if uuid is not None and p.get("user_id") is not None:
                    entity_to_agent[str(uuid)] = int(p["user_id"])
    elif use_llm and Config.LLM_API_KEY:
        from app.world.oasis_profile_generator import OasisProfileGenerator

        # 不传 graph_id，跳过 Zep 二次检索；失败直接抛错，禁止回退规则空壳
        # 增量写入 shared/reddit_profiles.json，供 Step2 realtime / SSE 预览
        reddit_path = os.path.join(output_dir, "reddit_profiles.json")
        twitter_path = os.path.join(output_dir, "twitter_profiles.csv")
        gen = OasisProfileGenerator(graph_id=None)

        def _profile_progress(current: int, total: int, msg: str) -> None:
            # N>1：回写预期 / 进度消息 / 细分 stage，供 Step2 SSE 实时展示
            try:
                t_int = int(total or 0)
                c_int = int(current or 0)
                shared_parent = os.path.basename(
                    os.path.dirname(os.path.abspath(output_dir))
                )
                if not str(shared_parent).startswith("dec_"):
                    return
                from app.engine.scenario_runner import (
                    _read_prepare_progress,
                    _write_prepare_progress,
                )

                prep = _read_prepare_progress(shared_parent) or {}
                prev_expected = int(prep.get("total_expected") or 0)
                text = str(msg or "")
                stage = "profiles"
                low = text.lower()
                if "cast" in low or "分角" in text or "规划" in text:
                    stage = "cast"
                elif "review" in low or "终审" in text:
                    stage = "review"

                fields: Dict[str, Any] = {
                    "stage": stage,
                    "message": text or prep.get("message"),
                    "profile_count": max(c_int, int(prep.get("profile_count") or 0)),
                    "status": "running",
                }
                if t_int > 0 and (not prev_expected or t_int <= prev_expected):
                    fields["total_expected"] = t_int
                # 进度粗估：Cast/Review 固定区间，生成中按 k/n
                if stage == "cast":
                    fields["progress"] = 30
                elif stage == "review":
                    fields["progress"] = 80
                elif t_int > 0:
                    fields["progress"] = min(75, 35 + int(40 * c_int / t_int))

                _write_prepare_progress(shared_parent, **fields)
            except Exception as e:
                logger.debug(f"更新 prepare_progress 跳过: {e}")

        oasis_profiles = gen.generate_profiles_from_entities(
            entities,
            use_llm=True,
            graph_id=None,
            parallel_count=Config.llm_parallel_workers(),
            realtime_output_path=reddit_path,
            output_platform="reddit",
            progress_callback=_profile_progress,
        )
        for p in oasis_profiles:
            profiles_data.append(p.to_dict())
            if p.source_entity_uuid:
                entity_to_agent[p.source_entity_uuid] = p.user_id
        gen.save_profiles(oasis_profiles, twitter_path, platform="twitter")
        gen.save_profiles(oasis_profiles, reddit_path, platform="reddit")
    elif use_llm and not Config.LLM_API_KEY:
        raise RuntimeError("已请求 LLM 人设生成，但未配置 LLM_API_KEY")

    if not profiles_data:
        if use_llm:
            raise RuntimeError("LLM 人设生成未产出任何结果（已禁用规则兜底）")
        for i, ent in enumerate(entities):
            row = _rule_based_profile(ent, i)
            profiles_data.append(row)
            entity_to_agent[ent.uuid] = i

    # 统一补全真实省市
    from app.world.china_location import enrich_profile_location

    for p in profiles_data:
        enrich_profile_location(p)

    # 关注关系注入 persona
    follows = (network or {}).get("follows") or []
    agent_follows: Dict[int, List[int]] = {}
    for pair in follows:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        src, dst = int(pair[0]), int(pair[1])
        agent_follows.setdefault(src, []).append(dst)

    id_to_name = {int(p["user_id"]): p["name"] for p in profiles_data}
    for p in profiles_data:
        uid = int(p["user_id"])
        names = [id_to_name[d] for d in agent_follows.get(uid, []) if d in id_to_name]
        p["persona"] = _enrich_persona_with_follows(p.get("persona") or "", names)

    twitter_path = os.path.join(output_dir, "twitter_profiles.csv")
    reddit_path = os.path.join(output_dir, "reddit_profiles.json")
    _write_twitter_csv(profiles_data, twitter_path)
    _write_reddit_json(profiles_data, reddit_path)

    mapping_path = os.path.join(output_dir, "entity_agent_mapping.json")
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(entity_to_agent, f, ensure_ascii=False, indent=2)

    if entity_id_to_agent is not None:
        entity_id_to_agent.update(entity_to_agent)

    return {
        "profiles": profiles_data,
        "twitter_path": twitter_path,
        "reddit_path": reddit_path,
        "mapping_path": mapping_path,
        "entity_to_agent": entity_to_agent,
        "agent_count": len(profiles_data),
    }


def _write_twitter_csv(profiles: List[Dict[str, Any]], path: str) -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "name", "username", "user_char", "description"])
        for idx, p in enumerate(profiles):
            bio = (p.get("bio") or "").replace("\n", " ").replace("\r", " ")
            persona = (p.get("persona") or "").replace("\n", " ").replace("\r", " ")
            user_char = bio
            if persona and persona != bio:
                user_char = f"{bio} {persona}"
            writer.writerow(
                [
                    p.get("user_id", idx),
                    p.get("name", f"agent_{idx}"),
                    p.get("user_name") or p.get("username") or f"user_{idx}",
                    user_char,
                    bio,
                ]
            )


def _write_reddit_json(profiles: List[Dict[str, Any]], path: str) -> None:
    data = []
    for idx, p in enumerate(profiles):
        data.append(
            {
                "user_id": p.get("user_id", idx),
                "username": p.get("user_name") or p.get("username") or f"user_{idx}",
                "name": p.get("name", f"agent_{idx}"),
                "bio": (p.get("bio") or "")[:150],
                "persona": p.get("persona") or "",
                "karma": p.get("karma", 1000),
                "age": p.get("age", 30),
                "gender": p.get("gender") or "other",
                "mbti": p.get("mbti") or "ISTJ",
                "country": p.get("country") or "中国",
                "province": p.get("province") or "",
                "city": p.get("city") or "",
                "district": p.get("district") or "",
                "province_adcode": p.get("province_adcode") or "",
                "city_adcode": p.get("city_adcode") or "",
                "district_adcode": p.get("district_adcode") or "",
                "profession": p.get("profession"),
                "source_entity_uuid": p.get("source_entity_uuid"),
                "source_entity_type": p.get("source_entity_type"),
            }
        )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_from_entities(
    entities: List[EntityNode],
    output_dir: str,
    use_llm: bool = False,
    max_agents: int = MAX_AGENTS,
) -> Dict[str, Any]:
    """OasisProfileGenerator 适配：实体已就绪时跳过 Zep。"""
    fake_slice = {
        "nodes": [
            {
                "uuid": e.uuid,
                "name": e.name,
                "labels": e.labels,
                "summary": e.summary,
                "attributes": e.attributes,
            }
            for e in entities[:max_agents]
        ],
        "edges": [],
    }
    return generate_profiles_from_slice(
        fake_slice, output_dir, max_agents=max_agents, use_llm=use_llm
    )
