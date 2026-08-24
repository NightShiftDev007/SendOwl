"""Readable, bounded sources for native multi-source research reports."""

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from app.evidence.contracts import EvidenceBundleDetail
from app.research_interviews.contracts import ResearchPersonaInterview
from app.research_projects.contracts import ResearchRunReport
from app.world_graphs.contracts import SemanticWorldGraphDetail

MAX_SOURCE_CHARACTERS = 80_000


@dataclass(frozen=True, slots=True)
class ResearchReportSource:
    tool_name: str
    target_id: UUID
    source_label: str
    evidence_kind: str
    text: str

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()


def _bounded(text: str) -> str:
    if len(text) <= MAX_SOURCE_CHARACTERS:
        return text
    notice = "\n\n[来源过长；报告输入在此处按固定字符上限截断。完整资源仍可在技术审计中核对。]"
    return text[: MAX_SOURCE_CHARACTERS - len(notice)] + notice


def render_snapshot_source(bundle: EvidenceBundleDetail) -> ResearchReportSource:
    lines = [
        "# 冻结的现实背景证据",
        f"快照标题：{bundle.title}",
        f"快照版本：v{bundle.version}",
        f"媒体数量：{bundle.item_count}",
        f"政策数量：{bundle.policy_item_count}",
        "",
        "## 媒体",
    ]
    lines.extend(
        f"{item.position + 1}. {item.source_name}《{item.title}》；"
        f"发布时间：{item.published_at.isoformat()}；国家或地区：{item.country_code or '未标注'}；"
        f"冻结摘要：{item.excerpt}；原文：{item.original_url}"
        for item in bundle.items
    )
    lines.extend(("", "## 政策"))
    if bundle.policy_items:
        lines.extend(
            f"{item.position + 1}. {item.authority_name}《{item.title}》；"
            f"管辖区：{item.jurisdiction_code}；发布日期：{item.publication_date.isoformat()}；"
            f"原文：{item.original_url}"
            for item in bundle.policy_items
        )
    else:
        lines.append("本快照没有冻结政策文件。")
    lines.extend(
        (
            "",
            "## 使用边界",
            "这些来源用于固定研究的现实背景，不证明合成情境、Persona 动作"
            "或报告判断会在现实中发生。",
        )
    )
    return ResearchReportSource(
        tool_name="read_world_snapshot",
        target_id=bundle.world_snapshot_id,
        source_label="SandOwl：冻结的现实背景证据",
        evidence_kind="world_snapshot",
        text=_bounded("\n".join(lines)),
    )


def render_graph_source(graph: SemanticWorldGraphDetail) -> ResearchReportSource:
    names = {node.id: node.name for node in graph.nodes}
    lines = [
        "# 冻结证据提取出的语义图",
        f"实体数量：{len(graph.nodes)}",
        f"关系数量：{len(graph.edges)}",
        "",
        "## 实体",
    ]
    lines.extend(
        f"{node.position + 1}. [{node.entity_type}] {node.name}：{node.summary}"
        for node in graph.nodes
    )
    lines.extend(("", "## 关系"))
    if graph.edges:
        lines.extend(
            f"{edge.position + 1}. {names[edge.source_node_id]} --{edge.relation_type}--> "
            f"{names[edge.target_node_id]}：{edge.fact}"
            for edge in graph.edges
        )
    else:
        lines.append("本图没有抽取到实体间关系。")
    lines.extend(
        (
            "",
            "## 使用边界",
            "语义图只整理冻结证据中可直接支持的实体与关系，不补充外部事实，也不推断社会关系。",
        )
    )
    return ResearchReportSource(
        tool_name="read_world_graph",
        target_id=graph.id,
        source_label="SandOwl：冻结证据语义图",
        evidence_kind="world_graph",
        text=_bounded("\n".join(lines)),
    )


def render_run_source(report: ResearchRunReport) -> ResearchReportSource:
    run = report.run
    lines = [
        "# 冻结的单次合成模拟记录",
        f"研究项目：{report.research_project.title}",
        f"研究问题：{report.research_project.research_question}",
        f"模拟要求：{run.simulation_requirement}",
        f"Seed：{run.seed}",
        f"轮数：{run.rounds}",
        f"每轮分钟数：{run.minutes_per_round}",
        f"合成人物数量：{run.cohort.persona_count}",
        "",
        "## 合成情境输入",
    ]
    if run.simulation_plan is None:
        lines.append(f"第 0 分钟：{run.initial_post}")
    else:
        lines.extend(
            f"第 {item.offset_minutes} 分钟：{item.content}"
            for item in run.simulation_plan.scheduled_posts
        )
    lines.extend(("", "## 已记录事件"))
    for event in report.events:
        actor = "实验预置" if event.actor_kind == "scenario" else f"Persona {event.persona_id}"
        content = "" if event.content is None else f"；内容：{event.content}"
        lines.append(
            f"#{event.sequence}；第 {event.round} 轮；{actor}；动作：{event.action_type}{content}"
        )
    lines.extend(("", "## 逐轮图记忆"))
    if report.graph_memory:
        lines.extend(
            f"第 {memory.round} 轮：累计 {memory.cumulative_event_count} 个事件，"
            f"{len(memory.nodes)} 个节点，{len(memory.edges)} 条关系。"
            for memory in report.graph_memory
        )
    else:
        lines.append("这是历史运行，没有逐轮图记忆。")
    lines.extend(
        (
            "",
            "## 使用边界",
            "这是合成模拟记录，不是现实用户行为、现实预测、商业建议或方案比较。",
        )
    )
    return ResearchReportSource(
        tool_name="read_simulation_run",
        target_id=run.id,
        source_label="SandOwl：冻结的单次合成模拟记录",
        evidence_kind="simulation_run",
        text=_bounded("\n".join(lines)),
    )


def render_interviews_source(
    run_id: UUID,
    interviews: tuple[ResearchPersonaInterview, ...],
) -> ResearchReportSource | None:
    succeeded = tuple(item for item in interviews if item.status == "succeeded")
    if not succeeded:
        return None
    lines = [
        "# 用户明确发起的运行后 Persona 追问",
        "以下回答是在运行结束后，根据同一冻结运行状态生成的合成回答；不是与仍在运行的代理实时通信。",
        "",
    ]
    for position, item in enumerate(succeeded, start=1):
        lines.extend(
            (
                f"## {position}. {item.persona.display_name}",
                f"问题：{item.question}",
                f"回答：{item.answer_markdown}",
                "",
            )
        )
    lines.extend(
        (
            "## 使用边界",
            "这些回答只代表冻结 Persona 在本次合成运行后的追加观察，不代表真人观点。",
        )
    )
    return ResearchReportSource(
        tool_name="read_persona_interviews",
        target_id=run_id,
        source_label="SandOwl：经用户明确发起的运行后 Persona 追问",
        evidence_kind="persona_interviews",
        text=_bounded("\n".join(lines)),
    )
