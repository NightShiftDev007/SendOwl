"""Build deal / broker / timing labels from imported parquet."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    LISTING_TYPE,
    PARQUET_DIR,
    REPORT_DIR,
    SIGN_TYPE_RENT,
    SIGN_TYPE_SALE,
)
from .ids import series_str_id


def _read(table: str) -> pd.DataFrame:
    path = PARQUET_DIR / f"{table}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def build_deal_labels() -> pd.DataFrame:
    hs = _read("e_housesource_sign_record").copy()
    hs["housing_resource_id"] = series_str_id(hs["housing_resource_id"])
    hs["project_sign_id"] = series_str_id(hs["project_sign_id"])
    hs["create_by"] = series_str_id(hs["create_by"])
    hs["id"] = series_str_id(hs["id"])
    hs["sign_time"] = _to_dt(hs["create_time"])
    hs["status"] = pd.to_numeric(hs["status"], errors="coerce")
    hs["sign_type"] = pd.to_numeric(hs["sign_type"], errors="coerce")
    hs["listing_type_code"] = pd.to_numeric(hs["type"], errors="coerce")
    hs["listing_type"] = hs["listing_type_code"].map(LISTING_TYPE)
    hs["is_rent"] = hs["sign_type"].isin(SIGN_TYPE_RENT).astype(int)
    hs["is_sale"] = hs["sign_type"].isin(SIGN_TYPE_SALE).astype(int)
    hs["approved"] = (hs["status"] == 1).astype(int)

    # Enrich with project_sign contract_time / money / 计租 when available
    ps = _read("e_project_sign").copy()
    ps["id"] = series_str_id(ps["id"])
    ps["contract_time"] = _to_dt(ps["contract_time"])
    ps["rent_start_time"] = _to_dt(ps["rent_start_time"]) if "rent_start_time" in ps.columns else pd.NaT
    ps["rent_end_time"] = _to_dt(ps["rent_end_time"]) if "rent_end_time" in ps.columns else pd.NaT
    ps["ps_status"] = pd.to_numeric(ps["status"], errors="coerce")
    ps["housing_resource_id_ps"] = series_str_id(ps["housing_resource_id"])
    ps["project_id"] = series_str_id(ps["project_id"])
    for money_col in ("contract_money", "contract_forecast_money", "first_year_rent", "rent_area", "channel_fee"):
        if money_col in ps.columns:
            ps[money_col] = pd.to_numeric(ps[money_col], errors="coerce")
        else:
            ps[money_col] = np.nan
    keep_cols = [
        "id",
        "contract_time",
        "ps_status",
        "contract_money",
        "contract_forecast_money",
        "project_id",
        "housing_resource_id_ps",
        "rent_start_time",
        "rent_end_time",
        "first_year_rent",
        "rent_area",
        "channel_fee",
    ]
    keep = ps[keep_cols].rename(columns={"id": "project_sign_id"})
    deals = hs.merge(keep, on="project_sign_id", how="left")
    deals["event_time"] = deals["contract_time"].fillna(deals["sign_time"])
    deals = deals[deals["approved"] == 1].copy()
    deals["deal_id"] = deals["id"]
    # 租赁：计租日起算的签约→起租间隔（天）
    deals["days_sign_to_rent_start"] = (deals["rent_start_time"] - deals["event_time"]).dt.days
    return deals


def build_broker_attributions(deals: pd.DataFrame) -> pd.DataFrame:
    """One row per (deal, broker) with attribution source."""
    ps = _read("e_project_sign").copy()
    ps["id"] = series_str_id(ps["id"])
    ps["status"] = pd.to_numeric(ps["status"], errors="coerce")
    approved_sign_ids = set(ps.loc[ps["status"] == 1, "id"].dropna())

    comm = _read("e_project_sign_commission").copy()
    comm["project_sign_id"] = series_str_id(comm["project_sign_id"])
    comm["user_id"] = series_str_id(comm["user_id"])
    comm = comm[comm["project_sign_id"].isin(approved_sign_ids)].copy()
    comm["attr_source"] = "commission"

    deal_keys = deals[
        ["deal_id", "project_sign_id", "housing_resource_id", "listing_type", "event_time", "is_rent", "is_sale"]
    ].copy()
    via_comm = deal_keys.merge(
        comm[["project_sign_id", "user_id", "user_type", "commission_rate", "attr_source"]],
        on="project_sign_id",
        how="inner",
    )
    # 个人佣金 = 预估佣金总额 × 分成比例（百分制）
    money = deals[["deal_id", "contract_forecast_money", "contract_money"]].drop_duplicates("deal_id")
    via_comm = via_comm.merge(money, on="deal_id", how="left")
    rate = pd.to_numeric(via_comm["commission_rate"], errors="coerce").fillna(0) / 100.0
    via_comm["personal_commission"] = pd.to_numeric(via_comm["contract_forecast_money"], errors="coerce") * rate

    # Fallback: project owner
    proj = _read("e_project_base").copy()
    proj["id"] = series_str_id(proj["id"])
    proj["user_id"] = series_str_id(proj["user_id"])
    ps2 = ps[["id", "project_id"]].copy()
    ps2["project_id"] = series_str_id(ps2["project_id"])
    ps2 = ps2.rename(columns={"id": "project_sign_id"})
    via_proj = deal_keys.merge(ps2, on="project_sign_id", how="left")
    via_proj = via_proj.merge(proj[["id", "user_id"]].rename(columns={"id": "project_id"}), on="project_id", how="left")
    via_proj = via_proj[via_proj["user_id"].notna()].copy()
    via_proj["attr_source"] = "project_owner"
    via_proj["user_type"] = None
    via_proj["commission_rate"] = None
    via_proj["personal_commission"] = np.nan
    via_proj["contract_forecast_money"] = np.nan
    via_proj["contract_money"] = np.nan

    # Fallback: listing maintainer
    maintain_rows = []
    for listing_type, table, id_col in [
        ("plant", "e_plant_base", "id"),
        ("warehouse", "e_warehouse_base", "id"),
        ("office", "e_office_room", "id"),
    ]:
        base = _read(table).copy()
        base[id_col] = series_str_id(base[id_col])
        mid = "maintain_person_id" if "maintain_person_id" in base.columns else None
        if mid is None:
            continue
        base["user_id"] = series_str_id(base[mid])
        sub = deal_keys[deal_keys["listing_type"] == listing_type].merge(
            base[[id_col, "user_id"]].rename(columns={id_col: "housing_resource_id"}),
            on="housing_resource_id",
            how="left",
        )
        sub = sub[sub["user_id"].notna()].copy()
        sub["attr_source"] = "maintainer"
        sub["user_type"] = None
        sub["commission_rate"] = None
        sub["personal_commission"] = np.nan
        sub["contract_forecast_money"] = np.nan
        sub["contract_money"] = np.nan
        maintain_rows.append(sub)

    via_maint = pd.concat(maintain_rows, ignore_index=True) if maintain_rows else deal_keys.iloc[0:0].copy()

    # Prefer commission > project_owner > maintainer (first non-empty per deal)
    attributed_deals = set(via_comm["deal_id"])
    via_proj = via_proj[~via_proj["deal_id"].isin(attributed_deals)]
    attributed_deals |= set(via_proj["deal_id"])
    via_maint = via_maint[~via_maint["deal_id"].isin(attributed_deals)]

    cols = [
        "deal_id",
        "project_sign_id",
        "housing_resource_id",
        "listing_type",
        "event_time",
        "is_rent",
        "is_sale",
        "user_id",
        "user_type",
        "commission_rate",
        "personal_commission",
        "contract_money",
        "contract_forecast_money",
        "attr_source",
    ]
    out = pd.concat(
        [via_comm.reindex(columns=cols), via_proj.reindex(columns=cols), via_maint.reindex(columns=cols)],
        ignore_index=True,
    )
    return out


def resolve_listing_join(deals: pd.DataFrame) -> dict:
    """Measure housing_resource_id join rates to base tables by type."""
    stats = {}
    for code, name, table in [(1, "plant", "e_plant_base"), (3, "warehouse", "e_warehouse_base")]:
        base_ids = set(series_str_id(_read(table)["id"]).dropna())
        sub = deals[deals["listing_type_code"] == code]
        hit = sub["housing_resource_id"].isin(base_ids).sum()
        stats[name] = {
            "deals": int(len(sub)),
            "joined": int(hit),
            "rate": float(hit / len(sub)) if len(sub) else None,
        }
    # office: try room then base
    office = deals[deals["listing_type_code"] == 2]
    room_ids = set(series_str_id(_read("e_office_room")["id"]).dropna())
    base_ids = set(series_str_id(_read("e_office_base")["id"]).dropna())
    hit_room = office["housing_resource_id"].isin(room_ids).sum()
    hit_base = office["housing_resource_id"].isin(base_ids).sum()
    stats["office"] = {
        "deals": int(len(office)),
        "joined_room": int(hit_room),
        "joined_base": int(hit_base),
        "prefer": "e_office_room" if hit_room >= hit_base else "e_office_base",
        "rate_room": float(hit_room / len(office)) if len(office) else None,
        "rate_base": float(hit_base / len(office)) if len(office) else None,
    }
    return stats


def save_labels() -> dict:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    deals = build_deal_labels()
    attrs = build_broker_attributions(deals)
    join_stats = resolve_listing_join(deals)

    deals_path = PARQUET_DIR / "labels_deals.parquet"
    attrs_path = PARQUET_DIR / "labels_broker_attr.parquet"
    deals.to_parquet(deals_path, index=False)
    attrs.to_parquet(attrs_path, index=False)

    monthly = (
        deals.assign(month=deals["event_time"].dt.to_period("M").astype(str))
        .groupby(["month", "listing_type"], dropna=False)
        .size()
        .reset_index(name="n")
    )
    summary = {
        "approved_deals": int(len(deals)),
        "event_time_min": str(deals["event_time"].min()),
        "event_time_max": str(deals["event_time"].max()),
        "by_listing_type": deals["listing_type"].value_counts(dropna=False).to_dict(),
        "rent_vs_sale": {
            "rent": int(deals["is_rent"].sum()),
            "sale": int(deals["is_sale"].sum()),
        },
        "broker_attr_rows": int(len(attrs)),
        "broker_attr_by_source": attrs["attr_source"].value_counts().to_dict(),
        "deals_with_any_broker": int(attrs["deal_id"].nunique()),
        "commission_coverage": float(attrs.loc[attrs["attr_source"] == "commission", "deal_id"].nunique() / len(deals))
        if len(deals)
        else 0.0,
        "listing_join": join_stats,
        "monthly": monthly.to_dict(orient="records"),
        "paths": {"deals": str(deals_path), "broker_attr": str(attrs_path)},
    }
    (REPORT_DIR / "labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
