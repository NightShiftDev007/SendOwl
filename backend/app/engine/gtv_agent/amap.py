"""高德 Web 服务增强：逆地理 + 周边 POI（可选，有 Key 才调用）。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

from app.utils.logger import get_logger

logger = get_logger("adc.engine.gtv_agent.amap")

_CACHE_DIR = Path(__file__).resolve().parents[3] / "scripts" / "gtv_forecast" / "_data" / "amap_cache"


def amap_api_key() -> str:
    return (
        os.environ.get("AMAP_API_KEY")
        or os.environ.get("GAODE_API_KEY")
        or ""
    ).strip()


def amap_available() -> bool:
    return bool(amap_api_key())


def _cache_path(listing_id: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(listing_id))
    return _CACHE_DIR / f"{safe}.json"


def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        with urlopen(url, timeout=6) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as e:
        logger.debug("amap request failed: %s", e)
        return None


def reverse_geocode(lng: float, lat: float) -> Dict[str, Any]:
    key = amap_api_key()
    if not key:
        return {}
    qs = urlencode(
        {
            "key": key,
            "location": f"{lng},{lat}",
            "extensions": "base",
        }
    )
    data = _get_json(f"https://restapi.amap.com/v3/geocode/regeo?{qs}")
    if not data or str(data.get("status")) != "1":
        return {}
    regeo = data.get("regeocode") or {}
    return {
        "amap_address": str(regeo.get("formatted_address") or ""),
        "amap_raw": {"addressComponent": regeo.get("addressComponent")},
    }


def nearby_pois(lng: float, lat: float, keywords: str = "工业园|高速|物流") -> List[str]:
    key = amap_api_key()
    if not key:
        return []
    qs = urlencode(
        {
            "key": key,
            "location": f"{lng},{lat}",
            "keywords": keywords,
            "radius": 3000,
            "offset": 3,
            "page": 1,
            "extensions": "base",
        }
    )
    data = _get_json(f"https://restapi.amap.com/v3/place/around?{qs}")
    if not data or str(data.get("status")) != "1":
        return []
    pois = data.get("pois") or []
    out = []
    for p in pois[:3]:
        name = str(p.get("name") or "").strip()
        dist = str(p.get("distance") or "").strip()
        if name:
            out.append(f"{name}" + (f"（{dist}m）" if dist else ""))
    return out


def enrich_profile_with_amap(profile: Dict[str, Any], *, use_cache: bool = True) -> Dict[str, Any]:
    """就地增强 profile；无 Key / 无坐标则跳过。"""
    out = dict(profile)
    if not amap_available():
        return out
    lng = out.get("longitude")
    lat = out.get("latitude")
    try:
        lng_f = float(lng)
        lat_f = float(lat)
    except Exception:
        return out
    if not lng_f or not lat_f:
        return out

    lid = str(out.get("listing_id") or "")
    cache_file = _cache_path(lid) if lid and use_cache else None
    if cache_file and cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            out.update({k: cached[k] for k in ("amap_address", "amap_poi_summary") if k in cached})
            return out
        except Exception:
            pass

    regeo = reverse_geocode(lng_f, lat_f)
    if regeo.get("amap_address"):
        out["amap_address"] = regeo["amap_address"]
    pois = nearby_pois(lng_f, lat_f)
    if pois:
        out["amap_poi_summary"] = "；".join(pois)
    payload = {
        "amap_address": out.get("amap_address") or "",
        "amap_poi_summary": out.get("amap_poi_summary") or "",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if cache_file:
        try:
            cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return out


def enrich_profiles_batch(profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """仅对本局抽样房源调用；无 Key 原样返回。"""
    if not amap_available():
        return profiles
    out = []
    for p in profiles:
        try:
            out.append(enrich_profile_with_amap(p))
            time.sleep(0.05)  # 轻限流
        except Exception as e:
            logger.debug("amap enrich skip: %s", e)
            out.append(p)
    return out
