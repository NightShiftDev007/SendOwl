#!/usr/bin/env python3
"""
多方案编排脚本：同一共享世界 + 不同 initial_posts → 顺序跑 MiroFish 模拟。

用法：
  # 1) 先通过 MiroFish UI/API 建好项目与模拟（prepare 完成），记下 simulation_id
  # 2) 导出共享世界到 prototype/shared/
  python prototype/run_scenarios.py export --simulation-id sim_xxxx

  # 3) 为三方案创建副本、patch 干预并启动
  python prototype/run_scenarios.py run-all --base-simulation-id sim_xxxx

  # 离线演示（无 Zep/不跑真模拟）：
  python prototype/run_scenarios.py synthesize
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
SCENARIOS_PATH = ROOT / "scenarios.json"
SHARED_DIR = ROOT / "shared"
OUTPUTS_DIR = ROOT / "outputs"
MIROFISH_DIR = Path(os.environ.get("MIROFISH_DIR", Path.home() / "Workspace/web/MiroFish"))
MIROFISH_API = os.environ.get("MIROFISH_API", "http://localhost:5001").rstrip("/")
SIM_DATA_DIR = MIROFISH_DIR / "backend" / "uploads" / "simulations"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_scenarios() -> Dict[str, Any]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def http_json(method: str, path: str, body: Optional[dict] = None, timeout: int = 60) -> dict:
    url = f"{MIROFISH_API}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"无法连接 MiroFish API ({MIROFISH_API}). 请先在 MiroFish 目录执行 npm run backend"
        ) from e


def sim_dir(simulation_id: str) -> Path:
    return SIM_DATA_DIR / simulation_id


def require_prepared(simulation_id: str) -> Path:
    d = sim_dir(simulation_id)
    required = ["simulation_config.json", "twitter_profiles.csv", "state.json"]
    missing = [f for f in required if not (d / f).exists()]
    if missing:
        # reddit_profiles optional if twitter-only
        if "twitter_profiles.csv" in missing and (d / "reddit_profiles.json").exists():
            missing = [f for f in missing if f != "twitter_profiles.csv"]
        if missing:
            raise FileNotFoundError(
                f"模拟 {simulation_id} 未准备完成，缺少: {missing}. 目录: {d}"
            )
    return d


def export_shared(simulation_id: str) -> Path:
    src = require_prepared(simulation_id)
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    dest = SHARED_DIR / "base_simulation"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(
            "actions.jsonl",
            "simulation.log",
            "run_state.json",
            "*.db",
            "ipc",
            "__pycache__",
            "twitter_actions*",
            "reddit_actions*",
        ),
    )
    meta = {
        "exported_at": _utc_now(),
        "source_simulation_id": simulation_id,
        "source_dir": str(src),
    }
    (SHARED_DIR / "export_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[export] 共享世界已导出到 {dest}")
    return dest


def _load_profiles_index(base: Path) -> List[Dict[str, Any]]:
    """从 twitter csv / reddit json 建立 agent 索引，便于按 hint 选 poster。"""
    agents: List[Dict[str, Any]] = []
    csv_path = base / "twitter_profiles.csv"
    json_path = base / "reddit_profiles.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for i, row in enumerate(data):
                agents.append(
                    {
                        "agent_id": int(row.get("user_id", row.get("agent_id", i))),
                        "name": str(row.get("name", row.get("username", f"agent_{i}"))),
                        "username": str(row.get("username", "")),
                        "bio": str(row.get("bio", row.get("persona", "")))[:500],
                        "entity_type": str(row.get("entity_type", row.get("label", ""))),
                    }
                )
    elif csv_path.exists():
        import csv

        with csv_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader):
                agents.append(
                    {
                        "agent_id": int(row.get("user_id", row.get("agent_id", i))),
                        "name": str(row.get("name", row.get("username", f"agent_{i}"))),
                        "username": str(row.get("username", "")),
                        "bio": str(row.get("bio", ""))[:500],
                        "entity_type": str(row.get("description", "")),
                    }
                )
    return agents


def pick_poster_id(agents: List[Dict[str, Any]], hint: str, keywords: List[str]) -> int:
    if not agents:
        return 0
    hint = (hint or "").lower()
    scored: List[tuple] = []
    for a in agents:
        text = f"{a.get('name','')} {a.get('username','')} {a.get('bio','')} {a.get('entity_type','')}".lower()
        score = 0
        if hint == "official":
            for kw in keywords + ["official", "government", "bureau", "局", "政府", "公告"]:
                if kw.lower() in text:
                    score += 3
        elif hint == "citizen":
            for kw in ["市民", "citizen", "通勤", "家长", "商户", "person", "resident"]:
                if kw.lower() in text:
                    score += 2
            # 避免官方
            for kw in ["局", "official", "government"]:
                if kw.lower() in text:
                    score -= 3
        scored.append((score, a["agent_id"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def patch_config_for_scenario(
    config: Dict[str, Any],
    scenario: Dict[str, Any],
    agents: List[Dict[str, Any]],
    keywords: List[str],
) -> Dict[str, Any]:
    cfg = deepcopy(config)
    posts = []
    for p in scenario["initial_posts"]:
        poster_id = pick_poster_id(agents, p.get("poster_hint", "official"), keywords)
        posts.append(
            {
                "content": p["content"],
                "poster_agent_id": poster_id,
                "poster_hint": p.get("poster_hint"),
            }
        )
    cfg.setdefault("event_config", {})
    cfg["event_config"]["initial_posts"] = posts
    cfg["event_config"]["hot_topics"] = [
        "电动自行车限行",
        "江城大道",
        "外卖骑手",
        scenario["name"],
    ]
    cfg["event_config"]["narrative_direction"] = scenario.get("hypothesis", "")
    cfg["_demo_scenario"] = {
        "id": scenario["id"],
        "name": scenario["name"],
        "patched_at": _utc_now(),
    }
    # 缩短 demo 时长：若存在 time_config，压到约 24-36 模拟小时
    if "time_config" in cfg:
        cfg["time_config"]["total_simulation_hours"] = min(
            int(cfg["time_config"].get("total_simulation_hours", 72)), 36
        )
    return cfg


def materialize_scenario_dir(
    base_sim_id: str, scenario: Dict[str, Any], scenarios_doc: Dict[str, Any]
) -> Path:
    src = require_prepared(base_sim_id)
    out_id = f"demo_{scenario['id']}_{base_sim_id}"
    dest = sim_dir(out_id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(
            "actions.jsonl",
            "simulation.log",
            "run_state.json",
            "*.db",
            "ipc",
            "__pycache__",
        ),
    )

    config_path = dest / "simulation_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    agents = _load_profiles_index(dest)
    keywords = scenarios_doc.get("shared_world", {}).get("preferred_poster_keywords", [])
    patched = patch_config_for_scenario(config, scenario, agents, keywords)
    config_path.write_text(json.dumps(patched, ensure_ascii=False, indent=2), encoding="utf-8")

    # 重置 state 为 ready
    state_path = dest / "state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {}
    state["simulation_id"] = out_id
    state["status"] = "ready"
    state["demo_scenario_id"] = scenario["id"]
    state["demo_parent_simulation_id"] = base_sim_id
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    # 记录映射
    mapping = {
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "simulation_id": out_id,
        "parent_simulation_id": base_sim_id,
        "initial_posts": patched["event_config"]["initial_posts"],
        "created_at": _utc_now(),
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / f"scenario_{scenario['id']}_mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[materialize] {scenario['id']} -> {out_id}")
    print(f"  posts: {json.dumps(mapping['initial_posts'], ensure_ascii=False)[:200]}...")
    return dest


def _env_status(simulation_id: str) -> str:
    p = sim_dir(simulation_id) / "env_status.json"
    if not p.exists():
        return ""
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("status") or "")
    except Exception:
        return ""


def _db_post_count(simulation_id: str) -> int:
    dbs = list(sim_dir(simulation_id).glob("*_simulation.db")) + list(
        sim_dir(simulation_id).glob("*.db")
    )
    if not dbs:
        return 0
    import sqlite3

    try:
        conn = sqlite3.connect(str(dbs[0]))
        n = conn.execute("SELECT COUNT(*) FROM post").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0


def _close_env_best_effort(simulation_id: str) -> None:
    try:
        http_json("POST", "/api/simulation/close-env", {"simulation_id": simulation_id}, timeout=30)
        print(f"  [run] 已请求 close-env: {simulation_id}")
    except Exception as e:
        print(f"  [run] close-env 失败（可忽略）: {e}")
    try:
        http_json("POST", "/api/simulation/stop", {"simulation_id": simulation_id}, timeout=30)
    except Exception:
        pass


def _copy_run_artifacts(simulation_id: str) -> Path:
    src = sim_dir(simulation_id)
    out = OUTPUTS_DIR / simulation_id
    out.mkdir(parents=True, exist_ok=True)
    for name in [
        "actions.jsonl",
        "simulation_config.json",
        "state.json",
        "run_state.json",
        "env_status.json",
        "simulation.log",
    ]:
        p = src / name
        if p.exists():
            shutil.copy2(p, out / name)
    twitter_actions = src / "twitter" / "actions.jsonl"
    if twitter_actions.exists():
        (out / "twitter").mkdir(exist_ok=True)
        shutil.copy2(twitter_actions, out / "twitter" / "actions.jsonl")
        # 兼容 metrics.py 根目录 actions.jsonl
        shutil.copy2(twitter_actions, out / "actions.jsonl")
    for db in src.glob("*.db"):
        shutil.copy2(db, out / db.name)
    return out


def start_and_wait(
    simulation_id: str,
    platform: str,
    max_rounds: int,
    poll_sec: int = 10,
    stall_sec: int = 180,
    timeout_sec: int = 45 * 60,
) -> dict:
    print(f"[run] 启动 {simulation_id} platform={platform} max_rounds={max_rounds} no_wait=True")
    started = http_json(
        "POST",
        "/api/simulation/start",
        {
            "simulation_id": simulation_id,
            "platform": platform,
            "max_rounds": max_rounds,
            "force": True,
            "enable_graph_memory_update": False,
            "no_wait": True,  # 关键：避免卡在采访等待模式
        },
    )
    if not started.get("success"):
        raise RuntimeError(f"启动失败: {started}")

    t0 = time.time()
    last_progress_at = t0
    last_round = -1
    last_posts = -1
    runner = "starting"

    while True:
        status = http_json("GET", f"/api/simulation/{simulation_id}/run-status")
        data = status.get("data") or {}
        runner = data.get("runner_status") or data.get("status") or ""
        current_round = data.get("current_round")
        if current_round is None:
            current_round = data.get("twitter_current_round")
        posts = _db_post_count(simulation_id)
        env_st = _env_status(simulation_id)
        elapsed = int(time.time() - t0)
        print(
            f"  ... status={runner} round={current_round} posts={posts} "
            f"env={env_st or '-'} elapsed={elapsed}s"
        )

        # 进度心跳：轮次或帖子数变化则刷新
        try:
            cr = int(current_round) if current_round is not None else -1
        except (TypeError, ValueError):
            cr = -1
        if cr > last_round or posts > last_posts:
            last_round = max(last_round, cr)
            last_posts = max(last_posts, posts)
            last_progress_at = time.time()

        # 正常结束
        if runner in ("completed", "stopped", "failed", "error"):
            break
        if runner == "idle" and (posts > 0 or (sim_dir(simulation_id) / "twitter" / "actions.jsonl").exists()):
            break

        # 进入采访等待模式 = 轮次已结束（兼容旧后端未传 no_wait）
        if env_st == "alive" and (cr >= max_rounds or posts > 0):
            print("  [run] 检测到 env_status=alive（轮次已结束，进入等待模式），自动关闭环境")
            _close_env_best_effort(simulation_id)
            runner = "completed_via_close_env"
            break

        # 无进展超时
        if time.time() - last_progress_at > stall_sec and elapsed > 60:
            print(f"  [run] {stall_sec}s 无进展，判定卡住，尝试关闭并收尾")
            _close_env_best_effort(simulation_id)
            runner = "stalled"
            break

        if time.time() - t0 > timeout_sec:
            _close_env_best_effort(simulation_id)
            raise TimeoutError(f"模拟超时: {simulation_id} ({timeout_sec}s)")

        time.sleep(poll_sec)

    out = _copy_run_artifacts(simulation_id)
    meta = {
        "simulation_id": simulation_id,
        "finished_at": _utc_now(),
        "elapsed_sec": int(time.time() - t0),
        "final_status": runner,
        "posts": _db_post_count(simulation_id),
        "start_response": started.get("data"),
    }
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[run] 完成 {simulation_id} -> {out} ({meta['elapsed_sec']}s, posts={meta['posts']})")
    return meta


def run_all(base_simulation_id: str) -> None:
    doc = load_scenarios()
    defaults = doc.get("run_defaults", {})
    platform = defaults.get("platform", "twitter")
    max_rounds = int(defaults.get("max_rounds", 25))

    results = []
    for scenario in doc["scenarios"]:
        materialize_scenario_dir(base_simulation_id, scenario, doc)
        sim_id = f"demo_{scenario['id']}_{base_simulation_id}"
        # 确保 MiroFish SimulationManager 能发现该目录：若 create API 需要，可再调 create；
        # 多数情况下直接 start 即可（目录+state 已就绪）。
        meta = start_and_wait(sim_id, platform=platform, max_rounds=max_rounds)
        results.append({"scenario_id": scenario["id"], **meta})

    summary = {"finished_at": _utc_now(), "results": results}
    (OUTPUTS_DIR / "run_all_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[run-all] 全部完成。下一步: python prototype/metrics.py")


def synthesize() -> None:
    """生成离线合成 actions，供无 Zep 时演示对比页。"""
    from synthesize_demo_data import generate_all

    generate_all()
    print("[synthesize] 离线数据已生成。下一步: python prototype/metrics.py --synthetic")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 决策中心 Demo · 多方案编排")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="导出共享世界")
    p_export.add_argument("--simulation-id", required=True)

    p_run = sub.add_parser("run-all", help="物化三方案并顺序运行")
    p_run.add_argument("--base-simulation-id", required=True)

    p_one = sub.add_parser("materialize", help="仅物化方案目录，不运行")
    p_one.add_argument("--base-simulation-id", required=True)

    sub.add_parser("synthesize", help="生成离线合成演示数据")

    p_health = sub.add_parser("health", help="检查 MiroFish API / 环境")
    args = parser.parse_args()

    if args.cmd == "export":
        export_shared(args.simulation_id)
    elif args.cmd == "run-all":
        run_all(args.base_simulation_id)
    elif args.cmd == "materialize":
        doc = load_scenarios()
        for scenario in doc["scenarios"]:
            materialize_scenario_dir(args.base_simulation_id, scenario, doc)
    elif args.cmd == "synthesize":
        synthesize()
    elif args.cmd == "health":
        print(f"MIROFISH_DIR={MIROFISH_DIR} exists={MIROFISH_DIR.exists()}")
        print(f"MIROFISH_API={MIROFISH_API}")
        env_path = MIROFISH_DIR / ".env"
        if env_path.exists():
            keys = {
                k: ("set" if v and v != "your_zep_api_key_here" else "EMPTY")
                for k, v in (
                    line.split("=", 1)
                    for line in env_path.read_text().splitlines()
                    if "=" in line and not line.startswith("#")
                )
            }
            print("env:", {k: keys.get(k) for k in ["LLM_API_KEY", "ZEP_API_KEY", "LLM_MODEL_NAME"]})
        try:
            r = http_json("GET", "/api/graph/project/list")
            print("api_ok projects=", r.get("count"))
        except Exception as e:
            print("api_fail:", e)
            sys.exit(1)


if __name__ == "__main__":
    main()
