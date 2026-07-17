"""CLI: python -m scripts.gtv_forecast [import|labels|gate|backtest|train|score|calibrate|run]."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GTV deal forecast pilot")
    parser.add_argument(
        "command",
        choices=["import", "labels", "gate", "backtest", "train", "score", "calibrate", "run"],
        help="pipeline stage",
    )
    parser.add_argument("--force", action="store_true", help="re-import parquet even if exists")
    args = parser.parse_args(argv)

    if args.command in {"import", "run"}:
        from .import_tables import import_all

        results = import_all(force=args.force)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    if args.command in {"labels", "run"}:
        from .labels import save_labels

        summary = save_labels()
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    if args.command in {"gate", "run"}:
        from .feasibility import run_feasibility_gate

        gate = run_feasibility_gate()
        print(
            json.dumps(
                {
                    k: gate[k]
                    for k in (
                        "pass_gate",
                        "hard_pass",
                        "usable_fold_count",
                        "recommended_scope",
                        "decisions",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    if args.command in {"backtest", "run"}:
        from .models import run_backtest
        from .report import write_demo_report

        summary = run_backtest()
        path = write_demo_report(summary)
        print(
            json.dumps(
                {
                    "accept": summary.get("accept"),
                    "listing_avg": summary.get("listing_avg"),
                    "broker_avg": summary.get("broker_avg"),
                    "time_avg": summary.get("time_avg"),
                    "report": str(path),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    if args.command in {"train", "run"}:
        from .models import train_final

        meta = train_final()
        print(json.dumps(meta, ensure_ascii=False, indent=2, default=str))

    if args.command == "score":
        from .scoring import score_scenarios, write_score_artifacts

        multi = score_scenarios(
            [
                {"name": "Baseline·不干预", "kind": "baseline", "intervention": {}},
                {
                    "name": "方案A·加推带看",
                    "kind": "boost",
                    "intervention": {"gtv": {"boost_exposure": {"enabled": True, "factor": 1.8}}},
                },
                {
                    "name": "方案B·谈价协商",
                    "kind": "nego",
                    "intervention": {
                        "gtv": {
                            "negotiate_deal": {
                                "enabled": True,
                                "success_rate": 0.3,
                                "concession_pct": 0.05,
                            }
                        }
                    },
                },
            ]
        )
        paths = write_score_artifacts(multi)
        print(
            json.dumps(
                {
                    "mode": multi.get("mode"),
                    "n_scenarios": len(multi.get("scenarios") or []),
                    "paths": paths,
                    "summaries": [
                        {"name": s.get("name"), "summary": s.get("summary"), "delta": s.get("delta_vs_baseline")}
                        for s in multi.get("scenarios") or []
                    ],
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    if args.command == "calibrate":
        from .calibrate import calibrate_negotiate_prior

        out = calibrate_negotiate_prior()
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
