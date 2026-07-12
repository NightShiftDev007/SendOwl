#!/usr/bin/env python3
"""从 frontend/public/geojson 提取省/市/区县 adcode 索引 → china_adcode_index.json"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "frontend" / "public" / "geojson"
OUT = ROOT / "backend" / "app" / "world" / "data" / "china_adcode_index.json"

MUNI = {"110000", "120000", "310000", "500000", "810000", "820000"}


def _norm_code(code) -> str:
    s = str(code or "").strip()
    if not s or not s.isdigit():
        return ""
    return s.zfill(6)[-6:]


def _add(
    by_adcode: dict,
    *,
    adcode: str,
    level: int,
    name: str,
    fullname: str,
    center,
    parent_adcode: str = "",
    filename: str = "",
) -> None:
    if not adcode or not center or len(center) < 2:
        return
    if adcode in by_adcode:
        # prefer entry with filename / fuller name
        old = by_adcode[adcode]
        if filename and not old.get("filename"):
            old["filename"] = filename
        return
    by_adcode[adcode] = {
        "adcode": adcode,
        "level": level,  # 1 province, 2 city, 3 district
        "name": name or fullname or adcode,
        "fullname": fullname or name or adcode,
        "center": [float(center[0]), float(center[1])],
        "parent_adcode": parent_adcode or "",
        "filename": filename or "",
    }


def main() -> int:
    if not (GEO / "100000.json").exists():
        print(f"missing {GEO / '100000.json'}", file=sys.stderr)
        return 1

    by_adcode: dict = {}

    nat = json.loads((GEO / "100000.json").read_text(encoding="utf-8"))
    for f in nat.get("features") or []:
        pr = f.get("properties") or {}
        code = _norm_code(pr.get("code"))
        if not code:
            continue
        _add(
            by_adcode,
            adcode=code,
            level=1,
            name=pr.get("name") or "",
            fullname=pr.get("fullname") or pr.get("name") or "",
            center=pr.get("center"),
            parent_adcode="100000",
            filename=str(pr.get("filename") or code),
        )

    # Province files: cities (level 2) or muni districts (level 3)
    for p in sorted(GEO.glob("*0000.json")):
        if p.name == "100000.json":
            continue
        prov_code = _norm_code(p.stem)
        data = json.loads(p.read_text(encoding="utf-8"))
        for f in data.get("features") or []:
            pr = f.get("properties") or {}
            code = _norm_code(pr.get("code"))
            if not code:
                continue
            lv = pr.get("level")
            try:
                lv = int(lv) if lv is not None else (3 if prov_code in MUNI else 2)
            except Exception:
                lv = 2
            parent = prov_code
            filename = str(pr.get("filename") or "")
            if not filename and lv == 2:
                filename = f"{prov_code}/{code}"
            _add(
                by_adcode,
                adcode=code,
                level=lv,
                name=pr.get("name") or "",
                fullname=pr.get("fullname") or pr.get("name") or "",
                center=pr.get("center"),
                parent_adcode=parent,
                filename=filename,
            )

    # Subdir city/district files
    for d in sorted(x for x in GEO.iterdir() if x.is_dir()):
        prov_code = _norm_code(d.name)
        for p in d.glob("*.json"):
            code_stem = _norm_code(p.stem)
            data = json.loads(p.read_text(encoding="utf-8"))
            feats = data.get("features") or []
            rel = f"{d.name}/{p.stem}"
            for f in feats:
                pr = f.get("properties") or {}
                code = _norm_code(pr.get("code") or code_stem)
                if not code:
                    continue
                lv = pr.get("level")
                try:
                    lv = int(lv) if lv is not None else 3
                except Exception:
                    lv = 3
                # parent: city file stem if district, else province
                if lv == 3:
                    if code_stem.endswith("00") and not code_stem.endswith("0000"):
                        parent = code_stem
                    elif prov_code in MUNI:
                        parent = prov_code
                    else:
                        parent = code[:4] + "00"
                else:
                    parent = prov_code
                _add(
                    by_adcode,
                    adcode=code,
                    level=lv,
                    name=pr.get("name") or "",
                    fullname=pr.get("fullname") or pr.get("name") or "",
                    center=pr.get("center"),
                    parent_adcode=parent if parent != code else prov_code,
                    filename=rel if lv == 2 else (f"{prov_code}/{parent}" if lv == 3 else ""),
                )

    # Top-level district fragments (e.g. 110101.json under muni)
    for p in sorted(GEO.glob("*.json")):
        stem = p.stem
        if stem in ("100000", "china") or (stem.endswith("0000") and len(stem) == 6):
            continue
        if not (stem.isdigit() and len(stem) == 6):
            continue
        code = _norm_code(stem)
        data = json.loads(p.read_text(encoding="utf-8"))
        for f in data.get("features") or []:
            pr = f.get("properties") or {}
            c = _norm_code(pr.get("code") or code)
            if not c:
                continue
            lv = pr.get("level")
            try:
                lv = int(lv) if lv is not None else 3
            except Exception:
                lv = 3
            prov = c[:2] + "0000"
            parent = prov if prov in MUNI else (c[:4] + "00")
            _add(
                by_adcode,
                adcode=c,
                level=lv,
                name=pr.get("name") or "",
                fullname=pr.get("fullname") or pr.get("name") or "",
                center=pr.get("center"),
                parent_adcode=parent,
                filename="",
            )

    # Ensure municipalities exist as city-level endpoints too (level stays 1, flagged)
    for m in MUNI:
        if m in by_adcode:
            by_adcode[m]["is_municipality"] = True

    # Name → adcode reverse (longest names first at lookup time)
    name_to_adcode: dict = {}

    def register_name(key: str, adcode: str) -> None:
        if not key:
            return
        if key not in name_to_adcode:
            name_to_adcode[key] = adcode
            return
        old = by_adcode.get(name_to_adcode[key], {})
        new = by_adcode.get(adcode, {})
        if int(new.get("level") or 0) > int(old.get("level") or 0):
            name_to_adcode[key] = adcode

    for adcode, meta in by_adcode.items():
        for key in (meta.get("fullname"), meta.get("name")):
            register_name(key, adcode)
        full = meta.get("fullname") or meta.get("name") or ""
        for suffix in ("市", "地区", "盟", "州", "林区", "区", "县", "旗", "自治县", "自治旗"):
            if full.endswith(suffix) and len(full) > len(suffix):
                short = full[: -len(suffix)]
                if short:
                    register_name(short, adcode)
                break

    # Aliases
    name_to_adcode["江城"] = "420100"
    name_to_adcode["江城市"] = "420100"

    levels = {1: 0, 2: 0, 3: 0}
    for m in by_adcode.values():
        levels[int(m.get("level") or 0)] = levels.get(int(m.get("level") or 0), 0) + 1

    out = {
        "source": "frontend/public/geojson",
        "counts": {
            "total": len(by_adcode),
            "province": levels.get(1, 0),
            "city": levels.get(2, 0),
            "district": levels.get(3, 0),
        },
        "municipalities": sorted(MUNI),
        "by_adcode": by_adcode,
        "name_to_adcode": name_to_adcode,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} total={len(by_adcode)} levels={levels} names={len(name_to_adcode)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
