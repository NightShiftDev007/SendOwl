"""
OASIS Agent Profile生成器
将Zep图谱中的实体转换为OASIS模拟平台所需的Agent Profile格式

优化改进：
1. 调用Zep检索功能二次丰富节点信息
2. 优化提示词生成非常详细的人设
3. 区分个人实体和抽象群体实体
"""

import json
import random
import re
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime

from openai import OpenAI
from zep_cloud.client import Zep

from app.config import Config
from app.utils.logger import get_logger
from app.utils.locale import get_language_instruction, get_locale, set_locale, t
from app.utils.llm_client import LLMClient, with_rate_limit_retry
from app.ontology.zep_entity_reader import EntityNode, ZepEntityReader
from app.world.china_location import (
    format_location_label,
    location_instruction_for_llm,
    resolve_location,
)

logger = get_logger('mirofish.oasis_profile')


@dataclass
class OasisAgentProfile:
    """OASIS Agent Profile数据结构"""
    # 通用字段
    user_id: int
    user_name: str
    name: str
    bio: str
    persona: str
    
    # 可选字段 - Reddit风格
    karma: int = 1000
    
    # 可选字段 - Twitter风格
    friend_count: int = 100
    follower_count: int = 150
    statuses_count: int = 500
    
    # 额外人设信息
    age: Optional[int] = None
    gender: Optional[str] = None
    mbti: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    province_adcode: Optional[str] = None
    city_adcode: Optional[str] = None
    district_adcode: Optional[str] = None
    profession: Optional[str] = None
    interested_topics: List[str] = field(default_factory=list)
    
    # 来源实体信息
    source_entity_uuid: Optional[str] = None
    source_entity_type: Optional[str] = None
    
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    
    def to_reddit_format(self) -> Dict[str, Any]:
        """转换为Reddit平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息（如果有）
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.province:
            profile["province"] = self.province
        if self.city:
            profile["city"] = self.city
        if self.district:
            profile["district"] = self.district
        if self.province_adcode:
            profile["province_adcode"] = self.province_adcode
        if self.city_adcode:
            profile["city_adcode"] = self.city_adcode
        if self.district_adcode:
            profile["district_adcode"] = self.district_adcode
        if self.profession:
            profile["profession"] = self.profession
        # 始终写出，避免前端「关联话题数」因缺字段显示 0
        profile["interested_topics"] = list(self.interested_topics or [])
        
        return profile
    
    def to_twitter_format(self) -> Dict[str, Any]:
        """转换为Twitter平台格式"""
        profile = {
            "user_id": self.user_id,
            "username": self.user_name,  # OASIS 库要求字段名为 username（无下划线）
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "created_at": self.created_at,
        }
        
        # 添加额外人设信息
        if self.age:
            profile["age"] = self.age
        if self.gender:
            profile["gender"] = self.gender
        if self.mbti:
            profile["mbti"] = self.mbti
        if self.country:
            profile["country"] = self.country
        if self.province:
            profile["province"] = self.province
        if self.city:
            profile["city"] = self.city
        if self.district:
            profile["district"] = self.district
        if self.province_adcode:
            profile["province_adcode"] = self.province_adcode
        if self.city_adcode:
            profile["city_adcode"] = self.city_adcode
        if self.district_adcode:
            profile["district_adcode"] = self.district_adcode
        if self.profession:
            profile["profession"] = self.profession
        profile["interested_topics"] = list(self.interested_topics or [])
        
        return profile
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为完整字典格式"""
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "name": self.name,
            "bio": self.bio,
            "persona": self.persona,
            "karma": self.karma,
            "friend_count": self.friend_count,
            "follower_count": self.follower_count,
            "statuses_count": self.statuses_count,
            "age": self.age,
            "gender": self.gender,
            "mbti": self.mbti,
            "country": self.country,
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "province_adcode": self.province_adcode,
            "city_adcode": self.city_adcode,
            "district_adcode": self.district_adcode,
            "profession": self.profession,
            "interested_topics": self.interested_topics,
            "source_entity_uuid": self.source_entity_uuid,
            "source_entity_type": self.source_entity_type,
            "created_at": self.created_at,
        }


