"""
本体 Schema 模板与案例材料路径
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from app.config import Config

_TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "templates"
)
_OPINION_CASE_DIR = os.path.join(_TEMPLATES_DIR, "opinion_case")
_SCENARIOS_PATH = os.path.join(_TEMPLATES_DIR, "opinion_propagation_scenarios.json")

# 与 prototype case 对齐的舆论传播本体
OPINION_SCHEMA: Dict[str, Any] = {
    "entity_types": [
        {
            "name": "GovernmentOfficial",
            "description": "Government officials and traffic police leaders who announce and enforce policy",
            "attributes": [
                {"name": "title", "type": "text", "description": "Official title"},
                {"name": "stance", "type": "text", "description": "Policy stance"},
            ],
            "examples": ["周明远", "交管局发言人"],
        },
        {
            "name": "DeliveryRider",
            "description": "Food delivery riders whose livelihood depends on road access",
            "attributes": [
                {"name": "platform", "type": "text", "description": "Delivery platform"},
                {"name": "daily_orders", "type": "text", "description": "Typical daily orders"},
            ],
            "examples": ["阿杰", "小雨"],
        },
        {
            "name": "Organization",
            "description": "Fallback for any organization, agency, platform, or association",
            "attributes": [
                {"name": "org_type", "type": "text", "description": "Organization category"},
            ],
            "examples": ["丰台交通支队", "速达外卖", "丰台外卖骑手协会"],
        },
        {
            "name": "CommuterCitizen",
            "description": "Daily commuters by car, metro, or e-bike concerned about traffic order",
            "attributes": [
                {"name": "commute_mode", "type": "text", "description": "Primary commute mode"},
            ],
            "examples": ["王建国", "刘敏", "老周"],
        },
        {
            "name": "SelfMedia",
            "description": "Independent content creators amplifying local narratives",
            "attributes": [
                {"name": "followers", "type": "text", "description": "Follower count"},
            ],
            "examples": ["阿凯", "丰台街访"],
        },
        {
            "name": "Journalist",
            "description": "Professional journalists covering policy and public opinion",
            "attributes": [
                {"name": "outlet", "type": "text", "description": "Media outlet"},
            ],
            "examples": ["李楠"],
        },
        {
            "name": "StreetMerchant",
            "description": "Street-side shop owners sensitive to foot traffic and delivery access",
            "attributes": [
                {"name": "business", "type": "text", "description": "Business type"},
            ],
            "examples": ["孙姐"],
        },
        {
            "name": "StudentParent",
            "description": "Parents concerned about school-area traffic safety",
            "attributes": [
                {"name": "school_area", "type": "text", "description": "Nearby school area"},
            ],
            "examples": ["张丽"],
        },
        {
            "name": "ExpertScholar",
            "description": "Academic experts analyzing policy cost, fairness, and impact",
            "attributes": [
                {"name": "affiliation", "type": "text", "description": "University or institute"},
            ],
            "examples": ["林晓薇"],
        },
        {
            "name": "Person",
            "description": "Fallback for any individual person not covered by a more specific type",
            "attributes": [
                {"name": "role", "type": "text", "description": "Social role"},
            ],
            "examples": ["路人甲", "网友"],
        },
    ],
    "edge_types": [
        {
            "name": "WORKS_FOR",
            "description": "Employment or affiliation relationship",
            "source_targets": [
                {"source": "GovernmentOfficial", "target": "Organization"},
                {"source": "DeliveryRider", "target": "Organization"},
                {"source": "Journalist", "target": "Organization"},
                {"source": "Person", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "REPRESENTS",
            "description": "Represents or speaks for a group",
            "source_targets": [
                {"source": "Person", "target": "Organization"},
                {"source": "DeliveryRider", "target": "Organization"},
                {"source": "GovernmentOfficial", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "OPPOSES",
            "description": "Publicly opposes a person, org, or policy stance",
            "source_targets": [
                {"source": "DeliveryRider", "target": "GovernmentOfficial"},
                {"source": "StreetMerchant", "target": "Organization"},
                {"source": "Person", "target": "Person"},
                {"source": "SelfMedia", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "SUPPORTS",
            "description": "Publicly supports a person, org, or policy stance",
            "source_targets": [
                {"source": "CommuterCitizen", "target": "Organization"},
                {"source": "StudentParent", "target": "Organization"},
                {"source": "Person", "target": "Person"},
            ],
            "attributes": [],
        },
        {
            "name": "INFLUENCES",
            "description": "Influences opinion or narrative of another actor",
            "source_targets": [
                {"source": "SelfMedia", "target": "Person"},
                {"source": "Journalist", "target": "Person"},
                {"source": "ExpertScholar", "target": "Organization"},
                {"source": "GovernmentOfficial", "target": "Person"},
            ],
            "attributes": [],
        },
        {
            "name": "FOLLOWS",
            "description": "Social media follow / attention relationship",
            "source_targets": [
                {"source": "Person", "target": "Person"},
                {"source": "Person", "target": "SelfMedia"},
                {"source": "Person", "target": "Organization"},
                {"source": "CommuterCitizen", "target": "Organization"},
            ],
            "attributes": [],
        },
        {
            "name": "REPORTS_ON",
            "description": "Media coverage relationship",
            "source_targets": [
                {"source": "Journalist", "target": "Organization"},
                {"source": "Journalist", "target": "Person"},
                {"source": "SelfMedia", "target": "Person"},
            ],
            "attributes": [],
        },
        {
            "name": "SERVES",
            "description": "Provides service to customers or citizens",
            "source_targets": [
                {"source": "DeliveryRider", "target": "CommuterCitizen"},
                {"source": "StreetMerchant", "target": "Person"},
                {"source": "Organization", "target": "Person"},
            ],
            "attributes": [],
        },
    ],
    "analysis_summary": "北京市丰台区电动自行车限行试点舆论场景：政府官员、骑手（含房山跨区）、通勤市民、商户、自媒体、记者、家长、专家等可发声主体。",
}

_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "opinion": OPINION_SCHEMA,
    "opinion_propagation": OPINION_SCHEMA,
    # 商业成交模板：建图仍走 LLM；此处仅注册名称避免 get_template KeyError
    "gtv_deal": OPINION_SCHEMA,
}


def get_template(name: str = "opinion") -> Dict[str, Any]:
    """返回命名模板的 schema 副本。"""
    key = (name or "opinion").strip().lower()
    if key not in _TEMPLATES:
        raise KeyError(f"未知模板: {name}，可用: {list(_TEMPLATES)}")
    # 深拷贝避免调用方修改全局
    return json.loads(json.dumps(_TEMPLATES[key], ensure_ascii=False))


def list_templates() -> List[str]:
    return list(_TEMPLATES.keys())


def get_case_dir(template: str = "opinion") -> str:
    """案例材料目录。"""
    key = (template or "opinion").strip().lower()
    if key == "gtv_deal":
        return os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "scripts",
                "gtv_forecast",
                "seeds",
            )
        )
    if key in ("opinion", "opinion_propagation"):
        return _OPINION_CASE_DIR
    return _OPINION_CASE_DIR


def get_case_file_paths(template: str = "opinion") -> List[str]:
    """返回案例 md 文件路径（按文件名排序）。"""
    case_dir = get_case_dir(template)
    if not os.path.isdir(case_dir):
        return []
    paths = [
        os.path.join(case_dir, f)
        for f in sorted(os.listdir(case_dir))
        if f.endswith((".md", ".txt", ".markdown"))
        # 演示报告缓存不当作本体种子上传
        and f not in ("demo_report.md",)
    ]
    return paths


def load_scenarios_template() -> Optional[Dict[str, Any]]:
    if not os.path.exists(_SCENARIOS_PATH):
        return None
    with open(_SCENARIOS_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_templates_dir() -> str:
    return _TEMPLATES_DIR
