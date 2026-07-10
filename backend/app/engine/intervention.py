"""
干预 DSL：描述初始帖与投放者提示，并 patch 到 simulation_config
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class InitialPost:
    content: str
    poster_hint: str = "official"
    poster_agent_id: Optional[int] = None
    poster_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "content": self.content,
            "poster_hint": self.poster_hint,
        }
        if self.poster_agent_id is not None:
            d["poster_agent_id"] = self.poster_agent_id
        if self.poster_keywords:
            d["poster_keywords"] = self.poster_keywords
        return d


@dataclass
class Intervention:
    """一次干预：一组初始帖 + 可选元数据。"""

    name: str = ""
    kind: str = "custom"
    initial_posts: List[InitialPost] = field(default_factory=list)
    hot_topics: List[str] = field(default_factory=list)
    narrative_direction: str = ""
    preferred_poster_keywords: List[str] = field(
        default_factory=lambda: ["交管", "官方", "周明远", "公安", "交通警察"]
    )

    @classmethod
    def from_dict(cls, data: Any) -> "Intervention":
        if data is None:
            return cls()
        if isinstance(data, Intervention):
            return data
        if isinstance(data, list):
            # 直接是 posts 列表
            posts = [_coerce_post(p) for p in data]
            return cls(initial_posts=posts)
        if not isinstance(data, dict):
            return cls()

        posts_raw = data.get("initial_posts") or data.get("posts") or []
        if not posts_raw and data.get("content"):
            posts_raw = [
                {
                    "content": data.get("content"),
                    "poster_hint": data.get("poster_hint") or "official",
                    "poster_agent_id": data.get("poster_agent_id"),
                    "poster_keywords": data.get("poster_keywords") or [],
                }
            ]
        posts = [_coerce_post(p) for p in posts_raw]
        return cls(
            name=str(data.get("name") or ""),
            kind=str(data.get("kind") or data.get("id") or "custom"),
            initial_posts=posts,
            hot_topics=list(data.get("hot_topics") or []),
            narrative_direction=str(
                data.get("narrative_direction") or data.get("hypothesis") or ""
            ),
            preferred_poster_keywords=list(
                data.get("preferred_poster_keywords")
                or ["交管", "官方", "周明远", "公安", "交通警察"]
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "initial_posts": [p.to_dict() for p in self.initial_posts],
            "hot_topics": self.hot_topics,
            "narrative_direction": self.narrative_direction,
            "preferred_poster_keywords": self.preferred_poster_keywords,
        }

    def intervention_text(self) -> str:
        parts = [self.name, self.narrative_direction]
        parts.extend(p.content for p in self.initial_posts)
        return "\n".join(x for x in parts if x)


def _coerce_post(p: Any) -> InitialPost:
    if isinstance(p, InitialPost):
        return p
    if isinstance(p, dict):
        return InitialPost(
            content=str(p.get("content") or ""),
            poster_hint=str(p.get("poster_hint") or "official"),
            poster_agent_id=p.get("poster_agent_id"),
            poster_keywords=list(p.get("poster_keywords") or []),
        )
    return InitialPost(content=str(p))


def pick_poster_id(
    agents: List[Dict[str, Any]],
    hint: str,
    keywords: List[str],
) -> int:
    if not agents:
        return 0
    hint = (hint or "").lower()
    scored = []
    for a in agents:
        text = (
            f"{a.get('name', '')} {a.get('username', '')} "
            f"{a.get('bio', '')} {a.get('persona', '')} "
            f"{a.get('entity_type', '')} {a.get('source_entity_type', '')}"
        ).lower()
        score = 0
        if hint == "official":
            for kw in list(keywords) + [
                "official",
                "government",
                "bureau",
                "局",
                "政府",
                "公告",
                "交管",
            ]:
                if kw.lower() in text:
                    score += 3
        elif hint == "citizen":
            for kw in ["市民", "citizen", "通勤", "家长", "商户", "person", "resident"]:
                if kw.lower() in text:
                    score += 2
            for kw in ["局", "official", "government"]:
                if kw.lower() in text:
                    score -= 3
        else:
            # 通用：hint 本身当关键词
            if hint and hint in text:
                score += 4
            for kw in keywords:
                if kw.lower() in text:
                    score += 1
        scored.append((score, int(a.get("agent_id", a.get("user_id", 0)))))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def load_agents_index(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agents = []
    for i, row in enumerate(profiles):
        agents.append(
            {
                "agent_id": int(row.get("user_id", row.get("agent_id", i))),
                "name": str(row.get("name", row.get("username", f"agent_{i}"))),
                "username": str(row.get("username") or row.get("user_name") or ""),
                "bio": str(row.get("bio") or row.get("persona") or "")[:500],
                "persona": str(row.get("persona") or ""),
                "entity_type": str(
                    row.get("source_entity_type")
                    or row.get("entity_type")
                    or row.get("profession")
                    or ""
                ),
            }
        )
    return agents


def apply_to_config(
    config: Dict[str, Any],
    intervention: Union[Intervention, Dict, List, None],
    agents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    将干预写入 config.event_config.initial_posts，
    按 poster_hint / keywords 解析 poster_agent_id。
    """
    cfg = deepcopy(config)
    iv = Intervention.from_dict(intervention)
    agents = agents or []
    keywords = iv.preferred_poster_keywords

    posts = []
    for p in iv.initial_posts:
        poster_id = p.poster_agent_id
        if poster_id is None:
            kws = p.poster_keywords or keywords
            poster_id = pick_poster_id(agents, p.poster_hint, kws)
        posts.append(
            {
                "content": p.content,
                "poster_agent_id": int(poster_id),
                "poster_hint": p.poster_hint,
            }
        )

    cfg.setdefault("event_config", {})
    cfg["event_config"]["initial_posts"] = posts
    if iv.hot_topics:
        cfg["event_config"]["hot_topics"] = iv.hot_topics
    if iv.narrative_direction:
        cfg["event_config"]["narrative_direction"] = iv.narrative_direction
    cfg["_intervention"] = iv.to_dict()
    return cfg
