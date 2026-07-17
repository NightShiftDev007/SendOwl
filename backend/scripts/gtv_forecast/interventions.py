"""GTV 干预 DSL：直接杠杆 + 两段式谈价（敏感性分析，非因果、非单方改挂牌价）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_NEGO_CONCESSION_PCT, DEFAULT_NEGO_SUCCESS_RATE
from .ids import series_str_id


def extract_gtv_levers(intervention: Any) -> dict[str, Any]:
    """从 scenario.intervention 取出 gtv 杠杆配置。"""
    if intervention is None:
        return {}
    if not isinstance(intervention, dict):
        return {}
    gtv = intervention.get("gtv")
    if isinstance(gtv, dict):
        return gtv
    # 扁平字段兼容
    keys = ("boost_exposure", "reassign_broker", "negotiate_deal")
    if any(k in intervention for k in keys):
        return {k: intervention[k] for k in keys if k in intervention}
    return {}


def _scope_mask(df: pd.DataFrame, scope: str) -> pd.Series:
    scope = (scope or "all").strip().lower()
    if scope in ("", "all"):
        return pd.Series(True, index=df.index)
    if scope == "top_heat":
        heat = pd.to_numeric(df.get("heat"), errors="coerce").fillna(0)
        thr = heat.quantile(0.8) if len(heat) else 0
        return heat >= thr
    if scope.startswith("city:"):
        city = scope.split(":", 1)[1].strip()
        return df["city_name"].astype(str) == city
    if scope.startswith("type:"):
        lt = scope.split(":", 1)[1].strip()
        return df["listing_type"].astype(str) == lt
    return pd.Series(True, index=df.index)


def apply_direct_levers(
    listing_df: pd.DataFrame,
    broker_df: pd.DataFrame,
    gtv: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """应用公司可控杠杆：加推带看、换维护人。"""
    notes: list[str] = []
    listing_df = listing_df.copy()
    broker_df = broker_df.copy()

    boost = gtv.get("boost_exposure") or {}
    if isinstance(boost, dict) and boost.get("enabled"):
        factor = float(boost.get("factor") or 1.5)
        factor = max(1.0, min(factor, 5.0))
        mask = _scope_mask(listing_df, str(boost.get("listing_scope") or "all"))
        for col in ("follow_num", "show_num"):
            if col in listing_df.columns:
                listing_df[col] = pd.to_numeric(listing_df[col], errors="coerce").fillna(0).astype(float)
                listing_df.loc[mask, col] = listing_df.loc[mask, col] * factor
        listing_df["heat"] = listing_df["follow_num"].fillna(0) + listing_df["show_num"].fillna(0)
        listing_df["log_heat"] = np.log1p(listing_df["heat"])
        notes.append(f"加推带看×{factor:.2f}（范围 {boost.get('listing_scope') or 'all'}）")

    reassign = gtv.get("reassign_broker") or {}
    if isinstance(reassign, dict) and reassign.get("enabled"):
        to_uid = series_str_id(pd.Series([reassign.get("to_user_id")])).iloc[0]
        from_uid = reassign.get("from_user_id")
        if to_uid and str(to_uid) not in ("", "None", "<NA>"):
            mask = _scope_mask(listing_df, str(reassign.get("listing_scope") or "all"))
            if from_uid:
                from_s = series_str_id(pd.Series([from_uid])).iloc[0]
                mask = mask & (listing_df["maintain_person_id"].astype(str) == str(from_s))
            n = int(mask.sum())
            listing_df.loc[mask, "maintain_person_id"] = to_uid
            notes.append(f"换维护人 → {to_uid}（{n} 套房源）")
            # 粗更新经纪人组合热度
            if len(broker_df) and "user_id" in broker_df.columns:
                port = listing_df.groupby("maintain_person_id").agg(
                    n_listings=("listing_id", "count"),
                    port_heat=("follow_num", "sum"),
                    port_show=("show_num", "sum"),
                )
                broker_df = broker_df.drop(columns=["n_listings", "port_heat", "port_show"], errors="ignore")
                broker_df = broker_df.merge(port, left_on="user_id", right_index=True, how="left")
                for c in ("n_listings", "port_heat", "port_show"):
                    broker_df[c] = broker_df[c].fillna(0)
                broker_df["hist_rate"] = broker_df["hist_deals"] / (broker_df["n_listings"] + 1)

    return listing_df, broker_df, notes


def apply_negotiate_branch(
    listing_df: pd.DataFrame,
    gtv: dict[str, Any],
    *,
    success: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """谈价分支：谈成则合同/佣金路径更优（敏感性），谈不成维持原条件。

    明示：非公司单方改挂牌价；改的是「协商后合同条件」对成交概率与期望金额的影响假设。
    """
    listing_df = listing_df.copy()
    nego = gtv.get("negotiate_deal") or {}
    meta: dict[str, Any] = {
        "enabled": bool(isinstance(nego, dict) and nego.get("enabled")),
        "branch": "success" if success else "fail",
        "disclaimer": "敏感性分析：与业主协商谈价，非公司单方改挂牌价，非因果推断",
    }
    if not meta["enabled"]:
        return listing_df, meta

    p = float(nego.get("success_rate") if nego.get("success_rate") is not None else DEFAULT_NEGO_SUCCESS_RATE)
    p = max(0.0, min(1.0, p))
    concession = float(
        nego.get("concession_pct") if nego.get("concession_pct") is not None else DEFAULT_NEGO_CONCESSION_PCT
    )
    concession = max(0.0, min(0.5, concession))
    mask = _scope_mask(listing_df, str(nego.get("listing_scope") or "all"))
    meta.update(
        {
            "success_rate": p,
            "concession_pct": concession,
            "listing_scope": nego.get("listing_scope") or "all",
            "n_listings": int(mask.sum()),
        }
    )

    for col in ("follow_num", "show_num", "price", "prior_contract_money", "prior_commission", "prior_days_to_rent"):
        if col in listing_df.columns:
            listing_df[col] = pd.to_numeric(listing_df[col], errors="coerce").astype(float)

    if success:
        # 买方更易接受 → 成交概率上升；合同金额/佣金按让步幅度下调
        if "price" in listing_df.columns:
            listing_df.loc[mask, "price"] = listing_df.loc[mask, "price"] * (1.0 - concession)
        # 用热度代理「谈判推进」
        listing_df.loc[mask, "follow_num"] = listing_df.loc[mask, "follow_num"].fillna(0) * (
            1.0 + 0.35 * (1.0 - concession)
        )
        listing_df.loc[mask, "show_num"] = listing_df.loc[mask, "show_num"].fillna(0) * (1.0 + 0.25)
        listing_df["heat"] = listing_df["follow_num"].fillna(0) + listing_df["show_num"].fillna(0)
        listing_df["log_heat"] = np.log1p(listing_df["heat"])
        for col in ("prior_contract_money", "prior_commission"):
            if col in listing_df.columns:
                listing_df.loc[mask, col] = listing_df.loc[mask, col] * (1.0 - concession)
        # 租赁计租节奏略提前
        if "prior_days_to_rent" in listing_df.columns:
            listing_df.loc[mask, "prior_days_to_rent"] = listing_df.loc[mask, "prior_days_to_rent"] * 0.9
        meta["contract_factor"] = 1.0 - concession
        meta["deal_lift"] = "heat/price path improved"
    else:
        # 谈不成：维持原条件，略计跟进占用（热度微降）
        listing_df.loc[mask, "follow_num"] = listing_df.loc[mask, "follow_num"].fillna(0) * 0.98
        listing_df["heat"] = listing_df["follow_num"].fillna(0) + listing_df["show_num"].fillna(0)
        listing_df["log_heat"] = np.log1p(listing_df["heat"])
        meta["contract_factor"] = 1.0
        meta["deal_lift"] = "status quo + follow cost"

    return listing_df, meta


def blend_branch_results(
    success_result: dict[str, Any],
    fail_result: dict[str, Any],
    success_rate: float,
) -> dict[str, Any]:
    """期望 = p×谈成 + (1−p)×谈不成。"""
    p = max(0.0, min(1.0, float(success_rate)))
    q = 1.0 - p
    out = deepcopy(success_result)
    ss = success_result.get("summary") or {}
    fs = fail_result.get("summary") or {}

    def _mix(a, b):
        try:
            return p * float(a or 0) + q * float(b or 0)
        except (TypeError, ValueError):
            return a

    summary = {
        **ss,
        "expected_deals": _mix(ss.get("expected_deals"), fs.get("expected_deals")),
        "expected_contract_money": _mix(ss.get("expected_contract_money"), fs.get("expected_contract_money")),
        "expected_commission": _mix(ss.get("expected_commission"), fs.get("expected_commission")),
        "expected_personal_commission": _mix(
            ss.get("expected_personal_commission"), fs.get("expected_personal_commission")
        ),
        "negotiate": {
            "success_rate": p,
            "disclaimer": "敏感性分析：与业主协商谈价，非公司单方改挂牌价，非因果推断",
            "success_branch": ss,
            "fail_branch": fs,
        },
    }
    out["summary"] = summary
    out["mode"] = success_result.get("mode") or "model"
    out["negotiate_blended"] = True
    return out
