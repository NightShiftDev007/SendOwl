"""
决策指标服务：包装 metrics_core，支持单次 run 与方案聚合对比
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.decision import metrics_core as mc
from app.ontology import registry
from app.utils.logger import get_logger

logger = get_logger("adc.decision.metrics")


def _load_actions_from_run_dir(run_dir: str | Path) -> tuple[List[Dict], List[Dict]]:
    """返回 (actions, interviews)。"""
    d = Path(run_dir)
    interviews: List[Dict] = []
    actions: List[Dict] = []

    if (d / "bundle.json").exists():
        bundle = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
        return list(bundle.get("actions") or []), list(bundle.get("interviews") or [])

    actions_path = d / "actions.jsonl"
    if not actions_path.exists() and (d / "twitter" / "actions.jsonl").exists():
        actions_path = d / "twitter" / "actions.jsonl"
    if actions_path.exists():
        actions = mc.load_actions_jsonl(actions_path)

    db_actions: List[Dict] = []
    for db in list(d.glob("*_simulation.db")) + list(d.glob("*.db")):
        db_actions = mc.actions_from_db(db)
        if db_actions:
            break

    contentful_from_log = []
    for a in actions:
        args = a.get("action_args") if isinstance(a.get("action_args"), dict) else {}
        content = a.get("content") or (args.get("content") if args else "") or ""
        if content.strip() and a.get("action_type") not in (None, "LLM_ACTION"):
            contentful_from_log.append(
                {
                    **a,
                    "content": content,
                    "action_type": a.get("action_type") or "CREATE_POST",
                }
            )

    if db_actions:
        actions = db_actions
    elif contentful_from_log:
        actions = contentful_from_log

    if (d / "interviews.json").exists():
        interviews = json.loads((d / "interviews.json").read_text(encoding="utf-8"))

    return actions, interviews


def compute_run_metrics(
    run_dir: str | Path,
    scenario_id: str = "",
    scenario_name: str = "",
    color: str = "#333",
) -> Dict[str, Any]:
    """对单个 run 目录计算指标。"""
    actions, interviews = _load_actions_from_run_dir(run_dir)
    return mc.compute_metrics(
        scenario_id=scenario_id or Path(run_dir).name,
        scenario_name=scenario_name or scenario_id or Path(run_dir).name,
        actions_raw=actions,
        interviews=interviews,
        color=color,
    )


def _mean_std(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0, "n": 0}
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return {"mean": round(mean, 4), "std": 0.0, "n": 1}
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return {"mean": round(mean, 4), "std": round(math.sqrt(var), 4), "n": n}


def aggregate_scenario(runs_metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    对同一方案多次采样的 metrics 做 mean ± std。
    聚合 totals 与 stance shares。
    """
    if not runs_metrics:
        return {
            "summary": {
                "total_actions": {"mean": 0, "std": 0, "n": 0},
                "contentful_actions": {"mean": 0, "std": 0, "n": 0},
                "max_cascade_depth": {"mean": 0, "std": 0, "n": 0},
                "stance_share": {
                    "supportive": {"mean": 0, "std": 0, "n": 0},
                    "opposing": {"mean": 0, "std": 0, "n": 0},
                    "neutral": {"mean": 0, "std": 0, "n": 0},
                },
            },
            "runs": [],
        }

    totals = [float(m.get("summary", {}).get("total_actions", 0)) for m in runs_metrics]
    contentful = [
        float(m.get("summary", {}).get("contentful_actions", 0)) for m in runs_metrics
    ]
    depths = [
        float(m.get("summary", {}).get("max_cascade_depth", 0)) for m in runs_metrics
    ]
    supportive = [
        float(m.get("summary", {}).get("stance_share", {}).get("supportive", 0))
        for m in runs_metrics
    ]
    opposing = [
        float(m.get("summary", {}).get("stance_share", {}).get("opposing", 0))
        for m in runs_metrics
    ]
    neutral = [
        float(m.get("summary", {}).get("stance_share", {}).get("neutral", 0))
        for m in runs_metrics
    ]

    first = runs_metrics[0]
    return {
        "scenario_id": first.get("scenario_id"),
        "scenario_name": first.get("scenario_name"),
        "color": first.get("color", "#333"),
        "summary": {
            "total_actions": _mean_std(totals),
            "contentful_actions": _mean_std(contentful),
            "max_cascade_depth": _mean_std(depths),
            "stance_share": {
                "supportive": _mean_std(supportive),
                "opposing": _mean_std(opposing),
                "neutral": _mean_std(neutral),
            },
        },
        # 用均值曲线：取第一次采样的曲线作代表（MVP）
        "activity_curve": first.get("activity_curve") or [],
        "reach_curve": first.get("reach_curve") or [],
        "stance_curve": first.get("stance_curve") or [],
        "sample_count": len(runs_metrics),
        "runs": runs_metrics,
    }


