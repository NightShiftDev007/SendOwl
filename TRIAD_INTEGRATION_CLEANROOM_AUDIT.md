# SandOwl 三方整合 Clean-room 审计

> **已废止：** 本文曾把 `ai-decision-center` 与 MiroFish 误判为相互独立的来源，并由此建议空白重建。用户随后确认 ADC 是基于 MiroFish 的研究性二开，且目标是整合三方能力而非清除 Git 血缘。当前实施基线改为 [`TRIAD_INTEGRATION_REFACTOR_PLAN.md`](TRIAD_INTEGRATION_REFACTOR_PLAN.md)；本文仅保留为历史审计记录，不得作为删除或迁移依据。

日期：2026-08-16  
目标来源：AgendaScope + MiroFish + MatrAIx  
明确排除：ai-decision-center（ADC）代码、领域模型、产品流程与 Git 血缘

## 结论

当前 `/Users/ssyb/Workspace/web/SandOwl` **不是干净的三方整合仓库**。它的 Git 历史始于：

```text
b4db2dd Initial commit: AI Decision Center P1 MVP
```

随后 `3699223 feat: establish unified V2 integration workspace` 删除了大量旧 ADC 实现，但重新建立了 `WorldSnapshot → Baseline/Alternatives Scenario → paired Semantic Experiment → DecisionReport` 领域链。再之后，AgendaScope 与 MatrAIx 能力被叠加到该 V2 底座。当前 MiroFish 仓库本身不作为运行时，SandOwl 主要直接运行 OASIS/CAMEL，并重写了若干受 MiroFish 启发的图、报告和访谈能力。

因此当前实际形态是：

```text
ADC 血缘与多方案领域模型
+ AgendaScope 数据导入
+ MatrAIx Persona / Evaluation
+ MiroFish 交互模式与 OASIS/CAMEL
```

这不满足“三方整合且不掺杂 ADC”的目标。仅修改页面名称或隐藏 Comparison 不足以纠正问题。

## 审计证据

1. SandOwl 与 `ai-decision-center` 共享从 `b4db2dd` 开始的提交历史。
2. 当前 SandOwl `README.md` 明写“AgendaScope、原 ai-decision-center、MatrAIx 与 MiroFish/OASIS”。
3. `3699223` 的 README 标题是 `SandOwl · AI Decision Center V2`，并定义无干预基线与 1～5 个备选方案。
4. `backend/migrations/versions/20260812_core_0006_immutable_scenarios.py` 在数据库层强制 exactly one baseline，并保存 alternatives/interventions。
5. `backend/app/semantic_experiments/contracts.py` 把 Baseline + Alternatives、同 seed trial matrix 和 paired delta 作为正式契约。
6. 原始 MiroFish 以一个 `Project.simulation_requirement`、一份 `simulation_config.json`、一次 Simulation 和一份 Report 为主流程；没有 ADC 式 Decision、Baseline、Alternative 与 paired comparison 一等对象。
7. 当前 `NOTICE` 和 discovery 文档明确说明 MiroFish 是 reference upstream，未复制其 worker 源码，也不是当前直接运行的仓库。

## 来源与处置矩阵

| 当前模块/能力 | 主要来源判断 | 处置 | 原因 |
| --- | --- | --- | --- |
| `backend/app/media/**`、Media UI、AgendaScope sync | AgendaScope + 新整合胶水 | 保留设计，clean-room 迁移 | 真实三方目标组成部分 |
| `media_sources/articles/topics/propagation/first_utterances` | AgendaScope read model | 保留数据语义 | 不属于 ADC |
| `backend/app/populations/**`、Persona/Cohort 导入 | MatrAIx + 新整合胶水 | 保留设计，clean-room 迁移 | 真实三方目标组成部分 |
| `matraix_surveys/chat/web/linux/trial_archive/batch` | MatrAIx source samples 的重实现 | 单独评审后迁移 | 来源正确，但并非全部都是最小整合主链所必需 |
| `backend/oasis_worker` 的通用队列、心跳、产物校验 | 新整合基础设施 | 重新抽取或重写 | 机制中立，但当前任务契约大量依赖 ADC Scenario/Experiment |
| `world_models` 与冻结 Evidence | 新整合胶水，概念受 ADC/V2 影响 | 保留“冻结证据”需求，重命名并重建模型 | 可追溯性有价值，但不能继续携带 ADC World/Decision 语义 |
| `scenarios`、baseline、alternatives、interventions | ADC 多方案领域模型 | 退休 | 与用户明确范围冲突 |
| `semantic_experiments` 的 variant matrix、paired delta | ADC 多方案领域模型 | 退休 | MiroFish 原生无此一等模型 |
| `decision_threads` | ADC Decision 产品层的延伸 | 退休或替换为普通 Research Case | 当前引用 Scenario/Experiment/Report hash |
| DecisionReport V1/V2 的 Comparison、Assumptions 方案列 | ADC 对比报告语义 | 退休 | 与多方案链绑定 |
| Report 问答、Persona Interview | MiroFish 交互模式 + 新实现 | 重新绑定到 MiroFish Report 后迁移 | 不能继续依赖 ADC DecisionReport |
| `world_graphs`、语义图、RunInteractionGraph | MiroFish 图模式 + 新实现 | 评审后迁移 | 需明确接真实 MiroFish graph/runtime，不能只模仿 UI |
| bounded ReportAgent | MiroFish ReportAgent 的受控重设计 | 暂缓迁移 | 当前不是实际 MiroFish ReportAgent；需先决定集成边界 |
| Policy evidence | SandOwl 新增，非三方来源 | 移出三方最小主链 | 属于额外产品范围，不是 ADC 污染但仍是 scope creep |
| Worker domain isolation、readiness、hashing、append-only audit | 中立工程能力 | clean-room 重建 | 可以保留原则，避免复制带 ADC 血缘实现 |

