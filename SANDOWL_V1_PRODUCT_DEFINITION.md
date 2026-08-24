# SandOwl V1 Product Definition

状态：Phase 4 产品定义基线  
日期：2026-08-16  
依据：两个已完成的 Vertical Slice、当前产品代码、Decision Thread 与 DecisionReport V2 数据契约

## 1. 本阶段结论

SandOwl V1 应定义为：

> 面向研究员与分析师的 evidence-bound scenario experimentation workspace。它把经人工确认的现实证据冻结为可追溯上下文，让用户比较一组明确标注为 synthetic assumptions 的方案，并输出不越过观测边界的 DecisionReport。

V1 的产品单元不是一篇媒体文章、一个 Agent、一次 Trial 或一份孤立报告，而是一条可恢复、可追加修订的 **Decision Thread**。

当前两个 Vertical Slice 已经证明同一条领域链路能承载政策/规则与企业沟通/舆情两类问题。它们证明的是运行链路和数据契约的泛化，不是市场需求、现实预测能力、因果效度或商业建议能力。因此 Phase 4 的主要任务是验证目标用户和工作流，而不是继续增加第三类 synthetic demo 或扩展 Agent runtime。

## 2. 产品定位

### 2.1 产品承诺

用户带着一个有边界的决策问题进入系统，最终得到一份可以回答以下问题的封存产物：

1. 依据了哪些现实来源？
2. 哪些内容是人为设定的实验假设？
3. 实验使用了什么 Persona、模型、配置和运行边界？
4. 实际持久化了哪些 synthetic observations？
5. 基线与备选方案出现了哪些可复算差异？
6. 哪些解释被允许，哪些结论没有被证明？

### 2.2 V1 不是什么

V1 不是：

- 现实预测系统；
- 自动选择“最佳方案”的优化器；
- 真人消费者、员工、工会或公众研究的替代品；
- 通用 Agent framework、Agent OS 或自主研究组织；
- 全自动事实核查、政策采集或实时舆情处置平台；
- MatrAIx、MiroFish 与 AgendaScope 三套产品的聚合入口。

“AI Decision Intelligence OS”可以保留为长期方向，但不能作为 V1 已经兑现的产品承诺。

## 3. 目标用户假设

以下用户定义是待验证假设，不是已经获得市场证明的事实。

### 3.1 第一目标用户

**持续跟踪政策、媒体和外部环境，并需要向团队提交可复核情景分析的研究员或分析师。**

典型环境：

- 企业战略、公共事务、政策研究、风险研究或专业咨询团队；
- 信息密集且时间有限；
- 已经会收集资料和构造方案，但缺少把 Evidence、Assumptions、Experiment 与 Limitations 固定在同一产物中的工具；
- 能理解模拟的边界，不要求系统给出确定预测。

### 3.2 参与角色

| 角色 | V1 中的职责 |
| --- | --- |
| Analyst | 建立问题、选择证据、构造 alternatives、运行实验、解释观测 |
| Research lead / reviewer | 检查来源、假设边界、实验配置与 limitations，决定报告能否进入内部讨论 |
| Decision stakeholder | 阅读和引用报告，但不直接配置底层 runtime |

V1 首轮验证应优先服务 Analyst；reviewer 是必要的第二阅读者；stakeholder 不是首要操作用户。

### 3.3 暂不作为第一用户

- 希望系统直接给出交易、投资、法律或公关建议的决策者；
- 需要实时大规模社交网络预测的运营团队；
- 需要自定义任意工具、任意网站或任意 Agent workflow 的开发者；
- 只需要媒体浏览、传统 BI dashboard 或通用聊天问答的用户。

## 4. 核心 Job To Be Done

> 当我需要在有限时间内比较一个现实议题下的几种干预方案时，帮助我把已确认的证据、明确的假设、可审计的合成实验和解释限制绑定起来，使我能向同事提交一份可复核的讨论材料，而不是一段无法追溯的 AI 结论。

辅助 jobs：

- 当来源或假设变化时，保留旧版本并创建新的 Decision Thread revision；
- 当同事质疑结论时，快速回到 snapshot、scenario、trial events 和 hashes；
- 当证据不足时，让报告明确暴露“不知道”和 simulation boundary；
- 当报告被导出后，仍保留稳定 Report ID 与内容 hash 以便引用和核验。

## 5. V1 主工作流

```text
提出一个有边界的决策问题
  → 选择并人工确认 Evidence
  → 冻结 WorldSnapshot
  → 创建 baseline 与 1～2 个 alternatives
  → 选择已冻结的 Persona Cohort
  → 运行有界 Semantic Experiment
  → 核对 Trial 状态与 persisted events
  → 生成并复核 DecisionReport V2
  → 导出、分享或追加 Decision Thread revision
```

### 5.1 工作流完成条件

一次 V1 workflow 只有在以下条件同时满足时才算完成：

