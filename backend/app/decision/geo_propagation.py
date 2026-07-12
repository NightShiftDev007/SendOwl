"""
城际传播飞线：人设 leaf adcode + span；视图层上卷。

逻辑主键一律 adcode；名称仅展示。旧人设无码时在解析边界回填一次。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.world.china_location import (
    BY_ADCODE,
    HUB_ADCODE,
    city_adcode,
    coord_of_adcode,
    enrich_profile_location,
    leaf_adcode_from_fields,
    meta_of_adcode,
    province_adcode,
    same_city,
    span_between,
)

MAPPING_NOTE = (
    "真实地理：人设省市区名称+adcode；飞线存最细 adcode，全国视图上卷到市；"
    "默认案例枢纽为北京；缺字段时解析回填"
)

PROPAGATION_TYPES = {
    "REPOST",
    "QUOTE_POST",
    "QUOTE",
    "CREATE_COMMENT",
    "COMMENT",
    "REPLY_TO_POST",
    "REPLY",
    "LIKE_POST",
    "LIKE",
}


def load_profiles(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    seen_ids = set()
    for path in paths:
        if not path or not Path(path).exists():
            continue
        p = Path(path)
        try:
            if p.suffix.lower() == ".json":
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for row in data:
                        if not isinstance(row, dict):
                            continue
                        uid = row.get("user_id")
                        if uid is not None and uid in seen_ids:
                            continue
                        if uid is not None:
                            seen_ids.add(uid)
                        profiles.append(row)
            elif p.suffix.lower() == ".csv":
                import csv

                with p.open(encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            uid = int(row.get("user_id"))
                        except Exception:
                            continue
                        if uid in seen_ids:
                            continue
                        seen_ids.add(uid)
                        profiles.append(
                            {
                                "user_id": uid,
                                "name": row.get("name") or "",
                                "username": row.get("username") or "",
                                "bio": row.get("description") or row.get("user_char") or "",
                                "persona": row.get("user_char") or "",
                                "province": row.get("province") or "",
                                "city": row.get("city") or "",
                                "district": row.get("district") or "",
                                "province_adcode": row.get("province_adcode") or "",
                                "city_adcode": row.get("city_adcode") or "",
                                "district_adcode": row.get("district_adcode") or "",
                            }
                        )
        except Exception:
            continue
    return profiles


def discover_profile_paths(
    run_dir: Optional[str | Path], shared_dir: Optional[str | Path] = None
) -> List[Path]:
    paths: List[Path] = []
    for base in (shared_dir, run_dir):
        if not base:
            continue
        d = Path(base)
        for name in ("reddit_profiles.json", "twitter_profiles.csv"):
            p = d / name
            if p.exists():
                paths.append(p)
    return paths


def assign_agent_adcodes(profiles: List[Dict[str, Any]]) -> Dict[int, str]:
    """user_id → leaf adcode。"""
    out: Dict[int, str] = {}
    name_to_adcode: Dict[str, str] = {}
    for p in profiles:
        enrich_profile_location(p)
        uid = p.get("user_id")
        if uid is None:
            continue
        try:
            uid = int(uid)
        except Exception:
            continue
        leaf = leaf_adcode_from_fields(
            province_adcode_v=p.get("province_adcode"),
            city_adcode_v=p.get("city_adcode"),
            district_adcode_v=p.get("district_adcode"),
        )
        if not leaf:
            continue
        out[uid] = leaf
        for key in ("name", "username", "user_name"):
            n = (p.get(key) or "").strip()
            if n:
                name_to_adcode[n] = leaf
                name_to_adcode[n.lower()] = leaf
    assign_agent_adcodes._name_to_adcode = name_to_adcode  # type: ignore[attr-defined]
    return out


# 兼容旧名
def assign_agent_cities(profiles: List[Dict[str, Any]]) -> Dict[int, str]:
    return assign_agent_adcodes(profiles)


def _resolve_adcode(
    agent_id: Any,
    agent_name: str,
    agent_adcode: Dict[int, str],
    name_to_adcode: Dict[str, str],
) -> Optional[str]:
    if agent_id is not None:
        try:
            aid = int(agent_id)
            if aid in agent_adcode:
                return agent_adcode[aid]
        except Exception:
            pass
    name = (agent_name or "").strip()
    if name and name in name_to_adcode:
        return name_to_adcode[name]
    if name and name.lower() in name_to_adcode:
        return name_to_adcode[name.lower()]
    from app.world.china_location import extract_adcode_from_text

    code = extract_adcode_from_text(name)
    if code and code in BY_ADCODE:
        return code
    return None


def _iter_raw_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for a in actions:
        if a.get("event_type") in (
            "round_start",
            "round_end",
            "simulation_start",
            "simulation_end",
        ):
            continue
        if a.get("agents_count") is not None and a.get("action_type") is None:
            continue
        at = a.get("action_type") or a.get("action") or a.get("type")
        if hasattr(at, "name"):
            at = at.name
        if not at:
            continue
        out.append(a)
    return out


def _node_from_adcode(adcode: str, value: int = 1) -> Optional[Dict[str, Any]]:
    meta = meta_of_adcode(adcode)
    if not meta:
        return None
    coord = coord_of_adcode(adcode)
    if not coord:
        return None
    lv = int(meta.get("level") or 0)
    level = {1: "province", 2: "city", 3: "district"}.get(lv, "city")
    if meta.get("is_municipality"):
        level = "province_muni"
    pac = province_adcode(adcode)
    cac = city_adcode(adcode)
    return {
        "adcode": adcode,
        "level": level,
        "name": meta.get("name") or "",
        "fullname": meta.get("fullname") or meta.get("name") or "",
        "province_adcode": pac,
        "city_adcode": cac,
        "province": (meta_of_adcode(pac) or {}).get("fullname") or "",
        "city": (meta_of_adcode(cac) or {}).get("fullname") or "",
        "coord": coord,
        "value": int(value),
        # 兼容旧前端
        "name_legacy": meta.get("name") or "",
    }


def extract_edges(
    actions: List[Dict[str, Any]],
    agent_adcode: Dict[int, str],
    name_to_adcode: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    name_to_adcode = name_to_adcode or getattr(assign_agent_adcodes, "_name_to_adcode", {}) or {}
    post_author: Dict[Any, Tuple[Any, str]] = {}
    activity: Counter = Counter()
    edge_counter: Counter = Counter()

    raw = _iter_raw_actions(actions)
    for a in raw:
        aid = a.get("agent_id") if a.get("agent_id") is not None else a.get("user_id")
        aname = a.get("agent_name") or a.get("username") or a.get("name") or ""
        code = _resolve_adcode(aid, aname, agent_adcode, name_to_adcode)
        if code:
            activity[code] += 1
        pid = a.get("post_id")
        args = a.get("action_args") if isinstance(a.get("action_args"), dict) else {}
        new_pid = args.get("new_post_id") or pid
        if new_pid is not None and aid is not None:
            post_author[new_pid] = (aid, aname)
        if pid is not None and aid is not None and str(a.get("action_type") or "").upper() in (
            "CREATE_POST",
            "CREATE_COMMENT",
        ):
            post_author[pid] = (aid, aname)

    for a in raw:
        at = str(a.get("action_type") or a.get("action") or "").upper()
        if at not in PROPAGATION_TYPES:
            continue
        aid = a.get("agent_id") if a.get("agent_id") is not None else a.get("user_id")
        aname = a.get("agent_name") or a.get("username") or a.get("name") or ""
        # 传播方向：origin(源) → actor(当前动作方)
        to_code = _resolve_adcode(aid, aname, agent_adcode, name_to_adcode)
        if not to_code:
            continue

        args = a.get("action_args") if isinstance(a.get("action_args"), dict) else {}
        origin_name = args.get("original_author_name") or a.get("original_author_name") or ""
        origin_id = args.get("original_author_id") or a.get("original_author_id")
        parent_pid = (
            a.get("parent_post_id")
            or a.get("original_post_id")
            or args.get("quoted_id")
            or args.get("original_post_id")
        )
        if origin_id is None and parent_pid is not None and parent_pid in post_author:
            origin_id, origin_name = post_author[parent_pid]

        from_code = _resolve_adcode(origin_id, origin_name, agent_adcode, name_to_adcode)
        if not from_code:
            from_code = HUB_ADCODE if HUB_ADCODE in BY_ADCODE else to_code

        if from_code == to_code:
            continue
        edge_counter[(from_code, to_code)] += 1

    lines = []
    for (a, b), c in sorted(edge_counter.items(), key=lambda x: -x[1]):
        lines.append(
            {
                "from": a,
                "to": b,
                "span": span_between(a, b),
                "count": int(c),
            }
        )

    nodes: List[Dict[str, Any]] = []
    for adcode, value in activity.most_common():
        node = _node_from_adcode(adcode, value)
        if node:
            nodes.append(node)
    present = {n["adcode"] for n in nodes}
    for line in lines:
        for key in ("from", "to"):
            code = line[key]
            if code not in present:
                node = _node_from_adcode(code, 1)
                if node:
                    nodes.append(node)
                    present.add(code)

    # 兼容旧字段 cities（用展示名，但新前端应读 nodes）
    cities = [
        {
            "name": n["name"] or n["fullname"],
            "adcode": n["adcode"],
            "value": n["value"],
            "coord": n["coord"],
        }
        for n in nodes
    ]
    return lines, nodes, cities


def merge_geo_payloads(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    edge_counter: Counter = Counter()
    node_value: Counter = Counter()
    for part in parts:
        for line in part.get("lines") or []:
            a, b = line["from"], line["to"]
            # 若旧数据是城市名，尝试不合并进新逻辑（跳过非数字）
            if not str(a).isdigit() or not str(b).isdigit():
                continue
            edge_counter[(a, b)] += int(line.get("count") or 0)
        for node in part.get("nodes") or []:
            code = node.get("adcode")
            if code:
                node_value[code] += int(node.get("value") or 0)
        # 旧 cities 带 adcode
        for city in part.get("cities") or []:
            code = city.get("adcode")
            if code and str(code).isdigit():
                node_value[str(code)] += int(city.get("value") or 0)

    lines = [
        {"from": a, "to": b, "span": span_between(a, b), "count": int(c)}
        for (a, b), c in sorted(edge_counter.items(), key=lambda x: -x[1])
    ]
    nodes = []
    for adcode, value in node_value.most_common():
        node = _node_from_adcode(adcode, value)
        if node:
            nodes.append(node)
    cities = [
        {
            "name": n["name"] or n["fullname"],
            "adcode": n["adcode"],
            "value": n["value"],
            "coord": n["coord"],
        }
        for n in nodes
    ]
    return {
        "nodes": nodes,
        "cities": cities,
        "lines": lines,
        "mapping_note": MAPPING_NOTE,
    }


def build_geo_propagation(
    actions: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    agent_adcode = assign_agent_adcodes(profiles)
    name_to_adcode = getattr(assign_agent_adcodes, "_name_to_adcode", {}) or {}
    for a in _iter_raw_actions(actions):
        aid = a.get("agent_id") if a.get("agent_id") is not None else a.get("user_id")
        aname = a.get("agent_name") or ""
        if aid is None:
            continue
        try:
            aid = int(aid)
        except Exception:
            continue
        if aid not in agent_adcode:
            from app.world.china_location import extract_adcode_from_text, resolve_to_adcodes

            code = extract_adcode_from_text(aname)
            if not code:
                loc = resolve_to_adcodes(text=aname, seed=aid)
                code = leaf_adcode_from_fields(
                    province_adcode_v=loc.get("province_adcode"),
                    city_adcode_v=loc.get("city_adcode"),
                    district_adcode_v=loc.get("district_adcode"),
                )
            if code and code in BY_ADCODE:
                agent_adcode[aid] = code
                if aname:
                    name_to_adcode[aname] = code

    lines, nodes, cities = extract_edges(actions, agent_adcode, name_to_adcode)
    return {
        "nodes": nodes,
        "cities": cities,
        "lines": lines,
        "mapping_note": MAPPING_NOTE,
        "agent_city_count": len(agent_adcode),
    }


def load_actions_prefer_jsonl(run_dir: str | Path) -> List[Dict[str, Any]]:
    d = Path(run_dir)
    candidates = [
        d / "actions.jsonl",
        d / "twitter" / "actions.jsonl",
        d / "reddit" / "actions.jsonl",
    ]
    for p in candidates:
        if not p.exists():
            continue
        rows = []
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if rows:
            return rows
    try:
        from app.decision.metrics_service import _load_actions_from_run_dir

        actions, _ = _load_actions_from_run_dir(run_dir)
        return actions
    except Exception:
        return []


def build_geo_for_scenario_runs(
    run_dirs: List[str],
    shared_dir: Optional[str] = None,
) -> Dict[str, Any]:
    parts = []
    for rd in run_dirs:
        if not rd or not Path(rd).is_dir():
            continue
        profiles = load_profiles(discover_profile_paths(rd, shared_dir))
        actions = load_actions_prefer_jsonl(rd)
        if not actions and not profiles:
            continue
        parts.append(build_geo_propagation(actions, profiles))
    if not parts:
        if shared_dir:
            profiles = load_profiles(discover_profile_paths(None, shared_dir))
            if profiles:
                agent_adcode = assign_agent_adcodes(profiles)
                counts: Counter = Counter(agent_adcode.values())
                nodes = []
                for code, value in counts.most_common():
                    node = _node_from_adcode(code, value)
                    if node:
                        nodes.append(node)
                cities = [
                    {
                        "name": n["name"] or n["fullname"],
                        "adcode": n["adcode"],
                        "value": n["value"],
                        "coord": n["coord"],
                    }
                    for n in nodes
                ]
                return {
                    "nodes": nodes,
                    "cities": cities,
                    "lines": [],
                    "mapping_note": MAPPING_NOTE,
                }
        return {"nodes": [], "cities": [], "lines": [], "mapping_note": MAPPING_NOTE}
    return merge_geo_payloads(parts)


# —— 视图上卷（也可供前端复用逻辑的服务端辅助；前端自行实现） ——

def rollup_lines_for_view(
    lines: List[Dict[str, Any]],
    *,
    view: str = "nation",
    focus_adcode: str = "",
) -> List[Dict[str, Any]]:
    """
    view: nation | province | city
    返回上卷后的 from/to（仍带 span/count 合并）。
    """
    focus = str(focus_adcode or "").strip()
    merged: Counter = Counter()
    for line in lines:
        a, b = line.get("from"), line.get("to")
        if not a or not b:
            continue
        span = line.get("span") or span_between(a, b)
        count = int(line.get("count") or 1)

        if view == "nation":
            if span == "intra_city":
                continue
            fa, fb = city_adcode(a), city_adcode(b)
        elif view == "province":
            if focus and not (
                province_adcode(a) == focus or province_adcode(b) == focus
            ):
                continue
            if span == "intra_city":
                fa, fb = a, b
            else:
                fa, fb = city_adcode(a), city_adcode(b)
        else:  # city / district view
            if focus:
                if not (same_city(a, focus) and same_city(b, focus)):
                    continue
            fa, fb = a, b

        if not fa or not fb or fa == fb:
            continue
        merged[(fa, fb, span_between(fa, fb))] += count

    out = [
        {"from": a, "to": b, "span": sp, "count": int(c)}
        for (a, b, sp), c in sorted(merged.items(), key=lambda x: -x[1])
    ]
    return out
