#!/usr/bin/env python3
"""通过 MiroFish API 构建共享世界（本体→图谱→prepare）。

需要：
  - MiroFish 后端已启动 (npm run backend)
  - .env 中 LLM_API_KEY 与 ZEP_API_KEY 均有效
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path

import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
CASE_DIR = ROOT / "case"
MIROFISH_API = os.environ.get("MIROFISH_API", "http://localhost:5001").rstrip("/")
REQ_PATH = CASE_DIR / "05_simulation_requirement.md"


def multipart_encode(fields: dict, files: list) -> tuple[bytes, str]:
    boundary = f"----DemoBoundary{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for k, v in fields.items():
        lines.append(f"--{boundary}".encode())
        lines.append(f'Content-Disposition: form-data; name="{k}"'.encode())
        lines.append(b"")
        lines.append(str(v).encode("utf-8"))
    for field_name, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        lines.append(f"--{boundary}".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode()
        )
        lines.append(f"Content-Type: {ctype}".encode())
        lines.append(b"")
        lines.append(content)
    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def http_json(method: str, path: str, body=None, timeout=120, headers=None):
    data = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None and not isinstance(body, (bytes, bytearray)):
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    elif isinstance(body, (bytes, bytearray)):
        data = body
    req = urllib.request.Request(f"{MIROFISH_API}{path}", data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {path}: {e.read().decode('utf-8', errors='replace')}") from e


def main():
    req_text = REQ_PATH.read_text(encoding="utf-8") if REQ_PATH.exists() else (
        "预测江城市电动自行车限行新政不同发布策略下的舆论传播与观点分布"
    )
    files = []
    for p in sorted(CASE_DIR.glob("*.md")):
        if p.name.startswith("05_"):
            continue
        files.append(("files", p.name, p.read_text(encoding="utf-8").encode("utf-8")))
    if not files:
        raise SystemExit("case/ 下没有材料文件")

    print("[1/4] 生成本体...")
    body, ctype = multipart_encode(
        {
            "simulation_requirement": req_text,
            "project_name": "江城市限行新政Demo",
            "additional_context": "虚构案例，用于多方案发布策略对比",
        },
        files,
    )
    ontology_resp = http_json("POST", "/api/graph/ontology/generate", body=body, headers={"Content-Type": ctype}, timeout=900)
    if not ontology_resp.get("success"):
        raise RuntimeError(ontology_resp)
    project_id = ontology_resp["data"]["project_id"]
    print(f"  project_id={project_id}")
    print(f"  entities={len(ontology_resp['data']['ontology'].get('entity_types', []))}")

    print("[2/4] 构建图谱...")
    build_resp = http_json(
        "POST",
        "/api/graph/build",
        {"project_id": project_id, "graph_name": "jiangcheng_ebike_demo"},
        timeout=60,
    )
    if not build_resp.get("success"):
        raise RuntimeError(build_resp)
    task_id = build_resp["data"]["task_id"]
    graph_id = None
    for _ in range(180):
        task = http_json("GET", f"/api/graph/task/{task_id}")
        data = task.get("data") or {}
        status = data.get("status")
        print(f"  task={status} progress={data.get('progress')}")
        if status in ("completed", "success", "done"):
            graph_id = (data.get("result") or {}).get("graph_id") or data.get("graph_id")
            break
        if status in ("failed", "error"):
            raise RuntimeError(data)
        time.sleep(5)
    # fallback: read project
    proj = http_json("GET", f"/api/graph/project/{project_id}")
    graph_id = graph_id or (proj.get("data") or {}).get("graph_id")
    if not graph_id:
        raise RuntimeError(f"图谱构建未拿到 graph_id: {proj}")
    print(f"  graph_id={graph_id}")

    print("[3/4] 创建模拟...")
    create = http_json(
        "POST",
        "/api/simulation/create",
        {
            "project_id": project_id,
            "graph_id": graph_id,
            "enable_twitter": True,
            "enable_reddit": False,
        },
    )
    if not create.get("success"):
        raise RuntimeError(create)
    simulation_id = create["data"]["simulation_id"]
    print(f"  simulation_id={simulation_id}")

    print("[4/4] 准备环境 (profiles + config)...")
    prep = http_json("POST", "/api/simulation/prepare", {"simulation_id": simulation_id}, timeout=60)
    if not prep.get("success"):
        raise RuntimeError(prep)
    for _ in range(240):
        st = http_json("POST", "/api/simulation/prepare/status", {"simulation_id": simulation_id})
        data = st.get("data") or {}
        status = data.get("status") or data.get("prepare_status")
        print(f"  prepare={status} {data.get('message') or data.get('stage') or ''}")
        if status in ("ready", "completed", "success"):
            break
        if status in ("failed", "error"):
            raise RuntimeError(data)
        time.sleep(5)

    meta = {
        "project_id": project_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "api": MIROFISH_API,
    }
    out = ROOT / "shared" / "world_meta.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成。共享世界 simulation_id={simulation_id}")
    print("下一步:")
    print(f"  python prototype/run_scenarios.py export --simulation-id {simulation_id}")
    print(f"  python prototype/run_scenarios.py run-all --base-simulation-id {simulation_id}")
    print(f"  python prototype/metrics.py")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        if "ZEP" in str(e).upper() or "zep" in str(e):
            print("提示: 请在 MiroFish/.env 填入有效 ZEP_API_KEY 后重试。", file=sys.stderr)
        sys.exit(1)
