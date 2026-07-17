"""T0-aligned feature tables for listing and broker tasks."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .config import HORIZON_DAYS, NEG_POS_RATIO, PARQUET_DIR, RANDOM_SEED
from .ids import series_str_id


def _read(table: str, columns: list[str] | None = None) -> pd.DataFrame:
    path = PARQUET_DIR / f"{table}.parquet"
    return pd.read_parquet(path, columns=columns)


def _sid(s: pd.Series) -> pd.Series:
    return series_str_id(s)


def _dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _optional_table(table: str) -> pd.DataFrame | None:
    path = PARQUET_DIR / f"{table}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _attach_mid_scores(listings: pd.DataFrame) -> pd.DataFrame:
    """相对定价/热度分（lyy_mid）；缺表时填 0。"""
    out = listings.copy()
    out["mid_rent_score"] = 0.0
    out["mid_sale_score"] = 0.0
    out["mid_popularity"] = 0.0
    mid = _optional_table("e_carrier_carrier_sort_score_info")
    if mid is None or mid.empty:
        return out
    mid = mid.copy()
    mid["listing_id"] = _sid(mid["id"])
    for src, dst in [
        ("carrier_rent_total_score", "mid_rent_score"),
        ("carrier_sale_total_score", "mid_sale_score"),
        ("carrier_popularity", "mid_popularity"),
    ]:
        if src in mid.columns:
            mid[dst] = pd.to_numeric(mid[src], errors="coerce").fillna(0)
        else:
            mid[dst] = 0.0
    keep = mid[["listing_id", "mid_rent_score", "mid_sale_score", "mid_popularity"]].drop_duplicates(
        "listing_id"
    )
    out = out.drop(columns=["mid_rent_score", "mid_sale_score", "mid_popularity"], errors="ignore")
    return out.merge(keep, on="listing_id", how="left").fillna(
        {"mid_rent_score": 0.0, "mid_sale_score": 0.0, "mid_popularity": 0.0}
    )


def _attach_need_match(listings: pd.DataFrame) -> pd.DataFrame:
    """线索意向区域 × 项目载体匹配强度（粗粒度计数特征）。"""
    out = listings.copy()
    out["need_match_cnt"] = 0.0
    carrier = _optional_table("e_project_carrier")
    intent = _optional_table("e_clue_intentarea")
    if carrier is None or intent is None or carrier.empty:
        return out
    carrier = carrier.copy()
    # carrier 行上的房源 id 字段名不统一，尽量猜
    lid_col = None
    for c in ("housing_resource_id", "carrier_id", "plant_id", "warehouse_id", "room_id", "other_id"):
        if c in carrier.columns:
            lid_col = c
            break
    if lid_col is None:
        return out
    carrier["listing_id"] = _sid(carrier[lid_col])
    cnt = carrier.groupby("listing_id").size().rename("need_match_cnt")
    out = out.drop(columns=["need_match_cnt"], errors="ignore")
    out = out.merge(cnt, left_on="listing_id", right_index=True, how="left")
    out["need_match_cnt"] = out["need_match_cnt"].fillna(0)
    return out


def _attach_refund_signal(listings: pd.DataFrame, deals: pd.DataFrame) -> pd.DataFrame:
    """城市维度回款兑现率（签约预估佣金 vs 回款），作期望佣金可信度代理。"""
    out = listings.copy()
    out["city_refund_rate"] = 0.5
    refund = _optional_table("e_project_refund")
    if refund is None or refund.empty or deals is None or deals.empty:
        return out
    refund = refund.copy()
    if "project_id" not in refund.columns:
        return out
    refund["project_id"] = _sid(refund["project_id"])
    refunded = set(refund["project_id"].dropna())
    d = deals.copy()
    if "project_id" not in d.columns:
        return out
    d["project_id"] = _sid(d["project_id"])
    d = d.merge(
        listings[["listing_id", "city_name"]],
        left_on="housing_resource_id",
        right_on="listing_id",
        how="left",
    )
    d["has_refund"] = d["project_id"].isin(refunded).astype(int)
    rate = d.groupby("city_name")["has_refund"].mean()
    out["city_refund_rate"] = out["city_name"].map(rate).fillna(0.5)
    return out


def _bool01(s: pd.Series) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    raw = s.astype(str).str.strip().str.lower()
    return raw.isin(["1", "1.0", "true", "yes", "y", "是"]).astype(float)


def _attach_office_geo(base: pd.DataFrame) -> pd.DataFrame:
    """办公房间经 office_id → e_office_base 补坐标/行政区。"""
    out = base.copy()
    if "office_id" not in out.columns:
        return out
    office = _optional_table("e_office_base")
    if office is None or office.empty:
        return out
    office = office.copy()
    office["office_id"] = _sid(office["id"])
    keep = ["office_id"]
    for c in ("longitude", "latitude", "province_name", "city_name", "region_name", "street_name"):
        if c in office.columns:
            keep.append(c)
    office = office[keep].drop_duplicates("office_id")
    out["office_id"] = _sid(out["office_id"])
    merged = out.merge(office, on="office_id", how="left", suffixes=("", "_ob"))
    for c in ("longitude", "latitude", "province_name", "city_name", "region_name", "street_name"):
        ob = f"{c}_ob"
        if ob in merged.columns:
            if c not in merged.columns:
                merged[c] = merged[ob]
            else:
                merged[c] = merged[c].where(merged[c].notna() & (merged[c] != 0), merged[ob])
            merged = merged.drop(columns=[ob])
    return merged


def attach_listing_quality_features(df: pd.DataFrame) -> pd.DataFrame:
    """批量并入质量/位置衍生字段；quality_score 与 Agent listing_profile 同公式。"""
    out = df.copy()
    for c in ("follow_num", "show_num", "area"):
        if c not in out.columns:
            out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["log_area"] = np.log1p(out["area"].clip(lower=0))
    if "has_elevator" not in out.columns:
        out["has_elevator"] = _bool01(out["is_elevator"]) if "is_elevator" in out.columns else 0.0
    else:
        out["has_elevator"] = pd.to_numeric(out["has_elevator"], errors="coerce").fillna(0)
    if "has_crown_block" not in out.columns:
        out["has_crown_block"] = _bool01(out["is_crown_block"]) if "is_crown_block" in out.columns else 0.0
    else:
        out["has_crown_block"] = pd.to_numeric(out["has_crown_block"], errors="coerce").fillna(0)

    # 地址拼接
    parts = []
    for c in ("province_name", "city_name", "region_name", "street_name"):
        if c in out.columns:
            parts.append(out[c].fillna("").astype(str))
    if parts:
        addr = parts[0]
        for p in parts[1:]:
            addr = addr + p
        out["address"] = addr.str.strip()
    else:
        out["address"] = out.get("city_name", pd.Series([""] * len(out))).fillna("").astype(str)

    if "listing_name" not in out.columns:
        name = out.get("name")
        ext = out.get("external_name")
        if name is not None or ext is not None:
            n = name.fillna("").astype(str) if name is not None else pd.Series([""] * len(out))
            e = ext.fillna("").astype(str) if ext is not None else pd.Series([""] * len(out))
            out["listing_name"] = n.where(n.str.len() > 0, e)
        else:
            out["listing_name"] = (
                out.get("city_name", pd.Series([""] * len(out))).fillna("").astype(str)
                + out.get("listing_type", pd.Series([""] * len(out))).fillna("").astype(str)
            )

    # 与 Agent listing_profile.compute_quality_score 同一公式（向量化批量）
    # 0.35×热度 + 0.25×设施 + 0.20×完整度 + 0.20×价位占位
    follow = out["follow_num"].fillna(0)
    show = out["show_num"].fillna(0)
    heat = np.minimum(1.0, np.log1p(follow + show) / np.log1p(50.0))
    has_struct = (
        out["structure"].fillna("").astype(str).str.len() > 0
        if "structure" in out.columns
        else pd.Series(False, index=out.index)
    )
    has_fire = (
        out["fire_level"].fillna("").astype(str).str.len() > 0
        if "fire_level" in out.columns
        else pd.Series(False, index=out.index)
    )
    has_div = (
        _bool01(out["is_divisible"]) if "is_divisible" in out.columns else pd.Series(0.0, index=out.index)
    )
    facility = (
        out["has_elevator"].fillna(0)
        + out["has_crown_block"].fillna(0)
        + has_div
        + has_struct.astype(float)
        + has_fire.astype(float)
    ) / 5.0
    has_name = out["listing_name"].fillna("").astype(str).str.len() > 0
    lng = pd.to_numeric(out["longitude"], errors="coerce") if "longitude" in out.columns else pd.Series(np.nan, index=out.index)
    lat = pd.to_numeric(out["latitude"], errors="coerce") if "latitude" in out.columns else pd.Series(np.nan, index=out.index)
    has_geo = lng.notna() & lat.notna() & lng.ne(0) & lat.ne(0)
    has_area = out["area"].fillna(0) > 0
    price = pd.to_numeric(out["rent_price_min"], errors="coerce") if "rent_price_min" in out.columns else pd.Series(np.nan, index=out.index)
    if "sale_price" in out.columns:
        price = price.fillna(pd.to_numeric(out["sale_price"], errors="coerce"))
    if "price" in out.columns:
        price = price.fillna(pd.to_numeric(out["price"], errors="coerce"))
    has_price = price.fillna(0) > 0
    completeness = (
        has_name.astype(float) + has_geo.astype(float) + has_area.astype(float) + has_price.astype(float)
    ) / 4.0
    price_fit = np.where(has_price, 0.6, 0.5)
    out["info_completeness"] = completeness
    out["quality_score"] = (0.35 * heat + 0.25 * facility + 0.20 * completeness + 0.20 * price_fit).clip(0, 1)
    return out


def load_listing_universe() -> pd.DataFrame:
    """Unified listing dim: id, type, city, maintainer, heat, create/up time, rent, quality."""
    frames = []
    specs = [
        ("plant", "e_plant_base", "e_plant_rent", "plant_id"),
        ("warehouse", "e_warehouse_base", "e_warehouse_rent", "warehouse_id"),
        ("office", "e_office_room", "e_office_room_rent", "room_id"),
    ]
    rent_fk = {
        "e_plant_rent": "plant_id",
        "e_warehouse_rent": "warehouse_id",
        "e_office_room_rent": "room_id",
    }
    # verify warehouse/office rent fk from parquet columns
    for rtable, default_fk in list(rent_fk.items()):
        pq = PARQUET_DIR / f"{rtable}.parquet"
        if not pq.exists():
            continue
        cols = pd.read_parquet(pq).columns
        if default_fk not in cols:
            # guess first *id* that isn't id
            cand = [c for c in cols if c.endswith("_id") and c != "id"]
            rent_fk[rtable] = cand[0] if cand else default_fk

    quality_cols = (
        "province_name",
        "region_name",
        "street_name",
        "longitude",
        "latitude",
        "structure",
        "fire_level",
        "is_elevator",
        "is_crown_block",
        "is_divisible",
        "name",
        "external_name",
        "office_id",
    )

    for ltype, base_table, rent_table, _ in specs:
        base = _read(base_table)
        base["listing_id"] = _sid(base["id"])
        base["listing_type"] = ltype
        for c in ("city_name", "city_code", "province_name", "region_name"):
            if c not in base.columns:
                base[c] = None
        for c in quality_cols:
            if c not in base.columns:
                base[c] = None
        if "maintain_person_id" not in base.columns:
            base["maintain_person_id"] = base.get("user_id")
        base["maintain_person_id"] = _sid(base["maintain_person_id"])
        base["follow_num"] = pd.to_numeric(base.get("follow_num"), errors="coerce").fillna(0)
        base["show_num"] = pd.to_numeric(base.get("show_num"), errors="coerce").fillna(0)
        base["create_time"] = _dt(base.get("create_time"))
        base["up_time"] = _dt(base.get("up_time"))
        base["status"] = pd.to_numeric(base.get("status"), errors="coerce")
        area_col = "sum_area" if "sum_area" in base.columns else ("area" if "area" in base.columns else None)
        base["area"] = pd.to_numeric(base[area_col], errors="coerce") if area_col else np.nan
        base["longitude"] = pd.to_numeric(base.get("longitude"), errors="coerce")
        base["latitude"] = pd.to_numeric(base.get("latitude"), errors="coerce")
        if ltype == "office":
            base = _attach_office_geo(base)

        rent = _read(rent_table)
        fk = rent_fk[rent_table]
        rent[fk] = _sid(rent[fk])
        price_cols = [c for c in ("rent_convert_min", "rent_price_min", "sale_price") if c in rent.columns]
        rkeep = rent[[fk] + price_cols].copy()
        for c in price_cols:
            rkeep[c] = pd.to_numeric(rkeep[c], errors="coerce")
        rkeep = rkeep.rename(columns={fk: "listing_id"})
        merged = base.merge(rkeep, on="listing_id", how="left")
        keep_cols = [
            "listing_id",
            "listing_type",
            "city_name",
            "city_code",
            "maintain_person_id",
            "follow_num",
            "show_num",
            "create_time",
            "up_time",
            "status",
            "area",
            "province_name",
            "region_name",
            "street_name",
            "longitude",
            "latitude",
            "structure",
            "fire_level",
            "is_elevator",
            "is_crown_block",
            "is_divisible",
            "name",
            "external_name",
            *[c for c in price_cols if c in merged.columns],
        ]
        frames.append(merged[[c for c in keep_cols if c in merged.columns]])
    listings = pd.concat(frames, ignore_index=True)
    listings = _attach_mid_scores(listings)
    listings = _attach_need_match(listings)
    try:
        deals = load_deals()
    except Exception:
        deals = pd.DataFrame()
    listings = _attach_refund_signal(listings, deals)
    listings = attach_listing_quality_features(listings)
    return listings


def load_deals() -> pd.DataFrame:
    d = pd.read_parquet(PARQUET_DIR / "labels_deals.parquet")
    d["housing_resource_id"] = _sid(d["housing_resource_id"])
    d["event_time"] = _dt(d["event_time"])
    return d


def build_listing_samples_for_t0(t0: pd.Timestamp, listings: pd.DataFrame, deals: pd.DataFrame, horizon_days: int = HORIZON_DAYS) -> pd.DataFrame:
    """Positive: signed in [t0, t0+H). Negative: created before t0, not signed before t0+H, undersampled."""
    t0 = pd.Timestamp(t0)
    te = t0 + timedelta(days=horizon_days)

    # deals known by T0 (for leakage-safe history) and in window
    past_deals = deals[deals["event_time"] < t0]
    win_deals = deals[(deals["event_time"] >= t0) & (deals["event_time"] < te)]

    # eligible universe: created before t0
    univ = listings[listings["create_time"].notna() & (listings["create_time"] < t0)].copy()
    # exclude already signed before t0
    signed_before = set(past_deals["housing_resource_id"].dropna())
    univ = univ[~univ["listing_id"].isin(signed_before)].copy()

    pos_ids = set(win_deals["housing_resource_id"].dropna())
    univ["label"] = univ["listing_id"].isin(pos_ids).astype(int)
    # days to sign for positives
    et = win_deals.groupby("housing_resource_id")["event_time"].min()
    univ["event_time"] = univ["listing_id"].map(et)
    univ["days_to_sign"] = (univ["event_time"] - t0).dt.days

    # features at T0 (snapshot fields are current-state proxies; declare in report)
    univ["days_since_create"] = (t0 - univ["create_time"]).dt.days
    univ["days_since_up"] = (t0 - univ["up_time"]).dt.days
    univ["heat"] = univ["follow_num"].fillna(0) + univ["show_num"].fillna(0)
    univ["log_heat"] = np.log1p(univ["heat"])
    if "rent_convert_min" in univ.columns:
        price = pd.to_numeric(univ["rent_convert_min"], errors="coerce")
    elif "rent_price_min" in univ.columns:
        price = pd.to_numeric(univ["rent_price_min"], errors="coerce")
    else:
        price = pd.Series(np.nan, index=univ.index)
    univ["price"] = price
    univ["has_rent"] = price.notna().astype(int)

    # city historical conversion before T0
    city_hist = (
        past_deals.merge(
            listings[["listing_id", "city_name"]],
            left_on="housing_resource_id",
            right_on="listing_id",
            how="left",
        )
        .groupby("city_name")
        .size()
    )
    city_base = univ.groupby("city_name").size()
    city_rate = (city_hist / city_base.replace(0, np.nan)).fillna(0)
    univ["city_hist_deal_rate"] = univ["city_name"].map(city_rate).fillna(0)
    for c in ("mid_rent_score", "mid_sale_score", "mid_popularity", "need_match_cnt", "city_refund_rate"):
        if c not in univ.columns:
            univ[c] = 0.0 if c != "city_refund_rate" else 0.5

    # 经济量先验：城市×业态历史合同额/佣金中位数（泄漏安全：仅 past_deals）
    econ = _city_type_econ_priors(past_deals, listings)
    univ["city_name"] = univ["city_name"].fillna("UNK").astype(str)
    univ["listing_type"] = univ["listing_type"].fillna("UNK").astype(str)
    univ = univ.merge(econ, on=["city_name", "listing_type"], how="left")
    for c in ("prior_contract_money", "prior_commission", "prior_days_to_rent"):
        if c not in univ.columns:
            univ[c] = np.nan

    pos = univ[univ["label"] == 1]
    neg = univ[univ["label"] == 0]
    n_neg = min(len(neg), max(len(pos) * NEG_POS_RATIO, len(pos)))
    if len(neg) and n_neg:
        neg = neg.sample(n=n_neg, random_state=RANDOM_SEED)
    sample = pd.concat([pos, neg], ignore_index=True)
    sample["t0"] = t0
    sample["horizon_days"] = horizon_days
    # rent/sale label for positives
    rs = win_deals.groupby("housing_resource_id")[["is_rent", "is_sale"]].max()
    sample["is_rent"] = sample["listing_id"].map(rs["is_rent"]).fillna(0).astype(int)
    sample["is_sale"] = sample["listing_id"].map(rs["is_sale"]).fillna(0).astype(int)
    return sample


def _city_type_econ_priors(past_deals: pd.DataFrame, listings: pd.DataFrame) -> pd.DataFrame:
    if past_deals is None or past_deals.empty:
        return pd.DataFrame(
            columns=["city_name", "listing_type", "prior_contract_money", "prior_commission", "prior_days_to_rent"]
        )
    d = past_deals.copy()
    # deals 已有 listing_type；城市从 listing 维表补齐
    city_map = listings.drop_duplicates("listing_id").set_index("listing_id")["city_name"]
    if "city_name" not in d.columns:
        d["city_name"] = d["housing_resource_id"].map(city_map)
    else:
        d["city_name"] = d["city_name"].fillna(d["housing_resource_id"].map(city_map))
    if "listing_type" not in d.columns:
        type_map = listings.drop_duplicates("listing_id").set_index("listing_id")["listing_type"]
        d["listing_type"] = d["housing_resource_id"].map(type_map)
    d["city_name"] = d["city_name"].fillna("UNK").astype(str)
    d["listing_type"] = d["listing_type"].fillna("UNK").astype(str)
    # 合同/佣金中位数忽略 0，避免「挂 0」把城市先验拉成 0
    d["contract_money_pos"] = pd.to_numeric(d.get("contract_money"), errors="coerce")
    d.loc[d["contract_money_pos"] <= 0, "contract_money_pos"] = np.nan
    d["commission_pos"] = pd.to_numeric(d.get("contract_forecast_money"), errors="coerce")
    d.loc[d["commission_pos"] <= 0, "commission_pos"] = np.nan
    d["days_rent_pos"] = pd.to_numeric(d.get("days_sign_to_rent_start"), errors="coerce")
    d.loc[d["days_rent_pos"] < 0, "days_rent_pos"] = np.nan
    agg = (
        d.groupby(["city_name", "listing_type"], dropna=False)
        .agg(
            prior_contract_money=("contract_money_pos", "median"),
            prior_commission=("commission_pos", "median"),
            prior_days_to_rent=("days_rent_pos", "median"),
        )
        .reset_index()
    )
    return agg


def build_scoring_universe(t0: pd.Timestamp | None = None, horizon_days: int = HORIZON_DAYS) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """当前快照：全部未成交在架房源 + 活跃经纪人，供在线打分（不做负采样）。"""
    listings = load_listing_universe()
    deals = load_deals()
    attrs = pd.read_parquet(PARQUET_DIR / "labels_broker_attr.parquet")
    if t0 is None:
        t0 = pd.Timestamp(deals["event_time"].max()) if len(deals) else pd.Timestamp.utcnow().tz_localize(None)
    t0 = pd.Timestamp(t0).tz_localize(None) if getattr(t0, "tzinfo", None) else pd.Timestamp(t0)

    past_deals = deals[deals["event_time"] < t0]
    univ = listings[listings["create_time"].notna() & (listings["create_time"] < t0)].copy()
    signed_before = set(past_deals["housing_resource_id"].dropna())
    univ = univ[~univ["listing_id"].isin(signed_before)].copy()
    univ["label"] = 0
    univ["days_to_sign"] = np.nan
    univ["days_since_create"] = (t0 - univ["create_time"]).dt.days
    univ["days_since_up"] = (t0 - univ["up_time"]).dt.days
    univ["heat"] = univ["follow_num"].fillna(0) + univ["show_num"].fillna(0)
    univ["log_heat"] = np.log1p(univ["heat"])
    if "rent_convert_min" in univ.columns:
        price = pd.to_numeric(univ["rent_convert_min"], errors="coerce")
    elif "rent_price_min" in univ.columns:
        price = pd.to_numeric(univ["rent_price_min"], errors="coerce")
    else:
        price = pd.Series(np.nan, index=univ.index)
    univ["price"] = price
    univ["has_rent"] = price.notna().astype(int)
    city_hist = (
        past_deals.merge(
            listings[["listing_id", "city_name"]],
            left_on="housing_resource_id",
            right_on="listing_id",
            how="left",
        )
        .groupby("city_name")
        .size()
    )
    city_base = univ.groupby("city_name").size()
    city_rate = (city_hist / city_base.replace(0, np.nan)).fillna(0)
    univ["city_hist_deal_rate"] = univ["city_name"].map(city_rate).fillna(0)
    for c in ("mid_rent_score", "mid_sale_score", "mid_popularity", "need_match_cnt", "city_refund_rate"):
        if c not in univ.columns:
            univ[c] = 0.0 if c != "city_refund_rate" else 0.5
    econ = _city_type_econ_priors(past_deals, listings)
    univ["city_name"] = univ["city_name"].fillna("UNK").astype(str)
    univ["listing_type"] = univ["listing_type"].fillna("UNK").astype(str)
    univ = univ.merge(econ, on=["city_name", "listing_type"], how="left")
    univ["t0"] = t0
    univ["horizon_days"] = horizon_days
    univ["is_rent"] = 1
    univ["is_sale"] = 0

    brokers = build_broker_samples_for_t0(t0, attrs, listings, horizon_days=horizon_days)
    return univ, brokers, t0


def build_broker_samples_for_t0(t0: pd.Timestamp, attrs: pd.DataFrame, listings: pd.DataFrame, horizon_days: int = HORIZON_DAYS) -> pd.DataFrame:
    t0 = pd.Timestamp(t0)
    te = t0 + timedelta(days=horizon_days)
    attrs = attrs.copy()
    attrs["event_time"] = _dt(attrs["event_time"])
    attrs["user_id"] = _sid(attrs["user_id"])

    past = attrs[attrs["event_time"] < t0]
    win = attrs[(attrs["event_time"] >= t0) & (attrs["event_time"] < te)]

    users = _read("e_sys_user")
    users["user_id"] = _sid(users["user_id"])
    if "del_flag" in users.columns:
        users = users[users["del_flag"].isna() | users["del_flag"].astype(str).isin(["0", "0.0"])].copy()

    # active brokers: had listing maintain or past deal or dept
    maint = set(listings["maintain_person_id"].dropna())
    past_brokers = set(past["user_id"].dropna())
    active = maint | past_brokers
    brokers = users[users["user_id"].isin(active)].copy()

    hist_cnt = past.groupby("user_id").size()
    win_cnt = win.groupby("user_id").size()
    brokers["hist_deals"] = brokers["user_id"].map(hist_cnt).fillna(0)
    brokers["label_deals"] = brokers["user_id"].map(win_cnt).fillna(0)
    brokers["label"] = (brokers["label_deals"] > 0).astype(int)

    # portfolio heat
    port = listings.groupby("maintain_person_id").agg(
        n_listings=("listing_id", "count"),
        port_heat=("follow_num", "sum"),
        port_show=("show_num", "sum"),
    )
    brokers = brokers.merge(port, left_on="user_id", right_index=True, how="left")
    for c in ("n_listings", "port_heat", "port_show"):
        brokers[c] = brokers[c].fillna(0)
    brokers["hist_rate"] = brokers["hist_deals"] / (brokers["n_listings"] + 1)
    brokers["t0"] = t0
    return brokers


def build_all_samples(t0_list: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    listings = load_listing_universe()
    deals = load_deals()
    attrs = pd.read_parquet(PARQUET_DIR / "labels_broker_attr.parquet")
    listing_parts = []
    broker_parts = []
    for t0s in t0_list:
        t0 = pd.Timestamp(t0s)
        listing_parts.append(build_listing_samples_for_t0(t0, listings, deals))
        broker_parts.append(build_broker_samples_for_t0(t0, attrs, listings))
    listing_df = pd.concat(listing_parts, ignore_index=True)
    broker_df = pd.concat(broker_parts, ignore_index=True)
    listing_df.to_parquet(PARQUET_DIR / "samples_listing.parquet", index=False)
    broker_df.to_parquet(PARQUET_DIR / "samples_broker.parquet", index=False)
    return listing_df, broker_df
