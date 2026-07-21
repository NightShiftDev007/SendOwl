"""从 CRM 现实种子 / 统计榜抽样构建成交世界（线索×多经纪）。"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional

from app.engine.gtv_agent.state import DealThread
from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.world")

DEFAULT_CLUE_N = int(os.environ.get("GTV_AGENT_CLUE_N", "8"))
DEFAULT_BROKERS_PER_CLUE = int(os.environ.get("GTV_AGENT_BROKERS_PER_CLUE", "3"))
DEFAULT_CLUE_MIN = int(os.environ.get("GTV_AGENT_CLUE_MIN", "6"))
DEFAULT_CLUE_MAX = int(os.environ.get("GTV_AGENT_CLUE_MAX", "12"))
DEFAULT_CLUE_SCALE = float(os.environ.get("GTV_AGENT_CLUE_SCALE", "1.25"))
# 兼容旧环境变量：总线程约等于线索×每线索经纪人数
DEFAULT_N_THREADS = int(
    os.environ.get(
        "GTV_AGENT_THREADS",
        str(DEFAULT_CLUE_N * DEFAULT_BROKERS_PER_CLUE),
    )
)


def resolve_clue_n(expected_deals: Optional[float] = None, *, explicit: Optional[int] = None) -> int:
    """线索数：优先显式 → 统计 expected_deals×scale（夹紧）→ 固定默认。"""
    if explicit is not None:
        return max(1, int(explicit))
    mode = str(os.environ.get("GTV_AGENT_CLUE_MODE", "stat") or "stat").lower()
    fixed = max(1, int(os.environ.get("GTV_AGENT_CLUE_N", DEFAULT_CLUE_N)))
    if mode in ("fixed", "env") or expected_deals is None:
        return fixed
    try:
        ed = float(expected_deals)
    except Exception:
        return fixed
    if ed <= 0:
        return fixed
    scale = float(os.environ.get("GTV_AGENT_CLUE_SCALE", DEFAULT_CLUE_SCALE))
    lo = max(1, int(os.environ.get("GTV_AGENT_CLUE_MIN", DEFAULT_CLUE_MIN)))
    hi = max(lo, int(os.environ.get("GTV_AGENT_CLUE_MAX", DEFAULT_CLUE_MAX)))
    n = int(round(ed * scale))
    return max(lo, min(hi, max(1, n)))


def rank_seed_boards(
    listings: List[Dict[str, Any]],
    brokers: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按统计分降序，优先把三榜头部注入 Agent 世界。"""

    def _score(row: Dict[str, Any]) -> float:
        for k in ("score", "label_deals", "hist_deals", "heat", "quality_score"):
            try:
                v = float(row.get(k))
                if v == v:  # not NaN
                    return v
            except Exception:
                continue
        return 0.0

    L = sorted(list(listings or []), key=_score, reverse=True)
    B = sorted(list(brokers or []), key=_score, reverse=True)
    return L, B

_NAME_CACHE: Dict[str, str] = {}


def _extract_gtv(intervention: Any) -> Dict[str, Any]:
    if not isinstance(intervention, dict):
        return {}
    gtv = intervention.get("gtv")
    if isinstance(gtv, dict):
        return gtv
    return {}


def _lookup_listing_names(listing_ids: List[str]) -> Dict[str, str]:
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


def _broker_name(br: Dict[str, Any], i: int) -> str:
    name = str(
        br.get("nick_name") or br.get("user_name") or br.get("display_name") or f"经纪人{i+1}"
    )
    if name in ("None", "nan", ""):
        name = str(br.get("user_name") or f"经纪人{i+1}")
    return name


def _pick_brokers_for_clue(
    brokers: List[Dict[str, Any]], k: int, rng: random.Random, *, start: int
) -> List[Dict[str, Any]]:
    if not brokers:
        return _fallback_brokers(k, rng)
    if len(brokers) >= k:
        # 尽量不重复：从打乱池取
        pool = list(brokers)
        rng.shuffle(pool)
        return pool[:k]
    out = []
    for j in range(k):
        out.append(brokers[(start + j) % len(brokers)])
    return out


