# SandOwl Vertical Slice Demo Case Design

## 选择的案例

**D：AI 生成内容水印规则变化的反应实验**（与候选 B“AI 监管政策变化影响模拟”同域，但把范围收窄到内容标识/水印规则）。

这是一个链路验证案例，不是政策预测或商业决策模型。它只回答：在同一份冻结证据、同一批 Persona 和固定 seed 下，不同的**假设性规则公告**是否能被 SandOwl 转换为可审计、可比较的实验观察。

## 为什么选择这个案例

1. 当前 AgendaScope 导入数据中已经存在同一事件簇的多条文章，包括欧盟 AI 内容标识规则、Anthropic 水印、用户反弹及监管数据请求，不需要新增采集。
2. 当前 Scenario 模型原生支持一个 baseline、最多五个 alternatives，以及按时间偏移冻结的 Reddit `initial_post` intervention；本案例可直接映射为三条路径。
3. 当前 Persona 数据集和 Cohort API 可提供 5 个既有 Persona，不需要生成大规模人口数据。
4. 当前 Semantic Experiment 原生支持 baseline 与最多两个 alternative 的笛卡尔实验，并保留 experiment、trial、seed、event 和 comparison。
5. 当前 Decision Report 能从已完成的 Semantic Experiment 生成 Evidence、Observation、Comparison 和 Limitation 类型的审计结果。
6. 案例规模可以限制为 5 个 Persona、3 个 variant、1 个 seed、1 个 round，适合在一天内验证。

## 用户问题

> 在固定的 AI 内容水印相关新闻证据和固定 Persona cohort 下，与保持当前信息环境相比，“立即加强水印/披露要求”及“延迟并分阶段实施”两种假设性公告，在一次受限的语义实验中分别产生了哪些可观察行为差异？

这个问题刻意不问“未来会怎样”“哪个方案最好”或“真实社会支持率是多少”。输出只能描述这次受限实验中发生的事件。

## WorldSnapshot

WorldSnapshot 使用当前 AgendaScope 媒体导入中的以下精确 article revision：

| Article ID | 标题 | 来源 | 发布时间 | 冻结用途 |
| --- | --- | --- | --- | --- |
| `d521ebfa-e188-4368-833b-134d6ca2e19e` | Claude watermark backlash drives users to cancel subscriptions | ARY News | 2026-08-15T15:42:26Z | 用户反弹背景 |
| `5f6c48d8-1f9e-4ada-b1e4-9ee2296fade9` | Νέοι κανόνες στη χρήση Τεχνητής Νοημοσύνης από την ΕΕ... | Proto Thema | 2026-08-14T09:05:00Z | 欧盟 AI 内容标识规则背景 |
| `10b2e2df-ed1a-4f77-964d-23878227672d` | Anthropic unveils AI watermarks to comply with EU law | Dawn | 2026-08-12T10:48:57Z | 企业合规措施背景 |
| `4e917480-7109-4d7e-a2ba-194bc827ecff` | European regulators seek Claude usage data from Anthropic, upsetting some users | Times of India | 2026-08-13T05:53:46Z | 监管与用户信任背景 |

创建时传入每条文章当前的 `evidence_revision_sha256`，由 WorldSnapshot 保存 source、URL、title、captured text、source timestamp、capture timestamp 和 revision digest，并生成整个 snapshot 的 `snapshot_sha256`。只使用 sealed snapshot 进入后续步骤。

这里不把新闻标题或摘录当成事实裁决；它们只是 AgendaScope 已采集并可追溯的媒体证据。

## Scenario

Scenario 固定以下三条路径：

### Baseline：保持当前信息环境

- 不注入新公告。
- 假设：Persona 只接触冻结证据及当前环境，不额外收到规则变化信号。

### Alternative 1：立即加强水印与披露要求

