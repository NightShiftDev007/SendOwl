# SandOwl V1 Internal Pilot Dry Run

日期：2026-08-16  
执行方式：仅使用本地 SandOwl 浏览器 UI  
案例：Phase 3 — Northstar Mobility response timing  
付费操作：无  
首次检查：仅使用浏览器 UI，无数据库、脚本或 API 辅助操作  
P1 修复复验：浏览器 UI + 只读 API 身份核对，无付费模型调用

## 1. 结论

**两项 P1 已修复并通过 Northstar UI-only 主链复验，可以开始首名受控外部参与者。**

主链路已经证明：

- 首页清楚提供“进入 Decision Workspace”入口；
- 现有 Scenario、Cohort 和 succeeded Experiment 可以只通过 UI 绑定为 Decision Thread；
- Thread revision 提供“打开报告”入口，不需要手工复制 Experiment ID；
- V2 七章节、Report ID/hash、synthetic 标签、场景初始帖与模拟生成帖计数均可见；
- Observation 提供三条 Trial events 入口；
- 报告明确禁止预测、因果、总体推断和最佳方案。

首次 dry run 发现的两个真实主路径阻塞现已关闭：

1. 空 Portfolio 现在可先保存 `title + decision_question` 草稿，不要求预先存在 Scenario；
2. Reviewer 现在可从每条 V2 Evidence 直接打开绑定 WorldSnapshot 和原始来源。

复验继续使用既有 Northstar Scenario、Cohort、Experiment 和 sealed DecisionReport V2，没有创建新实验或改写历史报告哈希。

## 2. 本次创建的持久资源

本次没有创建 WorldSnapshot、Scenario、Cohort、Experiment、Trial 或 Report，也没有调用模型。

只通过 UI 创建了一个 Decision Thread：

| Resource | Identity |
| --- | --- |
| Decision Thread | `96aaa6a8-0bd9-487b-b89c-9a744c2c05b4` |
| Revision | 1 |
| Scenario | Phase 3 — Northstar Mobility response timing `[synthetic demo data]` |
| Experiment | `b37534ab-970c-4ab3-9545-8483337355d0` |
| DecisionReport V2 | `d1387633-660e-4519-b315-0e98f11265bf` |

该 Thread 是首轮引导任务的可复用入口，不是新的实验结果。

P1 修复复验另创建一个 question-first Thread，用于证明草稿和首次封存是两步独立操作：

| Resource | Identity |
| --- | --- |
| Decision Thread | `09650ae8-2df5-475d-819a-c04cb9f5222f` |
| Draft state | `latest_revision = null`、`revisions = []` |
| Sealed Revision | `0f6eb893-237d-4c6f-ba93-c3751f11c4fb`（version 1） |
| Existing Experiment | `b37534ab-970c-4ab3-9545-8483337355d0` |
| Existing DecisionReport V2 | `d1387633-660e-4519-b315-0e98f11265bf` |

该复验只新增 Decision Thread 与 Revision，不触发任何模型或实验执行。

## 3. UI-only Walkthrough

| 阶段 | 操作 | 结果 |
| --- | --- | --- |
| 首页 | 打开 `#/overview` | SandOwl 品牌和“进入 Decision Workspace”入口可见 |
| Portfolio | 进入 `#/threads` | 目录初始为空；页面要求选择已封存 Scenario |
| Thread 创建 | 选择 Phase 3 Scenario | 成功；Scenario 选项显示 snapshot version |
| Context | 选择对应 Cohort | 成功；显示 Persona 数量 |
| Experiment | 选择唯一 compatible Experiment | 成功；选项只显示 `succeeded · 3 variants · 3 trials` |
| Persist | 点击“创建持久决策任务” | 成功创建 Revision 1 |
| Report | 点击 Revision 中“打开报告” | 成功进入正确 Experiment 的 Reports 页面 |
| Report identity | 查看正文与 provenance | Report ID、V1/V2 ID/hash 均可见 |
| Boundary | 查看七章节 | Evidence、Assumptions、Experiment、Observation、Comparison、Analysis、Limitations 完整 |
| Observation | 检查三个 trials | 场景初始帖与模拟生成帖分开展示；三条 events 入口存在 |
| Evidence recovery | 在 Evidence 章节查找链接 | 0 条可点击 Evidence 链接 |
| Context return | 从 Reports 点击顶层 Decision Workspace | 返回 Portfolio，但不会保持当前 Thread 选中状态 |

### P1 修复复验

| 阶段 | 操作 | 结果 |
| --- | --- | --- |
| Question first | 输入任务标题和 Northstar 原 decision question | 成功创建零 Revision 草稿 |
| Draft recovery | 自动进入新 Thread，并刷新目录 | 目录显示“草稿 · 未绑定上下文” |
| Revision 1 | 选择唯一匹配 Scenario、对应 Cohort 与既有 Experiment | 成功封存 Revision 1 |
| Report recovery | 从 Revision 1 点击“打开报告” | 进入既有 Experiment 的 V2 报告 |
| Frozen evidence | 点击首条“查看冻结副本” | 进入 WorldModel `0a03bc0b-20c8-40c0-a3ac-8a6c58e0f8e0` 的 snapshot `214a681f-8b9d-4a2f-bce3-b816cdba43e7` |
| Source recovery | 检查 Evidence actions | 6 条来源各有 1 个冻结副本入口和 1 个原始来源入口 |