## 必须退休的 ADC 依赖链

### 后端领域与 API

- `backend/app/scenarios/**`
- `backend/app/semantic_experiments/**`
- `backend/app/decision_threads/**`
- `backend/app/decision_reports/**` 中依赖 Scenario/paired comparison 的部分
- `backend/app/api/scenarios.py`
- `backend/app/api/semantic_experiments.py`
- `backend/app/api/decision_threads.py`
- `backend/app/api/decision_reports.py` 中的 ADC 报告路径
- `backend/app/simulations/**` 中编译 Scenario Alternative 的部分
- Survey、ReportQuestion、PersonaInterview 中引用 Scenario/DecisionReport 的外键与契约

### 数据库谱系

直接属于 ADC 多方案链：

- `core_0006`、`core_0007`：Scenario / Variant / Intervention
- `core_0010`：Semantic Experiment / Variant / Trial / paired comparison 输入
- `core_0012`：Decision Thread
- `core_0013`：Decision Report
- `core_0014`、`core_0015`、`core_0023`：绑定 ADC Report 的问题链
- `core_0016`：绑定 Scenario 的 Survey
- `core_0017`、`core_0018`：绑定 ADC Report 的 Persona Interview
- `core_0042`：七章节 DecisionReport V2

不能在现有应用库上直接 drop 这些表：当前 sealed 数据和外键很多，且用户工作树包含大量未提交代码。应建立新 schema/新数据库并显式选择需要迁移的三方数据。

### 前端

- Decision Workspace 中的“决策任务 / 决策实验”主线
- `ScenarioPage.tsx`
- `SemanticExperimentPage.tsx`
- `DecisionThreadsPage.tsx`
- `DecisionReportsPage.tsx` 与 `DecisionReportV2Page.tsx` 的多方案内容
- Baseline、备选方案、配对差值、Comparison、最佳方案边界相关文案
- 与 Scenario/Experiment 深链绑定的 Run Studio 入口

### 当前数据

下列资源是错误范围下生成的开发数据，不迁移到 clean-room：

- Northstar 多方案实验及报告
- 星桥充电多方案实验 `20b05cdf-526b-4be8-bd9e-b1e429ebf662`
- 星桥充电 DecisionReport V2 `becfe677-16d1-46ab-9cff-2b135f94315b`
- 相关 Scenario、Decision Thread 和 paired comparison

它们现在是 append-only sealed 数据，不应在当前库中强删。clean-room 使用新数据库即可自然隔离。

## 可保留的三方能力

### AgendaScope

- Source、Article、Topic、Agenda Event、结构化传播关系和首发观察
- 只读 PostgreSQL 导入/同步契约
- 原始 URL、发布时间、捕获时间、完整正文与来源身份
- 媒体检索、来源档案、议题时间线与传播证据

### MatrAIx

- Persona Dataset、Persona Profile、Cohort 与顺序身份
- Source sample task 的授权与来源说明
- Survey、Chat、Web、Linux 等 evaluation 能力可作为独立 Task 层逐项接入
- Trial、Artifact、Verifier、Trajectory 的严格区分

### MiroFish

- Project / Graph 构建流程
- `simulation_requirement`
- Persona/profile 与 simulation config 生成
- Simulation Manager / Runner 与 OASIS 执行
- Actions、platform DB、运行进度
- ReportAgent 报告生成
- Agent Interview / Interaction
- 五步工作流的真实运行语义；UI 可以重做，但不能用 ADC 多方案流替换

## 无 ADC 的目标主链

```text
AgendaScope Evidence Selection
  → Research Case（新整合胶水，仅保存研究问题与来源范围）
  → MiroFish Project / Graph Context
  → 一个 simulation_requirement
  → MatrAIx Dataset / Cohort 绑定
  → MiroFish Simulation Config
  → OASIS Simulation Run
  → Actions / Platform Artifact / Graph Update
  → MiroFish Report
  → Agent Interaction / MatrAIx Evaluation
```

