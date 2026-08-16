# SandOwl AI Decision Center

## Register

product

## Users

面向持续跟踪政策、媒体与现实环境的研究员、分析师和决策团队。用户通常在信息密集、时间有限的工作场景中，需要把外部证据转化为可复核的世界状态，再比较多种干预方案，而不是浏览一个展示型网站。

## Product Purpose

Survey、Chat、Web、Linux 均以最多五次、保留旧失败记录的不可变 attempt 谱系实现本地恢复；它不冒充 Harbor retry、执行器或 reward 系统。

AgendaScope 首发观察只保存成功的正向判断、精确文章引用、实体投影与模型版本；不保存模型推理，不声称证明全网不存在更早表述，缺失或非法发生日期不会被猜测补齐。

SandOwl 的产品方向是将媒体与政策证据、世界模型和 OASIS 群体实验收敛为一条决策工作流：先建立可追溯的现实依据，再构造情景、运行对照实验，最后产出带证据链和不确定性说明的决策报告。成功标准是用户能够清楚回答“依据是什么、假设是什么、实验观测到了什么、结果的限制是什么”。

当前 Core 已接通持久 Decision Thread、AgendaScope 媒体证据、不可变世界快照、由快照直接计算的证据世界图、千问 evidence-backed 语义世界图、有界 World Slice 与证据发布时间线、Scenario、MatrAIx Persona World/Cohort、capability 驱动的 Task Gallery、OASIS 有界语义 Playground、真实 Trial 互动图、MatrAIx Survey，以及基于 comparison 的持久章节式 Findings、Markdown 导出、绑定同一快照语义图且最多五轮的证据追问链和绑定 Report/Cohort/Persona 的合成 Persona 证据访谈（单人或 2～8 人原子会话），不包含 Company 主体、企业关系链或 GTV。直接证据图只表达 Snapshot、Article、Source、Country 的可证明关系；千问图只保存能够逐字回指冻结文章的实体与关系；World Slice 只查询已封存图的有向 1～3 跳邻域；Evidence Timeline 只按冻结文章发布时间组织对象，不冒充事实生效时间；运行互动图只表达已记录的模拟事件；Decision Report 只封存可复算配对计数、限制和来源哈希，不生成“最佳方案”。Survey 只聚合成功 Persona 的精确选择、Likert 统计和原始理由，不把 synthetic responses 解释为真人研究。Trial Archive 已统一 Survey/Chat/Web/Linux 的持久 Trial；Batch Registry 可不可变登记 Survey/Chat/Web/Linux 的 sealed parent，但原子 native launch 仍只支持 Survey/Chat。Linux parent 是对一个真实固定 Linux Trial 的内容寻址封存，不是 Cohort 别名或 Harbor Job。两者都不冒充 Harbor 执行器或 reward 系统。Chat detail 提供由真实 transcript 严格派生、内容寻址的 ATIF-v1.7 projection，并明确不含未记录的 reasoning、工具调用、reward 或 Harbor 原生遥测。语义世界图默认使用 PostgreSQL 自建存储，可选阿里云 GDB，Zep Cloud 仅保留为兼容 Provider；前端 ECharts/现有 SVG 不承担图谱后端职责。政策数据领域、事实有效期/混合检索、MiroFish 完整自主规划 ReportAgent 工具链、MatrAIx Harbor launch/retry/verifier/artifact 执行面，以及 Decision Thread 的协作权限与审计仍是待整合范围。

Persona 证据访谈是当前已接通的 MiroFish 交互切片：它冻结绑定 Report、Cohort、Persona profile 与模型配置，支持单人追问和 2～8 人同问题会话，只允许引用固定报告章节，并始终标注为 synthetic perspective。报告页同时提供固定的证据脉络与对照边界叙事镜头，复用同一内容寻址问答队列与逐字引用，不接 Zep、不做预测。MatrAIx Chat 已以固定 Acme REST 与 MCP 两个 source sample 接通真实 sidecar、多轮 transcript 和严格自述反馈，固定 Web quote-choice source sample 也已接通隔离 Playwright 执行器，但尚未泛化为用户自定义 Chat、任意 MCP 或任意网址。完整自主 ReAct ReportAgent 与运行中 Agent IPC 仍未接通。

## Brand Personality

冷静、可信、前瞻。保留 MatrAIx 数字世界与任务驾驶舱的现代感，但所有视觉表达都服务于分析、比较和判断，不制造虚假的确定性。

## Anti-references

- 不做传统 BI 的组件堆叠和无差别指标墙。
- 不做营销站式的大字、渐变、玻璃卡片和装饰性动效。
- 不把 AgendaScope、MatrAIx、MiroFish 暴露成三个需要用户理解或分别进入的产品。
- 不沿用旧版线性五步向导作为全局信息架构；步骤只用于确实有先后依赖的单次任务。

## Design Principles

1. 证据先于结论：每项判断都能回到来源、时间和处理状态。
2. 一个工作台、一条任务主线：采集、建模、实验与报告共享上下文。
3. 对照优于单次结果：默认呈现基线、备选方案、配对观测和不确定性。
4. 渐进披露复杂度：先给出当前决策所需内容，再允许专家下钻。
5. 能力边界透明：明确区分真实数据、推断、模拟结果和人工判断。

## Accessibility & Inclusion

以 WCAG 2.2 AA 为基线；正文和状态信息满足对比度要求，所有交互支持键盘与清晰焦点，状态不只依赖颜色，数据图表提供文本等价信息，并尊重减少动态效果的系统设置。
