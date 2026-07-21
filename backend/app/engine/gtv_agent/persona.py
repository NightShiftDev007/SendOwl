"""经纪人人设：Step2 规则骨架 + LLM 润色；Step3 只读复用。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.persona")

ARCHETYPES = ("冲刺型", "深耕型", "协作型", "谨慎型")

DEFAULT_POOL_SIZE = int(os.environ.get("GTV_PERSONA_POOL_SIZE", "30"))


def _f(row: Dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k not in row or row.get(k) is None:
            continue
        try:
            v = float(row.get(k))
            if v == v:
                return v
        except Exception:
            continue
    return default


def _broker_id(row: Dict[str, Any]) -> str:
    return str(row.get("user_id") or row.get("broker_id") or "").strip()


def _broker_name(row: Dict[str, Any], i: int = 0) -> str:
    name = str(
        row.get("nick_name") or row.get("user_name") or row.get("display_name") or ""
    ).strip()
    if not name or name in ("None", "nan"):
        name = f"经纪人{i + 1}"
    return name


def _hash_unit(s: str) -> float:
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def derive_broker_persona_skeleton(row: Dict[str, Any], *, index: int = 0) -> Dict[str, Any]:
    """由统计字段确定性推导人格骨架（可回放）。"""
    bid = _broker_id(row) or f"demo_B{index}"
    name = _broker_name(row, index)
    score = _f(row, "score", default=0.35)
    hist = _f(row, "hist_deals", default=0.0)
    hist_rate = _f(row, "hist_rate", default=0.0)
    if hist_rate <= 0 and hist > 0:
        n_list = max(1.0, _f(row, "n_listings", default=1.0))
        hist_rate = hist / (n_list + 1.0)
    n_listings = _f(row, "n_listings", default=0.0)
    port_heat = _f(row, "port_heat", "heat", default=0.0)
    port_show = _f(row, "port_show", default=0.0)
    noise = _hash_unit(bid)

    # 归一到大致 0–1
    assertiveness = min(1.0, 0.25 + 0.45 * min(1.0, score) + 0.2 * min(1.0, hist / 8.0) + 0.1 * noise)
    patience = min(1.0, 0.2 + 0.35 * min(1.0, n_listings / 40.0) + 0.25 * min(1.0, port_show / 30.0))
    coop = min(1.0, 0.2 + 0.35 * (1.0 - min(1.0, score)) + 0.25 * min(1.0, port_heat / 40.0) + 0.1 * (1 - noise))
    price_flex = min(1.0, 0.25 + 0.4 * (1.0 - min(1.0, hist_rate * 3)) + 0.2 * patience)

    # 分型：按主导特质（盘源量大不单方面锁死「深耕」，避免真实池同质化）
    scores = {
        "冲刺型": assertiveness * 1.25 + min(1.0, score) * 0.55 + min(1.0, hist / 6.0) * 0.45,
        "深耕型": patience * 1.0 + min(1.0, n_listings / 55.0) * 0.35 + min(1.0, port_show / 40.0) * 0.25,
        "协作型": coop * 1.25 + (1 - assertiveness) * 0.35 + min(1.0, port_heat / 50.0) * 0.2,
        "谨慎型": (1 - assertiveness) * 0.75 + patience * 0.45 + (1 - price_flex) * 0.55 + (1 - min(1.0, score)) * 0.25,
    }
    # 轻微噪声打破并列，保持同 id 可回放
    for k in scores:
        scores[k] += 0.03 * _hash_unit(f"{bid}:{k}")
    archetype = max(scores, key=scores.get)

    if archetype == "冲刺型":
        style = "直给、节奏快，倾向少轮次推进到签约，话术偏结果导向。"
        talk = "少寒暄，尽快约带看/锁条件；同线索竞争时优先抢签。"
        prefer_direct = True
        coop_bias = 0.2 + 0.15 * coop
    elif archetype == "深耕型":
        style = "跟进细、重匹配与带看质量，愿意多轮夯实客户需求。"
        talk = "先问清预算与产线需求，再推房；不急于一口价成交。"
        prefer_direct = False
        coop_bias = 0.35 + 0.2 * coop
    elif archetype == "协作型":
        style = "擅转介与协助带看，愿意与同伴分工换取线索内成交。"
        talk = "主动协调同伴资源；自己未必抢第一签，但推动组内成交。"
        prefer_direct = False
        coop_bias = 0.55 + 0.25 * coop
    else:
        style = "谨慎评估风险与价格，谈价与流失阈值更高，少冲动直签。"
        talk = "条件不齐不推签；业主让步不足时倾向继续谈或退出。"
        prefer_direct = False
        coop_bias = 0.25 + 0.2 * coop

    coop_bias = float(max(0.08, min(0.92, coop_bias)))
    persona_label = archetype
    bio = (
        f"{name}，工业地产经纪人（{archetype}）。"
        f"历史成交约 {int(hist)} 单，模型分 {score:.2f}，盘源约 {int(n_listings)}。"
        f"{style}"
    )

    return {
        "broker_id": bid,
        "broker_name": name,
        "archetype": archetype,
        "persona_label": persona_label,
        "traits": {
            "assertiveness": round(assertiveness, 3),
            "patience": round(patience, 3),
            "coop": round(coop, 3),
            "price_flex": round(price_flex, 3),
        },
        "biases": {
            "coop_bias": round(coop_bias, 3),
            "prefer_direct": prefer_direct,
            "negotiate_enabled": not prefer_direct or archetype == "谨慎型",
        },
        "style": style,
        "talk_constraints": talk,
        "bio": bio,
        "persona": f"{archetype}·{name}",
        "profession": "工业地产经纪人",
        "source": "skeleton",
        "stats": {
            "score": score,
            "hist_deals": hist,
            "hist_rate": hist_rate,
            "n_listings": n_listings,
            "port_heat": port_heat,
            "port_show": port_show,
        },
    }


def enrich_personas_with_llm(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量 LLM 润色 style/bio/talk_constraints；失败保留骨架。"""
    if not cards:
        return []
    if os.environ.get("GTV_PERSONA_SKIP_LLM", "").lower() in ("1", "true", "yes"):
        return list(cards)

    try:
        from app.engine.gtv_agent.agents import llm_available
        from app.utils.llm_client import LLMClient
    except Exception as e:
        logger.warning("人设 LLM 不可用，保留骨架: %s", e)
        return list(cards)

    if not llm_available():
        return list(cards)

    client = LLMClient()
    out: List[Dict[str, Any]] = []
    # 小批量，避免超长 prompt
    batch_size = int(os.environ.get("GTV_PERSONA_LLM_BATCH", "8"))
    for i in range(0, len(cards), batch_size):
        chunk = cards[i : i + batch_size]
        compact = [
            {
                "broker_id": c.get("broker_id"),
                "broker_name": c.get("broker_name"),
                "archetype": c.get("archetype"),
                "traits": c.get("traits"),
                "stats": c.get("stats"),
                "style_seed": c.get("style"),
            }
            for c in chunk
        ]
        system = (
            "你是工业地产 CRM 经纪人人设编剧。根据统计骨架为每位经纪人写简短中文人设。"
            "严格 JSON：{\"personas\":[{\"broker_id\",\"style\",\"bio\",\"talk_constraints\"}]}"
            "style≤40字；bio≤80字；talk_constraints≤40字。不要编造虚假成交数字。"
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps({"brokers": compact}, ensure_ascii=False),
            },
        ]
        try:
            raw = client.chat_json(messages, temperature=0.4, max_tokens=2048)
        except Exception as e2:
            logger.warning("人设 LLM 批次失败，保留骨架: %s", e2)
            out.extend(chunk)
            continue
        if not isinstance(raw, dict):
            raw = _extract_json(str(raw or ""))

        by_id = {}
        if isinstance(raw, dict):
            for p in raw.get("personas") or []:
                if isinstance(p, dict) and p.get("broker_id"):
                    by_id[str(p["broker_id"])] = p
        for c in chunk:
            p = by_id.get(str(c.get("broker_id") or ""))
            merged = dict(c)
            if p:
                if str(p.get("style") or "").strip():
                    merged["style"] = str(p["style"]).strip()[:80]
                if str(p.get("bio") or "").strip():
                    merged["bio"] = str(p["bio"]).strip()[:160]
                if str(p.get("talk_constraints") or "").strip():
                    merged["talk_constraints"] = str(p["talk_constraints"]).strip()[:80]
                merged["source"] = "llm"
                merged["persona"] = f"{merged.get('archetype')}·{merged.get('broker_name')}"
            out.append(merged)
    return out