明确不包含：

- Baseline
- Alternative A/B
- Decision / Scenario matrix
- same-seed paired comparison
- 自动方案排序或 verdict
- ADC Decision Workspace

如果未来需要重复模拟，只创建多个独立 `SimulationRun`；除非用户以后重新明确授权，否则不引入跨 Run 的多方案比较领域层。

## 建议的 clean-room 领域模型

| 新对象 | 关键字段 | 来源 |
| --- | --- | --- |
| `ResearchCase` | title、research_question、created_at | 新整合胶水 |
| `EvidenceSelection` | AgendaScope article/topic/event IDs、source revision、capture hash | AgendaScope |
| `MiroFishProjectBinding` | project_id、graph_id、simulation_requirement、config hash | MiroFish |
| `PopulationBinding` | MatrAIx dataset/cohort IDs、ordered persona hashes | MatrAIx |
| `SimulationRun` | project、population、model config、runtime status、artifact IDs | MiroFish/OASIS |
| `SimulationEvent` | append-only action/event、simulation clock、recording clock | MiroFish/OASIS |
| `SimulationReport` | report artifact、citations、generator identity | MiroFish |
| `AgentInteraction` | report/run binding、agent identity、question/answer/tool trace | MiroFish + MatrAIx |

这些对象都不含 baseline、alternative、variant、paired delta 或 decision verdict。

## Git 与仓库策略

### 推荐：新建 clean-room 仓库

原因：

1. 当前 Git 根提交就是 ADC；在原仓库删除文件仍保留 ADC 血缘。
2. 当前工作树有大量用户未提交修改，不能安全改写历史或大规模删除。
3. 新数据库、新 Alembic base 和新 Compose project 能确保不会误连 ADC schema/data。
4. 可以对每个迁移文件记录明确来源：AgendaScope、MiroFish、MatrAIx 或 new integration glue。

禁止采用：

- 在当前分支 `git reset --hard`；
- 删除当前数据库或 sealed 数据；
- 把当前仓库复制后声称已 clean-room；
- 仅改 README/导航就宣布移除 ADC；
- 把 OASIS 直接运行等同于已整合 MiroFish。

## 实施顺序

### Phase 0：冻结错误路线

- 不再新增 Scenario、Semantic Experiment、DecisionReport 或 Decision Thread。
- 当前服务只用于读取和导出已有用户数据。

### Phase 1：建立干净骨架

- 新 Git root、新数据库、新 Alembic base、新 Compose project。
- 只建立 shared contracts、health/readiness、结构化日志和测试基础。

### Phase 2：AgendaScope Evidence

- 迁移只读连接、Source/Article/Topic/Event 投影和来源核验。
- 建立 `ResearchCase + EvidenceSelection`，不创建 World/Scenario。

### Phase 3：MiroFish Runtime

- 先接 Project/Graph、single `simulation_requirement`、config generation 和一次真实 Simulation。
- 明确是迁移 MiroFish 模块、封装其服务，还是通过稳定 API 调用；不能只复刻 UI 名称。

### Phase 4：MatrAIx Population

- 导入 Dataset/Persona/Cohort。
- 把 Cohort 映射为 MiroFish/OASIS profile 输入，不引入 Scenario variant。

### Phase 5：Report 与 Interaction

- 接 MiroFish ReportAgent 和 Agent Interview。
- 再逐项接入 MatrAIx evaluation tasks。

### Phase 6：数据迁移与验收

- 只迁移 AgendaScope read model、授权允许的 MatrAIx Persona 数据和明确属于 MiroFish 的运行产物。
- 不迁移 ADC Scenario/Experiment/Decision/Comparison 数据。

## 第一条验收切片

```text
选择 1～5 条 AgendaScope 文章
→ 创建 ResearchCase
→ 写一个 simulation_requirement
→ 绑定 1 个 MatrAIx Cohort
→ 生成 MiroFish simulation config
→ 运行 1 次 OASIS simulation
→ 保存 actions/platform artifact
→ 生成 1 份 MiroFish report
→ 对 1 个 Agent 发起 1 次 interaction
```

成功标准：全过程不存在 `baseline`、`alternative`、`variant`、`paired_delta`、`decision_thread` 或 `DecisionReport V2` 对象；每个对象都能追溯到三方来源之一或明确标注的全新胶水代码。

## 开始实施前唯一需要确认的选择

严格“不掺杂 ADC”意味着不能继续使用当前 ADC Git 根。建议在 `/Users/ssyb/Workspace/web/` 下建立一个全新的 SandOwl clean-room 仓库，同时把当前仓库保留为只读审计来源。若只在当前仓库原地删改，可以去除运行时功能，但无法去除 Git 血缘，不能称为严格 clean-room。