def _pick_listing_for_broker(
    listings: List[Dict[str, Any]],
    *,
    city: str,
    prefer_idx: int,
    used_in_clue: List[str],
    rng: random.Random,
) -> Dict[str, Any]:
    if not listings:
        return _fallback_listings(1, rng)[0]
    same_city = [
        r
        for r in listings
        if str(r.get("city_name") or "") == city
        and str(r.get("listing_id") or "") not in used_in_clue
    ]
    if same_city:
        return same_city[prefer_idx % len(same_city)]
    unused = [r for r in listings if str(r.get("listing_id") or "") not in used_in_clue]
    if unused:
        return unused[prefer_idx % len(unused)]
    return listings[prefer_idx % len(listings)]


def build_world(
    *,
    n_threads: int = DEFAULT_N_THREADS,
    intervention: Optional[Dict[str, Any]] = None,
    seed: int = 42,
    leaderboard_listings: Optional[List[Dict[str, Any]]] = None,
    leaderboard_brokers: Optional[List[Dict[str, Any]]] = None,
    n_clues: Optional[int] = None,
    brokers_per_clue: Optional[int] = None,
    expected_deals: Optional[float] = None,
    decision_id: Optional[str] = None,
    prepared_personas: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """构建一局推演世界：一客户线索 × K 经纪人（可配不同房源）。"""
    from app.engine.gtv_agent.persona import load_broker_personas, resolve_persona_for_broker

    rng = random.Random(seed)
    persona_map: Dict[str, Dict[str, Any]] = dict(prepared_personas or {})
    if not persona_map and decision_id:
        persona_map = load_broker_personas(decision_id)
    gtv = _extract_gtv(intervention)
    boost = gtv.get("boost_exposure") or {}
    reassign = gtv.get("reassign_broker") or {}
    nego = gtv.get("negotiate_deal") or {}
    boost_on = bool(isinstance(boost, dict) and boost.get("enabled"))
    boost_factor = float(boost.get("factor") or 1.5) if boost_on else 1.0
    nego_on = bool(isinstance(nego, dict) and nego.get("enabled"))
    nego_concession = float(nego.get("concession_pct") or 0.05) if nego_on else 0.0

    clue_n = resolve_clue_n(expected_deals, explicit=n_clues)
    k_brokers = int(
        brokers_per_clue
        if brokers_per_clue is not None
        else os.environ.get("GTV_AGENT_BROKERS_PER_CLUE", DEFAULT_BROKERS_PER_CLUE)
    )
    clue_n = max(1, clue_n)
    k_brokers = max(2, k_brokers)

    listings, brokers = rank_seed_boards(
        list(leaderboard_listings or []),
        list(leaderboard_brokers or []),
    )
    used_demo = False
    # 保持统计分降序（勿 set/字母序），供重叠对照取 Top10
    stat_listing_ids: List[str] = []
    seen_l: set = set()
    for r in listings:
        lid = str(r.get("listing_id") or "")
        if not lid or lid.startswith("demo_") or lid in seen_l:
            continue
        seen_l.add(lid)
        stat_listing_ids.append(lid)
    stat_broker_ids: List[str] = []
    seen_b: set = set()
    for r in brokers:
        bid = str(r.get("user_id") or r.get("broker_id") or "")
        if not bid or bid in seen_b:
            continue
        seen_b.add(bid)
        stat_broker_ids.append(bid)

    need_listings = max(clue_n * k_brokers, n_threads, 8)
    if len(listings) < need_listings:
        listings = listings + _fallback_listings(need_listings - len(listings), rng)
        used_demo = True
    need_brokers = max(k_brokers * 2, min(len(brokers) + clue_n, clue_n * k_brokers))
    if len(brokers) < need_brokers:
        brokers = brokers + _fallback_brokers(need_brokers - len(brokers), rng)
        used_demo = True

    from app.engine.gtv_agent.listing_profile import enrich_listings
    from app.engine.gtv_agent.amap import enrich_profile_with_amap

    listings = enrich_listings(listings[:need_listings])
    listings = [enrich_profile_with_amap(r) for r in listings]

    threads: List[DealThread] = []
    client_names = ["陈总", "王经理", "刘厂长", "赵总", "周工", "吴总", "郑老板", "孙总", "钱总", "冯经理"]
    needs = ["厂房扩产", "仓储中转", "办公研发", "产线搬迁", "电商仓配"]

    thread_i = 0
    for ci in range(clue_n):
        # 线索锚点：取一个 listing 定城市/预算画像
        anchor = listings[ci % len(listings)]
        city = str(anchor.get("city_name") or "未知城市")
        ltype_pref = str(anchor.get("listing_type") or "plant")
        base_price = float(
            anchor.get("prior_contract_money")
            or anchor.get("price")
            or anchor.get("list_price")
            or 80000
        )
        if base_price <= 0:
            base_price = 80000.0
        area_pref = float(anchor.get("area") or 1000 + ci * 80)
        client_name = client_names[ci % len(client_names)]
        client_id = f"C{ci+1}"
        budget = base_price * rng.uniform(0.85, 1.15)
        need = needs[ci % len(needs)]
        clue_id = f"CLUE_{ci+1:03d}_{rng.randint(1000, 9999)}"
        deal_group_id = clue_id
        client_need = f"{need}·需{city}{ltype_pref}约{int(area_pref)}㎡，预算约{int(budget)}"

        group_brokers = _pick_brokers_for_clue(brokers, k_brokers, rng, start=ci * k_brokers)
        used_listings: List[str] = []

        for bi, br in enumerate(group_brokers):
            row = _pick_listing_for_broker(
                listings, city=city, prefer_idx=ci + bi, used_in_clue=used_listings, rng=rng
            )
            lid = str(row.get("listing_id") or f"L{thread_i}")
            used_listings.append(lid)
            is_demo = str(lid).startswith("demo_")
            ltype = str(row.get("listing_type") or ltype_pref)
            lname = str(row.get("listing_name") or f"{city}{ltype}")
            price = float(
                row.get("prior_contract_money")
                or row.get("price")
                or row.get("list_price")
                or base_price
            )
            if price <= 0:
                price = base_price
            area = float(row.get("area") or area_pref)

            broker_id = str(br.get("user_id") or f"B{ci}_{bi}")
            broker_name = _broker_name(br, thread_i)
            if isinstance(reassign, dict) and reassign.get("enabled") and reassign.get("to_user_id"):
                # 改派：把组内第一个经纪换成指定人，其余保持竞争
                if bi == 0:
                    broker_id = str(reassign.get("to_user_id"))
                    broker_name = f"改派·{broker_name}"

            persona = resolve_persona_for_broker(br, persona_map, index=thread_i)
            biases = persona.get("biases") or {}
            # 人设偏置为主，少量噪声避免全员同质
            prefer_direct = bool(biases.get("prefer_direct", False))
            if nego_on:
                prefer_direct = False
            elif rng.random() < 0.08:
                prefer_direct = not prefer_direct
            coop_bias = float(biases.get("coop_bias") or 0.35)
            coop_bias = float(max(0.08, min(0.92, coop_bias + rng.uniform(-0.06, 0.06))))
            if bi == k_brokers - 1 and coop_bias < 0.45:
                coop_bias = max(coop_bias, 0.5)
            nego_from_persona = bool(biases.get("negotiate_enabled", not prefer_direct))
            qscore = float(row.get("quality_score") or 0.5)
            min_follows = 1
            if qscore >= 0.65 or boost_on:
                min_shows = 1
            elif qscore < 0.35:
                min_shows = 3
            else:
                min_shows = 1 + (bi % 2) + (1 if qscore < 0.45 else 0)

            addr = str(
                row.get("amap_address") or row.get("address") or city or lname or ""
            ).strip()
            try:
                lng_f = float(row["longitude"]) if row.get("longitude") is not None else None
                lat_f = float(row["latitude"]) if row.get("latitude") is not None else None
            except Exception:
                lng_f, lat_f = None, None

            thread_i += 1
            t = DealThread(
                thread_id=f"T{thread_i}",
                listing_id=lid,
                listing_type=ltype,
                listing_name=lname,
                city_name=str(row.get("city_name") or city),
                list_price=price,
                area=area,
                broker_id=broker_id,
                broker_name=broker_name,
                client_id=client_id,
                client_name=client_name,
                client_budget=budget,
                client_need=client_need,
                landlord_name=f"业主{chr(65 + ((ci + bi) % 26))}",
                clue_id=clue_id,
                project_id=f"PRJ_{clue_id[-8:]}_{bi+1}",
                deal_group_id=deal_group_id,
                heat=float(row.get("heat") or row.get("follow_num") or 0)
                * (boost_factor if boost_on else 1.0)
                * (0.9 + 0.05 * bi),
                boost_factor=boost_factor if boost_on else 1.0,
                negotiate_enabled=nego_on or nego_from_persona or (not prefer_direct),
                prefer_direct=prefer_direct,
                coop_bias=coop_bias,
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
                persona=persona,
                persona_label=str(
                    persona.get("persona_label") or persona.get("archetype") or ""
                ),
            )
            t.notes.append(f"线索 {clue_id} · 客户 {client_name}")
            t.notes.append(
                f"人设·{t.persona_label or '—'} · {str(persona.get('style') or '')[:36]}"
            )
            t.notes.append(f"同线索竞争 {k_brokers} 经纪 · 协作倾向 {coop_bias:.2f}")
            if prefer_direct:
                t.notes.append("路径倾向·不谈价直签")
            else:
                t.notes.append("路径倾向·可谈判")
            t.notes.append(f"质量分 {qscore:.2f}")
            if boost_on:
                t.notes.append(f"干预·加推×{boost_factor:.1f}")
            if nego_on:
                t.notes.append(f"干预·开启业主谈价（建议让步{nego_concession:.0%}）")
                t.prefer_direct = False
                t.negotiate_enabled = True
            if is_demo:
                t.notes.append("非种子·demo 兜底房源")
            threads.append(t)

    ed_note = ""
    if expected_deals is not None:
        try:
            ed_note = f"；线索规模对齐统计预期成交 {float(expected_deals):.2f}"
        except Exception:
            ed_note = "；线索规模对齐统计轨"
    return {
        "n_threads": len(threads),
        "n_clues": clue_n,
        "brokers_per_clue": k_brokers,
        "expected_deals_hint": expected_deals,
        "stat_listing_ids": list(stat_listing_ids),
        "stat_broker_ids": list(stat_broker_ids),
        "boost_exposure": boost_on,
        "negotiate_deal": nego_on,
        "reassign_broker": bool(isinstance(reassign, dict) and reassign.get("enabled")),
        "threads": threads,
        "intervention_gtv": gtv,
        "used_demo_fallback": used_demo,
        "race_mode": "clue_first_sign_wins",
        "seed_note": (
            f"统计三榜种子：{clue_n} 条客户线索×每线索 {k_brokers} 经纪抢签（先签先赢，过程可协作）"
            + ed_note
            + ("；含 demo 兜底" if used_demo else "")
        ),
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
    names = ["陆雨", "王建平", "黎俊", "牛源", "唐铖", "唐祖波", "陈浩", "林峰", "周敏", "吴强"]
    return [
        {"user_id": f"U{i}_{rng.randint(10, 99)}", "nick_name": names[i % len(names)]}
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