class OasisProfileGenerator:
    """
    OASIS Profile生成器
    
    将Zep图谱中的实体转换为OASIS模拟所需的Agent Profile
    
    优化特性：
    1. 调用Zep图谱检索功能获取更丰富的上下文
    2. 生成非常详细的人设（包括基本信息、职业经历、性格特征、社交媒体行为等）
    3. 区分个人实体和抽象群体实体
    """
    
    # MBTI类型列表
    MBTI_TYPES = [
        "INTJ", "INTP", "ENTJ", "ENTP",
        "INFJ", "INFP", "ENFJ", "ENFP",
        "ISTJ", "ISFJ", "ESTJ", "ESFJ",
        "ISTP", "ISFP", "ESTP", "ESFP"
    ]
    
    # 常见国家列表
    COUNTRIES = [
        "China", "US", "UK", "Japan", "Germany", "France", 
        "Canada", "Australia", "Brazil", "India", "South Korea"
    ]
    
    # 个人类型实体（需要生成具体人设）
    INDIVIDUAL_ENTITY_TYPES = [
        "student", "alumni", "professor", "person", "publicfigure", 
        "expert", "faculty", "official", "journalist", "activist"
    ]
    
    # 群体/机构类型实体（需要生成群体代表人设）
    GROUP_ENTITY_TYPES = [
        "university", "governmentagency", "organization", "ngo", 
        "mediaoutlet", "company", "institution", "group", "community"
    ]
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        zep_api_key: Optional[str] = None,
        graph_id: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # Zep客户端用于检索丰富上下文
        self.zep_api_key = zep_api_key or Config.ZEP_API_KEY
        self.zep_client = None
        self.graph_id = graph_id
        
        if self.zep_api_key:
            try:
                self.zep_client = Zep(api_key=self.zep_api_key)
            except Exception as e:
                logger.warning(f"Zep客户端初始化失败: {e}")

        self.last_cast_sheet: Optional[Dict[str, Any]] = None
        self.last_excluded: List[Dict[str, Any]] = []
    
    def generate_profile_from_entity(
        self,
        entity: EntityNode,
        user_id: int,
        use_llm: bool = True,
        cast_anchor: Optional[Dict[str, Any]] = None,
        occupied_summary: Optional[str] = None,
        extra_constraint: Optional[str] = None,
    ) -> OasisAgentProfile:
        """
        从Zep实体生成OASIS Agent Profile

        Args:
            entity: Zep实体节点
            user_id: 用户ID（用于OASIS）
            use_llm: 是否使用LLM生成详细人设
            cast_anchor: Cast Sheet 分角锚点（role_slot/stance/voice 等）
            occupied_summary: 全员分角清单（静态 roster，差异化防撞）
            extra_constraint: 本地查重 / 终审点名重生成时的额外约束

        Returns:
            OasisAgentProfile
        """
        entity_type = entity.get_entity_type() or "Entity"

        # 基础信息
        name = entity.name
        user_name = self._generate_username(name)

        # 构建上下文信息
        context = self._build_entity_context(entity)

        # 先解析地域：只把地名交给 LLM，由模型自行生成地域人格（不写死气质文案）
        seed_loc = resolve_location(
            text=" ".join(
                [
                    name,
                    entity_type,
                    entity.summary or "",
                    json.dumps(entity.attributes or {}, ensure_ascii=False),
                ]
            ),
            entity_type=entity_type,
            seed=f"{entity.uuid}:{name}",
        )

        if use_llm:
            profile_data = self._generate_profile_with_llm(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                context=context,
                location_hint=seed_loc,
                cast_anchor=cast_anchor,
                occupied_summary=occupied_summary,
                extra_constraint=extra_constraint,
            )
        else:
            profile_data = self._generate_profile_rule_based(
                entity_name=name,
                entity_type=entity_type,
                entity_summary=entity.summary,
                entity_attributes=entity.attributes,
                location_hint=seed_loc,
            )

        loc = resolve_location(
            province=profile_data.get("province") or seed_loc.get("province"),
            city=profile_data.get("city") or profile_data.get("location") or seed_loc.get("city"),
            district=profile_data.get("district") or seed_loc.get("district"),
            province_adcode_v=seed_loc.get("province_adcode"),
            city_adcode_v=seed_loc.get("city_adcode"),
            district_adcode_v=seed_loc.get("district_adcode"),
            text=" ".join(
                [
                    name,
                    entity_type,
                    entity.summary or "",
                    json.dumps(entity.attributes or {}, ensure_ascii=False),
                    str(profile_data.get("bio") or ""),
                    str(profile_data.get("persona") or ""),
                ]
            ),
            entity_type=entity_type,
            seed=f"{entity.uuid}:{name}",
        )
        persona = profile_data.get("persona", entity.summary or f"A {entity_type} named {name}.")
        profession = profile_data.get("profession")
        topics = self._normalize_interested_topics(
            profile_data.get("interested_topics"),
            profession=profession,
            entity_type=entity_type,
            entity_summary=entity.summary,
            bio=profile_data.get("bio"),
        )
        
        return OasisAgentProfile(
            user_id=user_id,
            user_name=user_name,
            name=name,
            bio=profile_data.get("bio", f"{entity_type}: {name}"),
            persona=persona,
            karma=profile_data.get("karma", random.randint(500, 5000)),
            friend_count=profile_data.get("friend_count", random.randint(50, 500)),
            follower_count=profile_data.get("follower_count", random.randint(100, 1000)),
            statuses_count=profile_data.get("statuses_count", random.randint(100, 2000)),
            age=profile_data.get("age"),
            gender=profile_data.get("gender"),
            mbti=profile_data.get("mbti"),
            country=loc["country"],
            province=loc["province"],
            city=loc["city"],
            district=loc.get("district") or None,
            province_adcode=loc.get("province_adcode") or None,
            city_adcode=loc.get("city_adcode") or None,
            district_adcode=loc.get("district_adcode") or None,
            profession=profession,
            interested_topics=topics,
            source_entity_uuid=entity.uuid,
            source_entity_type=entity_type,
        )

    @staticmethod
    def _normalize_interested_topics(
        raw: Any,
        *,
        profession: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_summary: Optional[str] = None,
        bio: Optional[str] = None,
    ) -> List[str]:
        """规范化话题列表；LLM 漏返回时用职业/类型做轻量回填，避免 UI 恒为 0。"""
        topics: List[str] = []
        if isinstance(raw, list):
            topics = [str(t).strip() for t in raw if str(t or "").strip()]
        elif isinstance(raw, str) and raw.strip():
            topics = [x.strip() for x in re.split(r"[,，;；/|]", raw) if x.strip()]

        # 过滤过长/像句子的噪声
        topics = [t for t in topics if 1 < len(t) <= 16]
        if len(topics) >= 2:
            return topics[:8]

        fallback: List[str] = []
        for src in (profession, entity_type):
            s = str(src or "").strip()
            # 职业字段过长时取逗号/顿号前的短称
            if "，" in s or "," in s or "、" in s:
                s = re.split(r"[,，、]", s)[0].strip()
            if s and 1 < len(s) <= 16 and s not in fallback:
                fallback.append(s)

        # 仅从摘要抽短名词，不从整段 bio 切句
        blob = str(entity_summary or "")[:120]
        for token in re.findall(r"[\u4e00-\u9fff]{2,6}", blob):
            if token in fallback or token in topics:
                continue
            # 跳过常见虚词碎片
            if token in ("我们", "他们", "一个", "以及", "因为", "所以", "但是"):
                continue
            fallback.append(token)
            if len(fallback) >= 4:
                break

        merged = topics + [t for t in fallback if t not in topics]
        if len(merged) < 2:
            for extra in ("公共议题", "社会讨论", "本地生活"):
                if extra not in merged:
                    merged.append(extra)
                if len(merged) >= 2:
                    break
        return merged[:8]
    
    def _generate_username(self, name: str) -> str:
        """生成用户名"""
        # 移除特殊字符，转换为小写
        username = name.lower().replace(" ", "_")
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        
        # 添加随机后缀避免重复
        suffix = random.randint(100, 999)
        return f"{username}_{suffix}"
    
    def _search_zep_for_entity(self, entity: EntityNode) -> Dict[str, Any]:
        """
        使用Zep图谱混合搜索功能获取实体相关的丰富信息
        
        Zep没有内置混合搜索接口，需要分别搜索edges和nodes然后合并结果。
        使用并行请求同时搜索，提高效率。
        
        Args:
            entity: 实体节点对象
            
        Returns:
            包含facts, node_summaries, context的字典
        """
        import concurrent.futures
        
        if not self.zep_client:
            return {"facts": [], "node_summaries": [], "context": ""}
        
        entity_name = entity.name
        
        results = {
            "facts": [],
            "node_summaries": [],
            "context": ""
        }
        
        # 必须有graph_id才能进行搜索
        if not self.graph_id:
            logger.debug(f"跳过Zep检索：未设置graph_id")
            return results
        
        comprehensive_query = t('progress.zepSearchQuery', name=entity_name)
        
        def search_edges():
            """搜索边（事实/关系）- 带重试机制"""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=30,
                        scope="edges",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep边搜索第 {attempt + 1} 次失败: {str(e)[:80]}, 重试中...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep边搜索在 {max_retries} 次尝试后仍失败: {e}")
            return None
        
        def search_nodes():
            """搜索节点（实体摘要）- 带重试机制"""
            max_retries = 3
            last_exception = None
            delay = 2.0
            
            for attempt in range(max_retries):
                try:
                    return self.zep_client.graph.search(
                        query=comprehensive_query,
                        graph_id=self.graph_id,
                        limit=20,
                        scope="nodes",
                        reranker="rrf"
                    )
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.debug(f"Zep节点搜索第 {attempt + 1} 次失败: {str(e)[:80]}, 重试中...")
                        time.sleep(delay)
                        delay *= 2
                    else:
                        logger.debug(f"Zep节点搜索在 {max_retries} 次尝试后仍失败: {e}")
            return None
        
        try:
            # 并行执行edges和nodes搜索
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                edge_future = executor.submit(search_edges)
                node_future = executor.submit(search_nodes)
                
                # 获取结果
                edge_result = edge_future.result(timeout=30)
                node_result = node_future.result(timeout=30)
            
            # 处理边搜索结果
            all_facts = set()
            if edge_result and hasattr(edge_result, 'edges') and edge_result.edges:
                for edge in edge_result.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        all_facts.add(edge.fact)
            results["facts"] = list(all_facts)
            
            # 处理节点搜索结果
            all_summaries = set()
            if node_result and hasattr(node_result, 'nodes') and node_result.nodes:
                for node in node_result.nodes:
                    if hasattr(node, 'summary') and node.summary:
                        all_summaries.add(node.summary)
                    if hasattr(node, 'name') and node.name and node.name != entity_name:
                        all_summaries.add(f"相关实体: {node.name}")
            results["node_summaries"] = list(all_summaries)
            
            # 构建综合上下文
            context_parts = []
            if results["facts"]:
                context_parts.append("事实信息:\n" + "\n".join(f"- {f}" for f in results["facts"][:20]))
            if results["node_summaries"]:
                context_parts.append("相关实体:\n" + "\n".join(f"- {s}" for s in results["node_summaries"][:10]))
            results["context"] = "\n\n".join(context_parts)
            
            logger.info(f"Zep混合检索完成: {entity_name}, 获取 {len(results['facts'])} 条事实, {len(results['node_summaries'])} 个相关节点")
            
        except concurrent.futures.TimeoutError:
            logger.warning(f"Zep检索超时 ({entity_name})")
        except Exception as e:
            logger.warning(f"Zep检索失败 ({entity_name}): {e}")
        
        return results
    
    def _build_entity_context(self, entity: EntityNode) -> str:
        """
        构建实体的完整上下文信息
        
        包括：
        1. 实体本身的边信息（事实）
        2. 关联节点的详细信息
        3. Zep混合检索到的丰富信息
        """
        context_parts = []
        
        # 1. 添加实体属性信息
        if entity.attributes:
            attrs = []
            for key, value in entity.attributes.items():
                if value and str(value).strip():
                    attrs.append(f"- {key}: {value}")
            if attrs:
                context_parts.append("### 实体属性\n" + "\n".join(attrs))
        
        # 2. 添加相关边信息（事实/关系）
        existing_facts = set()
        if entity.related_edges:
            relationships = []
            for edge in entity.related_edges:  # 不限制数量
                fact = edge.get("fact", "")
                edge_name = edge.get("edge_name", "")
                direction = edge.get("direction", "")
                
                if fact:
                    relationships.append(f"- {fact}")
                    existing_facts.add(fact)
                elif edge_name:
                    if direction == "outgoing":
                        relationships.append(f"- {entity.name} --[{edge_name}]--> (相关实体)")
                    else:
                        relationships.append(f"- (相关实体) --[{edge_name}]--> {entity.name}")
            
            if relationships:
                context_parts.append("### 相关事实和关系\n" + "\n".join(relationships))
        
        # 3. 添加关联节点的详细信息
        if entity.related_nodes:
            related_info = []
            for node in entity.related_nodes:  # 不限制数量
                node_name = node.get("name", "")
                node_labels = node.get("labels", [])
                node_summary = node.get("summary", "")
                
                # 过滤掉默认标签
                custom_labels = [l for l in node_labels if l not in ["Entity", "Node"]]
                label_str = f" ({', '.join(custom_labels)})" if custom_labels else ""
                
                if node_summary:
                    related_info.append(f"- **{node_name}**{label_str}: {node_summary}")
                else:
                    related_info.append(f"- **{node_name}**{label_str}")
            
            if related_info:
                context_parts.append("### 关联实体信息\n" + "\n".join(related_info))
        
        # 4. 使用Zep混合检索获取更丰富的信息
        zep_results = self._search_zep_for_entity(entity)
        
        if zep_results.get("facts"):
            # 去重：排除已存在的事实
            new_facts = [f for f in zep_results["facts"] if f not in existing_facts]
            if new_facts:
                context_parts.append("### Zep检索到的事实信息\n" + "\n".join(f"- {f}" for f in new_facts[:15]))
        
        if zep_results.get("node_summaries"):
            context_parts.append("### Zep检索到的相关节点\n" + "\n".join(f"- {s}" for s in zep_results["node_summaries"][:10]))
        
        return "\n\n".join(context_parts)
    
    def _is_individual_entity(self, entity_type: str) -> bool:
        """判断是否是个人类型实体"""
        return entity_type.lower() in self.INDIVIDUAL_ENTITY_TYPES
    
    def _is_group_entity(self, entity_type: str) -> bool:
        """判断是否是群体/机构类型实体"""
        return entity_type.lower() in self.GROUP_ENTITY_TYPES
    
    def _generate_profile_with_llm(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        location_hint: Optional[Dict[str, Any]] = None,
        cast_anchor: Optional[Dict[str, Any]] = None,
        occupied_summary: Optional[str] = None,
        extra_constraint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        使用LLM生成非常详细的人设
        
        根据实体类型区分：
        - 个人实体：生成具体的人物设定
        - 群体/机构实体：生成代表性账号设定
        """
        
        is_individual = self._is_individual_entity(entity_type)
        
        if is_individual:
            prompt = self._build_individual_persona_prompt(
                entity_name,
                entity_type,
                entity_summary,
                entity_attributes,
                context,
                location_hint=location_hint,
            )
        else:
            prompt = self._build_group_persona_prompt(
                entity_name,
                entity_type,
                entity_summary,
                entity_attributes,
                context,
                location_hint=location_hint,
            )

        # 注入 Cast Sheet 锚点 / 已占位摘要 / 终审额外约束
        extras: List[str] = []
        if cast_anchor:
            extras.append(
                "### 分角契约（必须遵守，不得与同组撞车）\n"
                f"- role_slot: {cast_anchor.get('role_slot', '')}\n"
                f"- stance_axis: {cast_anchor.get('stance_axis', '')}\n"
                f"- voice: {cast_anchor.get('voice', '')}\n"
                f"- region_anchor: {cast_anchor.get('region_anchor', '')}\n"
                f"- must_not: {json.dumps(cast_anchor.get('must_not') or [], ensure_ascii=False)}\n"
                f"- similar_group: {cast_anchor.get('similar_group') or ''}"
            )
        if occupied_summary:
            extras.append(
                "### 全员分角清单（请刻意差异化，勿雷同）\n"
                f"{occupied_summary}"
            )
        if extra_constraint:
            extras.append(f"### 终审额外约束（强制遵守）\n{extra_constraint}")
        if extras:
            prompt = prompt + "\n\n" + "\n\n".join(extras)

        # 尝试多次生成，直到成功或达到最大重试次数
        max_attempts = 3
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                def _create():
                    return self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[
                            {"role": "system", "content": self._get_system_prompt(is_individual)},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.7 - (attempt * 0.1),  # 每次重试降低温度
                        max_tokens=2048,  # 短人设上限，防超长拖慢
                    )

                response = with_rate_limit_retry(_create)
                
                content = response.choices[0].message.content

                # 检查是否被截断（finish_reason不是'stop'）
                finish_reason = response.choices[0].finish_reason
                if finish_reason == 'length':
                    logger.warning(f"LLM输出被截断 (attempt {attempt+1}), 尝试修复...")
                    content = self._fix_truncated_json(content)

                try:
                    result = json.loads(content)

                    # 必需字段缺失视为失败，进入重试（禁止用空壳凑数）
                    bio = (result.get("bio") or "").strip() if isinstance(result.get("bio"), str) else result.get("bio")
                    persona = (result.get("persona") or "").strip() if isinstance(result.get("persona"), str) else result.get("persona")
                    if not bio or not persona:
                        raise ValueError("LLM 返回缺少 bio/persona")
                    # 拒绝明显空壳（EntityType: Name）
                    stub_bio = f"{entity_type}: {entity_name}"
                    if bio == stub_bio and len(str(persona)) < 80:
                        raise ValueError("LLM 返回疑似空壳人设")

                    return result

                except json.JSONDecodeError as je:
                    logger.warning(f"JSON解析失败 (attempt {attempt+1}): {str(je)[:80]}")

                    # 尝试修复JSON（仅接受真正修好的完整结果）
                    result = self._try_fix_json(content, entity_name, entity_type, entity_summary)
                    if result.get("_fixed"):
                        del result["_fixed"]
                        bio = (result.get("bio") or "").strip()
                        persona = (result.get("persona") or "").strip()
                        if bio and persona:
                            return result
                        last_error = ValueError("JSON 修复后仍缺少 bio/persona")
                    else:
                        last_error = je

                except ValueError as ve:
                    logger.warning(f"人设校验失败 (attempt {attempt+1}): {ve}")
                    last_error = ve

            except Exception as e:
                logger.warning(f"LLM调用失败 (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                time.sleep(1 * (attempt + 1))  # 指数退避
        
        logger.error(f"LLM生成人设失败（{max_attempts}次尝试）: {last_error}")
        raise RuntimeError(
            f"人设 LLM 生成失败（已禁用规则兜底）: {entity_name} / {entity_type}: {last_error}"
        ) from last_error
    
    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON（输出被max_tokens限制截断）"""
        import re
        
        # 如果JSON被截断，尝试闭合它
        content = content.strip()
        
        # 计算未闭合的括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查是否有未闭合的字符串
        # 简单检查：如果最后一个引号后没有逗号或闭合括号，可能是字符串被截断
        if content and content[-1] not in '",}]':
            # 尝试闭合字符串
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_json(self, content: str, entity_name: str, entity_type: str, entity_summary: str = "") -> Dict[str, Any]:
        """尝试修复损坏的JSON"""
        import re
        
        # 1. 首先尝试修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 2. 尝试提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 3. 处理字符串中的换行符问题
            # 找到所有字符串值并替换其中的换行符
            def fix_string_newlines(match):
                s = match.group(0)
                # 替换字符串内的实际换行符为空格
                s = s.replace('\n', ' ').replace('\r', ' ')
                # 替换多余空格
                s = re.sub(r'\s+', ' ', s)
                return s
            
            # 匹配JSON字符串值
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string_newlines, json_str)
            
            # 4. 尝试解析
            try:
                result = json.loads(json_str)
                result["_fixed"] = True
                return result
            except json.JSONDecodeError as e:
                # 5. 如果还是失败，尝试更激进的修复
                try:
                    # 移除所有控制字符
                    json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                    # 替换所有连续空白
                    json_str = re.sub(r'\s+', ' ', json_str)
                    result = json.loads(json_str)
                    result["_fixed"] = True
                    return result
                except:
                    pass
        
        # 修复失败：不返回空壳，交给上层重试/抛错
        logger.warning(f"JSON修复失败: {entity_name} ({entity_type})")
        return {}
    
    def _get_system_prompt(self, is_individual: bool) -> str:
        """获取系统提示词"""
        base_prompt = (
            "你是社交媒体用户画像生成专家。生成详细、真实的人设用于舆论模拟,最大程度还原已有现实情况。"
            "地域（省市区）是人格的一部分：你必须根据给定地名自行推断并写出地域人格，"
            "塑造语感、利益敏感点与政策第一反应；禁止只当地址标签，禁止套用外部模板文案。"
            "必须返回有效的JSON格式，所有字符串值不能包含未转义的换行符。"
            "硬性失败条件（违反即判失败）：bio 与 persona 都必须是非空字符串；"
            "禁止返回空壳人设（例如 bio 仅为「实体类型: 实体名」且 persona 过短）；"
            "interested_topics 必须为含 2-5 个非空关键词的数组（写在 persona 之前，避免被截断丢失）。"
        )
        return f"{base_prompt}\n\n{get_language_instruction()}"
    
    def _build_individual_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        location_hint: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建个人实体的详细人设提示词"""
        
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "无"
        context_str = context[:3000] if context else "无额外上下文"
        loc = location_hint or {}
        place = format_location_label(loc)
        loc_line = (
            f"预解析地域: {place}"
            f"（请写入 JSON 的 province/city/district；地域人格请你基于此地自行原创写入 persona，不要等待外部气质文案）"
        )
        
        return f"""为实体生成详细的社交媒体用户人设,最大程度还原已有现实情况。

