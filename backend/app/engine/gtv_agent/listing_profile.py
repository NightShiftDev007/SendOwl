"""从 GTV parquet 装配房源画像（位置/质量/租售价）+ 可解释 quality_score。"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.listing_profile")

_TYPE_TABLE = {
    "plant": ("e_plant_base.parquet", "e_plant_rent.parquet", "plant_id"),
    "warehouse": ("e_warehouse_base.parquet", "e_warehouse_rent.parquet", "warehouse_id"),
    "office": ("e_office_room.parquet", "e_office_room_rent.parquet", "office_room_id"),
}


def _parquet_dir():
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[3]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from scripts.gtv_forecast.config import PARQUET_DIR

    return PARQUET_DIR


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s in ("None", "nan", "NaT", "<NA>"):
        return ""
    return s


def _human_label(v: Any, *, max_len: int = 24) -> str:
    """展示用短文案；跳过字典雪花 ID / 纯数字编码。"""
    s = _safe_str(v)
    if not s:
        return ""
    # 科学计数法或超长数字 ID
    if "e+" in s.lower() or "e-" in s.lower():
        return ""
    digits = s.replace(".", "").replace("-", "")
    if digits.isdigit() and len(digits) >= 10:
        return ""
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _safe_float(v: Any, default: Any = 0.0) -> Any:
    try:
        if v is None:
            return default
        if isinstance(v, float) and math.isnan(v):
            return default
        return float(v)
    except Exception:
        return default


def _safe_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def build_address(
    province: str = "",
    city: str = "",
    region: str = "",
    street: str = "",
) -> str:
    parts = [p for p in (province, city, region, street) if p]
    # 避免省市重复
    out: List[str] = []
    for p in parts:
        if out and p.startswith(out[-1]):
            continue
        if out and out[-1] in p:
            out[-1] = p
            continue
        out.append(p)
    return "".join(out)


def compute_quality_score(profile: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """固定公式 0–1：热度 0.35 + 设施 0.25 + 完整度 0.20 + 价位占位 0.20。"""
    follow = _safe_float(profile.get("follow_num"))
    show = _safe_float(profile.get("show_num"))
    heat_raw = math.log1p(max(0.0, follow + show))
    heat = min(1.0, heat_raw / math.log1p(50.0))

    flags = [
        _safe_bool(profile.get("is_elevator")),
        _safe_bool(profile.get("is_crown_block")),
        _safe_bool(profile.get("is_divisible")),
        bool(_safe_str(profile.get("structure"))),
        bool(_safe_str(profile.get("fire_level"))),
    ]
    facility = sum(1 for f in flags if f) / max(1, len(flags))

    completeness_bits = [
        bool(_safe_str(profile.get("listing_name"))),
        profile.get("longitude") not in (None, 0, 0.0) and profile.get("latitude") not in (None, 0, 0.0),
        _safe_float(profile.get("area")) > 0,
        _safe_float(profile.get("rent_price_min") or profile.get("sale_price") or profile.get("list_price")) > 0,
    ]
    completeness = sum(1 for b in completeness_bits if b) / max(1, len(completeness_bits))

    # 价位占位：有价格则 0.6，否则 0.5（无同城 prior 时的中性分）
    has_price = _safe_float(profile.get("rent_price_min") or profile.get("sale_price") or profile.get("list_price")) > 0
    price_fit = 0.6 if has_price else 0.5

    score = 0.35 * heat + 0.25 * facility + 0.20 * completeness + 0.20 * price_fit
    score = max(0.0, min(1.0, score))
    parts = {
        "heat": round(heat, 4),
        "facility": round(facility, 4),
        "completeness": round(completeness, 4),
        "price_fit": round(price_fit, 4),
    }
    return round(score, 4), parts


def quality_highlights(profile: Dict[str, Any]) -> str:
    bits = []
    area = _safe_float(profile.get("area"))
    if area > 0:
        bits.append(f"面积{int(area)}㎡")
    struct = _human_label(profile.get("structure"))
    if struct:
        bits.append(f"结构{struct}")
    fire = _human_label(profile.get("fire_level"))
    if fire:
        bits.append(f"消防{fire}")
    if _safe_bool(profile.get("is_elevator")):
        bits.append("有电梯")
    if _safe_bool(profile.get("is_crown_block")):
        bits.append("行车")
    if _safe_bool(profile.get("is_divisible")):
        bits.append("可分割")
    follow = int(_safe_float(profile.get("follow_num")))
    show = int(_safe_float(profile.get("show_num")))
    if follow or show:
        bits.append(f"热度跟进{follow}/带看{show}")
    qs = profile.get("quality_score")
    if qs is not None:
        bits.append(f"质量分{float(qs):.2f}")
    return " · ".join(bits) if bits else "—"


def _load_base_rows(listing_type: str, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    import pandas as pd

    if not ids:
        return {}
    pq = _parquet_dir()
    table, _, _ = _TYPE_TABLE.get(listing_type, _TYPE_TABLE["plant"])
    path = pq / table
    if not path.is_file():
        return {}
    id_set = {str(x) for x in ids}
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.warning("read %s failed: %s", table, e)
        return {}
    if "id" not in df.columns:
        return {}
    df = df[df["id"].astype(str).isin(id_set)]
    out: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        lid = str(row.get("id") or "")
        if not lid:
            continue
        name = _safe_str(row.get("name")) or _safe_str(row.get("external_name"))
        area = _safe_float(row.get("sum_area") if "sum_area" in row.index else None)
        if area <= 0:
            area = _safe_float(row.get("area") if "area" in row.index else None)
        if area <= 0:
            area = _safe_float(row.get("can_rent_area") if "can_rent_area" in row.index else None)
        rec = {
            "listing_id": lid,
            "listing_type": listing_type,
            "listing_name": name,
            "province_name": _safe_str(row.get("province_name")),
            "city_name": _safe_str(row.get("city_name")),
            "region_name": _safe_str(row.get("region_name")),
            "street_name": _safe_str(row.get("street_name")),
            "longitude": _safe_float(row.get("longitude"), default=None) if "longitude" in row.index else None,  # type: ignore
            "latitude": _safe_float(row.get("latitude"), default=None) if "latitude" in row.index else None,  # type: ignore
            "area": area,
            "structure": _safe_str(row.get("structure")),
            "fire_level": _safe_str(row.get("fire_level")),
            "new_old": _safe_str(row.get("new_old")),
            "wall_type": _safe_str(row.get("wall_type")),
            "is_elevator": _safe_bool(row.get("is_elevator")),
            "is_crown_block": _safe_bool(row.get("is_crown_block")),
            "is_divisible": _safe_bool(row.get("is_divisible")),
            "follow_num": _safe_float(row.get("follow_num")),
            "show_num": _safe_float(row.get("show_num")),
            "office_id": _safe_str(row.get("office_id")) if "office_id" in row.index else "",
            "park_id": _safe_str(row.get("park_id")) if "park_id" in row.index else "",
        }
        if rec["longitude"] == 0.0 and rec["latitude"] == 0.0:
            rec["longitude"] = None
            rec["latitude"] = None
        out[lid] = rec
    return out


def _attach_office_geo(rows: Dict[str, Dict[str, Any]]) -> None:
    """办公房间无经纬度：经 office_id → e_office_base。"""
    import pandas as pd

    need = {
        r["office_id"]: lid
        for lid, r in rows.items()
        if r.get("listing_type") == "office"
        and r.get("office_id")
        and (r.get("longitude") is None or r.get("latitude") is None)
    }
    if not need:
        return
    path = _parquet_dir() / "e_office_base.parquet"
    if not path.is_file():
        return
    try:
        df = pd.read_parquet(path)
    except Exception:
        return
    if "id" not in df.columns:
        return
    df = df[df["id"].astype(str).isin(set(need.keys()))]
    by_oid = {str(r["id"]): r for _, r in df.iterrows()}
    for oid, lid in need.items():
        base = by_oid.get(oid)
        if base is None:
            continue
        rows[lid]["longitude"] = _safe_float(base.get("longitude"), default=None)  # type: ignore
        rows[lid]["latitude"] = _safe_float(base.get("latitude"), default=None)  # type: ignore
        if not rows[lid].get("city_name"):
            rows[lid]["city_name"] = _safe_str(base.get("city_name"))
        if not rows[lid].get("region_name"):
            rows[lid]["region_name"] = _safe_str(base.get("region_name"))
        if not rows[lid].get("province_name"):
            rows[lid]["province_name"] = _safe_str(base.get("province_name"))
        if not rows[lid].get("street_name"):
            rows[lid]["street_name"] = _safe_str(base.get("street_name"))


def _attach_rent(listing_type: str, rows: Dict[str, Dict[str, Any]]) -> None:
    import pandas as pd

    if not rows:
        return
    _, rent_table, fk = _TYPE_TABLE.get(listing_type, _TYPE_TABLE["plant"])
    path = _parquet_dir() / rent_table
    if not path.is_file():
        # office 有时外键名不同
        if listing_type == "office":
            for alt_fk in ("room_id", "office_room_id", "housing_resource_id"):
                pass
        return
    try:
        df = pd.read_parquet(path)
    except Exception:
        return
    # 猜测外键列
    fk_col = fk if fk in df.columns else None
    if fk_col is None:
        for c in ("plant_id", "warehouse_id", "office_room_id", "room_id", "housing_resource_id"):
            if c in df.columns:
                fk_col = c
                break
    if fk_col is None:
        return
    id_set = set(rows.keys())
    df = df[df[fk_col].astype(str).isin(id_set)]
    # 取每房源最新一条
    if "update_time" in df.columns:
        df = df.sort_values("update_time")
    for lid, grp in df.groupby(df[fk_col].astype(str)):
        last = grp.iloc[-1]
        rows[lid]["rent_price_min"] = _safe_float(last.get("rent_price_min"), default=None)  # type: ignore
        rows[lid]["rent_price_max"] = _safe_float(last.get("rent_price_max"), default=None)  # type: ignore
        rows[lid]["sale_price"] = _safe_float(last.get("sale_price"), default=None)  # type: ignore
        rows[lid]["property_price"] = _safe_float(last.get("property_price"), default=None)  # type: ignore


def load_listing_profiles(
    items: Sequence[Tuple[str, str]],
) -> Dict[str, Dict[str, Any]]:
    """items: [(listing_id, listing_type), ...] → id -> profile。"""
    by_type: Dict[str, List[str]] = {}
    for lid, ltype in items:
        t = (ltype or "plant").lower()
        if t not in ("plant", "warehouse", "office"):
            t = "plant"
        by_type.setdefault(t, []).append(str(lid))

    merged: Dict[str, Dict[str, Any]] = {}
    for t, ids in by_type.items():
        rows = _load_base_rows(t, ids)
        if t == "office":
            _attach_office_geo(rows)
        _attach_rent(t, rows)
        for lid, rec in rows.items():
            rec["address"] = build_address(
                rec.get("province_name") or "",
                rec.get("city_name") or "",
                rec.get("region_name") or "",
                rec.get("street_name") or "",
            )
            qs, parts = compute_quality_score(rec)
            rec["quality_score"] = qs
            rec["quality_parts"] = parts
            rec["info_completeness"] = parts["completeness"]
            rec["has_elevator"] = 1.0 if rec.get("is_elevator") else 0.0
            rec["has_crown_block"] = 1.0 if rec.get("is_crown_block") else 0.0
            rec["log_area"] = math.log1p(max(0.0, _safe_float(rec.get("area"))))
            rec["quality_highlights"] = quality_highlights(rec)
            merged[lid] = rec
    return merged


def enrich_listing_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """单行榜单记录补齐画像。"""
    lid = str(row.get("listing_id") or "")
    ltype = str(row.get("listing_type") or "plant")
    if not lid:
        return dict(row)
    profiles = load_listing_profiles([(lid, ltype)])
    p = profiles.get(lid) or {}
    out = dict(row)
    if p:
        for k in (
            "listing_name",
            "address",
            "longitude",
            "latitude",
            "province_name",
            "city_name",
            "region_name",
            "street_name",
            "area",
            "structure",
            "fire_level",
            "quality_score",
            "quality_highlights",
            "quality_parts",
            "follow_num",
            "show_num",
            "is_elevator",
            "is_crown_block",
            "rent_price_min",
            "rent_price_max",
            "sale_price",
            "log_area",
            "has_elevator",
            "has_crown_block",
            "info_completeness",
        ):
            if p.get(k) is not None and (out.get(k) is None or out.get(k) == "" or k.startswith("quality") or k in ("address", "listing_name", "longitude", "latitude")):
                out[k] = p[k]
        out["listing_profile"] = {
            "address": p.get("address"),
            "area": p.get("area"),
            "structure": p.get("structure"),
            "fire_level": p.get("fire_level"),
            "quality_score": p.get("quality_score"),
            "rent_price_min": p.get("rent_price_min"),
            "sale_price": p.get("sale_price"),
        }
    else:
        # 兜底
        city = _safe_str(out.get("city_name"))
        ltype_s = _safe_str(out.get("listing_type")) or "房源"
        out.setdefault("listing_name", out.get("listing_name") or f"{city}{ltype_s}")
        out.setdefault("address", city)
        qs, parts = compute_quality_score(out)
        out["quality_score"] = qs
        out["quality_parts"] = parts
        out["quality_highlights"] = quality_highlights(out)
    return out


def enrich_listings(listings: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [dict(r) for r in listings]
    items = [
        (str(r.get("listing_id") or ""), str(r.get("listing_type") or "plant"))
        for r in rows
        if r.get("listing_id")
    ]
    profiles = load_listing_profiles(items)
    out = []
    for r in rows:
        lid = str(r.get("listing_id") or "")
        p = profiles.get(lid)
        if p:
            out.append(enrich_listing_row({**r, **{k: p.get(k) for k in p if k != "listing_profile"}}))
        else:
            out.append(enrich_listing_row(r))
    return out
