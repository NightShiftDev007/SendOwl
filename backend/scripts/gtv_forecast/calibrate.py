"""探索：挂牌价 vs 合同金额差 + 操作日志，用于校准谈价成功率先验。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import PARQUET_DIR, REPORT_DIR
from .features import load_listing_universe
from .ids import series_str_id


def _read(table: str) -> pd.DataFrame | None:
    path = PARQUET_DIR / f"{table}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def calibrate_negotiate_prior() -> dict:
    """估计历史「挂牌→合同」让步幅度分布，并扫描操作日志中的调价迹象。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    deals = _read("labels_deals")
    if deals is None:
        deals_path = PARQUET_DIR / "labels_deals.parquet"
        deals = pd.read_parquet(deals_path) if deals_path.exists() else None
    if deals is None or deals.empty:
        return {"ok": False, "error": "no_labels_deals"}

    listings = load_listing_universe().copy()
    if "rent_convert_min" in listings.columns:
        listings["list_price"] = pd.to_numeric(listings["rent_convert_min"], errors="coerce")
    elif "rent_price_min" in listings.columns:
        listings["list_price"] = pd.to_numeric(listings["rent_price_min"], errors="coerce")
    else:
        listings["list_price"] = np.nan
    # 租赁优先用签约 first_year_rent 对齐挂牌年租代理
    d = deals.copy()
    d["housing_resource_id"] = series_str_id(d["housing_resource_id"])
    d = d.merge(
        listings[["listing_id", "list_price", "listing_type", "city_name"]],
        left_on="housing_resource_id",
        right_on="listing_id",
        how="left",
    )
    d["contract_money"] = pd.to_numeric(d["contract_money"], errors="coerce")
    if "first_year_rent" in d.columns:
        fyr = pd.to_numeric(d["first_year_rent"], errors="coerce")
        # 有首年租金时优先用它与挂牌价比
        d["contract_money"] = fyr.where(fyr.notna() & (fyr > 0), d["contract_money"])
    d["list_price"] = pd.to_numeric(d["list_price"], errors="coerce")
    # 挂牌单价 vs 合同总额不可直接比；用有单价的子集估相对差代理
    # 若合同额与挂牌同量级则算 gap，否则只报分位数覆盖
    valid = d.dropna(subset=["contract_money", "list_price"])
    valid = valid[(valid["list_price"] > 0) & (valid["contract_money"] > 0)]
    # 启发式：合同/挂牌 若在 10~1e6 倍之间视为可比金额；否则跳过比值
    ratio = valid["contract_money"] / valid["list_price"]
    comparable = valid[(ratio > 0.2) & (ratio < 5.0)].copy()
    comparable["concession_proxy"] = 1.0 - comparable["contract_money"] / comparable["list_price"]

    gap_stats = {}
    if len(comparable):
        gap_stats = {
            "n": int(len(comparable)),
            "concession_proxy_p25": float(comparable["concession_proxy"].quantile(0.25)),
            "concession_proxy_p50": float(comparable["concession_proxy"].quantile(0.50)),
            "concession_proxy_p75": float(comparable["concession_proxy"].quantile(0.75)),
            "mean_contract_over_list": float((comparable["contract_money"] / comparable["list_price"]).mean()),
            "note": "concession_proxy≈1-合同/挂牌；仅金额量级可比子集，探索性非因果",
        }
    else:
        gap_stats = {
            "n": 0,
            "note": "挂牌单价与合同总额量级多不可比，未能估计让步幅度；建议用 first_year_rent 等单位对齐后续迭代",
        }

    # 操作日志：关键词扫描调价/议价
    op_hits = {"tables": {}, "total_hits": 0}
    keywords = ("调价", "议价", "降价", "涨价", "改价", "谈价", "价格")
    for table in (
        "e_plant_operate_record",
        "e_warehouse_operation_record",
        "e_office_room_operation_record",
    ):
        op = _read(table)
        if op is None or op.empty:
            continue
        text_cols = [c for c in op.columns if c in ("operate_type", "type", "title", "content", "remark", "operate_content")]
        if not text_cols:
            # 无正文则只计行数
            op_hits["tables"][table] = {"rows": int(len(op)), "keyword_hits": 0}
            continue
        blob = op[text_cols].astype(str).agg(" ".join, axis=1)
        hits = int(blob.str.contains("|".join(keywords), regex=True).sum())
        op_hits["tables"][table] = {"rows": int(len(op)), "keyword_hits": hits}
        op_hits["total_hits"] += hits

    # 谈判次数表
    nego = _read("e_project_negotiation")
    invite = _read("e_project_invite")
    nego_stats = {
        "negotiation_rows": int(len(nego)) if nego is not None else 0,
        "invite_rows": int(len(invite)) if invite is not None else 0,
    }

    # 建议默认成功率：有谈判记录的项目占比作上界启发
    suggested_p = DEFAULT_SUGGESTED_P
    if nego is not None and not nego.empty and "project_id" in nego.columns:
        n_proj = nego["project_id"].nunique()
        # 粗：有谈判的项目未必都签；用 0.25~0.4 夹逼
        suggested_p = float(np.clip(0.25 + 0.05 * np.log1p(n_proj) / 10, 0.2, 0.45))

    out = {
        "ok": True,
        "listing_vs_contract": gap_stats,
        "operate_log_scan": op_hits,
        "negotiation_tables": nego_stats,
        "suggested_success_rate": suggested_p,
        "suggested_concession_pct": float(gap_stats.get("concession_proxy_p50") or 0.05)
        if gap_stats.get("n")
        else 0.05,
        "disclaimer": "探索性校准，人工假设仍可覆盖；非因果、非生产默认强制",
    }
    path = REPORT_DIR / "negotiate_calibration.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    out["path"] = str(path)
    return out


DEFAULT_SUGGESTED_P = 0.30