- Evidence 与 synthetic assumptions 可被用户清楚区分；
- WorldSnapshot、Scenario、Cohort 和 Experiment 均已封存；
- Trial 结果和失败状态保持真实，不人工补造；
- Observation 计数能与 persisted events 对账；
- DecisionReport V2 七章节完整且可下载；
- Report ID、hash 与上游资源身份可见；
- Analysis 不输出预测、因果或最佳方案；
- Limitations 明确说明 sample、synthetic inputs、model 和 simulation boundary。

## 6. V1 范围

### 6.1 V1 核心能力

| 能力 | V1 决策 | 当前状态 |
| --- | --- | --- |
| Decision Thread | 核心产品对象，组织一项决策的追加式上下文 | 已存在，需在主路径中前置 |
| Media / policy evidence | 允许研究员选择、阅读并人工确认来源 | 已存在 |
| WorldSnapshot | 冻结已确认 evidence 与内容身份 | 已存在 |
| Scenario | baseline + 1～2 alternatives，synthetic 标签强制保留 | 已存在 |
| Persona Cohort | 从已验证 dataset 选择有界 cohort | 已存在 |
| Semantic Experiment | 有界 variants × seeds × rounds 运行 | 已存在 |
| Observation audit | Trial 状态、events、计数和时钟边界可核验 | 已存在，展示口径需澄清 |
| DecisionReport V2 | 七个 typed sections、不可变 hash、Markdown 导出 | 已存在 |
| Revision / provenance | 保存旧资源并允许新的 Decision Thread revision | 基础能力已存在 |

### 6.2 V1 支撑能力，但不作为主导航承诺

- evidence graph、semantic graph、World Slice 与 timeline；
- report evidence Q&A；
- Persona evidence interview；
- Survey；
- fixed-sample Chat、Web、Linux evaluation；
- Task Gallery、Trial Archive 与 Batch Registry；
- bounded ReportAgent evidence draft。

这些能力可以保留给专家下钻或内部验证，但不能让首轮用户误以为必须理解并经过每个模块才能完成一项决策。

### 6.3 明确延期

- Worker M2、queue/lease 重构、autoscaling；
- 通用 Agent、planner、memory、reflection 或 self-evolution；
- 自主 ReAct ReportAgent；
- 新 Persona generator；
- 任意网址、任意 MCP、通用 Computer Use 或 Harbor runtime；
- 自动政策采集、自动事实裁决和现实有效期推断；
- 现实预测、推荐排序和“最佳方案”；
- 企业实体库、关系链、GTV 或行业知识平台扩张；
- 在真实用户需求出现前增加第三个 synthetic Vertical Slice。

## 7. 产品信息架构决策

现有十个工作区证明了组件能力，但不是理想的 V1 用户心智。V1 应采用“双层结构”：

1. **主层：Decision Portfolio / Decision Thread**  
   用户从一个问题进入，看到 Evidence、World、Scenario、Cohort、Run、Report 的当前状态和下一步动作。
2. **专家层：能力工作区**  
   Media、Policy、World、Persona、Task Gallery、Playground 和 Reports 继续存在，作为选择器、编辑器与核验工具，由 Decision Thread 深链进入。

这不是要求立即重写导航。首轮 pilot 可以使用现有页面，但必须记录用户在哪些模块之间迷失、何时需要工程人员提供 ID 或解释下一步。只有观察到稳定阻塞后，才实现 guided Decision Thread flow。

当前产品缺口：Decision Thread 在 UI 中从已封存 Scenario 开始创建，概念上却应从“问题 + evidence context”开始；Report 也主要通过 Experiment 间接进入 Thread。V1 pilot 应验证这一缺口是否真实阻碍用户，再决定最小 contract/UI 扩展，不能先行重构所有工作区。

## 8. 输出与语言边界

### 8.1 V1 主输出

V1 的标准交付物是 DecisionReport V2，而不是聊天回答。标准章节固定为：

1. Evidence
2. Assumptions
3. Experiment
4. Observation
5. Comparison
6. Analysis
7. Limitations

### 8.2 允许的表达

- “本次运行观察到……”
- “同一 seed 下的计数差异为……”
- “该差异包含一条 scenario initial post……”
- “结果受单 seed、Persona 数量与模型行为限制……”

### 8.3 禁止的表达

- “现实中将会……”
- “该方案导致……”
- “这是最佳方案……”
- “这些 Persona 代表消费者/员工/公众……”
- “媒体 evidence 已被系统独立证实……”

## 9. Phase 3 遗留问题处置

