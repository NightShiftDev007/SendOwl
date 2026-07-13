"""
决策报告服务：对比指标 → markdown 报告
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import Config
from app.utils.logger import get_logger

logger = get_logger("adc.decision.report")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rule_markdown(compare: Dict[str, Any]) -> str:
    lines = [
        f"# 决策对比报告：{compare.get('title') or compare.get('decision_id')}",
        "",
        f"生成时间：{_utc_now()}",
        "",
        "## 方案对比摘要",
        "",
    ]
    for sc in compare.get("scenarios") or []:
        name = sc.get("scenario_name") or sc.get("scenario_id")
        s = sc.get("summary") or {}
        ta = s.get("total_actions") or {}
        share = s.get("stance_share") or {}
        lines.append(f"### {name}")
        lines.append("")
        if sc.get("narrative"):
            lines.append(sc["narrative"])
            lines.append("")
        lines.append(
            f"- 总互动：{ta.get('mean', 0)} ± {ta.get('std', 0)} "
            f"（n={ta.get('n', 0)}）"
        )
        for stance in ("supportive", "opposing", "neutral"):
            st = share.get(stance) or {}
            label = {"supportive": "赞成", "opposing": "反对", "neutral": "中立"}[stance]
            lines.append(
                f"- {label}占比：{st.get('mean', 0):.1%} ± {st.get('std', 0):.1%}"
            )
        lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("本报告由对比指标自动生成（MVP）。完整 ReportAgent 叙事需可用的图谱与模拟环境。")
    return "\n".join(lines)


def generate_report(
    compare_payload: Dict[str, Any],
    graph_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    对比指标 → markdown。默认复用已有 compare_report.md（秒开）；
    force=True 时才重新调 LLM/规则生成。
    """
    Config.ensure_directories()
    did = decision_id or compare_payload.get("decision_id") or "unknown"
    out_dir = os.path.join(Config.DECISION_DIR, did, "report")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "compare_report.md")

    if not force and os.path.isfile(path) and os.path.getsize(path) > 0:
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = f.read()
            if cached.strip():
                logger.info(f"compare report cache hit: {path}")
                return {
                    "decision_id": did,
                    "path": path,
                    "source": "cache",
                    "markdown": cached,
                }
        except OSError as e:
            logger.warning(f"读取对比报告缓存失败: {e}")

    markdown = None
    source = "rules"

    # 尝试轻量 LLM 总结
    if Config.LLM_API_KEY:
        try:
            from app.utils.llm_client import LLMClient
            import json

            client = LLMClient()
            prompt = (
                "你是舆情决策分析师。根据下列多方案模拟对比指标，"
                "用中文写一份简洁 markdown 报告，包含：总体结论、各方案差异、风险提示。"
                "不要编造指标中没有的数字。\n\n"
                + json.dumps(
                    {
                        "title": compare_payload.get("title"),
                        "scenarios": [
                            {
                                "id": s.get("scenario_id"),
                                "name": s.get("scenario_name"),
                                "summary": s.get("summary"),
                                "narrative": s.get("narrative"),
                            }
                            for s in (compare_payload.get("scenarios") or [])
                        ],
                    },
                    ensure_ascii=False,
                )
            )
            markdown = client.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=3000,
            )
            source = "llm"
        except Exception as e:
            logger.warning(f"LLM 报告失败: {e}")

    # ReportAgent 较重且依赖模拟环境，MVP 仅在显式 graph_id + 有 LLM 时尝试跳过
    _ = graph_id  # reserved for future ReportAgent integration

    if not markdown:
        markdown = _rule_markdown(compare_payload)
        source = "rules"

    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)

    return {
        "decision_id": did,
        "path": path,
        "source": source,
        "markdown": markdown,
    }
