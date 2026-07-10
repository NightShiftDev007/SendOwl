#!/usr/bin/env python3
"""对运行中的模拟做代表性 Agent 采访，写入 outputs/interviews。

用法：
  python prototype/interview_agents.py --simulation-id demo_A_hard_sim_xxx
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
MIROFISH_API = os.environ.get("MIROFISH_API", "http://localhost:5001").rstrip("/")

QUESTIONS = [
    "你为什么支持或反对这次电动自行车限行政策的发布方式？",
    "如果官方改为试点加补贴，你的态度会变化吗？",
]


def http_json(method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{MIROFISH_API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation-id", required=True)
    parser.add_argument("--agent-ids", default="", help="逗号分隔；默认采访前几个活跃 agent")
    args = parser.parse_args()

    agent_ids = [int(x) for x in args.agent_ids.split(",") if x.strip()]
    if not agent_ids:
        # try agent-stats
        try:
            stats = http_json("GET", f"/api/simulation/{args.simulation_id}/agent-stats")
            rows = (stats.get("data") or {}).get("agents") or stats.get("data") or []
            if isinstance(rows, list) and rows:
                agent_ids = [int(r.get("agent_id", r.get("user_id", i))) for i, r in enumerate(rows[:3])]
        except Exception:
            agent_ids = [0, 2, 6]

    results = []
    for aid in agent_ids:
        for q in QUESTIONS[:1]:
            try:
                resp = http_json(
                    "POST",
                    "/api/simulation/interview",
                    {"simulation_id": args.simulation_id, "agent_id": aid, "prompt": q},
                )
                answer = ((resp.get("data") or {}).get("response")
                          or (resp.get("data") or {}).get("answer")
                          or json.dumps(resp, ensure_ascii=False)[:500])
            except Exception as e:
                answer = f"[interview failed] {e}"
            results.append(
                {
                    "agent_id": aid,
                    "question": q,
                    "answer": answer,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            print(f"agent={aid}: {str(answer)[:120]}...")

    out = OUTPUTS / args.simulation_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "interviews.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out / 'interviews.json'}")


if __name__ == "__main__":
    main()
