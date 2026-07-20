"""
GTV 成交推演场景适配器（template=gtv_deal）。

- Step2：轻量 prepare，跳过 Cast / 人设 / OASIS 双平台
- Step3：在线打分 + 干预 what-if + 多方案差分；无模型时回退静态缓存
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config
from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv")

TEMPLATE_GTV = "gtv_deal"

# 确保可 import scripts.gtv_forecast.*
_BACKEND_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

_SEED_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "scripts",
        "gtv_forecast",
        "seeds",
    )
)
_SCRIPT_DATA_REPORT = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "scripts",
        "gtv_forecast",
        "_data",
        "reports",
        "demo_report.md",
    )
)
_SCRIPT_DATA_LEADERBOARDS = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "scripts",
        "gtv_forecast",
        "_data",
        "reports",
        "leaderboards.json",
    )
)

_TYPE_LABEL = {"plant": "厂房", "office": "办公", "warehouse": "仓库"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def decision_template(decision_id: str) -> str:
    dec = registry.get_decision(decision_id) or {}
    ont_id = dec.get("ontology_id") or ""
    if not ont_id:
        return "opinion"
    ont = registry.get_ontology(ont_id) or {}
    return str(ont.get("template") or "opinion").strip().lower() or "opinion"


def is_gtv_deal(decision_id: str) -> bool:
    return decision_template(decision_id) == TEMPLATE_GTV


def seeds_dir() -> str:
    return _SEED_DIR


def load_demo_pack() -> Dict[str, Any]:
    """首页任务说明摘要包：MD + 标准提示词（非 CRM 全库）。"""
    root = seeds_dir()
    if not os.path.isdir(root):
        raise FileNotFoundError(f"GTV 种子目录不存在: {root}")

    prompt_path = os.path.join(root, "PROMPT.txt")
    prompt = ""
    if os.path.isfile(prompt_path):
        with open(prompt_path, encoding="utf-8") as f:
            prompt = f.read().strip()

    files: List[Dict[str, str]] = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".md"):
            continue
        if name == "demo_report.md":
            continue
        path = os.path.join(root, name)
        with open(path, encoding="utf-8") as f:
            files.append({"name": name, "content": f.read()})

    if not files:
        raise FileNotFoundError("GTV 种子 MD 为空")
    if not prompt:
        raise FileNotFoundError("缺少 seeds/PROMPT.txt")

    return {
        "template": TEMPLATE_GTV,
        "prompt": prompt,
        "files": files,
        "note": "任务说明摘要包（非 CRM 全库）；推演主读本机 parquet 种子底座",
    }


def get_seed_status() -> Dict[str, Any]:
    """CRM 种子底座就绪状态与规模摘要（不返回敏感绝对路径）。"""
    try:
        from scripts.gtv_forecast.config import PARQUET_DIR
    except Exception:
        return {
            "parquet_ready": False,
            "n_listings": 0,
            "n_brokers": 0,
            "n_signs": 0,
            "data_dir_label": "gtv_forecast/_data/parquet",
            "message": "未检测到本地 CRM 种子",
        }

    pq = PARQUET_DIR
    label = "gtv_forecast/_data/parquet"
    if not pq.is_dir():
        return {
            "parquet_ready": False,
            "n_listings": 0,
            "n_brokers": 0,
            "n_signs": 0,
            "data_dir_label": label,
            "message": "未检测到本地 CRM 种子",
        }

    def _nrows(name: str) -> int:
        path = pq / name
        if not path.is_file():
            return 0
        try:
            import pyarrow.parquet as pq_mod

            meta = pq_mod.read_metadata(path)
            return int(meta.num_rows or 0)
        except Exception:
            try:
                import pandas as pd

                return int(len(pd.read_parquet(path, columns=[])))
            except Exception:
                return 0

    n_plant = _nrows("e_plant_base.parquet")
    n_wh = _nrows("e_warehouse_base.parquet")
    n_office = _nrows("e_office_room.parquet")
    n_listings = n_plant + n_wh + n_office
    n_brokers = _nrows("e_sys_user.parquet")
    n_signs = _nrows("e_project_sign.parquet")
    ready = n_listings > 0
    return {
        "parquet_ready": ready,
        "n_listings": n_listings,
        "n_brokers": n_brokers,
        "n_signs": n_signs,
        "n_plant": n_plant,
        "n_warehouse": n_wh,
        "n_office": n_office,
        "data_dir_label": label,
        "message": "" if ready else "未检测到本地 CRM 种子",
    }


def resolve_demo_report_path() -> Optional[str]:
    """优先 _data 缓存，其次 seeds 内嵌 fixture。"""
    for path in (_SCRIPT_DATA_REPORT, os.path.join(_SEED_DIR, "demo_report.md")):
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def resolve_leaderboards_path() -> Optional[str]:
    for path in (
        _SCRIPT_DATA_LEADERBOARDS,
        os.path.join(_SEED_DIR, "leaderboards.json"),
    ):
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def compare_report_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "compare_report.md")


def deal_timeline_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "deal_timeline.json")


def scenario_scores_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "scenario_scores.json")


def clear_gtv_run_artifacts(decision_id: str) -> Dict[str, Any]:
    """重新推演前同步清空上一局 sidecar，避免前端轮询读到旧时间线。"""
    from app.engine.gtv_agent.runner import agent_status_path, deal_actions_path

    report_dir = os.path.join(Config.DECISION_DIR, decision_id, "report")
    os.makedirs(report_dir, exist_ok=True)
    empty_tl = {
        "template": TEMPLATE_GTV,
        "engine": "gtv_agent",
        "events": [],
        "event_count": 0,
        "note": "等待成交 Agent 全流程写入（CRM 种子底座）…",
        "generated_at": _utc_now(),
    }
    cleared: List[str] = []
    try:
        with open(deal_timeline_path(decision_id), "w", encoding="utf-8") as f:
            json.dump(empty_tl, f, ensure_ascii=False, indent=2)
        cleared.append("deal_timeline.json")
    except Exception as e:
        logger.warning("clear deal_timeline failed: %s", e)

    for rel, path in (
        ("deal_actions.jsonl", deal_actions_path(decision_id)),
        ("agent_results.json", os.path.join(report_dir, "agent_results.json")),
        ("agent_status.json", agent_status_path(decision_id)),
        ("compare_report.md", compare_report_path(decision_id)),
        ("scenario_scores.json", scenario_scores_path(decision_id)),
    ):
        try:
            if os.path.isfile(path):
                os.remove(path)
                cleared.append(rel)
        except Exception as e:
            logger.warning("clear %s failed: %s", rel, e)

    # 占位 agent_status，避免 enrich 仍吐旧 completed 摘要
    try:
        with open(agent_status_path(decision_id), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": "running",
                    "track": "agent",
                    "engine": "gtv_agent",
                    "current_round": 0,
                    "total_rounds": int(os.environ.get("GTV_AGENT_ROUNDS", "16")),
                    "message": "成交 Agent 轨准备中（已清空上一局）",
                    "updated_at": _utc_now(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        if "agent_status.json" not in cleared:
            cleared.append("agent_status.json")
    except Exception as e:
        logger.warning("reset agent_status failed: %s", e)

    return {"cleared": cleared, "deal_timeline": empty_tl}


def build_deal_timeline(
    max_listings: int = 6,
    listings: Optional[List[Dict[str, Any]]] = None,
    brokers: Optional[List[Dict[str, Any]]] = None,
    scenario_name: str = "",
) -> Dict[str, Any]:
    """基于三榜构造成交漏斗叙事：咨询 → 带看 → 意向 → 签约。

    不是 OASIS 发帖；事件日程按预测成交天数相对排布，供 Step3 时间线展示。
    """
    if listings is None or brokers is None:
        path = resolve_leaderboards_path()
        listings = list(listings or [])
        brokers = list(brokers or [])
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f) or {}
                if not listings:
                    listings = list(raw.get("listings") or [])
                if not brokers:
                    brokers = list(raw.get("brokers") or [])
            except Exception as e:
                logger.warning("读取 leaderboards 失败: %s", e)
    listings = list(listings or [])[: max(1, int(max_listings))]
    brokers = list(brokers or [])[:8]

    events: List[Dict[str, Any]] = []
    if not listings:
        # 无榜时仍给一条可读说明，避免 Step3 空白
        events.append(
            {
                "day": 0,
                "stage": "consult",
                "stage_label": "客户咨询",
                "text": "等待三榜数据以展开房源漏斗推演",
                "broker": "",
                "city": "",
                "listing_type": "",
                "listing_id": "",
                "score": None,
            }
        )
    else:
        for i, listing in enumerate(listings):
            broker = brokers[i % len(brokers)] if brokers else {}
            nick = str(broker.get("nick_name") or broker.get("user_id") or "经纪人")
            city = str(listing.get("city_name") or "—")
            ltype = str(listing.get("listing_type") or "")
            type_zh = _TYPE_LABEL.get(ltype, ltype or "房源")
            lid = str(listing.get("listing_id") or "")
            short_id = lid[-6:] if len(lid) > 6 else lid
            score = listing.get("score")
            pred = listing.get("pred_days_p50")
            actual = listing.get("days_to_sign")
            try:
                horizon = int(
                    round(
                        float(actual)
                        if actual is not None and str(actual) not in ("", "nan")
                        else (float(pred) if pred is not None else 20)
                    )
                )
            except (TypeError, ValueError):
                horizon = 20
            horizon = max(7, min(60, horizon))
            d_consult = 0 + (i % 3)
            d_show = max(d_consult + 2, int(horizon * 0.35))
            d_intent = max(d_show + 2, int(horizon * 0.7))
            d_sign = max(d_intent + 1, horizon)
            base = {
                "listing_id": lid,
                "listing_type": ltype,
                "city": city,
                "broker": nick,
                "score": round(float(score), 3) if score is not None else None,
            }
            events.append(
                {
                    **base,
                    "day": d_consult,
                    "stage": "consult",
                    "stage_label": "客户咨询",
                    "text": f"客户咨询{city}{type_zh}（…{short_id}）· 匹配经纪人 {nick}",
                }
            )
            events.append(
                {
                    **base,
                    "day": d_show,
                    "stage": "show",
                    "stage_label": "带看",
                    "text": f"{nick} 带看 {city}{type_zh}（…{short_id}）· 热度 {listing.get('heat', '—')}",
                }
            )
            events.append(
                {
                    **base,
                    "day": d_intent,
                    "stage": "intent",
                    "stage_label": "意向推进",
                    "text": f"进入意向谈判 · 预测成交分 {base['score'] if base['score'] is not None else '—'} · 约 {horizon} 天窗口",
                }
            )
            signed = int(listing.get("label") or 0) == 1
            events.append(
                {
                    **base,
                    "day": d_sign,
                    "stage": "sign" if signed else "hold",
                    "stage_label": "签合同成交" if signed else "窗口内未成交",
                    "text": (
                        f"审批通过签约 · {city}{type_zh}（…{short_id}）· 经纪人 {nick}"
                        if signed
                        else f"预测窗口结束未签约 · {city}{type_zh}（…{short_id}）仍可跟进"
                    ),
                }
            )

    events.sort(key=lambda e: (int(e.get("day") or 0), str(e.get("stage") or "")))
    return {
        "template": TEMPLATE_GTV,
        "engine": "gtv_forecast",
        "generated_at": _utc_now(),
        "source": resolve_leaderboards_path() or "",
        "scenario_name": scenario_name,
        "note": "成交漏斗推演叙事（咨询→带看→意向→签约），基于在线打分/缓存三榜，非社媒发帖模拟",
        "event_count": len(events),
        "events": events,
    }


def materialize_deal_timeline(
    decision_id: str,
    listings: Optional[List[Dict[str, Any]]] = None,
    brokers: Optional[List[Dict[str, Any]]] = None,
    scenario_name: str = "",
) -> Dict[str, Any]:
    timeline = build_deal_timeline(
        listings=listings, brokers=brokers, scenario_name=scenario_name
    )
    path = deal_timeline_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    return timeline


def load_deal_timeline(decision_id: str) -> Optional[Dict[str, Any]]:
    path = deal_timeline_path(decision_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_gtv_stub_sim(sim_id: str, title: str) -> None:
    """写入可通过 _sim_dir_looks_prepared / eventReady 门槛的最小 stub。"""
    run_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
    os.makedirs(run_dir, exist_ok=True)

    profiles = [
        {
            "user_id": 1,
            "user_name": "gtv_broker_a",
            "name": "演示经纪人A",
            "bio": "GTV 商业模板占位人设（非社媒推演）",
            "persona": "工业地产经纪人",
        },
        {
            "user_id": 2,
            "user_name": "gtv_listing_b",
            "name": "演示房源观察员B",
            "bio": "GTV 商业模板占位人设（非社媒推演）",
            "persona": "房源运营",
        },
    ]
    with open(os.path.join(run_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "twitter_profiles.json"), "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)

    event_config = {
        "initial_posts": [
            {
                "content": "GTV 成交推演：统计引擎将输出经纪人/房源/时间三榜（非社媒发帖）。",
                "agent_id": 1,
            },
            {
                "content": "回测优先复用已有 demo_report；能力边界见种子摘要。",
                "agent_id": 2,
            },
        ],
        "hot_topics": ["工业地产成交", "经纪人开单", "房源排序"],
        "narrative_direction": title or "GTV 成交统计推演",
    }
    cfg = {
        "time_config": {
            "total_rounds": 4,
            "minutes_per_round": 30,
            "start_time": _utc_now(),
        },
        "agent_configs": [
            {"agent_id": 1, "user_name": "gtv_broker_a"},
            {"agent_id": 2, "user_name": "gtv_listing_b"},
        ],
        "event_config": event_config,
        "simulation_requirement": title or "GTV 成交推演",
        "template": TEMPLATE_GTV,
        "engine": "gtv_forecast",
    }
    with open(os.path.join(run_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    marker = {
        "engine": "gtv_forecast",
        "template": TEMPLATE_GTV,
        "prepared_at": _utc_now(),
        "skip_oasis": True,
    }
    with open(os.path.join(run_dir, "gtv_engine.json"), "w", encoding="utf-8") as f:
        json.dump(marker, f, ensure_ascii=False, indent=2)


def prepare_gtv_deal(runner: Any, decision_id: str, force: bool = False) -> Dict[str, Any]:
    """轻量准备：跳过 Cast/人设/双平台，直接 prepared。"""
    from app.engine.scenario_runner import _write_prepare_progress

    dec = registry.get_decision(decision_id)
    if not dec:
        raise ValueError(f"决策不存在: {decision_id}")

    runs_existing = registry.list_runs_for_decision(decision_id) or []
    if (
        not force
        and str(dec.get("status") or "").lower() == "prepared"
        and runs_existing
        and all(
            r.get("sim_id")
            and os.path.isfile(
                os.path.join(
                    Config.OASIS_SIMULATION_DATA_DIR,
                    r["sim_id"],
                    "gtv_engine.json",
                )
            )
            for r in runs_existing
        )
    ):
        prefer = runs_existing[0].get("sim_id")
        world = {}
        try:
            world = runner.get_world_assets(decision_id, prefer_sim_id=prefer)
        except Exception:
            pass
        return {
            "decision_id": decision_id,
            "status": "completed",
            "progress": 100,
            "stage": "ready",
            "message": "商业模板环境已就绪（缓存）",
            "sim_id": prefer,
            "profile_count": len(world.get("profiles") or []) or 2,
            "config": world.get("config"),
            "already_prepared": True,
            "mode": "gtv_light",
            "template": TEMPLATE_GTV,
        }

    logger.info("商业模板：已跳过社媒环境准备 decision=%s", decision_id)
    _write_prepare_progress(
        decision_id,
        status="running",
        stage="ready",
        progress=40,
        message="商业模板：已跳过社媒环境准备",
        profile_count=2,
    )

    # 确保有 sim 空壳
    runner.ensure_sims(decision_id)
    runs = registry.list_runs_for_decision(decision_id) or []
    if not runs:
        raise ValueError("决策下无 Run，无法准备 GTV 环境")

    title = dec.get("title") or decision_id
    for run in runs:
        sim_id = run.get("sim_id")
        if not sim_id:
            continue
        if force or not os.path.isfile(
            os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id, "gtv_engine.json")
        ):
            _write_gtv_stub_sim(sim_id, title)
        registry.update_run(
            run["id"],
            status="ready",
            run_dir=os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id),
        )

    registry.update_decision(decision_id, status="prepared")
    prefer = runs[0].get("sim_id")
    _write_prepare_progress(
        decision_id,
        status="completed",
        stage="ready",
        progress=100,
        message="商业模板环境已就绪（跳过社媒人设/OASIS）",
        profile_count=2,
        config_ready=True,
    )

    world = {}
    try:
        world = runner.get_world_assets(decision_id, prefer_sim_id=prefer)
    except Exception as e:
        logger.debug("gtv get_world_assets: %s", e)

    return {
        "decision_id": decision_id,
        "status": "completed",
        "progress": 100,
        "stage": "ready",
        "message": "商业模板：已跳过社媒环境准备",
        "sim_id": prefer,
        "profile_count": len(world.get("profiles") or []) or 2,
        "config": world.get("config"),
        "already_prepared": False,
        "mode": "gtv_light",
        "template": TEMPLATE_GTV,
    }


def _load_decision_scenarios(decision_id: str) -> List[Dict[str, Any]]:
    rows = registry.list_scenarios(decision_id) or []
    out: List[Dict[str, Any]] = []
    for sc in rows:
        out.append(
            {
                "id": sc.get("id"),
                "scenario_id": sc.get("id"),
                "name": sc.get("name"),
                "kind": sc.get("kind"),
                "color": sc.get("color"),
                "intervention": sc.get("intervention") or {},
            }
        )
    if not out:
        out = [
            {
                "name": "Baseline·不干预",
                "kind": "baseline",
                "color": "#7f8c8d",
                "intervention": {},
            }
        ]
    return out


def _run_online_scoring(decision_id: str) -> Tuple[Dict[str, Any], str, str]:
    """多方案在线打分；失败则回退静态 demo_report。"""
    from scripts.gtv_forecast.scoring import (
        render_compare_markdown,
        score_scenarios,
        write_score_artifacts,
    )

    scenarios = _load_decision_scenarios(decision_id)
    try:
        multi = score_scenarios(scenarios)
        write_score_artifacts(multi)  # 同步写 scripts/_data/reports
        md = render_compare_markdown(multi)
        mode = str(multi.get("mode") or "model")
        src = f"online_score:{mode}"
    except Exception as e:
        logger.warning("GTV 在线打分失败，回退缓存报告: %s", e)
        multi = {"mode": "cache", "scenarios": [], "error": str(e)}
        src_path = resolve_demo_report_path()
        if not src_path:
            raise FileNotFoundError(
                "在线打分失败且无演示报告缓存。请先："
                "cd backend && .venv/bin/python -m scripts.gtv_forecast train"
            ) from e
        with open(src_path, encoding="utf-8") as f:
            md = f.read().strip() + "\n"
        src = src_path
        mode = "cache"

    out = compare_report_path(decision_id)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if not md.lstrip().startswith("#"):
        md = "# 商业模板 · GTV 成交推演\n\n" + md
    header = f"\n\n> decision=`{decision_id}` · 写入 {_utc_now()} · source=`{src}`\n"
    if "decision=`" not in md:
        # 插在首段后
        parts = md.split("\n", 1)
        md = parts[0] + header + (parts[1] if len(parts) > 1 else "")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md if md.endswith("\n") else md + "\n")

    scores_path = scenario_scores_path(decision_id)
    try:
        from scripts.gtv_forecast.scoring import json_safe

        multi = json_safe(multi)
    except Exception:
        pass
    with open(scores_path, "w", encoding="utf-8") as f:
        json.dump(multi, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)

    meta_path = os.path.join(os.path.dirname(out), "gtv_report_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "template": TEMPLATE_GTV,
                "source": src,
                "mode": multi.get("mode"),
                "n_scenarios": len(multi.get("scenarios") or []),
                "written_at": _utc_now(),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    return multi, out, src


def _write_run_states(
    decision_id: str,
    *,
    current_round: int,
    total_rounds: int,
    status: str,
    message: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    runs = registry.list_runs_for_decision(decision_id) or []
    for run in runs:
        sim_id = run.get("sim_id")
        if not sim_id:
            continue
        try:
            state_path = os.path.join(
                Config.OASIS_SIMULATION_DATA_DIR, sim_id, "run_state.json"
            )
            payload = {
                "simulation_id": sim_id,
                "status": status,
                "current_round": current_round,
                "total_rounds": total_rounds,
                "twitter_current_round": current_round,
                "reddit_current_round": current_round,
                "twitter_completed": status == "completed",
                "reddit_completed": status == "completed",
                "engine": "gtv_dual",
                "message": message,
                **(extra or {}),
            }
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("gtv run_state write skip: %s", e)


def _merge_dual_report(
    decision_id: str,
    multi: Dict[str, Any],
    agent_out: Dict[str, Any],
    stat_md: str,
) -> str:
    """合并统计轨 + Agent 轨报告。"""
    lines = [
        "# 商业模板 · GTV 双轨推演",
        "",
        "> **Agent 轨** = 成交过程涌现 · **统计轨** = 历史模型敏感性（非因果）· 谈价≠公司单方改挂牌价",
        "",
        "## 一、成交 Agent 轨（过程与涌现结果）",
        "",
    ]
    if agent_out.get("status") == "failed":
        lines += [
            f"**Agent 轨不可用**：{agent_out.get('error') or agent_out.get('message')}",
            "",
            "统计轨结果见下文，不受影响。",
            "",
        ]
    else:
        for sc in agent_out.get("scenarios") or []:
            s = sc.get("summary") or {}
            lines.append(f"### {sc.get('scenario_name')}")
            lines.append(
                f"- 签约落地 {s.get('n_signed', 0)} / 流失 {s.get('n_lost', 0)} / "
                f"线程 {s.get('n_threads', 0)}"
            )
            lines.append(
                f"- 报备 {s.get('n_reported', 0)} · 锁客 {s.get('n_locked', 0)} · "
                f"审批通过 {s.get('n_approved', 0)} · 回款 {s.get('n_payment', 0)}"
            )
            lines.append(
                f"- 谈价成交 {s.get('n_nego_signed', 0)} · 直签成交 {s.get('n_direct_signed', 0)}"
            )
            lines.append(
                f"- 涌现合同额 {float(s.get('expected_contract_money') or 0):,.0f} · "
                f"佣金 {float(s.get('expected_commission') or 0):,.0f}"
            )
            dlt = sc.get("delta_vs_baseline") or {}
            if dlt:
                cm = (dlt.get("expected_contract_money") or {}).get("abs")
                if cm is not None:
                    lines.append(f"- 较 Baseline 合同额 {float(cm):+,.0f}")
            lines.append("")
        # 动作摘录
        evs = (agent_out.get("timeline") or {}).get("events") or []
        if evs:
            lines.append("### 动作摘录（节选）")
            for e in evs[-12:]:
                lines.append(
                    f"- R{e.get('round') or e.get('day')} · {e.get('stage_label')} · {e.get('text')}"
                )
            lines.append("")

    lines += [
        "---",
        "",
        "## 二、统计模型对照（历史模型 / what-if）",
        "",
    ]
    # 去掉统计 md 重复一级标题
    body = (stat_md or "").strip()
    if body.startswith("#"):
        body = "\n".join(body.split("\n")[1:]).strip()
    lines.append(body or "_统计轨无正文_")
    lines.append("")

    out = compare_report_path(decision_id)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    md = "\n".join(lines)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md if md.endswith("\n") else md + "\n")
    return out


_DUAL_GEN: Dict[str, int] = {}


def _dual_gen_path(decision_id: str) -> str:
    return os.path.join(Config.DECISION_DIR, decision_id, "report", "dual_gen.json")


def _read_dual_gen(decision_id: str) -> int:
    """跨进程可读的双轨代数（Flask reloader 会丢内存 _DUAL_GEN）。"""
    path = _dual_gen_path(decision_id)
    if not os.path.isfile(path):
        return int(_DUAL_GEN.get(decision_id) or 0)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("gen") or 0)
    except Exception:
        return int(_DUAL_GEN.get(decision_id) or 0)


def _write_dual_gen(decision_id: str, gen: int) -> None:
    path = _dual_gen_path(decision_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"gen": int(gen), "updated_at": _utc_now()}, f, ensure_ascii=False)
    _DUAL_GEN[decision_id] = int(gen)


def _dual_track_worker(runner: Any, decision_id: str, gen: int) -> None:
    """后台：统计轨 → Agent 轨 → 合并报告。"""
    from app.engine.gtv_agent.runner import run_agent_track
    from app.engine.gtv_agent.agents import llm_available
    from scripts.gtv_forecast.scoring import render_compare_markdown

    def _stale() -> bool:
        # 磁盘 gen 优先：热重载后旧 daemon 线程仍可能存活，不能只看内存
        return _read_dual_gen(decision_id) != gen

    total_rounds = int(os.environ.get("GTV_AGENT_ROUNDS", "16"))
    now = _utc_now()
    try:
        # 清空上一轮 Agent 时间线，避免统计剧本残留冒充过程
        try:
            path = deal_timeline_path(decision_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "template": TEMPLATE_GTV,
                        "engine": "gtv_agent",
                        "events": [],
                        "event_count": 0,
                        "note": "等待成交 Agent 全流程写入（现实种子底座）…",
                        "generated_at": _utc_now(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass
        _write_run_states(
            decision_id,
            current_round=0,
            total_rounds=total_rounds,
            status="running",
            message="统计轨打分中…",
        )
        multi, _report_tmp, src = _run_online_scoring(decision_id)
        if _stale():
            logger.info("GTV dual stale after scoring decision=%s gen=%s", decision_id, gen)
            return
        scenarios = multi.get("scenarios") or []
        primary = next((s for s in scenarios if s.get("is_baseline")), None) or (
            scenarios[0] if scenarios else {}
        )
        stat_md = render_compare_markdown(multi)

        # 用统计榜作 Agent 世界抽样
        listings = list(primary.get("listings") or [])
        brokers = list(primary.get("brokers") or [])

        def on_progress(payload: Dict[str, Any]) -> None:
            if _stale():
                return
            r = int(payload.get("current_round") or 0)
            tl = payload.get("timeline") or {}
            path = deal_timeline_path(decision_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tl, f, ensure_ascii=False, indent=2)
            _write_run_states(
                decision_id,
                current_round=r,
                total_rounds=total_rounds,
                status="running",
                message=str(payload.get("message") or ""),
                extra={"gtv_stage": (tl.get("events") or [{}])[-1].get("stage_label") if tl.get("events") else ""},
            )

        # 无 LLM 且未开规则回退：Agent 轨明确失败，统计仍完成
        if not llm_available() and os.environ.get("GTV_AGENT_RULE_FALLBACK", "").lower() not in (
            "1",
            "true",
            "yes",
        ):
            agent_out = {
                "status": "failed",
                "track": "agent",
                "error": "LLM_API_KEY 未配置",
                "message": "成交 Agent 轨不可用：未配置 LLM。统计轨已完成，可对照三榜与经济量。",
                "scenarios": [],
                "timeline": {
                    "engine": "gtv_agent",
                    "events": [],
                    "note": "Agent 轨未运行（无 LLM）",
                    "event_count": 0,
                },
            }
            from app.engine.gtv_agent.runner import write_agent_status

            write_agent_status(decision_id, agent_out)
            # 禁止用统计剧本填满 Agent 时间线；仅写空轨 + 明示不可用
            path = deal_timeline_path(decision_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "template": TEMPLATE_GTV,
                        "engine": "gtv_agent",
                        "events": [],
                        "event_count": 0,
                        "note": "成交 Agent 轨未运行：未配置 LLM。下方统计轨仍可用。",
                        "generated_at": _utc_now(),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        else:
            # 对齐 registry scenarios（含 id）
            sc_rows = _load_decision_scenarios(decision_id)
            agent_out = run_agent_track(
                decision_id,
                sc_rows,
                total_rounds=total_rounds,
                listings=listings,
                brokers=brokers,
                on_progress=on_progress,
                should_abort=_stale,
            )
            if _stale():
                logger.info("GTV dual stale after agent decision=%s gen=%s", decision_id, gen)
                return
            if agent_out.get("status") != "failed":
                tl = agent_out.get("timeline") or {}
                path = deal_timeline_path(decision_id)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(tl, f, ensure_ascii=False, indent=2)

        if _stale():
            logger.info("GTV dual stale before finalize decision=%s gen=%s", decision_id, gen)
            return

        report_path = _merge_dual_report(decision_id, multi, agent_out, stat_md)

        runs = registry.list_runs_for_decision(decision_id) or []
        sc_by_id = {str(s.get("scenario_id")): s for s in scenarios}
        agent_by_name = {
            str(s.get("scenario_name")): s for s in (agent_out.get("scenarios") or [])
        }
        # 实际跑到的轮次（可能因全部 settle/lost 提前结束，或跑满 total_rounds）
        agent_rounds = 0
        for s in agent_out.get("scenarios") or []:
            for e in s.get("events") or []:
                try:
                    agent_rounds = max(agent_rounds, int(e.get("round") or e.get("day") or 0))
                except Exception:
                    pass
        if not agent_rounds:
            agent_rounds = int(agent_out.get("current_round") or total_rounds)

        for run in runs:
            sc = sc_by_id.get(str(run.get("scenario_id") or "")) or primary
            ag = agent_by_name.get(str((sc or {}).get("name") or ""))
            summary = (sc or {}).get("summary") or {}
            registry.update_run(
                run["id"],
                status="completed",
                started_at=run.get("started_at") or now,
                finished_at=_utc_now(),
                error="" if agent_out.get("status") != "failed" else str(agent_out.get("error") or ""),
                metrics={
                    "engine": "gtv_dual",
                    "template": TEMPLATE_GTV,
                    "report_source": src,
                    "stat_mode": multi.get("mode"),
                    "agent_status": agent_out.get("status"),
                    "agent_rounds": agent_rounds,
                    "agent_total_rounds": total_rounds,
                    "expected_deals": summary.get("expected_deals"),
                    "expected_contract_money": summary.get("expected_contract_money"),
                    "expected_commission": summary.get("expected_commission"),
                    "agent_signed": (ag or {}).get("summary", {}).get("n_signed") if ag else None,
                    "delta_vs_baseline": (sc or {}).get("delta_vs_baseline"),
                },
            )

        # 再次确认：finalize 前旧 worker 不得把决策打成 completed
        if _stale():
            logger.info("GTV dual stale at finalize decision=%s gen=%s", decision_id, gen)
            return

        from app.engine.gtv_agent.runner import write_agent_status

        # 与决策终态对齐：显式写 agent_status（含实际轮次 / 是否提前收官）
        if agent_out.get("status") != "failed":
            write_agent_status(
                decision_id,
                {
                    "status": "completed",
                    "track": "agent",
                    "engine": "gtv_agent",
                    "current_round": agent_rounds,
                    "total_rounds": total_rounds,
                    "early_stop": bool(agent_out.get("early_stop")),
                    "message": agent_out.get("message")
                    or f"成交 Agent 已完成 R{agent_rounds}/{total_rounds}",
                    "dual_gen": gen,
                },
            )

        _write_run_states(
            decision_id,
            current_round=agent_rounds,
            total_rounds=total_rounds,
            status="completed",
            message=f"GTV 双轨推演完成（Agent {agent_rounds}/{total_rounds} 轮）",
        )
        registry.update_decision(decision_id, status="completed")
        logger.info(
            "GTV 双轨完成 decision=%s report=%s agent=%s rounds=%s/%s stat=%s",
            decision_id,
            report_path,
            agent_out.get("status"),
            agent_rounds,
            total_rounds,
            multi.get("mode"),
        )
    except Exception as e:
        # 被新一轮推演取代时，禁止把决策打成 failed（否则新 worker 会被污染）
        if _stale() or "已取消" in str(e) or "被新的重新推演取代" in str(e):
            logger.info(
                "GTV dual aborted (stale/superseded) decision=%s gen=%s err=%s",
                decision_id,
                gen,
                e,
            )
            return
        logger.exception("GTV 双轨失败 decision=%s", decision_id)
        if _stale():
            return
        registry.update_decision(decision_id, status="failed")
        _write_run_states(
            decision_id,
            current_round=0,
            total_rounds=total_rounds,
            status="failed",
            message=str(e),
        )
        try:
            from app.engine.gtv_agent.runner import write_agent_status

            write_agent_status(
                decision_id,
                {"status": "failed", "track": "agent", "error": str(e), "message": str(e)},
            )
        except Exception:
            pass


def start_gtv_deal(runner: Any, decision_id: str, force: bool = False) -> Dict[str, Any]:
    """双轨：统计 what-if + 成交 Agent 逐轮；立即返回 running。"""
    import threading

    from app.engine.gtv_agent.runner import load_agent_status

    dec = registry.get_decision(decision_id)
    if not dec:
        raise ValueError(f"决策不存在: {decision_id}")

    status = str(dec.get("status") or "").lower()
    if status == "running" and not force:
        snap = runner.get_status(decision_id)
        snap["attached"] = True
        snap["decision_id"] = decision_id
        snap["message"] = "GTV 双轨推演进行中（附着）"
        snap["template"] = TEMPLATE_GTV
        snap["engine"] = "gtv_dual"
        ag = load_agent_status(decision_id)
        if ag:
            snap["agent_status"] = ag
        scores_path = scenario_scores_path(decision_id)
        if os.path.isfile(scores_path):
            try:
                with open(scores_path, encoding="utf-8") as f:
                    snap["scenario_scores"] = json.load(f)
            except Exception:
                pass
        tl = load_deal_timeline(decision_id)
        if tl:
            snap["deal_timeline"] = tl
        return snap

    if status == "completed" and not force:
        out = compare_report_path(decision_id)
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            timeline = load_deal_timeline(decision_id)
            snap = runner.get_status(decision_id)
            snap["decision_id"] = decision_id
            snap["message"] = "GTV 双轨推演已完成（缓存）"
            snap["template"] = TEMPLATE_GTV
            snap["compare_report"] = out
            snap["deal_timeline"] = timeline
            snap["engine"] = "gtv_dual"
            scores_path = scenario_scores_path(decision_id)
            if os.path.isfile(scores_path):
                try:
                    with open(scores_path, encoding="utf-8") as f:
                        snap["scenario_scores"] = json.load(f)
                except Exception:
                    pass
            ag = load_agent_status(decision_id)
            if ag:
                snap["agent_status"] = ag
            return snap

    if status in (None, "", "created", "pending", "prepare_failed") or force:
        prepare_gtv_deal(runner, decision_id, force=force)

    # 启动前同步清空上一局时间线/Agent 产物（必须在返回前完成，否则前端会立刻读到旧数据）
    cleared = clear_gtv_run_artifacts(decision_id)

    total_rounds = int(os.environ.get("GTV_AGENT_ROUNDS", "16"))
    registry.update_decision(decision_id, status="running")
    now = _utc_now()
    for run in registry.list_runs_for_decision(decision_id) or []:
        registry.update_run(run["id"], status="running", started_at=run.get("started_at") or now)
    _write_run_states(
        decision_id,
        current_round=0,
        total_rounds=total_rounds,
        status="running",
        message="GTV 双轨启动：统计轨 + Agent 轨",
    )

    gen = _read_dual_gen(decision_id) + 1
    _write_dual_gen(decision_id, gen)
    t = threading.Thread(
        target=_dual_track_worker,
        args=(runner, decision_id, gen),
        name=f"gtv-dual-{decision_id}-{gen}",
        daemon=True,
    )
    t.start()

    snap = runner.get_status(decision_id)
    snap["decision_id"] = decision_id
    snap["status"] = "running"
    snap["message"] = "GTV 双轨推演已启动（统计轨 + 成交 Agent）"
    snap["template"] = TEMPLATE_GTV
    snap["engine"] = "gtv_dual"
    snap["total_rounds"] = total_rounds
    snap["current_round"] = 0
    snap["force_restarted"] = bool(force)
    snap["deal_timeline"] = cleared.get("deal_timeline")
    snap["scenario_scores"] = None
    snap["agent_status"] = {
        "status": "running",
        "current_round": 0,
        "total_rounds": total_rounds,
        "message": "成交 Agent 轨准备中（已清空上一局）",
    }
    return snap


def enrich_gtv_status(decision_id: str, status: Dict[str, Any]) -> Dict[str, Any]:
    """供 get_decision_detail 挂载双轨字段。"""
    from app.engine.gtv_agent.runner import load_agent_status

    try:
        ag = load_agent_status(decision_id)
        if ag:
            status["agent_status"] = ag
            status["current_round"] = ag.get("current_round")
            status["total_rounds"] = ag.get("total_rounds")
        scores_path = scenario_scores_path(decision_id)
        if os.path.isfile(scores_path):
            with open(scores_path, encoding="utf-8") as f:
                status["scenario_scores"] = json.load(f)
        else:
            # 显式 null：重新推演清空后前端应丢掉旧统计卡
            status["scenario_scores"] = None
        tl = load_deal_timeline(decision_id)
        status["deal_timeline"] = tl or {
            "template": TEMPLATE_GTV,
            "engine": "gtv_agent",
            "events": [],
            "event_count": 0,
        }
        status["engine"] = status.get("engine") or "gtv_dual"
    except Exception as e:
        logger.debug("enrich_gtv_status: %s", e)
    return status
