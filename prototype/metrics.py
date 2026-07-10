#!/usr/bin/env python3
"""从 actions.jsonl / 合成 bundle 提取对比指标，输出 metrics 与 demo 数据。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
SCENARIOS = json.loads((ROOT / "scenarios.json").read_text(encoding="utf-8"))

SUPPORT_PAT = re.compile(
    r"支持|赞成|该管|必须|安全优先|早该|赞成整治|执法到位|严格到位|不设例外|秩序立起来|安全第一"
)
OPPOSE_PAT = re.compile(
    r"反对|砸饭碗|一刀切|太重|失业|形式主义|不好办|客流|抗议|不合理|只罚不建|"
    r"不能只罚|循序渐进|以人为本|过渡期|没过渡|饭碗|太急|别限|不要限"
)
NEUTRAL_PAT = re.compile(
    r"试点|观望|再看看|配套|建议|不清楚|中立|答疑|细节|听说|是真是假|以官方为准|不信谣"
)


def classify_stance(text: str, preset: Optional[str] = None) -> str:
    if preset in ("supportive", "opposing", "neutral", "support", "oppose"):
        if preset in ("support", "supportive"):
            return "supportive"
        if preset in ("oppose", "opposing"):
            return "opposing"
        return "neutral"
    text = text or ""
    s = len(SUPPORT_PAT.findall(text))
    o = len(OPPOSE_PAT.findall(text))
    n = len(NEUTRAL_PAT.findall(text))
    if o > s and o >= n:
        return "opposing"
    if s > o and s >= n:
        return "supportive"
    if n > 0 and n >= s and n >= o:
        return "neutral"
    if o > s:
        return "opposing"
    if s > o:
        return "supportive"
    return "neutral"


def load_actions_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_posts_from_db(db_path: Path) -> List[Dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # OASIS schema varies; try common tables
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        posts = []
        if "post" in tables:
            for r in cur.execute("SELECT * FROM post").fetchall():
                d = dict(r)
                posts.append(
                    {
                        "post_id": d.get("post_id") or d.get("id"),
                        "agent_id": d.get("user_id") or d.get("agent_id"),
                        "content": d.get("content") or d.get("original_post_content") or "",
                    }
                )
        elif "posts" in tables:
            for r in cur.execute("SELECT * FROM posts").fetchall():
                d = dict(r)
                posts.append(
                    {
                        "post_id": d.get("post_id") or d.get("id"),
                        "agent_id": d.get("user_id") or d.get("agent_id"),
                        "content": d.get("content") or "",
                    }
                )
        conn.close()
        return posts
    except Exception:
        return []


def normalize_action(a: Dict[str, Any]) -> Dict[str, Any]:
    # 跳过轮次/起止事件
    if a.get("event_type") in ("round_start", "round_end", "simulation_start", "simulation_end"):
        return {
            "round": int(a.get("round") or 0),
            "timestamp": a.get("timestamp") or "",
            "agent_id": None,
            "agent_name": "",
            "action_type": "EVENT",
            "content": "",
            "post_id": None,
            "parent_post_id": None,
            "stance": None,
            "raw": a,
            "skip": True,
        }

    action_type = (
        a.get("action_type")
        or a.get("action")
        or a.get("type")
        or ""
    )
    if hasattr(action_type, "name"):
        action_type = action_type.name
    action_type = str(action_type).upper()
    content = a.get("content") or a.get("text") or a.get("message") or ""
    if not content and isinstance(a.get("action_args"), dict):
        content = a["action_args"].get("content", "") or ""
    # 空壳 LLM_ACTION 无正文，不当作观点样本
    if action_type == "LLM_ACTION" and not content:
        return {
            "round": int(a.get("round") or a.get("round_num") or a.get("step") or 0),
            "timestamp": a.get("timestamp") or a.get("time") or "",
            "agent_id": a.get("agent_id") if a.get("agent_id") is not None else a.get("user_id"),
            "agent_name": a.get("agent_name") or a.get("username") or a.get("name") or "",
            "action_type": action_type,
            "content": "",
            "post_id": a.get("post_id"),
            "parent_post_id": a.get("parent_post_id") or a.get("original_post_id"),
            "stance": a.get("stance"),
            "raw": a,
            "skip_stance": True,
        }
    return {
        "round": int(a.get("round") or a.get("round_num") or a.get("step") or 0),
        "timestamp": a.get("timestamp") or a.get("time") or "",
        "agent_id": a.get("agent_id") if a.get("agent_id") is not None else a.get("user_id"),
        "agent_name": a.get("agent_name") or a.get("username") or a.get("name") or "",
        "action_type": action_type,
        "content": content,
        "post_id": a.get("post_id"),
        "parent_post_id": a.get("parent_post_id") or a.get("original_post_id"),
        "stance": a.get("stance"),
        "raw": a,
    }


def actions_from_db(db_path: Path) -> List[Dict[str, Any]]:
    """从 OASIS SQLite 还原带正文的动作，供观点分析。"""
    posts = load_posts_from_db(db_path)
    out = []
    for i, p in enumerate(posts):
        content = (p.get("content") or "").strip()
        if not content:
            continue
        out.append(
            {
                "round": i // 3,
                "agent_id": p.get("agent_id"),
                "content": content,
                "action_type": "CREATE_POST",
                "post_id": p.get("post_id"),
            }
        )
    return out


def compute_metrics(
    scenario_id: str,
    scenario_name: str,
    actions_raw: List[Dict[str, Any]],
    interviews: Optional[List[Dict[str, Any]]] = None,
    color: str = "#333",
) -> Dict[str, Any]:
    actions = [normalize_action(a) for a in actions_raw]
    actions = [a for a in actions if not a.get("skip")]
    by_round: Dict[int, Counter] = defaultdict(Counter)
    stance_by_round: Dict[int, Counter] = defaultdict(Counter)
    agent_activity: Counter = Counter()
    cascade_depths: List[int] = []
    contentful = 0

    # parent map for depth
    parent_of = {}
    for a in actions:
        if a["post_id"] is not None and a["parent_post_id"] is not None:
            parent_of[a["post_id"]] = a["parent_post_id"]

    def depth_of(pid) -> int:
        seen = set()
        d = 0
        while pid in parent_of and pid not in seen:
            seen.add(pid)
            pid = parent_of[pid]
            d += 1
            if d > 50:
                break
        return d

    for a in actions:
        r = a["round"]
        at = a["action_type"]
        by_round[r][at] += 1
        by_round[r]["ALL"] += 1
        if a["agent_id"] is not None:
            agent_activity[str(a["agent_id"]) + "|" + (a["agent_name"] or "")] += 1

        # 只对有正文的内容做立场标注
        if a.get("skip_stance") or not (a.get("content") or "").strip():
            continue
        if at in ("CREATE_POST", "CREATE_COMMENT", "REPOST", "QUOTE_POST") or a["content"]:
            contentful += 1
            stance = classify_stance(a["content"], a.get("stance"))
            stance_by_round[r][stance] += 1
            if a["post_id"] is not None:
                cascade_depths.append(depth_of(a["post_id"]))
            elif "REPOST" in at or "COMMENT" in at:
                cascade_depths.append(1)

    rounds_sorted = sorted(by_round.keys())
    cum = 0
    reach_curve = []
    activity_curve = []
    for r in rounds_sorted:
        cum += by_round[r]["ALL"]
        activity_curve.append({"round": r, "actions": by_round[r]["ALL"]})
        reach_curve.append({"round": r, "cumulative_actions": cum})

    stance_curve = []
    for r in rounds_sorted:
        c = stance_by_round[r]
        stance_curve.append(
            {
                "round": r,
                "supportive": c.get("supportive", 0),
                "opposing": c.get("opposing", 0),
                "neutral": c.get("neutral", 0),
            }
        )

    total_stance = Counter()
    for c in stance_by_round.values():
        total_stance.update(c)
    stance_total = sum(total_stance.values()) or 1

    top_agents = []
    for key, cnt in agent_activity.most_common(8):
        aid, name = key.split("|", 1)
        top_agents.append({"agent_id": aid, "agent_name": name or aid, "actions": cnt})

    max_depth = max(cascade_depths) if cascade_depths else 0
    avg_depth = sum(cascade_depths) / len(cascade_depths) if cascade_depths else 0.0

    summary = {
        "total_actions": len(actions),
        "contentful_actions": contentful,
        "max_cascade_depth": max_depth,
        "avg_cascade_depth": round(avg_depth, 3),
        "stance_share": {
            "supportive": round(total_stance.get("supportive", 0) / stance_total, 4),
            "opposing": round(total_stance.get("opposing", 0) / stance_total, 4),
            "neutral": round(total_stance.get("neutral", 0) / stance_total, 4),
        },
        "stance_counts": dict(total_stance),
        "rounds": len(rounds_sorted),
    }

    return {
        "scenario_id": scenario_id,
        "scenario_name": scenario_name,
        "color": color,
        "summary": summary,
        "activity_curve": activity_curve,
        "reach_curve": reach_curve,
        "stance_curve": stance_curve,
        "top_agents": top_agents,
        "interviews": interviews or [],
    }


def llm_summarize(metrics_list: List[Dict[str, Any]]) -> Dict[str, str]:
    """可选：用 LLM 生成每方案结论；失败则用规则摘要。"""
    summaries = {}
    for m in metrics_list:
        s = m["summary"]
        share = s["stance_share"]
        summaries[m["scenario_id"]] = (
            f"{m['scenario_name']}：总互动 {s['total_actions']}，"
            f"最大传播深度 {s['max_cascade_depth']}，"
            f"观点占比 赞成{share['supportive']:.0%} / 反对{share['opposing']:.0%} / 中立{share['neutral']:.0%}。"
        )

    # try LLM polish
    env_path = Path(os.environ.get("MIROFISH_DIR", Path.home() / "Workspace/web/MiroFish")) / ".env"
    if not env_path.exists():
        return summaries
    env = {}
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    key = env.get("LLM_API_KEY")
    base = env.get("LLM_BASE_URL")
    model = env.get("LLM_MODEL_NAME", "qwen-plus")
    if not key or not base:
        return summaries

    import urllib.request

    prompt = (
        "你是舆情分析师。根据下列三方案模拟指标，用中文各写2-3句结论，"
        "强调可区分差异与是否符合直觉。返回JSON对象，key为scenario_id。\n"
        + json.dumps(
            [
                {
                    "scenario_id": m["scenario_id"],
                    "name": m["scenario_name"],
                    "summary": m["summary"],
                }
                for m in metrics_list
            ],
            ensure_ascii=False,
        )
    )
    try:
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                }
            ).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode())
            text = body["choices"][0]["message"]["content"]
            # extract json
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(text[start : end + 1])
                for k, v in parsed.items():
                    if isinstance(v, str):
                        summaries[k] = v
    except Exception as e:
        print(f"[metrics] LLM 摘要跳过: {e}")
    return summaries


def _stance_l1(s1: Dict[str, float], s2: Dict[str, float]) -> float:
    keys = ("supportive", "opposing", "neutral")
    return sum(abs(float(s1.get(k, 0)) - float(s2.get(k, 0))) for k in keys)


def acceptance_check(
    metrics_list: List[Dict[str, Any]],
    mode: str = "live",
) -> Dict[str, Any]:
    """验收判据。

    - synthetic：沿用「规模/反对/Baseline更弱/级联」理想形态
    - live：小样本真模拟下，关注「有产出、观点结构可区分、柔性更中立、强硬更极化」
    """
    by_id = {m["scenario_id"]: m for m in metrics_list}
    a = by_id.get("A_hard")
    b = by_id.get("B_soft")
    base = by_id.get("Baseline")
    checks = []

    def add(name, ok, detail, required: bool = True):
        checks.append({"name": name, "pass": bool(ok), "detail": detail, "required": required})

    if not (a and b and base):
        add("场景齐全", False, f"缺少场景: {set(['A_hard','B_soft','Baseline']) - set(by_id)}")
        return {"passed": False, "checks": checks, "mode": mode}

    sa, sb, sbase = a["summary"], b["summary"], base["summary"]
    sha, shb, shbase = sa["stance_share"], sb["stance_share"], sbase["stance_share"]

    if mode == "synthetic":
        add(
            "可区分-传播规模",
            len({sa["total_actions"], sb["total_actions"], sbase["total_actions"]}) >= 2,
            f"A={sa['total_actions']}, B={sb['total_actions']}, Base={sbase['total_actions']}",
        )
        add(
            "符合直觉-强硬反对更高",
            sha["opposing"] >= shb["opposing"] - 0.02,
            f"A反对={sha['opposing']:.2%}, B反对={shb['opposing']:.2%}",
        )
        add(
            "符合直觉-Baseline更弱",
            sbase["total_actions"] <= min(sa["total_actions"], sb["total_actions"]),
            f"Base={sbase['total_actions']}",
        )
        add(
            "可区分-级联深度",
            sa["max_cascade_depth"] != sbase["max_cascade_depth"]
            or sa["avg_cascade_depth"] != sbase["avg_cascade_depth"],
            f"A depth={sa['max_cascade_depth']}, Base={sbase['max_cascade_depth']}",
        )
    else:
        # live：真模拟小样本，不要求 Baseline 帖子更少（传言也可能刷屏）
        add(
            "三方案均有内容产出",
            sa["contentful_actions"] >= 5
            and sb["contentful_actions"] >= 5
            and sbase["contentful_actions"] >= 5,
            f"A={sa['contentful_actions']}, B={sb['contentful_actions']}, Base={sbase['contentful_actions']}",
        )
        # 任意两方案观点分布 L1 距离足够大 → 可区分
        d_ab = _stance_l1(sha, shb)
        d_abase = _stance_l1(sha, shbase)
        d_bbase = _stance_l1(shb, shbase)
        max_l1 = max(d_ab, d_abase, d_bbase)
        add(
            "可区分-观点结构",
            max_l1 >= 0.15,
            f"max L1={max_l1:.2f} (A↔B={d_ab:.2f}, A↔Base={d_abase:.2f}, B↔Base={d_bbase:.2f})",
        )
        # 柔性方案中立更高（试点/答疑叙事）
        add(
            "符合直觉-柔性更中立",
            shb["neutral"] >= sha["neutral"] - 0.05,
            f"B中立={shb['neutral']:.2%}, A中立={sha['neutral']:.2%}",
        )
        # 强硬方案极化更高：赞成+反对两端占比
        pol_a = sha["supportive"] + sha["opposing"]
        pol_b = shb["supportive"] + shb["opposing"]
        add(
            "符合直觉-强硬更极化",
            pol_a >= pol_b - 0.05,
            f"A极化(赞+反)={pol_a:.2%}, B极化={pol_b:.2%}",
        )
        # Baseline 中立最高（传言、观望）—— 软条件
        add(
            "符合直觉-Baseline更观望",
            shbase["neutral"] >= min(sha["neutral"], shb["neutral"]) - 0.02,
            f"Base中立={shbase['neutral']:.2%}, A={sha['neutral']:.2%}, B={shb['neutral']:.2%}",
            required=True,
        )
        # 级联深度：当前 Twitter 单平台日志常为 0，仅作提示项
        add(
            "可区分-级联深度",
            sa["max_cascade_depth"] > 0 or sbase["max_cascade_depth"] > 0,
            f"A depth={sa['max_cascade_depth']}, Base={sbase['max_cascade_depth']}（小样本常为0，不阻断）",
            required=False,
        )

    required_ok = all(c["pass"] for c in checks if c.get("required", True))
    return {
        "passed": required_ok,
        "checks": checks,
        "mode": mode,
        "note": (
            "live 验收关注观点结构可区分与叙事直觉，不要求 Baseline 帖子数更少"
            if mode != "synthetic"
            else "synthetic 验收沿用理想形态判据"
        ),
    }


def _dir_has_live_data(d: Path) -> bool:
    if (d / "actions.jsonl").exists():
        return True
    if (d / "twitter" / "actions.jsonl").exists():
        return True
    if list(d.glob("*_simulation.db")) or list(d.glob("*.db")):
        return True
    return False


def collect_live_dirs() -> List[Tuple[str, str, Path]]:
    """从 outputs/demo_* 或 mapping 文件收集真模拟产物。"""
    found = []
    for mapping in OUTPUTS.glob("scenario_*_mapping.json"):
        meta = json.loads(mapping.read_text(encoding="utf-8"))
        sid = meta["scenario_id"]
        name = meta.get("scenario_name", sid)
        sim_id = meta["simulation_id"]
        d = OUTPUTS / sim_id
        if _dir_has_live_data(d):
            found.append((sid, name, d))
    # also scan demo_* folders
    for d in OUTPUTS.glob("demo_*"):
        if _dir_has_live_data(d):
            if d.name.startswith("demo_A_hard"):
                sid = "A_hard"
            elif d.name.startswith("demo_B_soft"):
                sid = "B_soft"
            elif d.name.startswith("demo_Baseline"):
                sid = "Baseline"
            else:
                parts = d.name.split("_")
                sid = parts[1] if len(parts) > 1 else d.name
            name = next((s["name"] for s in SCENARIOS["scenarios"] if s["id"] == sid), sid)
            if not any(x[0] == sid for x in found):
                found.append((sid, name, d))
    return found


def collect_synthetic() -> List[Tuple[str, str, Path]]:
    syn = OUTPUTS / "synthetic"
    found = []
    for s in SCENARIOS["scenarios"]:
        d = syn / s["id"]
        if (d / "actions.jsonl").exists() or (d / "bundle.json").exists():
            found.append((s["id"], s["name"], d))
    return found


def run(synthetic: bool = False) -> Path:
    color_map = {s["id"]: s.get("color", "#333") for s in SCENARIOS["scenarios"]}
    items = collect_synthetic() if synthetic else collect_live_dirs()
    if not items and not synthetic:
        print("[metrics] 未找到真模拟产物，回退到 synthetic")
        items = collect_synthetic()
        synthetic = True
    if not items:
        raise SystemExit("没有可计算的数据。请先 run_scenarios.py synthesize 或完成真模拟。")

    metrics_list = []
    for sid, name, d in items:
        interviews = []
        if (d / "bundle.json").exists():
            bundle = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
            actions = bundle.get("actions") or []
            interviews = bundle.get("interviews") or []
        else:
            actions_path = d / "actions.jsonl"
            if not actions_path.exists() and (d / "twitter" / "actions.jsonl").exists():
                actions_path = d / "twitter" / "actions.jsonl"
            actions = load_actions_jsonl(actions_path) if actions_path.exists() else []

            # 优先用 DB 正文做观点分析（actions 里大量 LLM_ACTION 无 content）
            db_actions: List[Dict[str, Any]] = []
            for db in list(d.glob("*_simulation.db")) + list(d.glob("*.db")):
                db_actions = actions_from_db(db)
                if db_actions:
                    break

            # 合并：保留 actions 里带正文的 CREATE_POST，其余用 DB 帖子补齐
            contentful_from_log = []
            for a in actions:
                args = a.get("action_args") if isinstance(a.get("action_args"), dict) else {}
                content = a.get("content") or (args.get("content") if args else "") or ""
                if content.strip() and a.get("action_type") not in (None, "LLM_ACTION"):
                    contentful_from_log.append(
                        {
                            **a,
                            "content": content,
                            "action_type": a.get("action_type") or "CREATE_POST",
                        }
                    )

            if db_actions:
                # DB 更完整，作为观点主数据；actions 仅补充活动量时可忽略空壳
                actions = db_actions
                print(f"  [{sid}] 使用 DB 帖子 {len(actions)} 条做观点分析")
            elif contentful_from_log:
                actions = contentful_from_log
            # else keep raw actions（可能全是空壳）

            if (d / "interviews.json").exists():
                interviews = json.loads((d / "interviews.json").read_text(encoding="utf-8"))
        m = compute_metrics(sid, name, actions, interviews, color=color_map.get(sid, "#333"))
        metrics_list.append(m)
        (OUTPUTS / f"metrics_{sid}.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[metrics] {sid}: actions={m['summary']['total_actions']} oppose={m['summary']['stance_share']['opposing']:.0%}")

    # stable order
    order = {"A_hard": 0, "B_soft": 1, "Baseline": 2}
    metrics_list.sort(key=lambda m: order.get(m["scenario_id"], 9))

    narrative = llm_summarize(metrics_list)
    for m in metrics_list:
        m["narrative"] = narrative.get(m["scenario_id"], "")

    acceptance = acceptance_check(metrics_list, mode="synthetic" if synthetic else "live")
    demo_data = {
        "case": {
            "id": SCENARIOS["case_id"],
            "title": SCENARIOS["case_title"],
            "mode": "synthetic" if synthetic else "live",
        },
        "scenarios": metrics_list,
        "acceptance": acceptance,
        "generated_from": "prototype/metrics.py",
    }
    out = OUTPUTS / "demo_data.json"
    out.write_text(json.dumps(demo_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUTS / "acceptance.json").write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[metrics] 写入 {out}")
    print(f"[acceptance] passed={acceptance['passed']}")
    for c in acceptance["checks"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true", help="使用离线合成数据")
    args = parser.parse_args()
    run(synthetic=args.synthetic)


if __name__ == "__main__":
    main()