def build_compare_payload(decision_id: str) -> Dict[str, Any]:
    """聚合决策下各方案指标，形成对比 payload。"""
    registry.init_schema()
    dec = registry.get_decision(decision_id)
    if not dec:
        raise ValueError(f"决策不存在: {decision_id}")

    scenarios = registry.list_scenarios(decision_id)
    aggregated = []
    for sc in scenarios:
        runs = registry.list_runs_for_scenario(sc["id"])
        metrics_list = []
        for r in runs:
            m = r.get("metrics")
            if not m and r.get("run_dir") and os.path.isdir(r["run_dir"]):
                try:
                    m = compute_run_metrics(
                        r["run_dir"],
                        scenario_id=sc.get("kind") or sc["id"],
                        scenario_name=sc.get("name") or "",
                        color=sc.get("color") or "#333",
                    )
                    registry.update_run(r["id"], metrics=m)
                except Exception as e:
                    logger.warning(f"compute metrics for {r['id']} failed: {e}")
            if m:
                # 确保带上方案元信息
                m = {
                    **m,
                    "scenario_id": sc.get("kind") or sc["id"],
                    "scenario_name": sc.get("name") or m.get("scenario_name"),
                    "color": sc.get("color") or m.get("color") or "#333",
                    "run_id": r["id"],
                    "seed": r.get("seed"),
                }
                metrics_list.append(m)
        aggregated.append(aggregate_scenario(metrics_list) if metrics_list else {
            "scenario_id": sc.get("kind") or sc["id"],
            "scenario_name": sc.get("name"),
            "color": sc.get("color"),
            "summary": aggregate_scenario([])["summary"],
            "sample_count": 0,
            "runs": [],
        })

    # 规则叙事
    flat_for_narrative = []
    for agg in aggregated:
        if not agg.get("runs"):
            continue
        # 用均值构造伪 summary 供 llm_summarize / 规则摘要
        s = agg["summary"]
        flat_for_narrative.append(
            {
                "scenario_id": agg.get("scenario_id"),
                "scenario_name": agg.get("scenario_name"),
                "color": agg.get("color"),
                "summary": {
                    "total_actions": s["total_actions"]["mean"],
                    "contentful_actions": s["contentful_actions"]["mean"],
                    "max_cascade_depth": s["max_cascade_depth"]["mean"],
                    "avg_cascade_depth": 0,
                    "stance_share": {
                        "supportive": s["stance_share"]["supportive"]["mean"],
                        "opposing": s["stance_share"]["opposing"]["mean"],
                        "neutral": s["stance_share"]["neutral"]["mean"],
                    },
                    "stance_counts": {},
                    "rounds": 0,
                },
            }
        )

    narratives = {}
    if flat_for_narrative:
        try:
            narratives = mc.llm_summarize(flat_for_narrative)
        except Exception:
            for m in flat_for_narrative:
                share = m["summary"]["stance_share"]
                narratives[m["scenario_id"]] = (
                    f"{m['scenario_name']}：总互动 {m['summary']['total_actions']}，"
                    f"赞成{share['supportive']:.0%} / 反对{share['opposing']:.0%} / "
                    f"中立{share['neutral']:.0%}。"
                )

    for agg in aggregated:
        sid = agg.get("scenario_id")
        agg["narrative"] = narratives.get(sid, "")

    return {
        "decision_id": decision_id,
        "title": dec.get("title"),
        "status": dec.get("status"),
        "scenarios": aggregated,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