def _extract_json(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def personas_to_sim_profiles(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """映射为 Step2 可读的 reddit/twitter_profiles 结构。"""
    profiles = []
    for i, c in enumerate(cards):
        bid = str(c.get("broker_id") or f"B{i}")
        profiles.append(
            {
                "user_id": i + 1,
                "broker_id": bid,
                "user_name": f"gtv_{bid}",
                "name": c.get("broker_name") or f"经纪人{i + 1}",
                "bio": c.get("bio") or "",
                "persona": c.get("persona") or c.get("persona_label") or c.get("archetype") or "",
                "profession": c.get("profession") or "工业地产经纪人",
                "archetype": c.get("archetype"),
                "persona_label": c.get("persona_label") or c.get("archetype"),
                "style": c.get("style") or "",
                "talk_constraints": c.get("talk_constraints") or "",
                "traits": c.get("traits") or {},
                "entity_type": "broker",
            }
        )
    return profiles


def broker_personas_path(decision_id: str) -> str:
    from app.config import Config

    return os.path.join(Config.DECISION_DIR, decision_id, "report", "broker_personas.json")


def save_broker_personas(decision_id: str, cards: List[Dict[str, Any]]) -> str:
    path = broker_personas_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "template": "gtv_deal",
        "count": len(cards),
        "personas": cards,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_broker_personas(decision_id: str) -> Dict[str, Dict[str, Any]]:
    """返回 broker_id -> persona。"""
    path = broker_personas_path(decision_id)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("读取 broker_personas 失败: %s", e)
        return {}
    cards = raw.get("personas") if isinstance(raw, dict) else raw
    out: Dict[str, Dict[str, Any]] = {}
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        bid = str(c.get("broker_id") or "").strip()
        if bid:
            out[bid] = c
    return out


def build_personas_for_brokers(
    brokers: List[Dict[str, Any]],
    *,
    pool_size: Optional[int] = None,
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    """去重后取 Top 池，骨架 → 可选 LLM。"""
    n = int(pool_size if pool_size is not None else DEFAULT_POOL_SIZE)
    n = max(4, min(60, n))
    seen = set()
    rows: List[Dict[str, Any]] = []
    for r in brokers or []:
        if not isinstance(r, dict):
            continue
        bid = _broker_id(r)
        if not bid or bid in seen:
            continue
        seen.add(bid)
        rows.append(r)
        if len(rows) >= n:
            break
    if not rows:
        # 演示兜底
        for i in range(min(8, n)):
            rows.append(
                {
                    "user_id": f"demo_U{i+1}",
                    "nick_name": ["陆雨", "王建平", "黎俊", "牛源", "唐铖", "陈浩", "林峰", "周敏"][i % 8],
                    "score": 0.7 - i * 0.05,
                    "hist_deals": max(0, 6 - i),
                    "n_listings": 10 + i * 3,
                    "hist_rate": 0.2,
                }
            )
    skeletons = [derive_broker_persona_skeleton(r, index=i) for i, r in enumerate(rows)]
    skeletons = _ensure_archetype_diversity(skeletons, rows)
    if use_llm:
        return enrich_personas_with_llm(skeletons)
    return skeletons


def _ensure_archetype_diversity(
    cards: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Top 池分数接近时避免全体同一 archetype：按得分位强制四分型。"""
    if len(cards) < 4:
        return cards
    kinds = {c.get("archetype") for c in cards}
    if len(kinds) >= 3:
        return cards
    # 按 score/hist 排序后切四段
    indexed = list(enumerate(rows))
    indexed.sort(
        key=lambda ir: (
            _f(ir[1], "score", default=0.0),
            _f(ir[1], "hist_deals", default=0.0),
        ),
        reverse=True,
    )
    n = len(indexed)
    assign = ["冲刺型", "深耕型", "协作型", "谨慎型"]
    out = list(cards)
    for rank, (orig_i, row) in enumerate(indexed):
        bucket = min(3, (rank * 4) // max(1, n))
        arch = assign[bucket]
        # 重跑骨架后覆盖 archetype 相关文案（保留 traits 再贴分型）
        base = derive_broker_persona_skeleton(row, index=orig_i)
        base["archetype"] = arch
        base["persona_label"] = arch
        # 按目标分型覆写 biases / 文案
        if arch == "冲刺型":
            base["style"] = "直给、节奏快，倾向少轮次推进到签约，话术偏结果导向。"
            base["talk_constraints"] = "少寒暄，尽快约带看/锁条件；同线索竞争时优先抢签。"
            base["biases"] = {
                "coop_bias": round(max(0.15, min(0.45, float((base.get("biases") or {}).get("coop_bias") or 0.25))), 3),
                "prefer_direct": True,
                "negotiate_enabled": False,
            }
        elif arch == "深耕型":
            base["style"] = "跟进细、重匹配与带看质量，愿意多轮夯实客户需求。"
            base["talk_constraints"] = "先问清预算与产线需求，再推房；不急于一口价成交。"
            base["biases"] = {
                "coop_bias": round(max(0.3, min(0.55, float((base.get("biases") or {}).get("coop_bias") or 0.4))), 3),
                "prefer_direct": False,
                "negotiate_enabled": True,
            }
        elif arch == "协作型":
            base["style"] = "擅转介与协助带看，愿意与同伴分工换取线索内成交。"
            base["talk_constraints"] = "主动协调同伴资源；自己未必抢第一签，但推动组内成交。"
            base["biases"] = {
                "coop_bias": round(max(0.55, min(0.9, float((base.get("biases") or {}).get("coop_bias") or 0.65))), 3),
                "prefer_direct": False,
                "negotiate_enabled": True,
            }
        else:
            base["style"] = "谨慎评估风险与价格，谈价与流失阈值更高，少冲动直签。"
            base["talk_constraints"] = "条件不齐不推签；业主让步不足时倾向继续谈或退出。"
            base["biases"] = {
                "coop_bias": round(max(0.2, min(0.5, float((base.get("biases") or {}).get("coop_bias") or 0.3))), 3),
                "prefer_direct": False,
                "negotiate_enabled": True,
            }
        name = base.get("broker_name") or "经纪人"
        base["persona"] = f"{arch}·{name}"
        base["bio"] = (
            f"{name}，工业地产经纪人（{arch}）。"
            f"历史成交约 {int(_f(row, 'hist_deals'))} 单，模型分 {_f(row, 'score'):.2f}。"
            f"{base['style']}"
        )
        base["source"] = "skeleton_balanced"
        out[orig_i] = base
    return out


def resolve_persona_for_broker(
    broker_row: Dict[str, Any],
    prepared: Dict[str, Dict[str, Any]],
    *,
    index: int = 0,
) -> Dict[str, Any]:
    """Step3：优先已准备人设，否则现场骨架。"""
    bid = _broker_id(broker_row)
    if bid and bid in prepared:
        return prepared[bid]
    return derive_broker_persona_skeleton(broker_row, index=index)
