#!/usr/bin/env python3
"""舆情模板端到端验收（离线路径，不依赖 Zep/OASIS 实时调用）。

验收项：
1. 创建舆情模板本体 + 假快照
2. 创建含 2 方案 + Baseline 的决策，每方案 sample_count=3
3. 用合成 actions 填充 9 次 Run 并计算指标
4. 对比面板可聚合；报告可生成；方案可区分

用法：
  cd backend && uv run python scripts/e2e_mvp_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import create_app
from app.config import Config
from app.decision.metrics_service import build_compare_payload, compute_run_metrics
from app.decision.report_service import generate_report
from app.engine.scenario_runner import ScenarioRunner
from app.ontology import registry
from app.ontology.snapshot import register_local_snapshot
from app.ontology.templates import get_template
from app.world.slicer import slice_world


def _import_smoke_helpers():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "smoke_offline_mvp", BACKEND / "scripts" / "smoke_offline_mvp.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    smoke = _import_smoke_helpers()
    app = create_app()
    registry.init_schema()
    Config.ensure_directories()

    schema = get_template("opinion")
    ont = registry.create_ontology(
        name="e2e_jiangcheng_opinion",
        template="opinion",
        schema=schema,
        schema_locked=True,
        status="ready",
        graph_id="local_fake_e2e",
    )
    ver = register_local_snapshot(ont["id"], smoke.FAKE_GRAPH, graph_id="local_fake_e2e")
    print(f"[e2e] ontology={ont['id']} version={ver['id']}")

    sliced = slice_world(
        smoke.FAKE_GRAPH,
        intervention_text="江城市交管局限行公告 周明远 骑手",
        k=2,
        use_llm_filter=False,
    )
    assert len(sliced["nodes"]) >= 3
    print(f"[e2e] slice nodes={len(sliced['nodes'])} edges={len(sliced['edges'])}")

    scenarios = [
        {
            "name": "方案A·强硬发布",
            "kind": "A_hard",
            "color": "#e74c3c",
            "intervention": {
                "name": "方案A·强硬发布",
                "kind": "A_hard",
                "initial_posts": [
                    {
                        "content": "【江城市交管局公告】自下周一零时起主干道禁止电动自行车通行。",
                        "poster_hint": "official",
                    }
                ],
            },
        },
        {
            "name": "方案B·柔性发布",
            "kind": "B_soft",
            "color": "#27ae60",
            "intervention": {
                "name": "方案B·柔性发布",
                "kind": "B_soft",
                "initial_posts": [
                    {
                        "content": "【江城市交管局公告】电动自行车通行管理试点启动：先试点90天。",
                        "poster_hint": "official",
                    }
                ],
            },
        },
        {
            "name": "Baseline·不正式发布",
            "kind": "Baseline",
            "color": "#7f8c8d",
            "intervention": {
                "name": "Baseline·不正式发布",
                "kind": "Baseline",
                "initial_posts": [
                    {
                        "content": "听说江城要限电瓶车？有人在群里传下周不让骑了。",
                        "poster_hint": "citizen",
                    }
                ],
            },
        },
    ]

    runner = ScenarioRunner()
    created = runner.create_decision(
        ontology_id=ont["id"],
        version_id=ver["id"],
        title="E2E 舆情模板验收（2方案+Baseline×3采样）",
        scenarios=scenarios,
        sample_count=3,
        max_rounds=10,
    )
    decision_id = created["decision"]["id"]
    runs = created["runs"]
    assert len(created["scenarios"]) == 3, created
    assert len(runs) == 9, f"expected 9 runs, got {len(runs)}"
    print(f"[e2e] decision={decision_id} scenarios=3 runs={len(runs)}")

    for sc in created["scenarios"]:
        kind = sc.get("kind") or "Baseline"
        for run in registry.list_runs_for_scenario(sc["id"]):
            run_dir = Path(Config.RUN_DIR) / run["id"]
            smoke._copy_synthetic_actions(kind, run_dir)
            # 轻微扰动：按 seed 复制后追加一行，保证同方案多次采样有方差
            seed = int(run.get("seed") or 42)
            with (run_dir / "actions.jsonl").open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "round": 99,
                            "agent_id": seed,
                            "agent_name": f"noise_{seed}",
                            "action_type": "CREATE_COMMENT",
                            "content": f"采样噪声 seed={seed} kind={kind}",
                            "stance": "neutral",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
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
                f"[e2e] run={run['id']} kind={kind} seed={seed} "
                f"actions={metrics['summary']['total_actions']}"
            )

    registry.update_decision(decision_id, status="completed")

    payload = build_compare_payload(decision_id)
    scenarios_out = payload.get("scenarios") or []
    assert len(scenarios_out) == 3, scenarios_out
    for s in scenarios_out:
        assert int(s.get("sample_count") or 0) == 3, s

    report = generate_report(payload, decision_id=decision_id)
    assert Path(report["path"]).exists()
    print(f"[e2e] report={report['path']} source={report['source']}")

    means = []
    for s in scenarios_out:
        mean = float((s.get("summary") or {}).get("total_actions", {}).get("mean") or 0)
        means.append(mean)
        print(
            f"  - {s.get('scenario_name')}: actions={mean} "
            f"n={s.get('sample_count')}"
        )

    if len(set(int(m) for m in means)) < 2:
        print("E2E_FAIL: scenarios not distinguishable by action count")
        return 1

    out = Path(Config.DECISION_DIR) / decision_id / "e2e_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "decision_id": decision_id,
                "sample_count": 3,
                "scenario_count": 3,
                "run_count": 9,
                "means": means,
                "report_path": report["path"],
                "passed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("E2E_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
