"""三角色决策：线索多经纪竞争/协作；每步必有理由。"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

from app.config import Config
from app.engine.gtv_agent.state import STAGE_LABEL, DealThread
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.agents")


def llm_available() -> bool:
    return bool(Config.LLM_API_KEY)


def _active_actor(stage: str) -> str:
    if stage in ("idle", "solidify"):
        return "broker"
    if stage == "negotiate":
        return "landlord"
    if stage == "show":
        return "client"
    return "broker"


def _peers_compact(t: DealThread, threads: List[DealThread]) -> List[Dict[str, Any]]:
    group = t.deal_group_id or t.clue_id
    out = []
    for p in threads:
        if p.thread_id == t.thread_id or p.closed:
            continue
        if (p.deal_group_id or p.clue_id) != group:
            continue
        out.append(
            {
                "thread_id": p.thread_id,
                "broker_id": p.broker_id,
                "broker": p.broker_name,
                "listing_id": p.listing_id,
                "listing_name": p.listing_name,
                "stage": p.stage,
                "stage_label": STAGE_LABEL.get(p.stage, p.stage),
                "show_count": p.show_count,
                "follow_count": p.follow_count,
                "negotiate_rounds": p.negotiate_rounds,
                "coop_bias": p.coop_bias,
                "heat": round(p.heat, 2),
            }
        )
    return out


def _thread_compact(t: DealThread, threads: List[DealThread]) -> Dict[str, Any]:
    """压缩单线程上下文，降低输入 token，避免输出截断。"""
    t.normalize_stage()
    peers = _peers_compact(t, threads)
    # peers 只留关键字段，最多 3 个
    peers_slim = [
        {
            "broker_id": p.get("broker_id"),
            "broker": p.get("broker"),
            "stage_label": p.get("stage_label"),
            "show_count": p.get("show_count"),
        }
        for p in peers[:3]
    ]
    style = str((t.persona or {}).get("style") or "")[:40]
    return {
        "thread_id": t.thread_id,
        "clue_id": t.clue_id,
        "stage": t.stage,
        "stage_label": STAGE_LABEL.get(t.stage, t.stage),
        "suggested_actor": _active_actor(t.stage),
        "city": t.city_name,
        "quality_score": round(float(t.quality_score or 0.5), 2),
        "listing_name": t.listing_name,
        "listing_id": t.listing_id,
        "list_price": t.list_price,
        "client": t.client_name,
        "client_budget": round(t.client_budget, 0),
        "client_need": (t.client_need or "")[:48],
        "broker_id": t.broker_id,
        "broker": t.broker_name,
        "follow_count": t.follow_count,
        "show_count": t.show_count,
        "min_shows": t.min_shows,
        "min_follows": t.min_follows,
        "prefer_direct": t.prefer_direct,
        "negotiate_enabled": t.negotiate_enabled,
        "negotiate_rounds": t.negotiate_rounds,
        "coop_bias": round(float(t.coop_bias or 0), 2),
        "persona": {
            "archetype": (t.persona or {}).get("archetype") or t.persona_label,
            "style": style,
        },
        "peers_same_clue": peers_slim,
    }


_SYSTEM_PROMPT = (
    "你是工业地产 GTV CRM 成交推演裁判。竞争单位是「客户线索」：同一 clue_id 下多名经纪人抢签，"
    "谁先签约谁赢，其余落败；过程中可以协作（转介/协助带看/交接主谈）。"
    "漏斗阶段只能是：未推进→夯实→房源匹配→带看→谈判→签约 / 流失。"
    "禁止：报备、锁客、约看、意向、审批、计租、回款。"
    "动作：open_project, solidify, follow_up, match_listing, complete_show, "
    "start_negotiate, counter_offer, accept_deal, sign_direct, "
    "refer_coop, assist_show, handoff, walk_away, timeout。"
    "协作动作必须带 target_broker_id（同线索 peers 中的 broker_id）。"
    "persona.archetype：冲刺型偏直签；深耕型偏夯实/带看；协作型偏协作；谨慎型偏谈判或流失。"
    "严格输出完整 JSON（勿截断）：{\"actions\":[{\"thread_id\",\"actor\",\"action\",\"text\",\"reason\","
    "\"target_broker_id\",\"concession_pct\"}]}"
    "本批每个 thread 恰好一条 action；reason 必填且点名人设 archetype。"
)


def _llm_chunk_actions(
    client: Any,
    chunk: List[DealThread],
    all_threads: List[DealThread],
    *,
    round_no: int,
    total_rounds: int,
    scenario_name: str,
    gtv: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """一小批线程一次 LLM；失败则该批规则回退（避免截断拖垮整轨）。"""
    compact = [_thread_compact(t, all_threads) for t in chunk]
    # 每条约 120–180 tokens 输出；批次小则不易截断
    max_tokens = int(os.environ.get("GTV_AGENT_LLM_MAX_TOKENS", str(max(1200, 350 * len(chunk)))))
    user = {
        "scenario": scenario_name,
        "round": round_no,
        "total_rounds": total_rounds,
        "intervention": gtv,
        "batch_size": len(chunk),
        "threads": compact,
        "hint": f"必须返回恰好 {len(chunk)} 条 actions，覆盖全部 thread_id；JSON 必须完整可解析。",
    }
    try:
        data = client.chat_json(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
            ],
            temperature=0.35,
            max_tokens=max_tokens,
        )
    except Exception as e:
        logger.warning(
            "Agent LLM 批次失败（%s 线程），规则回退: %s",
            len(chunk),
            str(e)[:160],
        )
        return _rule_batch(chunk, all_threads, round_no, total_rounds)

    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list) or not actions:
        logger.warning("Agent LLM 批次无 actions（%s 线程），规则回退", len(chunk))
        return _rule_batch(chunk, all_threads, round_no, total_rounds)
    return actions


def decide_round_batch(
    threads: List[DealThread],
    *,
    round_no: int,
    total_rounds: int,
    scenario_name: str,
    gtv: Dict[str, Any],
) -> List[Dict[str, Any]]:
    active = [t for t in threads if not t.closed]
    if not active:
        return []

    if os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes"):
        return _rule_batch(active, threads, round_no, total_rounds)

    if not llm_available():
        raise RuntimeError("LLM_API_KEY 未配置，成交 Agent 轨不可用（统计轨仍可独立运行）")

    from app.utils.llm_client import LLMClient

    client = LLMClient()
    # 分批：默认每批 8 条；同轮多批可并行（默认 3），温和加速
    batch_size = max(2, min(12, int(os.environ.get("GTV_AGENT_LLM_BATCH", "8"))))
    parallel = max(1, min(4, int(os.environ.get("GTV_AGENT_LLM_PARALLEL", "3"))))
    chunks = [active[i : i + batch_size] for i in range(0, len(active), batch_size)]
    actions: List[Dict[str, Any]] = []

    def _run_chunk(chunk: List[DealThread]) -> List[Dict[str, Any]]:
        return _llm_chunk_actions(
            client,
            chunk,
            threads,
            round_no=round_no,
            total_rounds=total_rounds,
            scenario_name=scenario_name,
            gtv=gtv,
        )

    if len(chunks) <= 1 or parallel <= 1:
        for chunk in chunks:
            actions.extend(_run_chunk(chunk))
    else:
        ordered: List[List[Dict[str, Any]]] = [[] for _ in chunks]
        workers = min(parallel, len(chunks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_chunk, chunk): idx for idx, chunk in enumerate(chunks)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    ordered[idx] = fut.result()
                except Exception as e:
                    logger.warning("Agent LLM 并行批次异常，规则回退: %s", str(e)[:160])
                    ordered[idx] = _rule_batch(chunks[idx], threads, round_no, total_rounds)
        for part in ordered:
            actions.extend(part)

    late = round_no >= max(3, total_rounds - 4)
    seen = {str(a.get("thread_id")) for a in actions if isinstance(a, dict)}
    for t in active:
        if t.thread_id not in seen:
            act, text, actor, reason, target = _rule_one(t, threads, late=late)
            row = {
                "thread_id": t.thread_id,
                "actor": actor,
                "action": act,
                "text": text,
                "reason": reason,
                "source": "rule_fill",
            }
            if target:
                row["target_broker_id"] = target
            actions.append(row)
    return _coerce_llm_actions(actions, active, threads, round_no=round_no, total_rounds=total_rounds)


_STALL_ACTIONS = frozenset(
    {"follow_up", "solidify", "inquire", "consult", "boost_touch", "timeout"}
)
_FORBIDDEN_ACTIONS = frozenset(
    {
        "submit_report",
        "lock_client",
        "schedule_show",
        "express_intent",
        "submit_sign",
        "approve_sign",
        "reject_sign",
        "set_rent_start",
        "record_payment",
        "settle_commission",
    }
)
_COOP_ACTIONS = frozenset({"refer_coop", "assist_show", "handoff"})


def _needs_progress_coerce(t: DealThread, action: str, *, late: bool) -> bool:
    act = (action or "").strip().lower()
    if act in _FORBIDDEN_ACTIONS:
        return True
    t.normalize_stage()
    if t.stage == "solidify" and t.follow_count >= t.min_follows and act in _STALL_ACTIONS:
        return True
    if t.stage == "show" and t.show_count >= t.min_shows and act in ("complete_show", "show"):
        return True
    if late and t.stage in ("idle", "solidify", "match") and act in _STALL_ACTIONS:
        return True
    if late and act in _COOP_ACTIONS and t.stage in ("negotiate", "show") and t.show_count >= t.min_shows:
        # 末轮该冲刺签约时不要只协作
        return True
    return False


def _coerce_llm_actions(
    actions: List[Dict[str, Any]],
    active: List[DealThread],
    all_threads: List[DealThread],
    *,
    round_no: int,
    total_rounds: int,
) -> List[Dict[str, Any]]:
    by_id = {t.thread_id: t for t in active}
    late = round_no >= max(3, total_rounds - 4)
    out: List[Dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        tid = str(a.get("thread_id") or "")
        t = by_id.get(tid)
        if not t:
            out.append(a)
            continue
        act = str(a.get("action") or "follow_up")
        if _needs_progress_coerce(t, act, late=late):
            rule_act, rule_text, actor, reason, target = _rule_one(t, all_threads, late=late)
            row = {
                **a,
                "actor": actor,
                "action": rule_act,
                "text": rule_text,
                "reason": reason,
                "concession_pct": a.get("concession_pct") or t.concession_pct or 0.05,
                "source": "llm_coerced",
            }
            if target:
                row["target_broker_id"] = target
            out.append(row)
        else:
            a.setdefault("source", "llm")
            if not str(a.get("reason") or "").strip():
                a["reason"] = fallback_reason(t, act, all_threads)
            out.append(a)
    return out


def _persona_bit(t: DealThread) -> str:
    label = t.persona_label or (t.persona or {}).get("archetype") or ""
    return f"人设「{label}」" if label else "人设未标注"


def fallback_reason(
    t: DealThread, action: str, threads: Optional[List[DealThread]] = None
) -> str:
    q = float(t.quality_score or 0.5)
    stage = STAGE_LABEL.get(t.stage, t.stage)
    act = (action or "").strip().lower()
    peers = _peers_compact(t, threads or [])
    peer_bit = ""
    if peers:
        top = max(peers, key=lambda p: (p.get("show_count") or 0, p.get("heat") or 0))
        peer_bit = f"；同线索最快对手 {top.get('broker')} 处于{top.get('stage_label')}"
    bits = [
        f"线索 {t.clue_id or t.deal_group_id}",
        _persona_bit(t),
        f"阶段「{stage}」",
        f"夯实{t.follow_count}/{t.min_follows}",
        f"带看{t.show_count}/{t.min_shows}",
        f"质量分{q:.2f}",
    ]
    arch = (t.persona or {}).get("archetype") or t.persona_label or ""
    if act in _COOP_ACTIONS:
        return "；".join(bits) + f"{peer_bit}；{arch or '协作型'}倾向协作，执行 {act}。"
    if act in ("walk_away", "timeout"):
        return "；".join(bits) + f"{peer_bit}；谨慎评估后退出竞争。"
    if act in ("sign_direct", "buy_at_list", "accept_deal", "sign"):
        return "；".join(bits) + f"{peer_bit}；{arch or '冲刺型'}抢先签约锁定线索。"
    if act in ("start_negotiate", "counter_offer"):
        return "；".join(bits) + f"{peer_bit}；按人设推进与业主谈判。"
    if act == "match_listing":
        return "；".join(bits) + "；需求已夯实，匹配跟进房源。"
    return "；".join(bits) + f"{peer_bit}；本轮执行 {act or '推进'}。"


def ensure_reason(
    action: Dict[str, Any], t: DealThread, threads: List[DealThread]
) -> str:
    reason = str(action.get("reason") or "").strip()
    if reason:
        return reason
    return fallback_reason(t, str(action.get("action") or ""), threads)


def _rule_batch(
    active: List[DealThread],
    all_threads: List[DealThread],
    round_no: int,
    total_rounds: int,
) -> List[Dict[str, Any]]:
    out = []
    late = round_no >= max(3, total_rounds - 3)
    for t in active:
        act, text, actor, reason, target = _rule_one(t, all_threads, late=late)
        row = {
            "thread_id": t.thread_id,
            "actor": actor,
            "action": act,
            "text": text,
            "reason": reason,
            "concession_pct": t.concession_pct or 0.05,
            "source": "rule_fallback",
        }
        if target:
            row["target_broker_id"] = target
        out.append(row)
    return out


def _rule_one(
    t: DealThread, threads: List[DealThread], *, late: bool
) -> Tuple[str, str, str, str, str]:
    """返回 action, text, actor, reason, target_broker_id。"""
    t.normalize_stage()
    listing = t.listing_label()
    broker = t.broker_label()
    loc = (t.amap_address or t.address or t.city_name or "").strip()
    loc_bit = f" · {loc}" if loc else ""
    q = float(t.quality_score or 0.5)
    high_q = q >= 0.65
    low_q = q < 0.35
    peers = [
        p
        for p in threads
        if not p.closed
        and p.thread_id != t.thread_id
        and (p.deal_group_id or p.clue_id) == (t.deal_group_id or t.clue_id)
    ]
    target = ""
    peer = None
    if peers:
        peer = max(peers, key=lambda x: (x.heat, x.show_count, x.follow_count))
        target = peer.broker_id

    arch = str((t.persona or {}).get("archetype") or t.persona_label or "")
    is_sprint = arch == "冲刺型" or (t.prefer_direct and t.coop_bias < 0.4)
    is_coop = arch == "协作型" or t.coop_bias >= 0.55
    is_careful = arch == "谨慎型"
    is_deep = arch == "深耕型"

    # 高协作倾向 / 协作型：同伴落后时协助
    coop_threshold = 0.45 if is_coop else 0.55
    if (
        peer
        and t.coop_bias >= coop_threshold
        and not late
        and t.stage in ("match", "show", "solidify")
        and peer.stage in ("idle", "solidify", "match")
        and t.show_count >= (0 if is_coop else 1)
    ):
        return (
            "assist_show",
            f"{broker} 协助 {peer.broker_label()} 带看推进 · 线索 {t.clue_id}",
            "broker",
            f"{_persona_bit(t)}；同线索同伴仍处{STAGE_LABEL.get(peer.stage)}，"
            f"协作倾向 {t.coop_bias:.2f}，协助带看加速组内成交（仍可被先签抢赢）。",
            target,
        )

    if t.stage == "idle":
        return (
            "open_project",
            f"线索 {t.clue_id} 未推进 · {t.client_name} · {listing}{loc_bit} · {broker}",
            "broker",
            f"{_persona_bit(t)}；客户线索 {t.clue_id}（{t.client_need}）分发给 {broker}，开始夯实抢签。",
            "",
        )

    if t.stage == "solidify":
        need = t.min_follows + (1 if low_q or is_deep or is_careful else 0)
        if is_sprint:
            need = max(1, t.min_follows)
        if t.follow_count < need:
            return (
                "follow_up",
                f"{broker} 夯实跟进第{t.follow_count + 1}次 · {t.client_name} · 线索 {t.clue_id}",
                "broker",
                f"{_persona_bit(t)}；线索 {t.clue_id} 夯实 {t.follow_count}/{need} 未达标，"
                f"{'深耕确认需求' if is_deep or is_careful else '继续确认需求以抢进度'}。",
                "",
            )
        return (
            "match_listing",
            f"{broker} 房源匹配 · {listing}{loc_bit} · 线索 {t.clue_id}",
            "broker",
            f"{_persona_bit(t)}；夯实已满，为线索 {t.clue_id} 匹配 {listing} 进入带看竞争。",
            "",
        )

    if t.stage == "match":
        return (
            "complete_show",
            f"{broker} 带看 · {listing}{loc_bit} · 线索 {t.clue_id}",
            "broker",
            f"{_persona_bit(t)}；房源已匹配，"
            f"{'尽快带看拉开差距' if is_sprint else '安排带看推进竞争'}。",
            "",
        )

    if t.stage == "show":
        extra_shows = 1 if (is_deep or is_careful) and not is_sprint else 0
        need_shows = t.min_shows + extra_shows
        if t.show_count < need_shows:
            return (
                "complete_show",
                f"{t.client_name} 第{t.show_count + 1}次带看 · {listing}{loc_bit} · {broker}",
                "client",
                f"{_persona_bit(t)}；线索 {t.clue_id} 带看 {t.show_count}/{need_shows}，继续看房。",
                "",
            )
        if (low_q and late) or (is_careful and low_q and t.show_count >= need_shows):
            return (
                "walk_away",
                f"{broker} 退出线索 {t.clue_id} · 质量分{q:.2f}",
                "broker",
                f"{_persona_bit(t)}；质量分偏低"
                f"{'且末轮' if late else ''}，谨慎退出该线索竞争。",
                "",
            )
        if peer and (is_coop or t.coop_bias >= 0.6) and peer.stage == "negotiate" and not late:
            return (
                "handoff",
                f"{broker} 交接主谈给 {peer.broker_label()} · 线索 {t.clue_id}",
                "broker",
                f"{_persona_bit(t)}；同伴已进谈判，协作交接增强其冲刺（赢家仍属先签者）。",
                target,
            )
        if (is_sprint or t.prefer_direct or high_q) and not t.negotiate_enabled:
            return (
                "sign_direct",
                f"{broker} 直签抢赢 · {listing}{loc_bit} · 线索 {t.clue_id}",
                "client",
                f"{_persona_bit(t)}；带看达标且宜直签，抢先签约锁定线索 {t.clue_id}。",
                "",
            )
        return (
            "start_negotiate",
            f"{broker} 进入谈判 · {listing}{loc_bit} · 线索 {t.clue_id}",
            "broker",
            f"{_persona_bit(t)}；带看达标，与业主谈判以尽快签约赢得线索。",
            "",
        )

    if t.stage == "negotiate":
        if low_q and late and t.negotiate_rounds >= 1:
            return (
                "walk_away",
                f"谈判破裂 · 线索 {t.clue_id} · {broker}",
                "client",
                f"{_persona_bit(t)}；谈判难收敛且质量分{q:.2f}偏低，退出竞争。",
                "",
            )
        need_rounds = 1 if (high_q or is_sprint) else (2 if not is_careful else 3)
        if t.negotiate_rounds >= need_rounds or late:
            return (
                "accept_deal",
                f"{broker} 谈妥签约 · {listing}{loc_bit} · 线索 {t.clue_id}",
                "landlord",
                f"{_persona_bit(t)}；谈判轮次达标，抢先签约成为线索 {t.clue_id} 赢家。",
                "",
            )
        return (
            "counter_offer",
            f"第{t.negotiate_rounds + 1}轮谈判 · {listing}{loc_bit} · {broker}",
            "landlord",
            f"{_persona_bit(t)}；谈判未收敛，继续还价同时盯防同线索对手进度。",
            "",
        )

    if t.stage == "signed":
        return (
            "accept_deal",
            f"已签约胜出 · 线索 {t.clue_id}",
            "broker",
            f"已是线索赢家，推演收官。",
            "",
        )

    return (
        "follow_up",
        f"{broker} 继续推进 · 线索 {t.clue_id}",
        "broker",
        fallback_reason(t, "follow_up", threads),
        "",
    )