实体名称: {entity_name}
实体类型: {entity_type}
实体摘要: {entity_summary}
实体属性: {attrs_str}
{loc_line}

上下文信息:
{context_str}

请生成JSON，包含以下字段（字段顺序请严格遵守，短字段在前，避免截断丢失）:

1. bio: 社交媒体简介，约100字（可点出本地身份）
2. interested_topics: 感兴趣话题数组，必须 2-5 个非空关键词（与事件/职业相关）
3. age: 年龄数字（必须是整数）
4. gender: 性别，必须是英文: "male" 或 "female"
5. mbti: MBTI类型（如INTJ、ENFP等）
6. country: 国家（必须为「中国」）
7. profession: 职业
8. persona: 详细人设描述（600-800字纯文本，勿超800字），需包含:
   - 基本信息（年龄、职业、所在地）与地域人格（基于「{place}」的语感/利益/对政策第一反应）
   - 与事件的关联、立场观点、社交媒体口吻
   - 一条关键个人记忆（与事件相关的已有动作或反应）
{location_instruction_for_llm()}

重要:
- 所有字段值必须是字符串或数字，不要使用换行符
- persona必须是一段连贯的文字描述，控制在600-800字
- {get_language_instruction()} (gender字段必须用英文male/female)
- 内容要与实体信息保持一致
- age必须是有效的整数，gender必须是"male"或"female"
- 硬性要求：bio、persona 均不得为空；interested_topics 必须 2-5 项；禁止空壳（bio 不能只是「{entity_type}: {entity_name}」这类占位，persona 须有实质内容）
"""

    def _build_group_persona_prompt(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        context: str,
        location_hint: Optional[Dict[str, Any]] = None,
    ) -> str:
        """构建群体/机构实体的详细人设提示词"""
        
        attrs_str = json.dumps(entity_attributes, ensure_ascii=False) if entity_attributes else "无"
        context_str = context[:3000] if context else "无额外上下文"
        loc = location_hint or {}
        place = format_location_label(loc)
        loc_line = (
            f"预解析地域: {place}"
            f"（请写入 JSON 的 province/city/district；辖区人格请你基于此地自行原创写入 persona）"
        )
        
        return f"""为机构/群体实体生成详细的社交媒体账号设定,最大程度还原已有现实情况。

