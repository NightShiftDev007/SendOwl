"""G0 feasibility gate report."""

from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from .config import HORIZON_DAYS, PARQUET_DIR, REPORT_DIR, TRAIN_LOOKBACK_DAYS
from .labels import save_labels


def _read_deals() -> pd.DataFrame:
    path = PARQUET_DIR / "labels_deals.parquet"
    if not path.exists():
        save_labels()
    return pd.read_parquet(path)


def _operate_listing_signal() -> dict:
    """Check whether operate_record has usable list/delist events."""
    path = PARQUET_DIR / "e_plant_operate_record.parquet"
    if not path.exists():
        return {"available": False, "note": "operate record not imported"}
    df = pd.read_parquet(path, columns=["type", "title"])
    type_vc = df["type"].astype(str).value_counts().head(20).to_dict()
    title_sample = df["title"].astype(str).value_counts().head(20).to_dict()
    keywords = ("上架", "下架", "LIST", "DELIST", "OFF", "ON_SHELF")
    hit = {
        k: int(v)
        for k, v in type_vc.items()
        if any(x.lower() in str(k).lower() for x in ("LIST", "SHELF", "OFF", "UP", "DOWN"))
    }
    title_hit = sum(1 for t in df["title"].astype(str) if any(k in t for k in keywords))
    return {
        "available": True,
        "type_top": type_vc,
        "title_top": title_sample,
        "type_list_like": hit,
        "title_keyword_hits": int(title_hit),
        "can_reconstruct_on_shelf": bool(hit) or title_hit > 100,
        "fallback": "create_time < T0 and not signed before T0",
    }


def rolling_t0_candidates(deals: pd.DataFrame, horizon_days: int = HORIZON_DAYS) -> list[dict]:
    """Month-start T0s where eval window has enough positives and train lookback fits."""
    tmin = deals["event_time"].min()
    tmax = deals["event_time"].max()
    if pd.isna(tmin) or pd.isna(tmax):
        return []
    # candidate T0 = month starts within (tmin + lookback, tmax - horizon]
    start = (tmin + pd.Timedelta(days=TRAIN_LOOKBACK_DAYS)).to_period("M").to_timestamp()
    end = (tmax - pd.Timedelta(days=horizon_days)).to_period("M").to_timestamp()
    if start > end:
        # relax: use month starts with at least some train history
        start = (tmin + pd.Timedelta(days=60)).to_period("M").to_timestamp()
    months = pd.date_range(start=start, end=end, freq="MS")
    out = []
    for t0 in months:
        te = t0 + timedelta(days=horizon_days)
        n_eval = int(((deals["event_time"] >= t0) & (deals["event_time"] < te)).sum())
        n_train = int(((deals["event_time"] >= t0 - pd.Timedelta(days=TRAIN_LOOKBACK_DAYS)) & (deals["event_time"] < t0)).sum())
        out.append(
            {
                "t0": str(t0.date()),
                "eval_end": str(te.date()),
                "n_eval_deals": n_eval,
                "n_train_deals": n_train,
                "usable": n_eval >= 20 and n_train >= 50,
            }
        )
    return out


def run_feasibility_gate() -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    label_summary = save_labels()
    deals = _read_deals()
    folds = rolling_t0_candidates(deals)
    usable_folds = [f for f in folds if f["usable"]]
    operate = _operate_listing_signal()

    by_type = label_summary.get("by_listing_type", {})
    plant_n = int(by_type.get("plant") or by_type.get("plant", 0) or 0)
    # value_counts may have None key
    plant_n = int(by_type.get("plant", 0) or 0)
    office_n = int(by_type.get("office", 0) or 0)
    warehouse_n = int(by_type.get("warehouse", 0) or 0)

    commission_cov = float(label_summary.get("commission_coverage", 0))
    join = label_summary.get("listing_join", {})

    decisions = []
    pass_gate = True

    if len(usable_folds) < 3:
        pass_gate = False
        decisions.append(
            f"usable rolling T0 folds={len(usable_folds)} < 3 → shrink scope or use H=90 / descriptive baseline"
        )
    else:
        decisions.append(f"usable rolling T0 folds={len(usable_folds)} OK")

    if commission_cov < 0.3:
        decisions.append(f"commission coverage={commission_cov:.2%} low → rely on project_owner/maintainer fallback")
    else:
        decisions.append(f"commission coverage={commission_cov:.2%} OK")

    if plant_n < 100:
        decisions.append(f"plant deals={plant_n} sparse")
    else:
        decisions.append(f"plant deals={plant_n} OK for primary demo")

    if office_n + warehouse_n < 80:
        decisions.append(
            f"office+warehouse deals={office_n + warehouse_n} → merge types or plant-only modeling for G1 demo"
        )
        scope = "plant_primary_merge_others"
    else:
        scope = "all_types_with_plant_highlight"
        decisions.append("office/warehouse sample sufficient to keep in pipeline")

    office_prefer = (join.get("office") or {}).get("prefer")
    decisions.append(f"office housing_resource_id prefer={office_prefer}")

    if not operate.get("can_reconstruct_on_shelf"):
        decisions.append(
            "cannot reconstruct historical on-shelf from operate_record → use approximate negatives "
            "(create_time < T0 & unsigned by T0); declare bias in report"
        )
    else:
        decisions.append("on-shelf reconstruction may be possible from operate_record")

    report = {
        "pass_gate": pass_gate or len(usable_folds) >= 2,  # soft pass if >=2 with shrink path
        "hard_pass": pass_gate,
        "recommended_scope": scope,
        "horizon_days": HORIZON_DAYS,
        "train_lookback_days": TRAIN_LOOKBACK_DAYS,
        "label_summary": label_summary,
        "folds": folds,
        "usable_fold_count": len(usable_folds),
        "operate_signal": {
            "can_reconstruct_on_shelf": operate.get("can_reconstruct_on_shelf"),
            "fallback": operate.get("fallback"),
            "type_list_like": operate.get("type_list_like"),
            "title_keyword_hits": operate.get("title_keyword_hits"),
        },
        "decisions": decisions,
        "shrink_path": "plant + top cities + H=90 or descriptive rank + baselines first",
    }
    # Soft-pass rule for this dump: if >=2 usable folds OR (>=1 and plant_n>=200), allow G1 with shrink
    if not report["hard_pass"]:
        report["pass_gate"] = len(usable_folds) >= 2 or (len(usable_folds) >= 1 and plant_n >= 200)
        if report["pass_gate"]:
            decisions.append("soft-pass: proceed G1 with shrink/short-history protocol")

    out = REPORT_DIR / "feasibility_gate.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    md = REPORT_DIR / "feasibility_gate.md"
    lines = [
        "# G0 可行性门禁",
        "",
        f"- hard_pass: **{report['hard_pass']}**",
        f"- pass_gate (allow G1): **{report['pass_gate']}**",
        f"- recommended_scope: `{report['recommended_scope']}`",
        f"- usable folds: {report['usable_fold_count']}",
        f"- approved deals: {label_summary.get('approved_deals')}",
        f"- event span: {label_summary.get('event_time_min')} → {label_summary.get('event_time_max')}",
        f"- commission coverage: {commission_cov:.2%}",
        "",
        "## Decisions",
        "",
    ]
    for d in decisions:
        lines.append(f"- {d}")
    lines += ["", "## Usable folds", ""]
    for f in usable_folds:
        lines.append(f"- T0={f['t0']} eval_deals={f['n_eval_deals']} train_deals={f['n_train_deals']}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
