# SandOwl Pilot Session 001

日期：2026-08-16（Asia/Shanghai）  
参与者角色：项目 Owner，以中文 Analyst 体验者身份参加  
是否符合第一目标用户假设：部分（熟悉项目背景，不是独立外部用户）  
任务：Northstar 引导案例  
主持人：Codex

## Outcome

本 Session 未满足完成条件。参与者只使用 SandOwl UI，没有使用数据库、脚本、API 或手工 UUID，也没有触发新实验或模型费用；但无法在不依赖主持提示的情况下找到持久任务并理解英文为主的 DecisionReport V2。

| 指标 | 结果 |
| --- | --- |
| 无数据库、脚本或 API 操作完成 | 是 |
| 无手工提供 UUID 完成 | 是 |
| 找到 sealed V2 | 是，需要 3 次路径提示/确认 |
| 正确区分 Evidence 与 assumptions | 未完成 |
| 正确解释 observations | 未完成 |
| 恢复关键 provenance | 未完成 |
| 未做预测、因果或总体误读 | 未评估 |
| 出现明确重复使用意愿 | 有条件：希望改用中国中文案例 |

最后可用状态：参与者已从 Decision Thread Revision 1 打开正确的 Northstar DecisionReport V2，但在 Evidence / Assumptions 识别阶段停止。

## Friction Log

| 顺序 | 当前页面 / 对象 | 参与者目标 | 实际行为与原话 | 是否需要提示 | 最小提示 | 严重度 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 首页 | 找到持久决策任务 | “1我就没找到” | 是 | 从产品主导航进入 Decision Workspace | major |
| 2 | 首页 CTA → 冻结现实 | 进入 Decision Workspace | “点击进入 Decision Workspace进到的是‘冻结现实页面’” | 是 | 使用顶部产品主导航的同名入口 | blocker |
| 3 | 已有 Thread Revision 1 | 打开既有报告 | “然后点追加上下文版本吗？” | 是 | 不修改资源；检查现有 Revision 1 | major |
| 4 | DecisionReport V2 | 确认报告入口 | “点击Revision 1的打包报告对吧？我打开了” | 需要确认 | 确认已进入正确报告 | minor |
| 5 | DecisionReport V2 | 区分 Evidence 与 assumptions | “找不到 这个页面有些看不懂，还大部分都是英文的” | 是 | 解释 01 Evidence 与 02 Assumptions 的中文含义 | blocker |

提示总次数：4  
错误入口次数：1  
手工寻找或抄录 ID 次数：0

## Evidence-backed Findings

### P1 — 首页 CTA 目标与文案不一致

首页中央按钮写作“进入 Decision Workspace”，实际进入 `#/world`（冻结现实），而顶部产品主导航的同名入口进入 `#/threads`。参与者按最显眼的 CTA 操作后进入错误阶段。

### P1 — 引导报告不适合中文参与者独立完成

报告章节标题、边界说明、Scenario、Trial 与 Analysis 大量使用英文。即使数据契约和七章节结构完整，参与者仍无法独立识别现实 Evidence 与 synthetic assumptions，核心理解任务因此失败。

### P2 — 已有 Thread 页面过度强调追加动作

参与者进入一个已有 Revision 1 的 Thread 后，把“追加上下文版本”理解为检查报告的下一步。已有结果的查看入口不够突出，编辑动作反而成为页面主动作。

## Boundary Comprehension

本轮未进入正式口述回答阶段。Evidence、synthetic assumption、Observation、Analysis、Limitations、Persona、delta 和最佳方案边界均记为“未评估”，不得视为通过。

## Reuse Intent

参与者主动提出：“可以用中国的重新生成案例吗？”

这是有条件的继续使用信号：参与者愿意继续，但要求案例背景、报告语言和核心标签以中文为主。下一轮应使用中国语境下的中文 Evidence 与虚构主体，不得把本轮未完成误写成 Northstar 案例已经通过中文用户验证。

## Observer Assessment

主要失败类别：导航 / 工作流摩擦，同时存在报告不可理解。  
本 Session 是否满足完成条件：否。  
产品价值信号：弱到中等（参与者愿意更换为中文案例继续）。  
是否允许进入下一名参与者：修复首页 CTA，并准备中文引导案例后再继续。

最小可验证修复：

1. 首页“进入 Decision Workspace”统一进入 Decision Thread 目录；
2. 准备一个中国语境、中文主文案的引导案例；
3. 报告为 Evidence、Assumptions、Observation、Analysis、Limitations 提供稳定中文标签；
4. 已有 Thread 默认突出“查看当前报告”，弱化“追加上下文版本”。

明确不应因此扩大的系统边界：Worker M2、第三方 Agent、通用预测能力或导航整体重写。

## Follow-up（不改变本 Session 结论）

已在同日完成并通过浏览器验收：

1. 首页中央 CTA 进入 `#/threads`；
2. 已有 Experiment 的 Thread 显示“查看当前报告”，追加上下文默认折叠；
3. V2 七章节使用稳定中文主标签，封存英文原文默认折叠；
4. 新建“共享充电宝误还扣费争议”中文引导案例，并冻结到 Decision Thread Revision 1。

这些修复只说明复测前置条件已经具备，不得把 Session 001 改判为通过。新的语义实验仍处于费用确认门前。
