# SandOwl 原生工作流 Pilot 参与者指南

状态：M16 Owner 零提示复测材料  
适用对象：研究员、研究负责人 / Reviewer  
建议时长：研究员 45–75 分钟，Reviewer 20–30 分钟

## 1. 本次验证回答什么

Pilot 只验证参与者能否通过 SandOwl 界面完成并复核下面这条原生链路：

```text
SandOwl 原生媒体证据与 AgendaContext
→ 冻结 WorldSnapshot / Graph
→ Research Project
→ MatrAIx Persona Cohort
→ 单一 Simulation Run
→ 冻结报告
→ ReportAgent 引用报告与 Agent Interaction
```

它不评价参与者，不证明模拟结果具有现实预测能力，也不要求创建基线、备选方案或方案排名。

主持人不得使用数据库、脚本、API 或手工 UUID 替参与者完成任务。参与者应把迷路、误解和预期直接说出来。

## 2. 开始前说明

主持人逐字说明：

> SandOwl 把人工确认的现实来源、明确标记的合成情境、合成人物动作和解释限制绑定在同一条研究记录中。它不预测现实、不证明因果、不代表真实人群，也不会选择最佳方案。

自带问题任务开始前必须完成 [`pilot-data-authorization-checklist.md`](pilot-data-authorization-checklist.md)。没有授权时只允许读取已封存的中文案例。

## 3. 任务 A：中文只读引导案例

案例：`UI 巡检 · 共享充电宝说明观察`。这是 M16 工程验收形成的完整原生案例；标题中的“UI 巡检”是资源身份的一部分，不表示参与者已经看到操作路径。

请参与者自行完成，主持人只记录、不提示按钮位置：

1. 从产品界面找到“UI 巡检 · 共享充电宝说明观察”；
2. 说明现实 Evidence、Research Project 和合成起始情境分别是什么；
3. 找到本次运行使用的冻结 WorldSnapshot，并打开原始媒体来源；
4. 找到 Cohort 人数、seed、轮数、定时合成更新和人物实际收到的冻结背景；
5. 区分“预置起始内容 2”和“人物新增帖子 0”；
6. 说明评论、反应和无动作计数只代表什么；
7. 找到 Report SHA-256、Run SHA-256 和 ReportAgent 草稿 SHA-256；
8. 打开一组折叠的冻结引用，说明引用原文与报告分析的关系；
9. 找到一次成功 Agent Interaction、一次成功 Persona 访谈和一个成功 Survey / Harbor Evaluation；
10. 用自己的话说明本报告证明了什么、没有证明什么。

任务 A 不重新运行模拟，不创建 ReportAgent 草稿，也不提交 Agent Interaction。

## 4. 任务 B：参与者自带问题

任务 B 只在数据与费用授权完成后执行：

1. 写下一个边界明确的研究问题；
2. 在媒体证据中选择允许使用的来源；
3. 人工确认并冻结一个不可变 WorldSnapshot；
4. 用该精确快照创建 Research Project；
5. 选择已有 Cohort，或在“模拟人群”中创建新的冻结 Cohort；
6. 为一次独立运行填写 simulation requirement 与合成起始内容；
7. 再次确认模型、费用和数据边界后提交一次 Simulation Run；
8. 核对事件、计数、限制和内容哈希；
9. 按需生成 ReportAgent 引用报告；
10. 把报告交给 Reviewer，不附加口头解释。

MatrAIx Evaluation 是独立可选任务，不用于给 Simulation Run 的结论打分。

## 5. Reviewer 任务

Reviewer 只能使用 SandOwl UI 和研究员提交的报告：

1. 区分现实 Evidence、合成起始情境、Simulation Observation、Analysis 与 Limitations；
2. 从报告恢复 WorldSnapshot 和至少一条原始来源；
3. 找到 Project、Run、Report 与引用报告的内容地址；
4. 核对起始帖子、生成帖子、评论、反应与无动作计数；
5. 判断报告是否支持现实预测、因果结论、总体推断或最佳方案；
6. 指出最值得补充的证据或下一次独立运行，而不是要求系统给出确定答案。

## 6. 主持规则

- 允许参与者思考、返回和走错路径；
- 只在数据安全、付费调用或不可逆操作前主动阻止；
- 每次询问“下一步是什么”都先记录，再给最小提示；
- 不把“能打开报告”视为完成，边界理解和来源恢复同样必须通过；
- 不把历史 DecisionReport 或多方案 Semantic Experiment 当作原生任务；
- 会后使用 [`pilot-observation-template.md`](pilot-observation-template.md) 单独记录每个 session。

## 7. 完成条件

- 不依赖工程人员或手工 UUID；
- 有分阶段完成时间、提示次数和错误入口记录；
- Reviewer 能恢复冻结来源；
- 参与者能正确区分现实证据与合成情境；
- 没有把 Persona、单 seed 或事件计数解释成现实总体结论；
- 记录参与者是否愿意再次使用以及用于什么问题。