| 问题 | V1 判定 | 本阶段处置 |
| --- | --- | --- |
| Observation 显示 `posts 0`，未展示 scenario initial post | 验证前必须修复的计数表达问题 | 同时展示“场景初始帖”和“模拟生成帖”，不改底层计数 |
| Report UUID 在 UI 不明显 | 验证前必须修复的追溯问题 | 在 V2 正文与 provenance 中明确显示 Report ID 和 SHA-256 |
| 新 Cohort 与旧 Cohort 同成员但 hash 不同 | 不是数据错误；现有 `cohort_sha256` 是包含 title 的完整资源内容身份 | 文档明确区分 dataset hash、Persona profile hashes、成员顺序与 cohort resource hash；V1 不修改 hash 算法 |
| 单 round 未模拟“七天后更新” | 实验设计边界，不是 runtime 缺陷 | 保持在 Limitations；只有目标用户提出跨阶段问题时才设计新的实验能力 |

不新增 `membership_hash` 字段。若 pilot 中用户确实需要跨 Cohort 比较相同成员，先用现有 dataset hash、ordered Persona IDs/profile hashes 形成展示层比较，再评估是否需要正式 contract。

## 10. 首轮真实用户验证

### 10.1 验证问题

首轮 pilot 只回答四个问题：

1. 目标 Analyst 是否真的需要把 Evidence、Assumptions、Observation 和 Limitations 固定在同一产物中？
2. 他能否在不依赖数据库、脚本或手工抄 ID 的情况下完成主工作流？
3. Reviewer 能否正确理解报告证明了什么、没有证明什么？
4. 完成一次任务后，团队是否愿意把下一项真实问题也放进 SandOwl？

### 10.2 招募与任务

建议招募 5 名符合第一目标用户描述的参与者，至少覆盖企业/咨询研究与政策/公共事务研究两种环境。数量是形成早期可用性信号的 pilot 规模，不用于统计推断。

每位参与者完成两段任务：

1. **引导任务**：使用一个已准备且无敏感信息的案例，理解 Evidence 与 synthetic assumptions 的边界；
2. **自带问题任务**：参与者带来一个真实但允许进入测试环境的有界问题，自行选择 evidence、构造 baseline/alternatives 并复核报告。

不在未经授权的情况下导入机密、个人数据、付费受限内容或真实企业内部材料。模型调用费用和数据处理边界应在任务开始前明确。

### 10.3 观察指标

| 指标 | 如何记录 |
| --- | --- |
| Completion | 是否在无工程人员操作数据库/脚本的情况下生成 sealed V2 |
| Time to first sealed report | 从明确问题到 V2 封存的实际时间，分段记录 Evidence、Scenario、Run、Review |
| Boundary comprehension | 用户能否用自己的话区分 Evidence、Assumptions、Observation、Analysis、Limitations |
| Provenance recovery | Reviewer 能否从报告回到 snapshot、scenario、trial events 和 Report ID/hash |
| Navigation friction | 错误入口、返回、寻找 ID、询问“下一步是什么”的次数与位置 |
| Interpretation errors | 是否把 event count、Persona 或 delta 误读为参与度、现实代表性、因果或预测 |
| Reuse intent | 用户是否提出下一项真实问题，并愿意再次使用或邀请 reviewer |

运行成本、queue wait、worker restart、失败类型和峰值内存继续记录，但它们不是本轮产品价值的替代指标。

### 10.4 Pilot 通过门槛

以下是进入 V1 implementation hardening 的建议 gate，不是市场规模证明：

- 大多数参与者能完成自带问题任务，且不需要工程人员直接操作底层资源；
- 所有成功报告都保持 Evidence/synthetic/observation 边界，没有生成预测、因果或最佳方案；
- Reviewer 能从 UI 恢复关键 provenance，不依赖执行报告中的手工 ID 清单；
- 至少出现明确的重复使用信号，而不只是“demo 很有趣”；
- 主要失败集中在可修复的工作流/表达问题，而不是用户认为整个实验产物没有用途。

若未达到，不继续增加 runtime 能力。先判断失败属于目标用户错误、Job 不成立、工作流摩擦、报告不可理解，还是 simulation 对任务没有决策价值。

## 11. Phase 4 实施顺序

1. 修正 Observation 计数标签和 Report identity 展示。
2. 冻结本文件作为 pilot 前产品基线。
3. 为参与者准备一页式任务说明、数据授权检查与观察记录表。
4. 进行 1 次内部 dry run，确认全流程无需数据库或临时脚本。
5. 完成首轮真实 Analyst + Reviewer sessions。
6. 按证据决定是否实现 guided Decision Thread、补充 contract，或调整目标用户。
7. 只有运行指标证明必要时才重新评估 Worker M2。

## 12. 当前仍需产品负责人决定

- 对外产品名已确定为 `SandOwl`；仓库目录、Compose project、镜像和环境变量中的 `SandOwl` / `sandowl` 继续作为内部技术标识；
- 首轮 pilot 的具体团队、数据授权人和允许使用的来源；
- 模型调用费用预算及单次任务上限；
- V1 是否只部署为内部单团队工具，还是需要认证、RBAC 与跨团队审计；
- 导出报告的保留期、分享方式和访问控制。

这些决定会影响上线与真实用户验证，但不需要通过扩展核心实验架构来提前解决。
