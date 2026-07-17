"""从 CRM 现实种子 / 统计榜抽样构建成交世界。"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional

from app.engine.gtv_agent.state import DealThread
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.world")

DEFAULT_N_THREADS = int(os.environ.get("GTV_AGENT_THREADS", "10"))

# listing_id -> display name（按需查询缓存）
_NAME_CACHE: Dict[str, str] = {}


def _extract_gtv(intervention: Any) -> Dict[str, Any]:
    if not isinstance(intervention, dict):
        return {}
    gtv = intervention.get("gtv")
    if isinstance(gtv, dict):
        return gtv
    return {}


def _lookup_listing_names(listing_ids: List[str]) -> Dict[str, str]:
    """按需从 GTV parquet 解析房源名称（name / external_name）。"""
    want = [str(x).strip() for x in listing_ids if str(x).strip() and not str(x).startswith("demo_")]
    missing = [x for x in want if x not in _NAME_CACHE]
    if not missing:
        return {k: _NAME_CACHE[k] for k in want if k in _NAME_CACHE}
    try:
        import sys
        from pathlib import Path

        import pandas as pd

        backend = Path(__file__).resolve().parents[3]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from scripts.gtv_forecast.config import PARQUET_DIR

        id_set = set(missing)
        tables = (
            "e_plant_base.parquet",
            "e_warehouse_base.parquet",
            "e_office_room.parquet",
        )
        for fname in tables:
            if not id_set:
                break
            path = PARQUET_DIR / fname
            if not path.is_file():
                continue
            try:
                df = pd.read_parquet(path, columns=["id", "name", "external_name"])
            except Exception:
                continue
            df = df[df["id"].astype(str).isin(id_set)]
            for _, row in df.iterrows():
                lid = str(row.get("id") or "").strip()
                name = str(row.get("name") or "").strip()
                if not name or name in ("None", "nan"):
                    name = str(row.get("external_name") or "").strip()
                if lid and name and name not in ("None", "nan"):
                    _NAME_CACHE[lid] = name
                    id_set.discard(lid)
    except Exception as e:
        logger.warning("按需加载房源名称失败: %s", e)
    return {k: _NAME_CACHE[k] for k in want if k in _NAME_CACHE}


def enrich_listings_with_names(listings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = [str(r.get("listing_id") or "") for r in listings]
    idx = _lookup_listing_names(ids)
    out = []
    for row in listings:
        r = dict(row)
        lid = str(r.get("listing_id") or "")
        name = str(r.get("listing_name") or r.get("name") or r.get("external_name") or "").strip()
        if (not name or name in ("None", "nan")) and lid in idx:
            name = idx[lid]
        if not name or name in ("None", "nan"):
            city = str(r.get("city_name") or "")
            ltype = str(r.get("listing_type") or "房源")
            name = f"{city}{ltype}".strip() or (f"房源{lid[-6:]}" if lid else "未知房源")
        r["listing_name"] = name
        out.append(r)
    return out


def build_world(
    *,
    n_threads: int = DEFAULT_N_THREADS,
    intervention: Optional[Dict[str, Any]] = None,
    seed: int = 42,
    leaderboard_listings: Optional[List[Dict[str, Any]]] = None,
    leaderboard_brokers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """构建一局推演世界：交易线程列表 + 干预标记。"""
    rng = random.Random(seed)
    gtv = _extract_gtv(intervention)
    boost = gtv.get("boost_exposure") or {}
    reassign = gtv.get("reassign_broker") or {}
    nego = gtv.get("negotiate_deal") or {}
    boost_on = bool(isinstance(boost, dict) and boost.get("enabled"))
    boost_factor = float(boost.get("factor") or 1.5) if boost_on else 1.0
    nego_on = bool(isinstance(nego, dict) and nego.get("enabled"))
    nego_concession = float(nego.get("concession_pct") or 0.05) if nego_on else 0.0

    listings = list(leaderboard_listings or [])
    brokers = list(leaderboard_brokers or [])
    used_demo = False

    if len(listings) < n_threads:
        need = n_threads - len(listings)
        listings = listings + _fallback_listings(need, rng)
        used_demo = True
    if not brokers:
        brokers = _fallback_brokers(8, rng)
        used_demo = True

    from app.engine.gtv_agent.listing_profile import enrich_listings
    from app.engine.gtv_agent.amap import enrich_profile_with_amap

    listings = enrich_listings(listings[: max(n_threads, 1)])
    # 高德增强（无 Key 则跳过）
    listings = [enrich_profile_with_amap(r) for r in listings]
    threads: List[DealThread] = []
    client_names = ["陈总", "王经理", "刘厂长", "赵总", "周工", "吴总", "郑老板", "孙总", "钱总", "冯经理"]

    for i in range(min(n_threads, len(listings))):
        row = listings[i]
        lid = str(row.get("listing_id") or f"L{i}")
        is_demo = str(lid).startswith("demo_")
        ltype = str(row.get("listing_type") or "plant")
        city = str(row.get("city_name") or "未知城市")
        lname = str(row.get("listing_name") or f"{city}{ltype}")
        price = float(
            row.get("prior_contract_money")
            or row.get("price")
            or row.get("list_price")
            or row.get("rent_price_min")
            or 80000
        )
        if price <= 0:
            price = 80000.0
        area = float(row.get("area") or 1000 + i * 50)
        br = brokers[i % len(brokers)]
        broker_id = str(br.get("user_id") or f"B{i}")
        broker_name = str(
            br.get("nick_name") or br.get("user_name") or br.get("display_name") or f"经纪人{i+1}"
        )
        if broker_name in ("None", "nan", ""):
            broker_name = str(br.get("user_name") or f"经纪人{i+1}")

        if isinstance(reassign, dict) and reassign.get("enabled") and reassign.get("to_user_id"):
            broker_id = str(reassign.get("to_user_id"))
            broker_name = f"改派·{broker_name}"

        client_name = client_names[i % len(client_names)]
        budget = price * rng.uniform(0.85, 1.15)
        prefer_direct = (not nego_on) and (rng.random() < 0.40)
        qscore = float(row.get("quality_score") or 0.5)
        min_follows = 1
        if qscore >= 0.65 or boost_on:
            min_shows = 1
        elif qscore < 0.35:
            min_shows = 3
        else:
            min_shows = 2

        clue_id = f"CLUE_{lid[-8:]}" if len(lid) >= 4 else f"CLUE_{i+1}"
        project_id = f"PRJ_{lid[-8:]}" if len(lid) >= 4 else f"PRJ_{i+1}"
        addr = str(
            row.get("amap_address")
            or row.get("address")
            or city
            or lname
            or ""
        ).strip()
        lng = row.get("longitude")
        lat = row.get("latitude")
        try:
            lng_f = float(lng) if lng is not None else None
            lat_f = float(lat) if lat is not None else None
        except Exception:
            lng_f, lat_f = None, None

        t = DealThread(
            thread_id=f"T{i+1}",
            listing_id=lid,
            listing_type=ltype,
            listing_name=lname,
            city_name=city,
            list_price=price,
            area=area,
            broker_id=broker_id,
            broker_name=broker_name,
            client_id=f"C{i+1}",
            client_name=client_name,
            client_budget=budget,
            client_need=f"需{city}{ltype}约{int(area)}㎡，预算{int(budget)}，地址{addr}",
            landlord_name=f"业主{chr(65 + (i % 26))}",
            clue_id=clue_id,
            project_id=project_id,
            heat=float(row.get("heat") or row.get("follow_num") or 0) * (boost_factor if boost_on else 1.0),
            boost_factor=boost_factor if boost_on else 1.0,
            negotiate_enabled=nego_on or (not prefer_direct),
            prefer_direct=prefer_direct,
            concession_pct=nego_concession if nego_on else 0.0,
            min_follows=min_follows,
            min_shows=min_shows,
            seed_source="demo" if is_demo else "seed",
            address=addr,
            longitude=lng_f,
            latitude=lat_f,
            quality_score=qscore,
            quality_highlights=str(row.get("quality_highlights") or ""),
            amap_address=str(row.get("amap_address") or ""),
            amap_poi_summary=str(row.get("amap_poi_summary") or ""),
            listing_profile=row.get("listing_profile")
            or {
                "address": addr,
                "area": area,
                "structure": row.get("structure"),
                "fire_level": row.get("fire_level"),
                "quality_score": qscore,
            },
        )
        if prefer_direct:
            t.notes.append("路径倾向·不谈价直签")
        else:
            t.notes.append("路径倾向·可谈价协商")
        t.notes.append(f"质量分 {qscore:.2f}")
        if boost_on:
            t.notes.append(f"干预·加推×{boost_factor:.1f}")
        if nego_on:
            t.notes.append(f"干预·开启业主谈价（建议让步{nego_concession:.0%}）")
            t.prefer_direct = False
            t.negotiate_enabled = True
        if isinstance(reassign, dict) and reassign.get("enabled"):
            t.notes.append("干预·更换维护人")
        if is_demo:
            t.notes.append("非种子·demo 兜底房源")
        threads.append(t)

    return {
        "n_threads": len(threads),
        "boost_exposure": boost_on,
        "negotiate_deal": nego_on,
        "reassign_broker": bool(isinstance(reassign, dict) and reassign.get("enabled")),
        "threads": threads,
        "intervention_gtv": gtv,
        "used_demo_fallback": used_demo,
        "seed_note": "CRM 种子底座抽样（房源/经纪人）；过程为推演涌现"
        + ("；部分线程含 demo 兜底" if used_demo else ""),
    }


def _fallback_listings(n: int, rng: random.Random) -> List[Dict[str, Any]]:
    cities = ["上海市", "廊坊市", "苏州市", "东莞市", "杭州市"]
    types = ["plant", "warehouse", "office"]
    out = []
    for i in range(n):
        city = cities[i % len(cities)]
        ltype = types[i % 3]
        lid = f"demo_{rng.randint(100000, 999999)}"
        out.append(
            {
                "listing_id": lid,
                "listing_type": ltype,
                "listing_name": f"{city}演示{ltype}（非种子）",
                "city_name": city,
                "prior_contract_money": rng.choice([30000, 50000, 80000, 120000]),
                "heat": rng.randint(0, 20),
                "area": rng.choice([800, 1200, 2000, 3500]),
            }
        )
    return out


def _fallback_brokers(n: int, rng: random.Random) -> List[Dict[str, Any]]:
    names = ["陆雨", "王建平", "黎俊", "牛源", "唐铖", "唐祖波", "陈浩", "林峰"]
    return [
        {"user_id": f"U{i}", "nick_name": names[i % len(names)]}
        for i in range(n)
    ]


def try_load_listings_from_parquet(n: int = 30) -> tuple[List[Dict], List[Dict]]:
    """优先用统计轨快照宇宙抽样本；失败则空列表。"""
    try:
        import sys
        from pathlib import Path

        backend = Path(__file__).resolve().parents[3]
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from scripts.gtv_forecast.features import build_scoring_universe
        from scripts.gtv_forecast.scoring import score_with_intervention

        scored = score_with_intervention({})
        listings = list(scored.get("listings") or [])[:n]
        brokers = list(scored.get("brokers") or [])[:20]
        if listings:
            return listings, brokers
        univ, brokers_df, _ = build_scoring_universe()
        sample = univ.head(n)
        listings = sample.to_dict(orient="records")
        brokers = brokers_df.head(20).to_dict(orient="records") if len(brokers_df) else []
        return listings, brokers
    except Exception as e:
        logger.warning("加载成交世界样本失败，将用演示房源: %s", e)
        return [], []
