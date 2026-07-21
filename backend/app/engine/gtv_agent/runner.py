"""成交 Agent 轨 runner：线索多经纪抢签，逐轮决策并落盘。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.config import Config
from app.engine.gtv_agent.agents import decide_round_batch, ensure_reason, llm_available
from app.engine.gtv_agent.state import (
    STAGE_LABEL,
    DealThread,
    close_clue_group_on_sign,
    summarize_threads,
)
from app.engine.gtv_agent.world import build_world, try_load_listings_from_parquet
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.runner")

DEFAULT_ROUNDS = int(os.environ.get("GTV_AGENT_ROUNDS", "12"))

_TIMELINE_NOTE = (
    "成交 Agent 推演：客户线索×多经纪抢签（先签先赢，过程可协作）；"
    "漏斗 未推进→夯实→房源匹配→带看→谈判→签约；每步含决策理由"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def agent_status_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "agent_status.json")


def deal_actions_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "deal_actions.jsonl")


def write_agent_status(decision_id: str, payload: Dict[str, Any]) -> None:
    path = agent_status_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {**payload, "updated_at": _utc_now()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)


def load_agent_status(decision_id: str) -> Optional[Dict[str, Any]]:
    path = agent_status_path(decision_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _append_action(decision_id: str, row: Dict[str, Any]) -> None:
    path = deal_actions_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _timeline_from_events(events: List[Dict[str, Any]], *, note: str = "") -> Dict[str, Any]:
    return {
        "template": "gtv_deal",
        "engine": "gtv_agent",
        "generated_at": _utc_now(),
        "note": note or _TIMELINE_NOTE,
        "event_count": len(events),
        "events": events,
    }


def _event_from_thread(
    t: DealThread,
    *,
    round_no: int,
    action: str,
    text: str,
    reason: str,
    actor: Any,
    prev: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "day": round_no,
        "round": round_no,
        "stage": t.stage,
        "stage_label": STAGE_LABEL.get(t.stage, t.stage),
        "actor": actor,
        "action": action,
        "text": text,
        "reason": reason,
        "broker_id": t.broker_id,
        "broker": t.broker_name,
        "broker_name": t.broker_name,
        "broker_label": t.broker_label(),
        "city": t.city_name,
        "address": t.amap_address or t.address,
        "amap_address": t.amap_address or "",
        "longitude": t.longitude,
        "latitude": t.latitude,
        "quality_score": t.quality_score,
        "quality_highlights": t.quality_highlights,
        "listing_id": t.listing_id,
        "listing_name": t.listing_name,
        "listing_type": t.listing_type,
        "listing_label": t.listing_label(),
        "thread_id": t.thread_id,
        "clue_id": t.clue_id,
        "deal_group_id": t.deal_group_id or t.clue_id,
        "project_id": t.project_id,
        "client_name": t.client_name,
        "path": t.path or None,
        "role_outcome": t.role_outcome or "",
        "role_outcome_label": {
            "winner": "胜出",
            "contributor": "协作",
            "loser": "落败",
            "lost": "流失",
        }.get(t.role_outcome or "", t.role_outcome or ""),
        "from_stage": prev,
        "from_stage_label": STAGE_LABEL.get(prev, prev),
        "source": source,
        "seed_source": t.seed_source,
        "persona_label": t.persona_label or (t.persona or {}).get("archetype") or "",
        "persona_archetype": (t.persona or {}).get("archetype") or t.persona_label or "",
    }


def _clue_groups_done(threads: List[DealThread]) -> bool:
    groups: Dict[str, List[DealThread]] = {}
    for t in threads:
        g = t.deal_group_id or t.clue_id or t.thread_id
        groups.setdefault(g, []).append(t)
    for members in groups.values():
        if any(not m.closed for m in members):
            # 组内尚有活跃且无人胜出 → 未完成
            if not any(m.role_outcome == "winner" or m.stage == "signed" for m in members):
                return False
    return True


def _align_with_stat(
    summary: Dict[str, Any],
    world: Dict[str, Any],
    *,
    expected_deals: Optional[float],
    expected_contract: Optional[float] = None,
    expected_commission: Optional[float] = None,
) -> Dict[str, Any]:
    """Agent 涌现 vs 统计预期的轻量对照。"""
    deals = list(summary.get("deals") or [])
    win_listings = {str(d.get("listing_id") or "") for d in deals if d.get("listing_id")}
    win_brokers = {str(d.get("winner_broker_id") or "") for d in deals if d.get("winner_broker_id")}
    # world.stat_* 已按统计分降序
    ranked_L = list(world.get("stat_listing_ids") or [])
    ranked_B = list(world.get("stat_broker_ids") or [])
    top_L = set(ranked_L[:10])
    top_B = set(ranked_B[:10])
    n_clue = int(summary.get("n_clue_deals") or summary.get("n_signed") or 0)
    ed = None
    try:
        ed = float(expected_deals) if expected_deals is not None else None
    except Exception:
        ed = None
    return {
        "stat_expected_deals": ed,
        "stat_expected_contract_money": expected_contract,
        "stat_expected_commission": expected_commission,
        "agent_clue_deals": n_clue,
        "agent_contract_money": float(summary.get("expected_contract_money") or 0),
        "agent_commission": float(summary.get("expected_commission") or 0),
        "n_clues": world.get("n_clues"),
        "brokers_per_clue": world.get("brokers_per_clue"),
        "n_threads": world.get("n_threads") or summary.get("n_threads"),
        "deal_gap": (None if ed is None else float(n_clue) - ed),
        "listing_overlap_top10": len(win_listings & top_L),
        "broker_overlap_top10": len(win_brokers & top_B),
        "seed_note": world.get("seed_note"),
    }


def run_agent_for_scenario(
    decision_id: str,
    scenario: Dict[str, Any],
    *,
    total_rounds: int = DEFAULT_ROUNDS,
    n_threads: Optional[int] = None,
    listings: Optional[List[Dict]] = None,
    brokers: Optional[List[Dict]] = None,
    expected_deals: Optional[float] = None,
    expected_contract_money: Optional[float] = None,
    expected_commission: Optional[float] = None,
    n_clues: Optional[int] = None,
    brokers_per_clue: Optional[int] = None,
    on_round: Optional[Callable[[int, Dict[str, Any]], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """跑单一方案的 Agent 轨。"""
    name = str(scenario.get("name") or "方案")
    gtv = {}
    iv = scenario.get("intervention") or {}
    if isinstance(iv, dict):
        gtv = iv.get("gtv") if isinstance(iv.get("gtv"), dict) else {}
        if not gtv and any(k in iv for k in ("boost_exposure", "negotiate_deal", "reassign_broker")):
            gtv = {k: iv[k] for k in ("boost_exposure", "negotiate_deal", "reassign_broker") if k in iv}

    if listings is None or brokers is None:
        L, B = try_load_listings_from_parquet(80)
        listings = listings if listings is not None else L
        brokers = brokers if brokers is not None else B

    # 线程上限随线索规模上浮，避免旧 GTV_AGENT_THREADS=12 截断大世界
    clue_guess = n_clues
    if clue_guess is None and expected_deals is not None:
        from app.engine.gtv_agent.world import resolve_clue_n

        clue_guess = resolve_clue_n(expected_deals)
    k_guess = brokers_per_clue or int(os.environ.get("GTV_AGENT_BROKERS_PER_CLUE", "3"))
    default_threads = max(
        int(os.environ.get("GTV_AGENT_THREADS", "12")),
        int(clue_guess or 8) * int(k_guess or 3),
    )

    world = build_world(
        n_threads=n_threads or default_threads,
        intervention=scenario.get("intervention") or {"gtv": gtv},
        seed=hash(name) % 10000,
        leaderboard_listings=listings or [],
        leaderboard_brokers=brokers or [],
        n_clues=n_clues,
        brokers_per_clue=brokers_per_clue,
        expected_deals=expected_deals,
        decision_id=decision_id,
    )
    threads: List[DealThread] = world["threads"]
    events: List[Dict[str, Any]] = []

    use_rule = os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes")
    if not llm_available() and not use_rule:
        raise RuntimeError("LLM_API_KEY 未配置，成交 Agent 轨不可用")

    last_round = 0
    for r in range(1, total_rounds + 1):
        if should_abort and should_abort():
            logger.info("Agent 轨中止（新一轮推演已启动）decision=%s round=%s", decision_id, r)
            raise RuntimeError("GTV Agent 轨已取消（被新的重新推演取代）")
        last_round = r
        actions = decide_round_batch(
            threads,
            round_no=r,
            total_rounds=total_rounds,
            scenario_name=name,
            gtv=gtv,
        )
        by_id = {t.thread_id: t for t in threads}
        winners_this_round: List[DealThread] = []

        for a in actions:
            if not isinstance(a, dict):
                continue
            tid = str(a.get("thread_id") or "")
            t = by_id.get(tid)
            if not t or t.closed:
                continue
            action = str(a.get("action") or "follow_up")
            payload = {
                "concession_pct": a.get("concession_pct"),
                "contract_money": a.get("contract_money"),
                "commission": a.get("commission"),
                "target_broker_id": a.get("target_broker_id"),
                "target_thread_id": a.get("target_thread_id"),
            }
            prev = t.stage
            t.apply_action(action, payload, peers=threads)
            text = str(a.get("text") or f"{a.get('actor')}:{action}")
            reason = ensure_reason(a, t, threads)
            t.last_reason = reason
            ev = _event_from_thread(
                t,
                round_no=r,
                action=action,
                text=text,
                reason=reason,
                actor=a.get("actor"),
                prev=prev,
                source=str(a.get("source") or "llm"),
            )
            events.append(ev)
            _append_action(decision_id, {**ev, "scenario": name})
            if t.stage == "signed" and t.role_outcome != "loser":
                winners_this_round.append(t)

        # 先签先赢：同线索关闭其余
        seen_groups = set()
        for w in winners_this_round:
            g = w.deal_group_id or w.clue_id
            if g in seen_groups:
                continue
            seen_groups.add(g)
            # 同组若多人同轮签约，只认第一个赢家
            if w.role_outcome == "loser":
                continue
            closed_evs = close_clue_group_on_sign(threads, w)
            for e in reversed(events):
                if e.get("thread_id") == w.thread_id and e.get("round") == r:
                    e["role_outcome"] = "winner"
                    e["role_outcome_label"] = "胜出"
                    break
            for peer, text, reason, prev_stage in closed_evs:
                ev = _event_from_thread(
                    peer,
                    round_no=r,
                    action="compete_lost",
                    text=text,
                    reason=reason,
                    actor="system",
                    prev=prev_stage,
                    source="race_mutex",
                )
                events.append(ev)
                _append_action(decision_id, {**ev, "scenario": name})

        snap = {
            "scenario": name,
            "current_round": r,
            "total_rounds": total_rounds,
            "summary": summarize_threads(threads),
            "events_so_far": len(events),
        }
        if on_round:
            on_round(r, {"events": list(events), "summary": snap["summary"], "scenario": name})

        if all(t.closed for t in threads) or _clue_groups_done(threads):
            break

    summary = summarize_threads(threads)
    align = _align_with_stat(
        summary,
        world,
        expected_deals=expected_deals,
        expected_contract=expected_contract_money,
        expected_commission=expected_commission,
    )
    return {
        "scenario_name": name,
        "scenario_id": scenario.get("id") or scenario.get("scenario_id"),
        "kind": scenario.get("kind"),
        "summary": summary,
        "stat_align": align,
        "threads": [t.to_dict() for t in threads],
        "events": events,
        "timeline": _timeline_from_events(events),
        "intervention_gtv": gtv,
        "engine": "gtv_agent",
        "current_round": last_round,
        "total_rounds": total_rounds,
        "early_stop": bool(last_round and last_round < total_rounds),
        "world_meta": {
            "seed_note": world.get("seed_note"),
            "used_demo_fallback": world.get("used_demo_fallback"),
            "n_clues": world.get("n_clues"),
            "brokers_per_clue": world.get("brokers_per_clue"),
            "race_mode": world.get("race_mode"),
            "expected_deals_hint": world.get("expected_deals_hint"),
        },
    }


def _match_stat_scenario(
    sc: Dict[str, Any],
    scored_scenarios: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """用统计轨同名方案的三榜/预期对齐 Agent 配局。"""
    if not scored_scenarios:
        return {}
    name = str(sc.get("name") or "")
    sid = str(sc.get("id") or sc.get("scenario_id") or "")
    for row in scored_scenarios:
        if not isinstance(row, dict):
            continue
        if sid and str(row.get("scenario_id") or row.get("id") or "") == sid:
            return row
        if name and str(row.get("name") or row.get("scenario_name") or "") == name:
            return row
    return scored_scenarios[0] if scored_scenarios else {}


def run_agent_track(
    decision_id: str,
    scenarios: List[Dict[str, Any]],
    *,
    total_rounds: int = DEFAULT_ROUNDS,
    listings: Optional[List[Dict]] = None,
    brokers: Optional[List[Dict]] = None,
    scored_scenarios: Optional[List[Dict[str, Any]]] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """多方案 Agent 轨。"""
    ap = deal_actions_path(decision_id)
    if os.path.isfile(ap):
        os.remove(ap)

    write_agent_status(
        decision_id,
        {
            "status": "running",
            "track": "agent",
            "current_round": 0,
            "total_rounds": total_rounds,
            "message": "成交 Agent：线索×多经纪抢签（对齐统计三榜）",
            "llm": llm_available(),
        },
    )

    results = []
    all_events: List[Dict[str, Any]] = []
    try:
        for sc in scenarios:
            scored = _match_stat_scenario(sc, scored_scenarios)
            sc_listings = list(scored.get("listings") or []) or listings
            sc_brokers = list(scored.get("brokers") or []) or brokers
            sc_sum = scored.get("summary") or {}

            def _num(v: Any) -> Optional[float]:
                if v is None:
                    return None
                try:
                    return float(v)
                except Exception:
                    return None

            ed = _num(sc_sum.get("expected_deals"))
            ecm = _num(sc_sum.get("expected_contract_money"))
            ecc = _num(sc_sum.get("expected_commission"))

            def _on_round(r: int, payload: Dict[str, Any], _sc=sc) -> None:
                nonlocal all_events
                all_events = list(payload.get("events") or [])
                for e in all_events:
                    e.setdefault("scenario", _sc.get("name"))
                st = {
                    "status": "running",
                    "track": "agent",
                    "current_round": r,
                    "total_rounds": total_rounds,
                    "scenario": _sc.get("name"),
                    "message": f"Agent 抢签 {_sc.get('name')} · R{r}/{total_rounds}",
                    "summary": payload.get("summary"),
                    "llm": llm_available(),
                }
                write_agent_status(decision_id, st)
                if on_progress:
                    on_progress(
                        {
                            **st,
                            "events": all_events,
                            "timeline": _timeline_from_events(all_events),
                        }
                    )

            if should_abort and should_abort():
                raise RuntimeError("GTV Agent 轨已取消（被新的重新推演取代）")
            one = run_agent_for_scenario(
                decision_id,
                sc,
                total_rounds=total_rounds,
                listings=sc_listings,
                brokers=sc_brokers,
                expected_deals=ed,
                expected_contract_money=ecm,
                expected_commission=ecc,
                on_round=_on_round,
                should_abort=should_abort,
            )
            results.append(one)
            all_events = list(one.get("events") or [])

        baseline = next(
            (
                r
                for r in results
                if "baseline" in str(r.get("kind") or "").lower()
                or "baseline" in str(r.get("scenario_name") or "").lower()
            ),
            results[0] if results else None,
        )
        for r in results:
            if baseline and r is not baseline:
                bs = baseline.get("summary") or {}
                ss = r.get("summary") or {}
                r["delta_vs_baseline"] = {
                    "n_signed": {
                        "abs": int(ss.get("n_signed") or 0) - int(bs.get("n_signed") or 0)
                    },
                    "expected_contract_money": {
                        "abs": float(ss.get("expected_contract_money") or 0)
                        - float(bs.get("expected_contract_money") or 0)
                    },
                    "expected_commission": {
                        "abs": float(ss.get("expected_commission") or 0)
                        - float(bs.get("expected_commission") or 0)
                    },
                }
            else:
                r["delta_vs_baseline"] = None
                r["is_baseline"] = True

        primary_events = (results[0].get("events") if results else []) or all_events
        actual_rounds = 0
        for r in results:
            try:
                actual_rounds = max(actual_rounds, int(r.get("current_round") or 0))
            except Exception:
                pass
            for e in r.get("events") or []:
                try:
                    actual_rounds = max(actual_rounds, int(e.get("round") or e.get("day") or 0))
                except Exception:
                    pass
        if not actual_rounds:
            actual_rounds = total_rounds
        early = any(bool(r.get("early_stop")) for r in results)
        msg = "成交 Agent 线索抢签已完成"
        if early and actual_rounds < total_rounds:
            msg = f"成交 Agent 已完成（线索竞争收官于 R{actual_rounds}/{total_rounds}）"
        out = {
            "status": "completed",
            "track": "agent",
            "engine": "gtv_agent",
            "current_round": actual_rounds,
            "total_rounds": total_rounds,
            "early_stop": early and actual_rounds < total_rounds,
            "scenarios": results,
            "timeline": _timeline_from_events(primary_events),
            "message": msg,
            "llm": llm_available(),
        }
        write_agent_status(decision_id, {k: out[k] for k in out if k != "scenarios"})
        full_path = os.path.join(Config.DECISION_DIR, decision_id, "report", "agent_results.json")
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
        return out
    except Exception as e:
        logger.exception("Agent 轨失败 decision=%s", decision_id)
        err = {
            "status": "failed",
            "track": "agent",
            "engine": "gtv_agent",
            "error": str(e),
            "message": f"成交 Agent 轨失败：{e}",
            "llm": llm_available(),
            "current_round": 0,
            "total_rounds": total_rounds,
        }
        write_agent_status(decision_id, err)
        return err
