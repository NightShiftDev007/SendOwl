"""Write human-readable demo report from backtest outputs."""

from __future__ import annotations

import json
from pathlib import Path

from .config import REPORT_DIR


def write_demo_report(summary: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    gate_path = REPORT_DIR / "feasibility_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.exists() else {}
    labels = gate.get("label_summary") or {}
    boards = summary.get("leaderboards") or {}

    lines = [
        "# GTV 成交推演试点 — G0/G1 演示报告",
        "",
        "> 离线试点，未接入决策中心五步流程 / OASIS。相对排序工具，非精确点预测。",
        "",
        "## 1. 数据与门禁",
        "",
        f"- 已通过签约：**{labels.get('approved_deals')}**",
        f"- 时间跨度：{labels.get('event_time_min')} → {labels.get('event_time_max')}",
        f"- 佣金归因覆盖：{labels.get('commission_coverage', 0):.1%}"
        if isinstance(labels.get("commission_coverage"), (int, float))
        else f"- 佣金归因覆盖：{labels.get('commission_coverage')}",
        f"- 门禁 pass_gate：**{summary.get('gate_pass')}** / accept(相对基线)：**{summary.get('accept')}**",
        f"- 回测折 T0：{', '.join(summary.get('folds_used') or [])}",
        "",
        "### 能力边界",
        "",
        "- 负样本采用近似定义：`create_time < T0` 且 T0 前未成交（操作日志无法可靠还原历史上下架）。",
        "- 房源 `follow_num`/`show_num`/`status` 为库内当前快照字段，存在一定时间泄漏风险；解读时以相对排序为主。",
        "- 历史约 1 年、正样本约千级；部分折可能使用 within-fold holdout。",
        "",
        "## 2. 回测指标（相对基线）",
        "",
        "### 房源成交",
        "",
    ]
    la = summary.get("listing_avg") or {}
    lines += [
        f"- model AUC: **{la.get('model_auc', float('nan')):.3f}** vs heat baseline **{la.get('heat_auc', float('nan')):.3f}**",
        f"- model Top50 hit: **{la.get('model_top50', float('nan')):.3f}** vs heat **{la.get('heat_top50', float('nan')):.3f}**",
        f"- beats heat: **{la.get('beats_heat_auc')}**",
        "",
        "### 经纪人开单",
        "",
    ]
    ba = summary.get("broker_avg") or {}
    lines += [
        f"- model AUC: **{ba.get('model_auc', float('nan')):.3f}** vs hist-rate **{ba.get('hist_auc', float('nan')):.3f}**",
        f"- beats hist: **{ba.get('beats_hist_auc')}**",
        "",
        "### 成交时间（天）",
        "",
    ]
    ta = summary.get("time_avg") or {}
    lines += [
        f"- model MAE: **{ta.get('model_mae', float('nan')):.2f}** vs median baseline **{ta.get('median_baseline_mae', float('nan')):.2f}**",
        f"- beats median: **{ta.get('beats_median')}**",
        "",
        "## 3. 三榜（最近一折演示）",
        "",
        "### 经纪人开单概率 Top",
        "",
        "| rank | nick | user_id | score | actual_deals | hist_deals |",
        "|------|------|---------|-------|--------------|------------|",
    ]
    for i, r in enumerate((boards.get("brokers") or [])[:20], 1):
        lines.append(
            f"| {i} | {r.get('nick_name') or '-'} | {r.get('user_id')} | {r.get('score', 0):.3f} | {r.get('label_deals')} | {r.get('hist_deals')} |"
        )
    lines += [
        "",
        "### 房源成交概率 Top（厂房优先展示，含其他类型）",
        "",
        "| rank | type | city | listing_id | score | label | heat | pred_days |",
        "|------|------|------|------------|-------|-------|------|-----------|",
    ]
    listings = boards.get("listings") or []
    plant_first = [r for r in listings if r.get("listing_type") == "plant"] + [
        r for r in listings if r.get("listing_type") != "plant"
    ]
    for i, r in enumerate(plant_first[:30], 1):
        pdays = r.get("pred_days_p50")
        pdays_s = f"{pdays:.0f}" if isinstance(pdays, (int, float)) and pdays == pdays else "-"
        lines.append(
            f"| {i} | {r.get('listing_type')} | {r.get('city_name') or '-'} | {r.get('listing_id')} | "
            f"{r.get('score', 0):.3f} | {r.get('label')} | {r.get('heat')} | {pdays_s} |"
        )
    lines += [
        "",
        "## 4. 复现命令",
        "",
        "```bash",
        "cd backend",
        ".venv/bin/python -m scripts.gtv_forecast import",
        ".venv/bin/python -m scripts.gtv_forecast labels",
        ".venv/bin/python -m scripts.gtv_forecast gate",
        ".venv/bin/python -m scripts.gtv_forecast backtest",
        "# or all-in-one:",
        ".venv/bin/python -m scripts.gtv_forecast run",
        "```",
        "",
        "产物目录：`backend/scripts/gtv_forecast/_data/reports/`",
        "",
    ]
    out = REPORT_DIR / "demo_report.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