## 4. Findings

### RESOLVED P1 — Decision Thread 不是实际工作流起点

空目录同时展示“新建决策任务”和“选择一条已封存 Scenario 作为决策起点”。用户在建立问题、选择 Evidence、冻结 WorldSnapshot 和创建 Scenario 之前，无法创建持久任务。

这与 V1 的产品单元“Decision Thread”冲突，也使自带问题任务在最需要保存上下文的前半程没有容器。顶部阶段顺序是“决策任务 → 媒体证据 → 冻结现实 → 决策实验”，但第一阶段又依赖第四阶段之前已经产生的对象。

影响：

- 真实 Analyst 无法从问题开始；
- 需要主持人解释先去哪个专家工作区；
- Evidence 和 Scenario 创建过程不属于持久 Thread；
- 无法满足“无需工程人员解释下一步”的 Pilot gate。

修复结果：新增严格 draft contract。草稿只持久化标题与问题，`latest_revision` 为 null；第一次绑定匹配 Scenario 时追加 version 1。数据库现有父表已允许零 Revision，因此无需迁移，也未放宽 revision 的封存约束。

### RESOLVED P1 — 报告 Evidence 无恢复入口

Evidence 章节显示 WorldSnapshot ID/hash、来源名称、文章标题与 captured content hash，但该 region 中可点击链接数量为 0。

影响：

- Reviewer 无法从报告直接打开原始来源；
- 无法进入对应 SandOwl evidence detail；
- Pilot 的 provenance recovery 任务必须靠复制标题后另行搜索；
- Report ID 可见并不能弥补 Evidence 回溯断点。

修复结果：每条 structured Evidence item 现在提供两个明确入口：

1. “查看冻结副本”进入绑定 WorldSnapshot 的 evidence detail；
2. “查看原始来源”使用报告已封存的 source URL。

链接继续使用报告已封存的 WorldSnapshot identity 和 source URL，没有查询或替换为当前 AgendaScope revision。

### P2 — Trial events 面向 API，而不是 Reviewer

Observation 有三条“查看事件”链接，目标是 `/api/v2/semantic-trials/{id}/events`。入口可追溯，但预期结果是原始 API 表示，不是产品内的可读事件核验视图。

影响：Reviewer 能拿到数据，但需要理解 JSON、字段名和 clock semantics，容易把 API 可用性误当成产品可用性。

最小修复方向：链接到现有 Playground 的 Trial detail，或提供只读 inline event ledger；保留原 API 作为专家导出，不作为默认 Reviewer 路径。

### P2 — Experiment 选择缺少身份

Decision Thread composer 中 compatible Experiment 只显示状态、variant 数和 trial 数。若同一 Scenario/Cohort 存在多个成功实验，用户无法根据时间、model、seed 或 hash 区分。

最小修复方向：选项显示创建时间、model 和短 experiment hash；不要求显示完整 UUID。

### P2 — 从 Report 返回后丢失 Thread 上下文

顶层“Decision Workspace”会返回 `#/threads`，当前 Thread 不再自动选中。用户必须在目录中再次选择。当前只有一个 Thread，因此可恢复；Portfolio 增长后会增加错误选择风险。

最小修复方向：报告页提供“返回 Decision Thread”深链，或在从 Thread 进入 Report 时保留 `thread_id` 查询参数。不要依赖浏览器历史作为唯一恢复方式。

## 5. 本轮没有证明的内容

- 没有真实 Analyst 参与，因此没有人类 completion time、理解度或重复使用信号；
- 没有执行自带问题任务；
- 没有导入新数据或触发付费模型调用；
- 没有证明 draft Thread contract 是最终正确方案；
- 没有证明 Simulation 对真实业务问题具有决策价值。

## 6. External Pilot Gate

当前判定：**PASS — 可以开始首名受控外部 Pilot。**

已验证：

- Analyst 可以从问题建立持久草稿，不要求预先存在 Scenario；
- Reviewer 可以从 V2 Evidence 直接恢复冻结副本和原始来源；
- 引导案例的 Northstar Thread 可从 Portfolio 直接打开；
- 现有 sealed resources、report hashes 和 synthetic boundaries 保持不变；
- 已再次执行 Northstar UI-only 主链复验，操作过程不依赖手工页面路径或 UUID。

P2 可在首轮内部 Pilot 中继续观察，但应记录提示次数和误读；若阻止 Reviewer 完成 provenance recovery，则升级为 P1。

## 7. 建议实施顺序

1. 先执行 1 名真实 Analyst / Reviewer 受控 session；
2. 使用 observation template 记录 completion、提示次数、Evidence recovery 与边界理解；
3. 若 Trial events、Experiment 身份或 Report → Thread 返回阻止任务完成，将对应 P2 升级为 P1；
4. 首名参与者通过后，再逐步扩展到总计 5 名 sessions；
5. 仅在真实使用数据证明需要时实现 P2，不增加第三个 synthetic Vertical Slice。

明确不做：第三个 synthetic Vertical Slice、Worker M2、通用 Agent、导航整体重写或现实预测能力扩张。
