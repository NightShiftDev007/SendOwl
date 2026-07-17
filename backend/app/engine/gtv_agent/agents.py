"""三角色决策：每轮批量 LLM；无 Key 时拒绝伪装。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from app.config import Config
from app.engine.gtv_agent.state import STAGE_LABEL, DealThread
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.agents")


def llm_available() -> bool:
    return bool(Config.LLM_API_KEY)


def _active_actor(stage: str) -> str:
    if stage in ("clue", "consult", "intent"):
        return "client"
    if stage == "negotiate":
        return "landlord"
    if stage in ("approve", "signed", "rent", "payment", "settle", "report", "lock"):
        return "broker"
    return "broker"


def decide_round_batch(
    threads: List[DealThread],
    *,
    round_no: int,
    total_rounds: int,
    scenario_name: str,
    gtv: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """对未关闭线程批量决策，返回 actions 列表。"""
    active = [t for t in threads if not t.closed]
    if not active:
        return []

    if os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes"):
        return _rule_batch(active, round_no, total_rounds)

    if not llm_available():
        raise RuntimeError("LLM_API_KEY 未配置，成交 Agent 轨不可用（统计轨仍可独立运行）")

    from app.utils.llm_client import LLMClient

    client = LLMClient()
    compact = []
    for t in active:
        compact.append(
            {
                "thread_id": t.thread_id,
                "clue_id": t.clue_id,
                "project_id": t.project_id,
                "stage": t.stage,
                "stage_label": STAGE_LABEL.get(t.stage, t.stage),
                "suggested_actor": _active_actor(t.stage),
                "city": t.city_name,
                "address": t.amap_address or t.address,
                "longitude": t.longitude,
                "latitude": t.latitude,
                "quality_score": t.quality_score,
                "quality_highlights": t.quality_highlights,
                "listing_type": t.listing_type,
                "listing_id": t.listing_id,
                "listing_name": t.listing_name,
                "listing_label": t.listing_label(),
                "list_price": t.list_price,
                "area": t.area,
                "client": t.client_name,
                "client_budget": round(t.client_budget, 0),
                "client_need": t.client_need,
                "broker_id": t.broker_id,
                "broker": t.broker_name,
                "broker_label": t.broker_label(),
                "landlord": t.landlord_name,
                "heat": t.heat,
                "follow_count": t.follow_count,
                "show_count": t.show_count,
                "min_shows": t.min_shows,
                "reported": t.reported,
                "locked": t.locked,
                "prefer_direct": t.prefer_direct,
                "negotiate_enabled": t.negotiate_enabled,
                "negotiate_rounds": t.negotiate_rounds,
                "concession_pct": t.concession_pct,
                "path": t.path,
                "approve_status": t.approve_status,
                "notes": t.notes[:4],
            }
        )

    system = (
        "你是工业地产 GTV CRM 成交推演裁判。根据每条交易线程当前漏斗阶段，决定本轮唯一动作。"
        "完整漏斗：线索接入→立项→咨询跟进(可多次)→报备→锁客→约看→带看(可多次)→意向确认→"
        "谈价协商(多轮还价)或不谈价直签→签约审批→签约生效→计租→回款→佣金归因 / 流失。"
        "角色：client=客户, broker=经纪人, landlord=业主（审批/报备/锁客/计租回款由 broker 侧执行）。"
        "动作枚举：intake_clue, open_project, inquire, follow_up, submit_report, lock_client, "
        "schedule_show, complete_show, express_intent, start_negotiate, counter_offer, "
        "accept_deal, buy_at_list, submit_sign, approve_sign, reject_sign, "
        "set_rent_start, record_payment, settle_commission, reject, walk_away, timeout。"
        "谈价=与业主协商，禁止写成公司单方改挂牌价。"
        "prefer_direct=true 时走 buy_at_list；negotiate_enabled 或干预谈价时走谈价多轮。"
        "带看次数未达 min_shows 前优先 complete_show；靠近末轮可 walk_away 或推进审批落地。"
        "quality_score≥0.65：意向后更易直签/谈成；quality_score<0.35：多跟进/多带看，末轮更易流失。"
        "严格输出 JSON：{\"actions\":[{\"thread_id\",\"actor\",\"action\",\"text\","
        "\"concession_pct\",\"contract_money\",\"commission\",\"rent_start_days\",\"payment_ratio\"}]}"
    )
    user = {
        "scenario": scenario_name,
        "round": round_no,
        "total_rounds": total_rounds,
        "intervention": gtv,
        "threads": compact,
        "hint": (
            "每条线程恰好一条 action；text 用中文短句，必须点名房源名称+listing_id、"
            "经纪人昵称+broker_id、地址/位置，以及当前阶段（基于 CRM 种子底座推演，非历史回放）。"
        ),
    }
    try:
        data = client.chat_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=0.45,
            max_tokens=4000,
        )
    except Exception as e:
        logger.warning("Agent 批量决策失败，使用规则推进: %s", e)
        if os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes"):
            return _rule_batch(active, round_no, total_rounds)
        raise

    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list) or not actions:
        if os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes"):
            return _rule_batch(active, round_no, total_rounds)
        raise RuntimeError("LLM 未返回有效 actions")
    seen = {str(a.get("thread_id")) for a in actions if isinstance(a, dict)}
    for t in active:
        if t.thread_id not in seen:
            actions.append(
                {
                    "thread_id": t.thread_id,
                    "actor": _active_actor(t.stage),
                    "action": "follow_up",
                    "text": f"{t.broker_name} 继续跟进 {t.client_name}",
                }
            )
    return actions


def _rule_batch(threads: List[DealThread], round_no: int, total_rounds: int) -> List[Dict[str, Any]]:
    """可复现规则推进完整 CRM 链至 settle（验收/无网）。"""
    out = []
    late = round_no >= max(3, total_rounds - 3)
    for t in threads:
        act, text, actor = _rule_one(t, late=late)
        out.append(
            {
                "thread_id": t.thread_id,
                "actor": actor,
                "action": act,
                "text": text,
                "concession_pct": t.concession_pct or 0.05,
                "rent_start_days": t.rent_start_days or 7,
                "payment_ratio": 1.0,
                "source": "rule_fallback",
            }
        )
    return out


def _rule_one(t: DealThread, *, late: bool) -> tuple[str, str, str]:
    listing = t.listing_label()
    broker = t.broker_label()
    loc = (t.amap_address or t.address or t.city_name or "").strip()
    loc_bit = f" · {loc}" if loc else ""
    q = float(t.quality_score or 0.5)
    high_q = q >= 0.65
    low_q = q < 0.35

    if t.stage == "clue":
        return (
            "intake_clue",
            f"接入线索 {t.clue_id} · 房源 {listing}{loc_bit}",
            "broker",
        )
    if t.stage == "project":
        return (
            "open_project",
            f"{broker} 立项 {t.project_id} · 房源 {listing}{loc_bit} · 对接 {t.client_name}",
            "broker",
        )
    if t.stage == "consult":
        # 低质量房源额外跟进一轮
        need_follows = t.min_follows + (1 if low_q else 0)
        if t.follow_count < need_follows:
            return (
                "follow_up",
                f"{broker} 第{t.follow_count + 1}次跟进 {t.client_name} · 房源 {listing}{loc_bit}",
                "broker",
            )
        return (
            "submit_report",
            f"{broker} 提交报备 · 线索 {t.clue_id} · 房源 {listing}",
            "broker",
        )
    if t.stage == "report":
        return "lock_client", f"{broker} 锁客 {t.client_name} · 房源 {listing}", "broker"
    if t.stage == "lock":
        return "schedule_show", f"{broker} 约看 · {listing}{loc_bit}", "broker"
    if t.stage == "schedule":
        return "complete_show", f"{broker} 完成带看 · {listing}{loc_bit}", "broker"
    if t.stage == "show":
        if t.show_count < t.min_shows:
            return (
                "complete_show",
                f"{t.client_name} 第{t.show_count + 1}次带看 · {listing}{loc_bit} · 维护人 {broker}",
                "client",
            )
        if low_q and late and t.show_count >= t.min_shows:
            return (
                "walk_away",
                f"{t.client_name} 因房源质量不足流失 · {listing}{loc_bit} · 质量分{q:.2f}",
                "client",
            )
        return (
            "express_intent",
            f"{t.client_name} 确认意向 · {listing}{loc_bit} · 经纪人 {broker}",
            "client",
        )
    if t.stage == "intent":
        if low_q and late:
            return (
                "walk_away",
                f"{t.client_name} 意向后流失 · {listing}{loc_bit} · 质量分{q:.2f}",
                "client",
            )
        # 高质量更易直签
        if (t.prefer_direct or high_q) and not t.negotiate_enabled:
            return (
                "buy_at_list",
                f"{t.client_name} 不谈价直签 · {listing}{loc_bit} · {broker}",
                "client",
            )
        if t.negotiate_enabled or not t.prefer_direct:
            return (
                "start_negotiate",
                f"{broker} 与{t.landlord_name}谈价（非公司改挂牌）· {listing}{loc_bit}",
                "broker",
            )
        return "buy_at_list", f"{t.client_name} 不谈价直签 · {listing}{loc_bit} · {broker}", "client"
    if t.stage == "negotiate":
        # 高质量更快谈成；低质量末轮更易流失
        if low_q and late and t.negotiate_rounds >= 1:
            return (
                "walk_away",
                f"{t.client_name} 谈价破裂流失 · {listing}{loc_bit} · 质量分{q:.2f}",
                "client",
            )
        need_rounds = 1 if high_q else 2
        if t.negotiate_rounds >= need_rounds or late:
            return (
                "accept_deal",
                f"{t.landlord_name} 接受条件并提交审批 · {listing}{loc_bit} · {broker}",
                "landlord",
            )
        return (
            "counter_offer",
            f"{t.landlord_name} 第{t.negotiate_rounds + 1}轮还价 · {listing}{loc_bit}",
            "landlord",
        )
    if t.stage == "direct":
        return "submit_sign", f"{broker} 提交一口价签约审批 · {listing}{loc_bit}", "broker"
    if t.stage == "approve":
        if late and (t.approve_status == "rejected" or low_q):
            return "walk_away", f"{t.client_name} 审批未过流失 · {listing}{loc_bit}", "client"
        return (
            "approve_sign",
            f"签约审批通过（{t.path or 'deal'}）· {listing}{loc_bit} · {broker}",
            "broker",
        )
    if t.stage == "signed":
        return (
            "set_rent_start",
            f"约定计租（签约后 {t.rent_start_days or 7} 日）· {listing}{loc_bit} · {broker}",
            "broker",
        )
    if t.stage == "rent":
        return "record_payment", f"记录回款 · {listing}{loc_bit} · 佣金路径 {broker}", "broker"
    if t.stage == "payment":
        return (
            "settle_commission",
            f"佣金归因 · {broker} · 房源 {listing}{loc_bit}",
            "broker",
        )
    return "follow_up", f"{broker} 继续跟进 · {listing}{loc_bit}", "broker"
