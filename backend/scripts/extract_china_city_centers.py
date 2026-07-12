#!/usr/bin/env python3
"""从 frontend/public/geojson 提取地级市中心点 → backend/app/world/data/china_city_centers.json"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "frontend" / "public" / "geojson"
OUT = ROOT / "backend" / "app" / "world" / "data" / "china_city_centers.json"

MUNI = {"110000", "120000", "310000", "500000", "810000", "820000"}


def main() -> int:
    if not (GEO / "100000.json").exists():
        print(f"missing {GEO / '100000.json'}", file=sys.stderr)
        return 1

    nat = json.loads((GEO / "100000.json").read_text(encoding="utf-8"))
    provinces = {}
    for f in nat.get("features") or []:
        pr = f.get("properties") or {}
        code = pr.get("code")
        if not code:
            continue
        provinces[str(code)] = {
            "name": pr.get("name") or "",
            "fullname": pr.get("fullname") or pr.get("name") or "",
            "center": pr.get("center"),
            "adcode": str(code),
        }

    cities: dict = {}

    def add_city(name, fullname, province, coord, adcode, level):
        if not name or not coord or len(coord) < 2:
            return
        meta = {
            "province": province,
            "coord": [float(coord[0]), float(coord[1])],
            "adcode": str(adcode),
            "fullname": fullname or name,
            "level": level,
        }
        if name not in cities:
            cities[name] = meta
        for alias in {fullname, (fullname or "").rstrip("市") or None}:
            if alias and alias not in cities:
                cities[alias] = meta

    for code, pmeta in provinces.items():
        if code in MUNI:
            add_city(
                pmeta["name"],
                pmeta["fullname"],
                pmeta["fullname"],
                pmeta["center"],
                code,
                1,
            )

    for p in sorted(GEO.glob("*0000.json")):
        if p.name == "100000.json":
            continue
        pmeta = provinces.get(p.stem) or {}
        province_full = pmeta.get("fullname") or pmeta.get("name") or ""
        data = json.loads(p.read_text(encoding="utf-8"))
        for f in data.get("features") or []:
            pr = f.get("properties") or {}
            if pr.get("level") != 2:
                continue
            add_city(
                pr.get("name"),
                pr.get("fullname") or pr.get("name"),
                province_full,
                pr.get("center"),
                pr.get("code"),
                2,
            )

    out = {
        "source": "frontend/public/geojson",
        "province_count": len(provinces),
        "city_count": len({v["adcode"] for v in cities.values()}),
        "provinces": provinces,
        "cities": cities,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} cities={out['city_count']} keys={len(cities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
