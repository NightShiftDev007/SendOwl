"""成交 Agent 轨 runner：逐轮决策并落盘。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.config import Config
from app.engine.gtv_agent.agents import decide_round_batch, llm_available
from app.engine.gtv_agent.state import STAGE_LABEL, DealThread, summarize_threads
from app.engine.gtv_agent.world import build_world, try_load_listings_from_parquet
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.runner")

DEFAULT_ROUNDS = int(os.environ.get("GTV_AGENT_ROUNDS", "16"))

_TIMELINE_NOTE = (
    "成交 Agent 推演（CRM 种子底座抽样）：线索→项目→跟进→报备→锁客→约看→带看→意向→"
    "谈价|直签→审批→签约→计租→回款→佣金；与统计轨并列，非社媒发帖、非历史流水回放"
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


def run_agent_for_scenario(
    decision_id: str,
    scenario: Dict[str, Any],
    *,
    total_rounds: int = DEFAULT_ROUNDS,
    n_threads: Optional[int] = None,
    listings: Optional[List[Dict]] = None,
    brokers: Optional[List[Dict]] = None,
    on_round: Optional[Callable[[int, Dict[str, Any]], None]] = None,
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
        L, B = try_load_listings_from_parquet(30)
        listings = listings if listings is not None else L
        brokers = brokers if brokers is not None else B

    world = build_world(
        n_threads=n_threads or int(os.environ.get("GTV_AGENT_THREADS", "10")),
        intervention=scenario.get("intervention") or {"gtv": gtv},
        seed=hash(name) % 10000,
        leaderboard_listings=listings or [],
        leaderboard_brokers=brokers or [],
    )
    threads: List[DealThread] = world["threads"]
    events: List[Dict[str, Any]] = []

    use_rule = os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() in ("1", "true", "yes")
    if not llm_available() and not use_rule:
        raise RuntimeError("LLM_API_KEY 未配置，成交 Agent 轨不可用")

    for r in range(1, total_rounds + 1):
        actions = decide_round_batch(
            threads,
            round_no=r,
            total_rounds=total_rounds,
            scenario_name=name,
            gtv=gtv,
        )
        by_id = {t.thread_id: t for t in threads}
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
                "rent_start_days": a.get("rent_start_days"),
                "payment_ratio": a.get("payment_ratio"),
            }
            prev = t.stage
            t.apply_action(action, payload)
            text = str(a.get("text") or f"{a.get('actor')}:{action}")
            ev = {
                "day": r,
                "round": r,
                "stage": t.stage,
                "stage_label": STAGE_LABEL.get(t.stage, t.stage),
                "actor": a.get("actor"),
                "action": action,
                "text": text,
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
                "project_id": t.project_id,
                "path": t.path or None,
                "from_stage": prev,
                "from_stage_label": STAGE_LABEL.get(prev, prev),
                "source": a.get("source") or "llm",
                "seed_source": t.seed_source,
            }
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

        if all(t.closed for t in threads):
            break

    summary = summarize_threads(threads)
    return {
        "scenario_name": name,
        "scenario_id": scenario.get("id") or scenario.get("scenario_id"),
        "kind": scenario.get("kind"),
        "summary": summary,
        "threads": [t.to_dict() for t in threads],
        "events": events,
        "timeline": _timeline_from_events(events),
        "intervention_gtv": gtv,
        "engine": "gtv_agent",
        "world_meta": {
            "seed_note": world.get("seed_note"),
            "used_demo_fallback": world.get("used_demo_fallback"),
        },
    }


def run_agent_track(
    decision_id: str,
    scenarios: List[Dict[str, Any]],
    *,
    total_rounds: int = DEFAULT_ROUNDS,
    listings: Optional[List[Dict]] = None,
    brokers: Optional[List[Dict]] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
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
            "message": "成交 Agent 全流程推演进行中（世界抽样自 CRM 种子底座）",
            "llm": llm_available(),
        },
    )

    results = []
    all_events: List[Dict[str, Any]] = []
    try:
        for sc in scenarios:
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
                    "message": f"Agent 推演 {_sc.get('name')} · R{r}/{total_rounds}",
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

            one = run_agent_for_scenario(
                decision_id,
                sc,
                total_rounds=total_rounds,
                listings=listings,
                brokers=brokers,
                on_round=_on_round,
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
        out = {
            "status": "completed",
            "track": "agent",
            "engine": "gtv_agent",
            "current_round": total_rounds,
            "total_rounds": total_rounds,
            "scenarios": results,
            "timeline": _timeline_from_events(primary_events),
            "message": "成交 Agent 全流程推演已完成",
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