- 在第 0 分钟注入一条 `scenario_actor` 的 synthetic Reddit 公告。
- 公告内容明确标记为 `synthetic demo data`，说明假设“所有面向公众的 AI 生成内容立即需要可见标识和机器可读来源信息”。
- 假设：立即生效可能改变 Persona 对透明度、隐私、使用便利和合规成本的表达。

### Alternative 2：延迟并分阶段实施

- 在第 0 分钟注入一条 `scenario_actor` 的 synthetic Reddit 公告。
- 公告内容明确标记为 `synthetic demo data`，说明假设“先开展 90 天试点，再分阶段执行内容标识要求”。
- 假设：延迟和试点可能产生与立即实施不同的表达或互动行为。

两个 alternative 都是假设性实验刺激，不是已发生政策，也不写入 evidence。

## Persona / Cohort

从当前系统中已 sealed 的 Persona dataset 选择 5 个既有 Persona，按其冻结属性映射到三类分析视角：

- 普通用户：2 人；
- 行业参与者：2 人；
- 观察者：1 人。

最终成员必须来自同一个现有 dataset，通过 Cohort API 以确定顺序 sealed。角色分类只用于解释选择覆盖面，不修改 Persona profile，不声称 Persona 代表真实人口。

如果现有 Persona 属性不足以可靠区分职业角色，则保留 5 个多样化既有 Persona，并把上述角色标签明确记录为 Demo 的分析性映射，而不是源数据事实。

## Simulation

优先运行当前 `Semantic Experiment`：

- scenario：上述 sealed Scenario；
- cohort：上述 5-persona sealed Cohort；
- variants：baseline + 2 alternatives；
- seeds：`[20260816]`；
- rounds：`1`；
- minutes per round：`60`；
- 理论 trial 数：`3`（每个 variant × 一个 seed）；
- 理论 Persona 决策机会：`15`（3 trials × 5 personas），实际事件数以运行结果为准。

实验只比较同一 seed、同一 cohort、同一 snapshot 下的归一化事件：发帖、评论、赞、踩或不行动。必须记录 experiment ID、trial ID、seed、状态、事件和 comparison；失败也作为真实运行结果记录，不替换成手工编造输出。

## Decision Report

仅在实验具有可比较的 completed trials 时调用系统的 Decision Report 生成入口。报告应包含：

1. **Evidence**：sealed WorldSnapshot 的证据身份、时间、hash 和冻结摘录；
2. **Experiment Observation**：本次 trials 中实际发生的动作与计数；
3. **Comparison**：baseline 与两个 alternatives 在同一 seed 下的差异；
4. **Limitation**：synthetic scenario、synthetic Persona、样本量、单 seed、单 round、模型依赖及媒体证据边界。

报告不得给出未来预测、确定性结论、真实总体比例或“最佳方案”。

## 证据、假设与模拟结果的边界

### 真实证据

- AgendaScope 当前数据库内上述四条媒体记录；
- 每条记录的 source、original URL、published timestamp、captured excerpt 和 revision hash；
- SandOwl 创建时 sealed 的 snapshot content、snapshot timestamp 和 snapshot hash；
- 系统实际产生的资源 ID、状态、事件、comparison 和 report 内容。

“真实”在这里表示系统中真实存在、可追溯和可复核，不表示媒体陈述已经被独立事实核验。

### 假设

- 两条政策/规则公告的文本、强度、生效时间和 90 天试点期；
- 这些公告通过 Reddit 样式 intervention 传播；
- 5 个 Persona 的视角覆盖可以用于验证技术链路；
- 一轮 60 分钟、单 seed 足以做 Demo 级对比。

所有假设性输入都标记为 `synthetic demo data`，不写入 evidence 表或伪装成 AgendaScope 来源。

### 模拟结果

- Semantic Experiment 中模型生成并被系统归一化、持久化的 Persona actions；
- 每个 trial 的 observed events、counts、status 和 failure detail；
- 系统从 completed trials 计算的 comparison；
- Decision Report 对上述证据和实验观察的受限整理。

模拟结果只描述这一次受控运行，不代表真实公众、企业、监管者或未来世界。