实体名称: {entity_name}
实体类型: {entity_type}
实体摘要: {entity_summary}
实体属性: {attrs_str}
{loc_line}

上下文信息:
{context_str}

请生成JSON，包含以下字段（字段顺序请严格遵守，短字段在前，避免截断丢失）:

1. bio: 官方账号简介，约100字，专业得体
2. interested_topics: 关注领域数组，必须 2-5 个非空关键词（与机构职能/事件相关）
3. age: 固定填30（机构账号的虚拟年龄）
4. gender: 固定填"other"（机构账号使用other表示非个人）
5. mbti: MBTI类型，用于描述账号风格，如ISTJ代表严谨保守
6. country: 国家（必须为「中国」）
7. profession: 机构职能描述
8. persona: 详细账号设定描述（600-800字纯文本，勿超800字），需包含:
   - 机构职能/辖区与基于「{place}」的发言风格、利益立场
   - 账号定位、官方口吻、对核心话题立场
   - 一条与事件相关的机构记忆（已有动作或反应）
{location_instruction_for_llm()}

重要:
- 所有字段值必须是字符串或数字，不允许null值
- persona必须是一段连贯的文字描述，控制在600-800字，不要使用换行符
- {get_language_instruction()} (gender字段必须用英文"other")
- age必须是整数30，gender必须是字符串"other"
- 机构账号发言要符合其身份定位
- 硬性要求：bio、persona 均不得为空；interested_topics 必须 2-5 项；禁止空壳（bio 不能只是「{entity_type}: {entity_name}」这类占位，persona 须有实质内容）"""
    
    def _generate_profile_rule_based(
        self,
        entity_name: str,
        entity_type: str,
        entity_summary: str,
        entity_attributes: Dict[str, Any],
        location_hint: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """使用规则生成基础人设（无 LLM 时仅标注属地，不写死地域气质）"""
        
        # 根据实体类型生成不同的人设
        entity_type_lower = entity_type.lower()
        loc = location_hint or resolve_location(
            text=" ".join(
                [
                    entity_name,
                    entity_type,
                    entity_summary or "",
                    json.dumps(entity_attributes or {}, ensure_ascii=False),
                ]
            ),
            entity_type=entity_type,
            seed=entity_name,
        )
        place = format_location_label(loc)
        
        if entity_type_lower in ["student", "alumni"]:
            base_persona = f"{entity_name} is a {entity_type.lower()} who is actively engaged in academic and social discussions. They enjoy sharing perspectives and connecting with peers."
        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            base_persona = f"{entity_name} is a recognized {entity_type.lower()} who shares insights and opinions on important matters. They are known for their expertise and influence in public discourse."
        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            base_persona = f"{entity_name} is a media entity that reports news and facilitates public discourse. The account shares timely updates and engages with the audience on current events."
        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            base_persona = f"{entity_name} is an institutional entity that communicates official positions, announcements, and engages with stakeholders on relevant matters."
        else:
            base_persona = entity_summary or f"{entity_name} is a {entity_type.lower()} participating in social discussions."

        persona = f"{base_persona} Based in {place}."

        common_loc = {
            "country": loc["country"],
            "province": loc["province"],
            "city": loc["city"],
            "district": loc.get("district") or "",
            "province_adcode": loc.get("province_adcode") or "",
            "city_adcode": loc.get("city_adcode") or "",
            "district_adcode": loc.get("district_adcode") or "",
        }

        if entity_type_lower in ["student", "alumni"]:
            return {
                "bio": f"{entity_type} with interests in academics and social issues.",
                "persona": persona,
                "age": random.randint(18, 30),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                **common_loc,
                "profession": "Student",
                "interested_topics": ["Education", "Social Issues", "Technology"],
            }
        
        elif entity_type_lower in ["publicfigure", "expert", "faculty"]:
            return {
                "bio": f"Expert and thought leader in their field.",
                "persona": persona,
                "age": random.randint(35, 60),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(["ENTJ", "INTJ", "ENTP", "INTP"]),
                **common_loc,
                "profession": entity_attributes.get("occupation", "Expert"),
                "interested_topics": ["Politics", "Economics", "Culture & Society"],
            }
        
        elif entity_type_lower in ["mediaoutlet", "socialmediaplatform"]:
            return {
                "bio": f"Official account for {entity_name}. News and updates.",
                "persona": persona,
                "age": 30,
                "gender": "other",
                "mbti": "ISTJ",
                **common_loc,
                "profession": "Media",
                "interested_topics": ["General News", "Current Events", "Public Affairs"],
            }
        
        elif entity_type_lower in ["university", "governmentagency", "ngo", "organization"]:
            return {
                "bio": f"Official account of {entity_name}.",
                "persona": persona,
                "age": 30,
                "gender": "other",
                "mbti": "ISTJ",
                **common_loc,
                "profession": entity_type,
                "interested_topics": ["Public Policy", "Community", "Official Announcements"],
            }
        
        else:
            return {
                "bio": entity_summary[:150] if entity_summary else f"{entity_type}: {entity_name}",
                "persona": persona,
                "age": random.randint(25, 50),
                "gender": random.choice(["male", "female"]),
                "mbti": random.choice(self.MBTI_TYPES),
                **common_loc,
                "profession": entity_type,
                "interested_topics": ["General", "Social Issues"],
            }
    
    def set_graph_id(self, graph_id: str):
        """设置图谱ID用于Zep检索"""
        self.graph_id = graph_id

    def _planner_client(self) -> LLMClient:
        """前置/后置规划用独立模型（默认 qwen3.7-plus）。"""
        return LLMClient(model=Config.LLM_CAST_PLANNER_MODEL)

    def _entity_brief_for_cast(self, entity: EntityNode) -> Dict[str, Any]:
        etype = entity.get_entity_type() or "Entity"
        summary = (entity.summary or "")[:200]
        return {
            "entity_uuid": entity.uuid,
            "name": entity.name,
            "entity_type": etype,
            "summary": summary,
        }

    def plan_cast_sheet(
        self,
        entities: List[EntityNode],
        simulation_requirement: str = "",
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """
        前置 LLM：输出 Cast Sheet（分角表）。
        - 近似实体保留多人，强制差异槽位（similar_group）
        - 可用 excluded 裁剪不适合做 Agent 的实体（不得扩编，保留数≥1）
        """
        briefs = [self._entity_brief_for_cast(e) for e in entities]
        entity_uuids = {e.uuid for e in entities}
        client = self._planner_client()

        system_prompt = (
            "你是舆论模拟的分角导演。请为候选实体输出 Cast Sheet（JSON）。"
            "要求：1) 每个输入实体都必须出现在 agents 数组；"
            "2) 近似/重复实体保留多人，用同一 similar_group 标注；"
            "同一 similar_group 内任意两人的 role_slot 与 stance_axis 的组合必须互不相同"
            "（仅 voice 不同不算差异，必须在 role_slot 或 stance_axis 至少一项上错开）；"
            "3) 不适合做社交媒体 Agent 的实体（纯地点、抽象概念、政策文件等）可设 excluded=true 并给 exclude_reason；"
            "4) 不得扩编（不得新增实体）；保留至少 1 个非 excluded；"
            "5) 只返回 JSON 对象，不要 markdown。"
            f"\n{get_language_instruction()}"
        )
        user_prompt = (
            f"模拟需求：{simulation_requirement or '（未提供，按实体信息推断）'}\n\n"
            f"候选实体 JSON：\n{json.dumps(briefs, ensure_ascii=False)}\n\n"
            "返回 JSON 格式：\n"
            "{\n"
            '  "cast_theme": "...",\n'
            '  "agents": [\n'
            "    {\n"
            '      "entity_uuid": "...",\n'
            '      "name": "...",\n'
            '      "role_slot": "...",\n'
            '      "stance_axis": "...",\n'
            '      "voice": "...",\n'
            '      "region_anchor": "...",\n'
            '      "must_not": ["..."],\n'
            '      "similar_group": null,\n'
            '      "excluded": false,\n'
            '      "exclude_reason": ""\n'
            "    }\n"
            "  ],\n"
            '  "conflict_pairs": [["nameA", "nameB"]]\n'
            "}"
        )

        last_error: Optional[Exception] = None
        prev_raw: Optional[Dict[str, Any]] = None
        for attempt in range(max_attempts):
            raw: Optional[Dict[str, Any]] = None
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                # 带着上一次的输出和校验错误重试，只让模型修正违规处，避免盲目重跑撞同样的错
                if prev_raw is not None and last_error is not None:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"你上一次输出的 Cast Sheet JSON 未通过校验，错误：{last_error}\n"
                                "上一次输出：\n"
                                f"{json.dumps(prev_raw, ensure_ascii=False)[:6000]}\n"
                                "请在保持其余内容不变的前提下修正违规部分，重新返回完整 JSON。"
                            ),
                        }
                    )
                raw = client.chat_json(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=8192,
                )
                sheet = self._validate_cast_sheet(raw, entity_uuids, entities)
                return sheet
            except Exception as e:
                last_error = e
                if isinstance(raw, dict):
                    prev_raw = raw
                logger.warning(f"Cast Sheet 规划失败 (attempt {attempt+1}): {e}")
                time.sleep(1 * (attempt + 1))

        # 严格校验多次未过：部分打捞——保留合法条目，剔除非法条目
        # （未覆盖的实体只是没有分角锚点，仍会正常生成人设）
        if isinstance(prev_raw, dict):
            try:
                sheet = self._validate_cast_sheet(
                    prev_raw, entity_uuids, entities, salvage=True
                )
                logger.warning(
                    f"Cast Sheet 严格校验未通过，已部分打捞：覆盖 "
                    f"{len(sheet['agents'])}/{len(entities)} 个实体，其余无分角锚点"
                )
                return sheet
            except Exception as e2:
                logger.warning(f"Cast Sheet 部分打捞失败: {e2}")

        raise RuntimeError(f"Cast Sheet 规划失败（已重试 {max_attempts} 次）: {last_error}") from last_error

    def _validate_cast_sheet(
        self,
        raw: Dict[str, Any],
        entity_uuids: set,
        entities: List[EntityNode],
        salvage: bool = False,
    ) -> Dict[str, Any]:
        """
        salvage=False：严格模式，任何违规抛错（供重试反馈）。
        salvage=True：打捞模式，保留合法条目、剔除非法条目，尽量不抛错。
        """
        agents = raw.get("agents")
        if not isinstance(agents, list) or not agents:
            raise ValueError("Cast Sheet 缺少 agents")

        by_uuid: Dict[str, Dict[str, Any]] = {}
        for row in agents:
            if not isinstance(row, dict):
                continue
            uid = row.get("entity_uuid")
            if not uid or uid not in entity_uuids:
                continue  # 丢弃未知 uuid
            by_uuid[uid] = row

        if not by_uuid:
            raise ValueError("Cast Sheet 无任何合法实体条目")

        missing = entity_uuids - set(by_uuid.keys())
        if missing and not salvage:
            raise ValueError(f"Cast Sheet 未覆盖实体: {list(missing)[:5]}")

        # similar_group 槽位互斥：撞车时本地自动错开，不再抛错重调 LLM
        group_slot_owners: Dict[str, Dict[tuple, List[str]]] = {}
        for uid, row in by_uuid.items():
            if row.get("excluded"):
                continue
            g = row.get("similar_group")
            if not g:
                continue
            key = str(g)
            slot = (
                str(row.get("role_slot") or "").strip().lower(),
                str(row.get("stance_axis") or "").strip().lower(),
            )
            owners = group_slot_owners.setdefault(key, {})
            names = owners.setdefault(slot, [])
            name = str(row.get("name") or uid)
            names.append(name)
            if len(names) == 1:
                continue
            # 与组内首个占位者撞槽位：改写立场侧重 + 追加 must_not 差异化约束
            first_name = names[0]
            base_stance = str(row.get("stance_axis") or "").strip()
            row["stance_axis"] = (
                f"{base_stance}（同组变体{len(names)}：立场侧重须与{first_name}明显不同）"
            )
            must_not = list(row.get("must_not") or [])
            must_not.append(f"与同组「{first_name}」的立场表述、经历、口吻雷同")
            row["must_not"] = must_not
            logger.warning(
                f"Cast Sheet 本地修复: similar_group={key} 内 {name} 与 {first_name} "
                f"槽位重复，已自动错开立场侧重"
            )

        kept = [r for r in by_uuid.values() if not r.get("excluded")]
        if len(kept) < 1:
            if salvage:
                # 打捞模式：模型把所有人都 excluded 了不可信，忽略其裁剪意见
                for row in by_uuid.values():
                    row["excluded"] = False
                    row["exclude_reason"] = ""
            else:
                raise ValueError("Cast Sheet 裁剪后无人保留（至少保留 1 人）")
        if len(kept) > len(entities):
            raise ValueError("Cast Sheet 不得扩编")

        name_by_uuid = {e.uuid: e.name for e in entities}
        for uid, row in by_uuid.items():
            row.setdefault("name", name_by_uuid.get(uid, ""))
            row.setdefault("must_not", [])
            row.setdefault("excluded", False)
            row.setdefault("exclude_reason", "")

        return {
            "cast_theme": raw.get("cast_theme") or "",
            "agents": list(by_uuid.values()),
            "agents_by_uuid": by_uuid,
            "conflict_pairs": raw.get("conflict_pairs") or [],
            "excluded": [
                {
                    "entity_uuid": r["entity_uuid"],
                    "name": r.get("name", ""),
                    "exclude_reason": r.get("exclude_reason") or "",
                }
                for r in by_uuid.values()
                if r.get("excluded")
            ],
        }

    def _profile_one_line_summary(self, profile: OasisAgentProfile, cast: Optional[Dict[str, Any]] = None) -> str:
        slot = (cast or {}).get("role_slot") or profile.profession or ""
        stance = (cast or {}).get("stance_axis") or ""
        bio = (profile.bio or "")[:80]
        return f"{profile.name}|{slot}|{stance}|{bio}"


    def _build_static_roster(
        self,
        work_entities: List[EntityNode],
        agents_by_uuid: Dict[str, Dict[str, Any]],
    ) -> str:
        """静态全员清单：姓名｜role_slot｜stance_axis（生成前即可确定，无需批间等待）。"""
        lines: List[str] = []
        for e in work_entities:
            cast = agents_by_uuid.get(e.uuid) or {}
            slot = str(cast.get("role_slot") or "").strip()
            stance = str(cast.get("stance_axis") or "").strip()
            if slot or stance:
                lines.append(f"{e.name}|{slot}|{stance}")
            else:
                # Cast Sheet 失败降级：仅实体名清单
                lines.append(e.name)
        return "\n".join(lines)

    def _persona_similarity(self, a: str, b: str) -> float:
        """本地 persona 相似度：SequenceMatcher ratio。"""
        from difflib import SequenceMatcher
        a = (a or "").strip()
        b = (b or "").strip()
        if not a or not b:
            return 0.0
        # 截断超长文本，避免极端耗时
        a = a[:4000]
        b = b[:4000]
        return SequenceMatcher(None, a, b).ratio()

    def _local_dedup_check(
        self,
        profiles: List[OasisAgentProfile],
        cast_sheet: Dict[str, Any],
        threshold: Optional[float] = None,
        max_regen: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        本地相似度查重（零 LLM 成本）。
        同 similar_group 内两两比较；无分组时全员两两。
        超阈值则保留先出现者，后者列入重生成（附点名约束）；截断至 max_regen。
        """
        if threshold is None:
            threshold = float(getattr(Config, "PROFILE_DEDUP_THRESHOLD", 0.60) or 0.60)
        if max_regen is None:
            max_regen = max(1, int(getattr(Config, "LLM_PROFILE_REVIEW_MAX_REGEN", 3) or 3))

        agents_by_uuid = cast_sheet.get("agents_by_uuid") or {}
        groups: Dict[str, List[OasisAgentProfile]] = {}
        ungrouped: List[OasisAgentProfile] = []
        for p in profiles:
            cast = agents_by_uuid.get(p.source_entity_uuid or "", {}) or {}
            sg = str(cast.get("similar_group") or "").strip()
            if sg:
                groups.setdefault(sg, []).append(p)
            else:
                ungrouped.append(p)

        if groups:
            pair_lists: List[List[OasisAgentProfile]] = list(groups.values())
            if len(ungrouped) > 1:
                pair_lists.append(ungrouped)
        else:
            pair_lists = [list(profiles)]

        flagged: Dict[str, Dict[str, Any]] = {}
        for group in pair_lists:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    keep, drop = group[i], group[j]
                    ratio = self._persona_similarity(keep.persona or "", drop.persona or "")
                    if ratio < threshold:
                        continue
                    uid_drop = drop.source_entity_uuid or ""
                    if not uid_drop or uid_drop in flagged:
                        continue
                    # 若 keep 已被标记为需重生成，则与下一对继续比
                    if (keep.source_entity_uuid or "") in flagged:
                        continue
                    flagged[uid_drop] = {
                        "entity_uuid": uid_drop,
                        "reason": (
                            f"与「{keep.name}」persona 相似度 {ratio:.2f} 超阈值 {threshold}"
                        ),
                        "extra_constraint": (
                            f"本地查重：与「{keep.name}」人设过于相似（相似度{ratio:.2f}）。"
                            f"请刻意错开立场侧重、个人经历与社交媒体口吻，禁止雷同表述。"
                        ),
                        "similarity": ratio,
                    }
                    logger.info(
                        f"本地查重命中: {drop.name} ≈ {keep.name} "
                        f"(ratio={ratio:.2f} ≥ {threshold})"
                    )

        rows = sorted(
            flagged.values(),
            key=lambda r: float(r.get("similarity") or 0),
            reverse=True,
        )
        if len(rows) > max_regen:
            logger.info(
                f"本地查重 regenerate={len(rows)} 超上限 {max_regen}，截断"
            )
            rows = rows[:max_regen]
        for r in rows:
            r.pop("similarity", None)
        if rows:
            logger.info(f"本地查重需重生成 {len(rows)} 人")
        else:
            logger.info("本地查重通过，无需重生成")
        return rows

    def review_cast(
        self,
        profiles: List[OasisAgentProfile],
        cast_sheet: Dict[str, Any],
        excluded: List[Dict[str, Any]],
        max_attempts: int = 2,
        max_regen: Optional[int] = None,
    ) -> Dict[str, Any]:
        """后置终审：只点名不重写。默认从宽，仅打回硬伤。"""
        if max_regen is None:
            max_regen = max(1, int(getattr(Config, "LLM_PROFILE_REVIEW_MAX_REGEN", 3) or 3))
        agents_by_uuid = cast_sheet.get("agents_by_uuid") or {}
        roster = []
        for p in profiles:
            cast = agents_by_uuid.get(p.source_entity_uuid or "", {})
            roster.append({
                "entity_uuid": p.source_entity_uuid,
                "name": p.name,
                "role_slot": cast.get("role_slot", ""),
                "stance_axis": cast.get("stance_axis", ""),
                "voice": cast.get("voice", ""),
                "bio": (p.bio or "")[:120],
                "persona_head": (p.persona or "")[:200],
            })

        client = self._planner_client()
        system_prompt = (
            "你是人设终审官。通读全员摘要与被裁名单，只点名硬伤，不要重写人设，不要追求完美。\n"
            "判定从宽：措辞相近、结构相似、同主题关注点重叠 → 一律放行（pass）。\n"
            "仅在以下硬伤时列入 regenerate（总数尽量少，最多 "
            f"{max_regen} 条）：\n"
            "1) 两个人设几乎逐字雷同或姓名/身份明显串戏；\n"
            "2) 明确违反分角契约（role_slot/stance 写反成对立阵营）；\n"
            "3) 人设为空壳/明显不可用。\n"
            "restore_excluded 仅用于「模拟需求核心当事人被误裁」；没有把握就不要 restore。\n"
            "有疑虑时优先 verdict=pass。\n"
            "返回 JSON：{\"verdict\":\"pass|revise\","
            "\"regenerate\":[{\"entity_uuid\",\"reason\",\"extra_constraint\"}],"
            "\"restore_excluded\":[{\"entity_uuid\",\"reason\"}]}"
            f"\n{get_language_instruction()}"
        )
        user_prompt = (
            f"cast_theme: {cast_sheet.get('cast_theme', '')}\n"
            f"打回上限：regenerate ≤ {max_regen}；超过请只保留最严重的。\n"
            f"全员摘要 JSON：\n{json.dumps(roster, ensure_ascii=False)}\n\n"
            f"被裁名单 JSON：\n{json.dumps(excluded, ensure_ascii=False)}\n"
        )

        last_error: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                raw = client.chat_json(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2048,
                )
                verdict = raw.get("verdict") or "pass"
                regenerate = raw.get("regenerate") if isinstance(raw.get("regenerate"), list) else []
                restore = raw.get("restore_excluded") if isinstance(raw.get("restore_excluded"), list) else []
                # 过滤未知 uuid
                known = {p.source_entity_uuid for p in profiles} | {
                    e.get("entity_uuid") for e in excluded
                }
                regenerate = [r for r in regenerate if isinstance(r, dict) and r.get("entity_uuid") in known]
                restore = [r for r in restore if isinstance(r, dict) and r.get("entity_uuid") in known]
                # 硬上限：防止终审把大半人设打回重跑
                if len(regenerate) > max_regen:
                    logger.info(
                        f"人设终审 regenerate={len(regenerate)} 超上限 {max_regen}，截断"
                    )
                    regenerate = regenerate[:max_regen]
                if len(restore) > max_regen:
                    restore = restore[:max_regen]
                if verdict not in ("pass", "revise"):
                    verdict = "revise" if (regenerate or restore) else "pass"
                if not regenerate and not restore:
                    verdict = "pass"
                return {
                    "verdict": verdict,
                    "regenerate": regenerate,
                    "restore_excluded": restore,
                }
            except Exception as e:
                last_error = e
                logger.warning(f"人设终审失败 (attempt {attempt+1}): {e}")
                time.sleep(1 * (attempt + 1))

        logger.warning(f"人设终审放弃，带意见放行: {last_error}")
        return {"verdict": "pass", "regenerate": [], "restore_excluded": [], "review_error": str(last_error)}

    def generate_profiles_from_entities(
        self,
        entities: List[EntityNode],
        use_llm: bool = True,
        progress_callback: Optional[callable] = None,
        graph_id: Optional[str] = None,
        parallel_count: int = 5,
        realtime_output_path: Optional[str] = None,
        output_platform: str = "reddit",
        simulation_requirement: str = "",
    ) -> List[OasisAgentProfile]:
        """
        批量从实体生成Agent Profile：
        Cast Sheet 前置 → 静态 roster 全并行生成 → 本地查重点名重生成
        （LLM 终审默认关闭，LLM_PROFILE_REVIEW_ROUNDS>0 时追加）
        """
        import concurrent.futures
        from threading import Lock

        if graph_id:
            self.graph_id = graph_id

        if not entities:
            return []

        # ---------- 前置：Cast Sheet ----------
        cast_sheet: Dict[str, Any] = {
            "cast_theme": "",
            "agents": [],
            "agents_by_uuid": {},
            "excluded": [],
        }
        if use_llm:
            if progress_callback:
                progress_callback(0, max(len(entities), 1), t("progress.planningCastSheet"))
            try:
                cast_sheet = self.plan_cast_sheet(entities, simulation_requirement=simulation_requirement)
                logger.info(
                    f"Cast Sheet 完成: theme={cast_sheet.get('cast_theme')!r}, "
                    f"kept={len(entities) - len(cast_sheet.get('excluded') or [])}, "
                    f"excluded={len(cast_sheet.get('excluded') or [])}"
                )
            except Exception as e:
                # 降级：Cast Sheet 不做关键路径门卫。失败则退回
                # 「实体名 roster + 全并行 + 本地查重」路径继续生成，不终止 prepare
                logger.warning(f"Cast Sheet 规划失败，降级为无分角表生成: {e}")

        agents_by_uuid: Dict[str, Dict[str, Any]] = cast_sheet.get("agents_by_uuid") or {}
        excluded_list: List[Dict[str, Any]] = list(cast_sheet.get("excluded") or [])
        excluded_uuids = {e["entity_uuid"] for e in excluded_list}

        # 保留实体（顺序稳定）
        work_entities = [e for e in entities if e.uuid not in excluded_uuids]
        if not work_entities:
            raise RuntimeError("Cast Sheet 裁剪后无人可生成人设")

        # uuid -> 稳定 user_id（按原始 entities 下标，保证与模拟 agent_id 可对齐）
        uuid_to_idx = {e.uuid: i for i, e in enumerate(entities)}

        total = len(work_entities)
        # Cast Sheet 裁剪后立刻回传准确总数，供 UI 预期 / state.entities_count 下调
        if progress_callback:
            progress_callback(0, total, t("progress.startGenerating"))
        profiles_by_uuid: Dict[str, OasisAgentProfile] = {}
        lock = Lock()
        current_locale = get_locale()

        def save_profiles_realtime():
            if not realtime_output_path:
                return
            with lock:
                existing = list(profiles_by_uuid.values())
                if not existing:
                    return
                try:
                    if output_platform == "reddit":
                        with open(realtime_output_path, "w", encoding="utf-8") as f:
                            json.dump(
                                [p.to_reddit_format() for p in existing],
                                f,
                                ensure_ascii=False,
                                indent=2,
                            )
                    else:
                        import csv
                        data = [p.to_twitter_format() for p in existing]
                        if data:
                            with open(realtime_output_path, "w", encoding="utf-8", newline="") as f:
                                writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                                writer.writeheader()
                                writer.writerows(data)
                except Exception as e:
                    logger.warning(f"实时保存 profiles 失败: {e}")

        # 静态 roster：全员分角清单，生成前即可确定（无批间栅栏）
        static_roster = self._build_static_roster(work_entities, agents_by_uuid)

        def generate_one(
            entity: EntityNode,
            occupied: str,
            extra_constraint: Optional[str] = None,
        ) -> OasisAgentProfile:
            set_locale(current_locale)
            cast = agents_by_uuid.get(entity.uuid)
            profile = self.generate_profile_from_entity(
                entity=entity,
                user_id=uuid_to_idx.get(entity.uuid, 0),
                use_llm=use_llm,
                cast_anchor=cast,
                occupied_summary=occupied or None,
                extra_constraint=extra_constraint,
            )
            self._print_generated_profile(
                entity.name, entity.get_entity_type() or "Entity", profile
            )
            return profile

        def run_parallel(
            batch_entities: List[EntityNode],
            constraints: Optional[Dict[str, str]] = None,
            occupied: Optional[str] = None,
        ) -> None:
            """全并行提交；单个失败即整体报错（保留原有语义）。"""
            constraints = constraints or {}
            occupied_summary = occupied if occupied is not None else static_roster
            errors: List[str] = []

            def worker(ent: EntityNode):
                return ent.uuid, generate_one(
                    ent, occupied_summary, constraints.get(ent.uuid)
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_count) as executor:
                futures = {executor.submit(worker, ent): ent for ent in batch_entities}
                for future in concurrent.futures.as_completed(futures):
                    ent = futures[future]
                    try:
                        uid, profile = future.result()
                        with lock:
                            profiles_by_uuid[uid] = profile
                        save_profiles_realtime()
                        if progress_callback:
                            progress_callback(
                                len(profiles_by_uuid),
                                total,
                                f"已完成 {len(profiles_by_uuid)}/{total}: {ent.name}",
                            )
                    except Exception as e:
                        errors.append(f"{ent.name}: {e}")
                        for pending in futures:
                            pending.cancel()
                        break
            if errors:
                raise RuntimeError(
                    f"人设生成失败（已禁用空壳兜底，可手动重试）: {'; '.join(errors)}"
                )

        logger.info(
            f"开始全并行生成 {total} 个Agent人设"
            f"（并行数: {parallel_count}，静态 roster，无批间栅栏）..."
        )
        print(f"\n{'='*60}")
        print(f"开始生成Agent人设 - 共 {total} 个实体，并行数: {parallel_count}")
        print(f"{'='*60}\n")

        # ---------- 全并行生成（无批间串行栅栏） ----------
        run_parallel(work_entities)

        max_regen = max(1, int(getattr(Config, "LLM_PROFILE_REVIEW_MAX_REGEN", 3) or 3))
        entity_by_uuid = {e.uuid: e for e in entities}

        # ---------- 本地相似度查重（替代默认 LLM 终审） ----------
        if progress_callback:
            progress_callback(total, total, "本地查重中…")
        dedup_rows = self._local_dedup_check(
            profiles=list(profiles_by_uuid.values()),
            cast_sheet=cast_sheet,
            max_regen=max_regen,
        )
        if dedup_rows:
            constraints = {
                r["entity_uuid"]: (r.get("extra_constraint") or r.get("reason") or "")
                for r in dedup_rows
                if r.get("entity_uuid")
            }
            regen_entities = [
                entity_by_uuid[uid]
                for uid in constraints
                if uid in entity_by_uuid
            ]
            logger.info(f"本地查重点名重生成 {len(regen_entities)} 人（仅一轮）")
            for ent in regen_entities:
                profiles_by_uuid.pop(ent.uuid, None)
            if regen_entities:
                run_parallel(regen_entities, constraints)

        # ---------- LLM 终审（opt-in：默认 LLM_PROFILE_REVIEW_ROUNDS=0） ----------
        max_review = max(0, int(Config.LLM_PROFILE_REVIEW_ROUNDS or 0))
        if max_review <= 0:
            logger.info("人设 LLM 终审已关闭（LLM_PROFILE_REVIEW_ROUNDS=0），跳过")
        for review_round in range(max_review):
            if progress_callback:
                progress_callback(
                    total,
                    total,
                    t("progress.reviewingProfiles", round=review_round + 1, max=max_review),
                )
            review = self.review_cast(
                profiles=list(profiles_by_uuid.values()),
                cast_sheet=cast_sheet,
                excluded=excluded_list,
                max_regen=max_regen,
            )
            if review.get("verdict") == "pass":
                logger.info(f"人设终审通过（round {review_round + 1}）")
                break

            regenerate_rows = review.get("regenerate") or []
            restore_rows = review.get("restore_excluded") or []
            logger.info(
                f"人设终审 revise round={review_round + 1}: "
                f"regenerate={len(regenerate_rows)} restore={len(restore_rows)} "
                f"(cap={max_regen})"
            )

            # 恢复误裁
            for row in restore_rows:
                uid = row.get("entity_uuid")
                ent = entity_by_uuid.get(uid)
                if not ent or uid in profiles_by_uuid:
                    continue
                excluded_list = [e for e in excluded_list if e.get("entity_uuid") != uid]
                excluded_uuids.discard(uid)
                if uid not in agents_by_uuid:
                    agents_by_uuid[uid] = {
                        "entity_uuid": uid,
                        "name": ent.name,
                        "role_slot": "restored_party",
                        "stance_axis": "to_be_differentiated",
                        "voice": "authentic",
                        "must_not": [],
                        "excluded": False,
                    }
                profiles_by_uuid[uid] = generate_one(
                    ent,
                    static_roster,
                    extra_constraint=row.get("reason")
                    or "终审要求恢复：请生成差异化核心当事人人设",
                )
                save_profiles_realtime()

            constraints = {
                r["entity_uuid"]: (r.get("extra_constraint") or r.get("reason") or "")
                for r in regenerate_rows
                if r.get("entity_uuid")
            }
            regen_entities = [
                entity_by_uuid[uid]
                for uid in constraints
                if uid in entity_by_uuid
            ]
            if regen_entities:
                for ent in regen_entities:
                    profiles_by_uuid.pop(ent.uuid, None)
                run_parallel(regen_entities, constraints)

            # 只审一轮时，重生成后不再二审（避免连环打回）
            if review_round == max_review - 1:
                if regenerate_rows or restore_rows:
                    logger.info(
                        f"人设终审结束（{max_review} 轮）：已按意见重生成后放行，"
                        f"不再二次打回"
                    )
                break

        # 按原始 entities 顺序输出（跳过仍 excluded 的）
        final_excluded = {e["entity_uuid"] for e in excluded_list}
        ordered: List[OasisAgentProfile] = []
        for e in entities:
            if e.uuid in final_excluded and e.uuid not in profiles_by_uuid:
                continue
            p = profiles_by_uuid.get(e.uuid)
            if p is not None:
                ordered.append(p)

        if not ordered:
            raise RuntimeError("人设生成失败：无有效 Profile")

        # 重新编号 user_id 为连续 0..n-1（下游 agent_id 依赖顺序）
        for i, p in enumerate(ordered):
            p.user_id = i

        if excluded_list and progress_callback:
            names = ", ".join(
                f"{e.get('name')}({e.get('exclude_reason') or 'excluded'})"
                for e in excluded_list
                if e.get("entity_uuid") not in profiles_by_uuid
            )
            if names:
                progress_callback(
                    len(ordered),
                    len(ordered),
                    t("progress.castExcluded", names=names[:200]),
                )

        self.last_cast_sheet = cast_sheet
        self.last_excluded = [
            e for e in excluded_list if e.get("entity_uuid") not in profiles_by_uuid
        ]

        print(f"\n{'='*60}")
        print(f"人设生成完成！共生成 {len(ordered)} 个Agent（裁剪 {len(self.last_excluded)}）")
        print(f"{'='*60}\n")

        return ordered

    def _print_generated_profile(self, entity_name: str, entity_type: str, profile: OasisAgentProfile):
        """实时输出生成的人设到控制台（完整内容，不截断）"""
        separator = "-" * 70
        topics_str = ', '.join(profile.interested_topics) if profile.interested_topics else '无'
        output_lines = [
            f"\n{separator}",
            t('progress.profileGenerated', name=entity_name, type=entity_type),
            f"{separator}",
            f"用户名: {profile.user_name}",
            f"",
            f"【简介】",
            f"{profile.bio}",
            f"",
            f"【详细人设】",
            f"{profile.persona}",
            f"",
            f"【基本属性】",
            f"年龄: {profile.age} | 性别: {profile.gender} | MBTI: {profile.mbti}",
            f"职业: {profile.profession} | 国家: {profile.country} | {profile.province}/{profile.city}/{profile.district or '-'} ({profile.city_adcode or ''}/{profile.district_adcode or ''})",
            f"兴趣话题: {topics_str}",
            separator
        ]
        print("\n".join(output_lines))

    
    def save_profiles(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """
        保存Profile到文件（根据平台选择正确格式）
        
        OASIS平台格式要求：
        - Twitter: CSV格式
        - Reddit: JSON格式
        
        Args:
            profiles: Profile列表
            file_path: 文件路径
            platform: 平台类型 ("reddit" 或 "twitter")
        """
        if platform == "twitter":
            self._save_twitter_csv(profiles, file_path)
        else:
            self._save_reddit_json(profiles, file_path)
    
    def _save_twitter_csv(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Twitter Profile为CSV格式（符合OASIS官方要求）
        
        OASIS Twitter要求的CSV字段：
        - user_id: 用户ID（根据CSV顺序从0开始）
        - name: 用户真实姓名
        - username: 系统中的用户名
        - user_char: 详细人设描述（注入到LLM系统提示中，指导Agent行为）
        - description: 简短的公开简介（显示在用户资料页面）
        
        user_char vs description 区别：
        - user_char: 内部使用，LLM系统提示，决定Agent如何思考和行动
        - description: 外部显示，其他用户可见的简介
        """
        import csv
        
        # 确保文件扩展名是.csv
        if not file_path.endswith('.csv'):
            file_path = file_path.replace('.json', '.csv')
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # 写入OASIS要求的表头
            headers = ['user_id', 'name', 'username', 'user_char', 'description']
            writer.writerow(headers)
            
            # 写入数据行
            for idx, profile in enumerate(profiles):
                # user_char: 完整人设（bio + persona），用于LLM系统提示
                user_char = profile.bio
                if profile.persona and profile.persona != profile.bio:
                    user_char = f"{profile.bio} {profile.persona}"
                # 处理换行符（CSV中用空格替代）
                user_char = user_char.replace('\n', ' ').replace('\r', ' ')
                
                # description: 简短简介，用于外部显示
                description = profile.bio.replace('\n', ' ').replace('\r', ' ')
                
                row = [
                    idx,                    # user_id: 从0开始的顺序ID
                    profile.name,           # name: 真实姓名
                    profile.user_name,      # username: 用户名
                    user_char,              # user_char: 完整人设（内部LLM使用）
                    description             # description: 简短简介（外部显示）
                ]
                writer.writerow(row)
        
        logger.info(f"已保存 {len(profiles)} 个Twitter Profile到 {file_path} (OASIS CSV格式)")
    
    def _normalize_gender(self, gender: Optional[str]) -> str:
        """
        标准化gender字段为OASIS要求的英文格式
        
        OASIS要求: male, female, other
        """
        if not gender:
            return "other"
        
        gender_lower = gender.lower().strip()
        
        # 中文映射
        gender_map = {
            "男": "male",
            "女": "female",
            "机构": "other",
            "其他": "other",
            # 英文已有
            "male": "male",
            "female": "female",
            "other": "other",
        }
        
        return gender_map.get(gender_lower, "other")
    
    def _save_reddit_json(self, profiles: List[OasisAgentProfile], file_path: str):
        """
        保存Reddit Profile为JSON格式
        
        使用与 to_reddit_format() 一致的格式，确保 OASIS 能正确读取。
        必须包含 user_id 字段，这是 OASIS agent_graph.get_agent() 匹配的关键！
        
        必需字段：
        - user_id: 用户ID（整数，用于匹配 initial_posts 中的 poster_agent_id）
        - username: 用户名
        - name: 显示名称
        - bio: 简介
        - persona: 详细人设
        - age: 年龄（整数）
        - gender: "male", "female", 或 "other"
        - mbti: MBTI类型
        - country: 国家
        """
        data = []
        for idx, profile in enumerate(profiles):
            # 使用与 to_reddit_format() 一致的格式
            item = {
                "user_id": profile.user_id if profile.user_id is not None else idx,  # 关键：必须包含 user_id
                "username": profile.user_name,
                "name": profile.name,
                "bio": profile.bio[:150] if profile.bio else f"{profile.name}",
                "persona": profile.persona or f"{profile.name} is a participant in social discussions.",
                "karma": profile.karma if profile.karma else 1000,
                "created_at": profile.created_at,
                # OASIS必需字段 - 确保都有默认值
                "age": profile.age if profile.age else 30,
                "gender": self._normalize_gender(profile.gender),
                "mbti": profile.mbti if profile.mbti else "ISTJ",
                "country": profile.country if profile.country else "中国",
                "province": profile.province or "",
                "city": profile.city or "",
                "district": profile.district or "",
                "province_adcode": profile.province_adcode or "",
                "city_adcode": profile.city_adcode or "",
                "district_adcode": profile.district_adcode or "",
            }
            
            # 可选字段
            if profile.profession:
                item["profession"] = profile.profession
            item["interested_topics"] = list(profile.interested_topics or [])
            
            data.append(item)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已保存 {len(profiles)} 个Reddit Profile到 {file_path} (JSON格式，包含user_id字段)")
    
    # 保留旧方法名作为别名，保持向后兼容
    def save_profiles_to_json(
        self,
        profiles: List[OasisAgentProfile],
        file_path: str,
        platform: str = "reddit"
    ):
        """[已废弃] 请使用 save_profiles() 方法"""
        logger.warning("save_profiles_to_json已废弃，请使用save_profiles方法")
        self.save_profiles(profiles, file_path, platform)

