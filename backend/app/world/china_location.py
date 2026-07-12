"""
中国行政区划（adcode 主键）：人设与飞线共用。

权威索引：data/china_adcode_index.json（由 geojson 提取）。
逻辑/校验一律用 adcode；名称仅展示与入库解析。
默认案例枢纽为北京（110000）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DATA_PATH = Path(__file__).resolve().parent / "data" / "china_adcode_index.json"

MUNICIPALITIES = {"110000", "120000", "310000", "500000", "810000", "820000"}
HUB_ADCODE = "110000"  # 北京（默认案例枢纽）

# adcode → meta
BY_ADCODE: Dict[str, Dict[str, Any]] = {}
# name → adcode（仅解析边界）
NAME_TO_ADCODE: Dict[str, str] = {}

# 兼容旧调用：短名 → 市级 meta（含 adcode）
CITY_META: Dict[str, Dict[str, Any]] = {}

_ALIAS_PATTERNS: List[Tuple[str, str]] = []
_NAME_PATTERNS: List[Tuple[str, str]] = []  # (name, adcode) 长词优先


def _norm_code(code: Any) -> str:
    s = str(code or "").strip()
    if not s or not s.isdigit():
        return ""
    return s.zfill(6)[-6:]


def _load() -> None:
    global BY_ADCODE, NAME_TO_ADCODE, CITY_META, _NAME_PATTERNS, _ALIAS_PATTERNS
    if BY_ADCODE:
        return

    if not _DATA_PATH.exists():
        # 极简兜底
        BY_ADCODE.update(
            {
                "110000": {
                    "adcode": "110000",
                    "level": 1,
                    "name": "北京",
                    "fullname": "北京市",
                    "center": [116.41, 39.90],
                    "parent_adcode": "100000",
                    "is_municipality": True,
                },
                "310000": {
                    "adcode": "310000",
                    "level": 1,
                    "name": "上海",
                    "fullname": "上海市",
                    "center": [121.47, 31.23],
                    "parent_adcode": "100000",
                    "is_municipality": True,
                },
                "420100": {
                    "adcode": "420100",
                    "level": 2,
                    "name": "武汉",
                    "fullname": "武汉市",
                    "center": [114.31, 30.52],
                    "parent_adcode": "420000",
                },
            }
        )
        NAME_TO_ADCODE.update(
            {"北京": "110000", "北京市": "110000", "上海": "310000", "上海市": "310000", "武汉": "420100", "武汉市": "420100", "江城": "420100", "江城市": "420100"}
        )
    else:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
        BY_ADCODE.update(raw.get("by_adcode") or {})
        NAME_TO_ADCODE.update(raw.get("name_to_adcode") or {})
        for m in raw.get("municipalities") or []:
            if m in BY_ADCODE:
                BY_ADCODE[m]["is_municipality"] = True

    # CITY_META 兼容：市级/直辖短名
    for adcode, meta in BY_ADCODE.items():
        lv = int(meta.get("level") or 0)
        if lv == 1 and adcode in MUNICIPALITIES:
            pass
        elif lv != 2 and not (lv == 1 and adcode in MUNICIPALITIES):
            if not (lv == 1 and meta.get("is_municipality")):
                if lv != 2:
                    continue
        if lv == 3:
            continue
        if lv == 1 and adcode not in MUNICIPALITIES:
            continue
        name = meta.get("name") or ""
        full = meta.get("fullname") or name
        entry = {
            "province": meta_of_adcode(province_adcode(adcode)).get("fullname")
            if province_adcode(adcode) != adcode
            else full,
            "coord": list(meta["center"]),
            "adcode": adcode,
            "fullname": full,
            "level": lv,
        }
        if name:
            CITY_META[name] = entry
        if full and full != name:
            CITY_META[full] = entry
        if full.endswith("市") and full[:-1]:
            CITY_META[full[:-1]] = entry

    # Fix province field for cities
    for name, entry in list(CITY_META.items()):
        pac = province_adcode(entry["adcode"])
        pm = BY_ADCODE.get(pac) or {}
        entry["province"] = pm.get("fullname") or pm.get("name") or entry.get("province") or ""

    _NAME_PATTERNS = sorted(NAME_TO_ADCODE.items(), key=lambda x: -len(x[0]))
    _ALIAS_PATTERNS = [(a, NAME_TO_ADCODE[a]) for a in ("江城", "江城市") if a in NAME_TO_ADCODE]


def meta_of_adcode(code: Optional[str]) -> Dict[str, Any]:
    c = _norm_code(code)
    return dict(BY_ADCODE.get(c) or {})


def coord_of_adcode(code: Optional[str]) -> Optional[List[float]]:
    meta = meta_of_adcode(code)
    center = meta.get("center")
    if not center or len(center) < 2:
        return None
    return [float(center[0]), float(center[1])]


def lookup_adcode(name: Optional[str]) -> Optional[str]:
    """名称 → adcode（仅解析边界）。"""
    if not name:
        return None
    s = str(name).strip()
    if not s:
        return None
    if s in NAME_TO_ADCODE:
        return NAME_TO_ADCODE[s]
    if s.isdigit() and _norm_code(s) in BY_ADCODE:
        return _norm_code(s)
    for alias, adcode in _NAME_PATTERNS:
        if alias == s:
            return adcode
    return None


def extract_adcode_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    for alias, adcode in _NAME_PATTERNS:
        if alias and alias in text:
            return adcode
    return None


def is_municipality(code: Optional[str]) -> bool:
    c = _norm_code(code)
    if not c:
        return False
    prov = c[:2] + "0000"
    return prov in MUNICIPALITIES or bool((BY_ADCODE.get(prov) or {}).get("is_municipality"))


def province_adcode(code: Optional[str]) -> str:
    c = _norm_code(code)
    if not c:
        return ""
    return c[:2] + "0000"


def city_adcode(code: Optional[str]) -> str:
    """上卷到市/直辖/省直管端点。"""
    c = _norm_code(code)
    if not c:
        return ""
    if is_municipality(c):
        return c[:2] + "0000"
    # already province
    if c.endswith("0000"):
        return c
    # prefecture city XXYY00
    cand = c[:4] + "00"
    if cand in BY_ADCODE:
        return cand
    # 省直管等：leaf 自身若在索引中
    if c in BY_ADCODE:
        return c
    return cand


def same_province(a: Optional[str], b: Optional[str]) -> bool:
    pa, pb = province_adcode(a), province_adcode(b)
    return bool(pa and pb and pa == pb)


def same_city(a: Optional[str], b: Optional[str]) -> bool:
    ca, cb = _norm_code(a), _norm_code(b)
    if not ca or not cb:
        return False
    if is_municipality(ca) or is_municipality(cb):
        return province_adcode(ca) == province_adcode(cb)
    return city_adcode(ca) == city_adcode(cb)


def span_between(a: Optional[str], b: Optional[str]) -> str:
    if same_city(a, b):
        return "intra_city"
    if same_province(a, b):
        return "cross_city"
    return "cross_province"


def leaf_adcode_from_fields(
    *,
    province_adcode_v: Optional[str] = None,
    city_adcode_v: Optional[str] = None,
    district_adcode_v: Optional[str] = None,
) -> Optional[str]:
    for c in (district_adcode_v, city_adcode_v, province_adcode_v):
        n = _norm_code(c)
        if n and n in BY_ADCODE:
            return n
    return None


def map_path_for_adcode(code: Optional[str]) -> Optional[str]:
    """返回 public/geojson 相对路径（无前缀），用于下钻加载。"""
    c = _norm_code(code)
    if not c:
        return None
    if c == "100000":
        return "100000.json"
    meta = BY_ADCODE.get(c) or {}
    fn = meta.get("filename") or ""
    if fn:
        return f"{fn}.json" if not str(fn).endswith(".json") else str(fn)
    if c in MUNICIPALITIES or (c.endswith("0000") and c in BY_ADCODE):
        return f"{c}.json"
    if c.endswith("00"):
        prov = province_adcode(c)
        return f"{prov}/{c}.json"
    # district: prefer parent city file
    parent = city_adcode(c)
    if parent in MUNICIPALITIES:
        return f"{parent}.json"
    prov = province_adcode(c)
    return f"{prov}/{parent}.json"


def resolve_to_adcodes(
    *,
    province: Optional[str] = None,
    city: Optional[str] = None,
    district: Optional[str] = None,
    province_adcode_v: Optional[str] = None,
    city_adcode_v: Optional[str] = None,
    district_adcode_v: Optional[str] = None,
    text: str = "",
    entity_type: str = "",
    seed: Any = None,
) -> Dict[str, str]:
    """
    返回成对字段：province/city/district 名称 + *_adcode。
    有码用码反查名；仅有名则解析；保证不出现有名无码用于飞线的脏数据。
    """
    d_code = _norm_code(district_adcode_v) or lookup_adcode(district)
    c_code = _norm_code(city_adcode_v) or lookup_adcode(city)
    p_code = _norm_code(province_adcode_v) or lookup_adcode(province)

    # 文本抽取
    if not d_code and not c_code:
        hit = extract_adcode_from_text(text)
        if hit:
            meta = BY_ADCODE.get(hit) or {}
            lv = int(meta.get("level") or 0)
            if lv == 3:
                d_code = hit
            elif lv == 2 or (lv == 1 and hit in MUNICIPALITIES):
                c_code = hit
            elif lv == 1:
                p_code = hit

    # 从更细推导上级
    leaf = d_code or c_code or p_code
    if not leaf:
        et = (entity_type or "").lower()
        pool = [HUB_ADCODE, "110000", "310000", "440100", "440300"]
        pool = [x for x in pool if x in BY_ADCODE] or list(BY_ADCODE.keys())[:8]
        if any(k in et for k in ("government", "official", "agency", "交管", "organization", "rider", "delivery", "骑手")):
            leaf = HUB_ADCODE if HUB_ADCODE in BY_ADCODE else pool[0]
        elif any(k in et for k in ("media", "记者", "outlet")):
            leaf = _stable_pick(seed, [x for x in ("110000", "310000", "440100", HUB_ADCODE) if x in BY_ADCODE] or pool)
        else:
            leaf = _stable_pick(seed, [x for x in (HUB_ADCODE, "420100", "430100", "360100", "340100") if x in BY_ADCODE] or pool)

    if d_code and d_code not in BY_ADCODE:
        d_code = ""
    if not c_code and leaf:
        c_code = city_adcode(leaf)
    if not p_code and leaf:
        p_code = province_adcode(leaf)
    if d_code:
        c_code = city_adcode(d_code)
        p_code = province_adcode(d_code)
    elif c_code:
        p_code = province_adcode(c_code)

    # 校验码存在
    if c_code and c_code not in BY_ADCODE:
        # 省直管已在 city_adcode 处理；若仍无则清空
        if leaf and leaf in BY_ADCODE:
            c_code = city_adcode(leaf)
        else:
            c_code = ""
    if p_code and p_code not in BY_ADCODE:
        p_code = province_adcode(c_code or leaf) if (c_code or leaf) else ""

    def _name(code: str) -> str:
        m = BY_ADCODE.get(code) or {}
        return str(m.get("fullname") or m.get("name") or "")

    out = {
        "country": "中国",
        "province": _name(p_code) if p_code else "",
        "province_adcode": p_code or "",
        "city": _name(c_code) if c_code else "",
        "city_adcode": c_code or "",
        "district": _name(d_code) if d_code else "",
        "district_adcode": d_code or "",
    }
    return out


def enrich_profile_location(profile: Dict[str, Any], entity_type: str = "") -> Dict[str, Any]:
    """就地补全 profile 的省市区名称+adcode。"""
    blob = " ".join(
        str(profile.get(k) or "")
        for k in (
            "name",
            "username",
            "user_name",
            "bio",
            "persona",
            "profession",
            "city",
            "province",
            "district",
            "location",
        )
    )
    loc = resolve_to_adcodes(
        province=profile.get("province"),
        city=profile.get("city") or profile.get("location"),
        district=profile.get("district"),
        province_adcode_v=profile.get("province_adcode"),
        city_adcode_v=profile.get("city_adcode"),
        district_adcode_v=profile.get("district_adcode"),
        text=blob,
        entity_type=entity_type or profile.get("source_entity_type") or "",
        seed=profile.get("user_id", profile.get("name")),
    )
    profile["country"] = loc["country"]
    profile["province"] = loc["province"]
    profile["province_adcode"] = loc["province_adcode"]
    profile["city"] = loc["city"]
    profile["city_adcode"] = loc["city_adcode"]
    profile["district"] = loc["district"]
    profile["district_adcode"] = loc["district_adcode"]
    return profile


def format_location_label(loc: Optional[Dict[str, Any]] = None, **kwargs: Any) -> str:
    """仅格式化省市区展示名，不写死地域气质。"""
    loc = dict(loc or {})
    loc.update({k: v for k, v in kwargs.items() if v})
    parts = [
        str(loc.get("province") or "").strip(),
        str(loc.get("city") or "").strip(),
        str(loc.get("district") or "").strip(),
    ]
    return " / ".join(p for p in parts if p) or "中国某地"


def location_instruction_for_llm() -> str:
    samples = "、".join(
        (
            BY_ADCODE[c]["name"]
            for c in ("110000", "110106", "110111", "310000", "440100", "420100")
            if c in BY_ADCODE
        )
    )
    return (
        "9. province: 中国省级行政区全称（如「北京市」「湖北省」）；不要输出编码\n"
        "10. city: 中国真实地级市/直辖市名（如「北京」「武汉」）；不要输出编码\n"
        "11. district: 可选，真实区县名（如「丰台区」「房山区」）；不确定可省略；不要输出编码\n"
        "12. 地域人格（硬性，由你自行生成）：province/city/district 不只是地址字段——"
        "必须在 persona 中根据该地真实社会语境自行推断并写出地域如何塑造此人/账号"
        "（语感、利益、通勤/生计、对政策的第一反应）；"
        "禁止套用模板口号，禁止只填地名却写成无根飘浮的抽象网民；"
        "不要等待外部提供「地域气质」文案，由你基于地名与实体信息原创。\n"
        f"常见示例：{samples} 等。禁止虚构城市名；"
        "场景若出现「丰台」「房山」请落在北京市对应区县。"
    )


# —— 兼容旧 API ——

def normalize_city(name: Optional[str]) -> Optional[str]:
    code = lookup_adcode(name)
    if not code:
        return None
    code = city_adcode(code)
    meta = BY_ADCODE.get(code) or {}
    return meta.get("name") or meta.get("fullname") or None


def extract_city_from_text(text: str) -> Optional[str]:
    code = extract_adcode_from_text(text)
    if not code:
        return None
    return normalize_city(meta_of_adcode(code).get("name")) or meta_of_adcode(city_adcode(code)).get("name")


def province_of(city: str) -> str:
    code = lookup_adcode(city) or ""
    if not code:
        return ""
    return meta_of_adcode(province_adcode(code)).get("fullname") or ""


def coord_of(city: str) -> Optional[List[float]]:
    code = lookup_adcode(city)
    if not code:
        # try CITY_META
        meta = CITY_META.get(city) or CITY_META.get(normalize_city(city) or "")
        if meta and meta.get("coord"):
            return list(meta["coord"])
        return None
    return coord_of_adcode(city_adcode(code))


def city_coords_map() -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for name, meta in CITY_META.items():
        full = str(meta.get("fullname") or "")
        if full.endswith("市") and name == full:
            continue
        out[name] = list(meta["coord"])
    return out


def resolve_location(
    *,
    province: Optional[str] = None,
    city: Optional[str] = None,
    district: Optional[str] = None,
    province_adcode_v: Optional[str] = None,
    city_adcode_v: Optional[str] = None,
    district_adcode_v: Optional[str] = None,
    text: str = "",
    entity_type: str = "",
    seed: Any = None,
) -> Dict[str, str]:
    """兼容旧返回；同时含 adcode 字段。"""
    return resolve_to_adcodes(
        province=province,
        city=city,
        district=district,
        province_adcode_v=province_adcode_v,
        city_adcode_v=city_adcode_v,
        district_adcode_v=district_adcode_v,
        text=text,
        entity_type=entity_type,
        seed=seed,
    )


def _stable_pick(seed: Any, pool: List[str]) -> str:
    raw = str(seed if seed is not None else "0").encode("utf-8")
    h = int(hashlib.md5(raw).hexdigest(), 16)
    return pool[h % len(pool)]


_load()

# 导出 CASE_ALIASES 供测试/兼容
CASE_ALIASES = {"江城": "武汉", "江城市": "武汉"}
