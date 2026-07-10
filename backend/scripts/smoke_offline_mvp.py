#!/usr/bin/env python3
"""
离线 MVP smoke：不依赖 Zep / OASIS。

流程：
1. 创建本体 + 手写小图谱快照
2. 创建决策（2 方案 + Baseline）
3. 用 prototype 合成 actions 填充假 run 目录并写 metrics
4. build_compare_payload 成功
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app import create_app
from app.config import Config
from app.decision.metrics_service import build_compare_payload, compute_run_metrics
from app.engine.scenario_runner import ScenarioRunner
from app.ontology import registry
from app.ontology.snapshot import register_local_snapshot
from app.ontology.templates import get_template, load_scenarios_template
from app.world.slicer import slice_world


FAKE_GRAPH = {
    "graph_id": "local_fake",
    "nodes": [
        {
            "uuid": "n1",
            "name": "周明远",
            "labels": ["GovernmentOfficial"],
            "summary": "市交管局局长，主张尽快落地限行",
            "attributes": {},
        },
        {
            "uuid": "n2",
            "name": "江城市交管局",
            "labels": ["Organization"],
            "summary": "政策发布与答疑主渠道",
            "attributes": {},
        },
        {
            "uuid": "n3",
            "name": "陈大伟",
            "labels": ["DeliveryRider"],
            "summary": "外卖骑手协会秘书长，反对无过渡期强硬限行",
            "attributes": {},
        },
        {
            "uuid": "n4",
            "name": "阿杰",
            "labels": ["DeliveryRider"],
            "summary": "全职外卖骑手",
            "attributes": {},
        },
        {
            "uuid": "n5",
            "name": "王建国",
            "labels": ["CommuterCitizen"],
            "summary": "私家车通勤族，支持限行",
            "attributes": {},
        },
        {
            "uuid": "n6",
            "name": "孙姐",
            "labels": ["StreetMerchant"],
            "summary": "沿街早餐店老板，担心客流",
            "attributes": {},
        },
        {
            "uuid": "n7",
            "name": "阿凯",
            "labels": ["SelfMedia"],
            "summary": "江城街访自媒体",
            "attributes": {},
        },
        {
            "uuid": "n8",
            "name": "李楠",
            "labels": ["Journalist"],
            "summary": "江城晚报记者",
            "attributes": {},
        },
        {
            "uuid": "n9",
            "name": "张丽",
            "labels": ["StudentParent"],
            "summary": "小学生家长，支持学校周边整治",
            "attributes": {},
        },
        {
            "uuid": "n10",
            "name": "林晓薇",
            "labels": ["ExpertScholar"],
            "summary": "江城大学交通学院副教授",
            "attributes": {},
        },
    ],
    "edges": [
        {
            "uuid": "e1",
            "name": "WORKS_FOR",
            "label": "WORKS_FOR",
            "source_node_uuid": "n1",
            "target_node_uuid": "n2",
        },
        {
            "uuid": "e2",
            "name": "OPPOSES",
            "label": "OPPOSES",
            "source_node_uuid": "n3",
            "target_node_uuid": "n1",
        },
        {
            "uuid": "e3",
            "name": "FOLLOWS",
            "label": "FOLLOWS",
            "source_node_uuid": "n5",
            "target_node_uuid": "n2",
        },
        {
            "uuid": "e4",
            "name": "INFLUENCES",
            "label": "INFLUENCES",
            "source_node_uuid": "n7",
            "target_node_uuid": "n5",
        },
        {
            "uuid": "e5",
            "name": "SUPPORTS",
            "label": "SUPPORTS",
            "source_node_uuid": "n9",
            "target_node_uuid": "n2",
        },
        {
            "uuid": "e6",
            "name": "REPORTS_ON",
            "label": "REPORTS_ON",
            "source_node_uuid": "n8",
            "target_node_uuid": "n2",
        },
        {
            "uuid": "e7",
            "name": "FOLLOWS",
            "label": "FOLLOWS",
            "source_node_uuid": "n4",
            "target_node_uuid": "n3",
        },
        {
            "uuid": "e8",
            "name": "OPPOSES",
            "label": "OPPOSES",
            "source_node_uuid": "n6",
            "target_node_uuid": "n2",
        },
    ],
}


def _copy_synthetic_actions(kind: str, run_dir: Path) -> None:
    """从 prototype 合成数据复制 actions。"""
    syn_root = REPO / "prototype" / "outputs" / "synthetic"
    src = syn_root / kind
    run_dir.mkdir(parents=True, exist_ok=True)
    if (src / "actions.jsonl").exists():
        shutil.copy2(src / "actions.jsonl", run_dir / "actions.jsonl")
    elif (src / "bundle.json").exists():
        bundle = json.loads((src / "bundle.json").read_text(encoding="utf-8"))
        with (run_dir / "actions.jsonl").open("w", encoding="utf-8") as f:
            for a in bundle.get("actions") or []:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
    else:
        # 最小假数据
        fake = [
            {
                "round": 0,
                "agent_id": 0,
                "agent_name": "交管局",
                "action_type": "CREATE_POST",
                "content": "江城限行公告，必须先把秩序立起来。",
                "post_id": 1,
                "stance": "supportive",
            },
            {
                "round": 1,
                "agent_id": 1,
                "agent_name": "陈大伟",
                "action_type": "CREATE_COMMENT",
                "content": "反对一刀切，没过渡期就是砸饭碗。",
                "post_id": 2,
                "parent_post_id": 1,
                "stance": "opposing",
            },
        ]
        with (run_dir / "actions.jsonl").open("w", encoding="utf-8") as f:
            for a in fake:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")


def main() -> int:
    app = create_app()
    registry.init_schema()
    Config.ensure_directories()

    # 1) ontology + fake snapshot
    schema = get_template("opinion")
    ont = registry.create_ontology(
        name="smoke_jiangcheng",
        template="opinion",
        schema=schema,
        schema_locked=True,
        status="ready",
        graph_id="local_fake",
    )
    ver = register_local_snapshot(ont["id"], FAKE_GRAPH, graph_id="local_fake")
    print(f"[smoke] ontology={ont['id']} version={ver['id']} v{ver['version']}")

    # slice sanity
    snap = FAKE_GRAPH
    sliced = slice_world(
        snap,
        intervention_text="江城市交管局限行公告 周明远 骑手",
        k=2,
        use_llm_filter=False,
    )
    assert len(sliced["nodes"]) >= 3, sliced
    print(f"[smoke] slice nodes={len(sliced['nodes'])} edges={len(sliced['edges'])}")

    # 2) decision with 3 scenarios
    scenarios_doc = load_scenarios_template() or {}
    sc_defs = scenarios_doc.get("scenarios") or [
        {
            "id": "A_hard",
            "name": "方案A·强硬发布",
            "color": "#e74c3c",
            "initial_posts": [
                {"content": "强硬限行公告", "poster_hint": "official"}
            ],
        },
        {
            "id": "B_soft",
            "name": "方案B·柔性发布",
            "color": "#27ae60",
            "initial_posts": [
                {"content": "试点+补贴公告", "poster_hint": "official"}
            ],
        },
        {
            "id": "Baseline",
            "name": "Baseline·不正式发布",
            "color": "#7f8c8d",
            "initial_posts": [
                {"content": "听说要限电瓶车？", "poster_hint": "citizen"}
            ],
        },
    ]

    runner = ScenarioRunner()
    created = runner.create_decision(
        ontology_id=ont["id"],
        version_id=ver["id"],
        title="离线 smoke 决策",
        scenarios=[
            {
                "name": s["name"],
                "kind": s.get("id") or s["name"],
                "color": s.get("color", "#333"),
                "initial_posts": s.get("initial_posts") or [],
                "hypothesis": s.get("hypothesis") or "",
            }
            for s in sc_defs
        ],
        sample_count=1,
        max_rounds=3,
    )
    decision_id = created["decision"]["id"]
    print(f"[smoke] decision={decision_id}")

    # 3) fill fake runs with synthetic actions + metrics (skip real OASIS)
    for sc in created["scenarios"]:
        kind = sc.get("kind") or "Baseline"
        runs = registry.list_runs_for_scenario(sc["id"])
        for run in runs:
            run_dir = Path(Config.RUN_DIR) / run["id"]
            _copy_synthetic_actions(kind, run_dir)
            metrics = compute_run_metrics(
                run_dir,
                scenario_id=kind,
                scenario_name=sc.get("name") or kind,
                color=sc.get("color") or "#333",
            )
            registry.update_run(
                run["id"],
                status="completed",
                run_dir=str(run_dir),
                metrics=metrics,
            )
            print(
                f"[smoke] run={run['id']} kind={kind} "
                f"actions={metrics['summary']['total_actions']}"
            )

    registry.update_decision(decision_id, status="completed")

    # 4) compare
    payload = build_compare_payload(decision_id)
    assert payload.get("scenarios"), payload
    assert len(payload["scenarios"]) >= 2
    print(
        f"[smoke] compare scenarios={len(payload['scenarios'])} "
        f"title={payload.get('title')}"
    )
    for sc in payload["scenarios"]:
        s = sc.get("summary") or {}
        ta = s.get("total_actions") or {}
        print(
            f"  - {sc.get('scenario_name')}: "
            f"actions={ta.get('mean')}±{ta.get('std')} "
            f"n={sc.get('sample_count')}"
        )

    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
