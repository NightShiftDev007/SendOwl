# Second Vertical Slice Design

## 选择结论

选择 **A：电动车品牌劳资争议结束后的回应节奏实验**。当前 AgendaScope 的 `/api/v2/media/articles?q=Tesla` 已经返回一组 2026-08-13 至 2026-08-16 的多来源报道，集中描述瑞典 Tesla 劳资争议/罢工结束及其后续讨论。该媒体簇足够支撑第二个 WorldSnapshot，不需要新增采集。

本案例使用 **Tesla Sweden strike media context** 作为现实证据背景，但不模拟或预测 Tesla 的真实未来行为。Scenario 中的目标主体使用虚构名称 `Northstar Mobility`，两条品牌回应文本明确标记为 `synthetic demo data`。这样既能验证品牌危机/劳资争议传播场景，也不会把合成事件包装为真实企业声明。

它与第一个“AI 生成内容水印规则变化”案例有清晰差异：第一个是政策/规则公告驱动的技术议题，第二个是企业沟通节奏和劳资争议传播议题。两者可以复用同一 WorldSnapshot、Scenario、Persona/Cohort、Semantic Experiment 和 DecisionReport 链路。新能源政策和 AI 监管政策仍可作为后续案例，但前者需要更明确的政策证据与行业参数，后者与首案同域，当前不如本案例适合验证泛化。

## Problem

### 决策问题

在一组已经冻结的劳资争议媒体证据背景下，一个研究员希望比较两个**假设性回应节奏**在受限语义实验中产生的可观察差异：

> 对一个面临长期劳资争议结束后舆论讨论的虚构电动车品牌，立即发布承认争议结束并承诺后续说明的公开回应，与先进行利益相关方核实、再分阶段更新的回应，在同一批 Persona 和同一 seed 下分别记录了哪些帖子、评论、反应和不行动事件？

这个问题只要求系统记录一次模拟环境中的行为事件和可重复的比较口径，不要求回答哪种节奏现实中更有效，也不要求预测真实员工、消费者、工会或媒体的未来行为。

### 案例边界

- AgendaScope 文章是可追溯的现实媒体 evidence；它们不是 SandOwl 独立事实核验后的判决。
- `Northstar Mobility` 是虚构的 Demo 主体，不是 Tesla 的别名，也不代表任何真实企业。
- 两个声明、时间窗口和利益相关方沟通安排都是 `synthetic demo data`。
- Persona actions 和 comparison 是 Semantic Experiment 的模拟输出，不能解释为真实劳资关系、品牌声誉或市场结果。

## Evidence

### AgendaScope 候选证据

以下候选记录在当前 SandOwl media read model 中可查，来自 Dagens Nyheter、DR Nyheder、Aftonbladet、Politiken 和 De Volkskrant 等不同来源。表中的 revision hash 是本次设计检查时 API 返回的当前值。

执行前必须再次调用 `/api/v2/media/articles/{id}`，确认文章仍可由当前 media API 读取，并把当时返回的精确 `evidence_revision_sha256` 用作 WorldSnapshot 创建请求的并发校验。snapshot item 最终持久化的是冻结内容及 `captured_text_sha256`，不是这个 selection-time revision 字段。下表不是已经 sealed 的 snapshot，也不能替代执行时的 snapshot hash。

| Article ID | Source | Published at (UTC) | Current title | Current revision SHA-256 |
| --- | --- | --- | --- | --- |
| `0889fa6e-92b9-48d8-a8d7-de5fd1332cfe` | Dagens Nyheter | 2026-08-13 14:51 | IF Metall avbryter strejken mot Tesla | `600fd9d8fe2a45ca29638ff5585595968f13bfbdbc4ff88c3e8636d20ce8e7b5` |
| `9c552d01-4756-4d30-90ba-3fcebf78a772` | DR Nyheder | 2026-08-13 14:19 | Langvarig Tesla-strejk i Sverige slutter ved midnat | `fe48ee68a3390e12c9a989914844570ded1fec28ff7a684b323b5122d0a5eac5` |
| `88b6aed5-ded5-44e2-b983-bfb3ddfb3520` | Aftonbladet | 2026-08-13 13:13 | IF Metall avbryter strejken mot Tesla | `c3b76e478d7fab0dbc9392125cd546a07278c166972e7427821f1a8bb0c5a09c` |
| `ee6d2868-8898-42c1-8375-3643ce5b91a7` | Politiken | 2026-08-13 18:19 | Forsker: Afslutning på svensk Tesla-strejke er ikke set før | `0474903aa3f8c65c156ce02d5f6cf831c0d231dff317b5bd62e1ebecea183c30` |
| `d6889945-6f2e-485e-af62-5daf008c0643` | De Volkskrant (via GN) | 2026-08-14 06:53 | Staking bij Zweedse tak Tesla stopt na drie jaar: geen stakende medewerkers meer over | `6727e740d1025e5d3be154e7def1015d5439628f0c118b02074f88e741768e19` |
| `75950a46-e45e-40df-b3a7-26c3619078ad` | Dagens Nyheter | 2026-08-14 09:50 | DN Debatt. ”Detta måste vi ta med oss efter Teslastrejken” | `51ecfde9c76a48646132ef1c8fd814bebcfe5bf754ffff447c8254484d16620d` |

### Evidence 能支持什么

这些记录可以支持以下有限陈述：

- AgendaScope 在多个时间点和来源中收录了与瑞典 Tesla 劳资争议/罢工结束及后续讨论有关的媒体文章。
- 这些文章可通过 article ID、来源、URL、时间和 revision hash 组成可审计的证据输入。
- 同一事件簇中的标题和时间顺序适合验证 WorldSnapshot 的复制、封存和 provenance。

这些记录不能支持以下陈述：

- 不能证明文章中的劳资关系、谈判结果或观点已经由 SandOwl 独立核验。
- 不能仅凭多篇文章证明存在跨媒体的因果传播链；只有 AgendaScope 的结构化传播字段明确记录的内容，才可作为相应的 imported observation。
- 不能推导 Tesla、Northstar Mobility 或任何真实品牌的员工关系、消费者信任、销量、股价或未来舆情。

文章可能是转载、评论、辩论或不同语言的报道。Report 中必须保留来源性质，不把多个标题计数当成独立事实数量。

## WorldSnapshot

### 冻结内容

创建一个新的 WorldModel 和 sealed WorldSnapshot，建议冻结上表的 5–6 条候选文章。实际 snapshot 至少保存：

- AgendaScope article ID、source name 和 original URL；
- title、冻结的 captured content/excerpt 和 country；
- published_at、captured_at 和 snapshot created_at；
- 每条冻结正文的 `captured_text_sha256`；创建请求同时使用执行时读取的 `evidence_revision_sha256` 防止选取期间发生 revision drift；
- 选取理由：罢工结束报道、跨来源确认、结束后的公共讨论；
- snapshot version、`snapshot_sha256` 和 sealed 状态。`sealed_at` 存在于数据库封存记录中，但当前 `SnapshotDetail` API 不单独暴露该字段；执行记录不应声称 API 已返回它。

WorldSnapshot 只复制和封存现实媒体 evidence，不把 `Northstar Mobility`、回应文本、Persona 分组或模拟结果写入 evidence。若执行前某个 revision 变化，必须重新选择并记录新 hash，不能静默沿用本设计表中的旧值。

### 现实数据与合成输入边界

| 内容 | 来源 | 标签 | 是否进入 WorldSnapshot |
| --- | --- | --- | --- |
| Tesla Sweden strike/劳资争议相关文章、来源、时间、URL、revision hash | AgendaScope media read model | real evidence | 是 |
| AgendaScope topic/article association | AgendaScope projection | imported observation | 可记录，但不当作独立事实判决 |
| `Northstar Mobility` 及其虚构争议背景 | 本 Demo 设计 | `synthetic demo data` | 否 |
| 两条品牌回应、公开渠道和时间承诺 | 本 Demo 设计 | `synthetic demo data` | 否 |
| Persona actions、events、metrics | Semantic Experiment/OASIS runtime | simulated observation | 否，进入 Experiment/Observation |

## Scenario

Scenario 必须绑定 sealed WorldSnapshot，并包含 baseline 和两个 alternatives。两个 intervention 文本必须显式带有 `synthetic demo data` 标记，避免被后续 UI 或报告误显示为 AgendaScope 证据。

### Baseline：不注入新的品牌回应

- Variant 名称：`baseline / no synthetic statement`
- 内容：不向环境注入新的 Northstar Mobility 公开声明，只提供冻结的媒体语境。
- 目的：记录没有本 Demo 新增品牌事件时的 Persona 动作基线。
- 计量规则：baseline 没有 scenario actor event；报告把 scenario intervention count 与 Persona response count 分开，不把 alternatives 多出的初始帖子解释为参与度提升。

### Alternative A：立即承认并承诺更新

- Variant 名称：`immediate acknowledgement with verified follow-up`
- 注入时间：`offset_minutes=0`，在第 1 round 注入。
- Intervention：`synthetic demo data — Northstar Mobility acknowledges the end of a fictional Swedish labor dispute, thanks affected workers and customers, states that it will publish a verified stakeholder update within 48 hours, and opens a public contact channel.`
- 假设边界：虚构声明模板，不是 Tesla 或任何真实公司的声明，也不代表真实法律、工会或劳动关系建议。
- 观察重点：Persona 是否创建帖子/评论、reaction 和 do-nothing 的构成，以及不同 Persona 的事件顺序。

### Alternative B：先核实、再分阶段更新

- Variant 名称：`staged stakeholder update`
- 注入时间：`offset_minutes=61`，在每轮 60 分钟的配置下于第 2 round 注入；这样测试的确包含回应时序差异，而不只是文案差异。
- Intervention：`synthetic demo data — Northstar Mobility says it is reviewing the outcome of a fictional labor dispute with local stakeholders, avoids unverified resolution claims, and promises separate worker, customer, and public updates within seven days.`
- 假设边界：虚构的谨慎沟通模板，不是对现实危机公关的最佳实践判定。
- 观察重点：在相同 cohort、seed 和 round 下，Persona 对“暂不确认、分阶段更新”的文本产生哪些可记录动作。

### Scenario 设计约束

- 三个 variant 使用同一个 sealed WorldSnapshot、同一个 sealed Cohort、同一个 prompt schema、同一个 model 和同一个 runtime 配置。
- 只改变 intervention 文本，不改变 Persona 顺序、seed、round、时间窗口或 worker identity。
- 不在 Scenario 中写入“公众将接受”“工会将同意”“声誉会恢复”等结果性断言。
- 首轮使用 2 rounds、每轮 60 minutes、1 seed：Alternative A 在第 1 round 注入，Alternative B 在第 2 round 注入；若时间允许，再用第二个 seed 复跑并分开报告，不能把少量 trial 合并成统计结论。

## Persona

### 最小 Cohort

复用首条 Vertical Slice 已验证的 MatrAIx development dataset 和 5 个既有 Persona，避免为第二案生成新人口数据，也能验证同一 Persona/Cohort 资源可跨案例复用。可重新创建新的 sealed Cohort，也可在产品支持时复用同一 sealed Cohort；无论哪种方式，都要记录实际 dataset/cohort hash 和成员顺序。

| 分析性视角 | Existing Persona | Persona ID | 使用依据 |
| --- | --- | --- | --- |
| 普通消费者视角 | Ruby Taylor | `1e059897-d1ad-439c-aa1f-ffd3b2da6be9` | 已存在于已验证 development dataset；不额外假设其职业、工会身份或汽车知识 |
| 普通消费者视角 | Noah Williams | `88a61011-0543-452d-b03d-e33cbc698415` | 已存在于已验证 development dataset；不额外假设其职业、工会身份或汽车知识 |
| 交通/运营行业视角 | Casey Brooks | `1f84c65e-bf76-4016-88e4-d6cd89fde9a4` | 冻结 profile 中有 `ind_automotive=Veteran`、`ind_logistics=Experienced`、`ind_media=Veteran` |
| 技术/行业观察视角 | Jordan Lee | `072930b8-c68c-4acf-996b-a655ab34062c` | 冻结 profile 中为 Software & AI / Engineering；只作为技术参与者视角，不推断其了解劳资谈判 |
| 媒体观察视角 | Ava Martinez | `41b9e8d3-f5e7-4915-afdb-0b916623fe4d` | 冻结 profile 中为 Media & Journalism、`ind_media=Veteran` |

“消费者”“交通/运营”“媒体观察”等是本案例的分析性映射，不写回 Persona profile，也不代表真实员工、工会、车主或媒体总体。当前 cohort 没有被声称为工会代表样本；不要为了补足这一点临时生成 synthetic Persona。

### 为什么不扩大样本

Semantic runtime 支持 1–8 个 Persona，本案例用 5 个完成跨案例链路验证。更多成员会增加 provider 成本和运行时间，但不会自动带来真实人口代表性。若后续需要评估劳资议题，应先设计有来源依据的 Persona 抽样规则，再另开实验，不把本 Slice 的 5 人结果外推。

## Simulation

### 运行方式

沿用已经验证的 Semantic Experiment/OASIS 流程，不新增模拟引擎：

1. 重新读取候选 articles，选择当前 revision 并创建 sealed WorldSnapshot。
2. 创建绑定 snapshot 的 Scenario：baseline + Alternative A + Alternative B，并封存。
3. 从现有 dataset 创建 5-persona sealed Cohort，并封存。
4. 创建 2-round Semantic Experiment，生成 3 个 trials，每个 variant 一个。
5. 使用已验证可访问的 `qwen3.7-plus` 和当前有效的 OpenAI-compatible LLM 配置，记录 model/config hash、seed、prompt schema、round 参数和 worker/runtime identity。
6. 等三个 trials 到达终态后，读取所有 persisted events，再生成 DecisionReport。

当前标准 worker 有 Semantic/Survey/Chat/Web/Linux 组合 readiness 耦合。如果 Phase 2 执行时该问题还没有处理，可以使用已经验证的 semantic-only operational path，但必须在 execution log 和 report limitation 中记录；这不是最终 worker topology，也不能把临时绕过写成产品能力。

### 预注册观察指标

本案例不重复首案中把场景干预计入总动作数的混淆。运行前固定以下口径：

- 每个 variant 的 scenario intervention event count，单独列出；
- 每个 variant 的 Persona `create_post`、`create_comment`、reaction 和 `do_nothing` 数量；
- 每个 variant 的 Persona authored content count；
- event sequence、actor kind、persona ID、round、phase 和持久化时间字段；
- baseline 与两个 alternatives 的 paired delta，明确每个 variant 只有一次 trial，即 `n=1`。

不输出或不推断：

- 工会/员工/消费者的真实立场、情绪或意见代表性；
- 媒体 reach、转发量、品牌信任、股价、销量、员工留任或谈判结果；
- 未来舆情走势、因果效应、概率或“应该采用”的回应排序。

`observed_at_raw` 与 trial 完成时间可能来自不同 OASIS/SandOwl 时钟语义。报告应分别标记 raw observation time 与 SandOwl recorded/completed time，不把它们当作同一时钟的精确传播延迟。

## DecisionReport

最终报告应按 DecisionReport V2 的七个独立区域输出；在 V2 API 尚未落地前，至少在现有 report 的 provenance/limitation 中保留以下边界，不能用一段叙述性分析替代证据和观察的独立记录。

### Evidence

- WorldSnapshot ID、snapshot version、snapshot SHA-256、created_at 和 sealed 状态；如读取数据库 `sealed_at`，需明确它不是当前 `SnapshotDetail` 字段；
- 实际冻结的 article IDs、source names、published/captured timestamps、URLs 和 `captured_text_sha256`；selection-time revision hash 只作为创建审计输入，不能假装是当前 snapshot item 已持久化的字段；
- 说明 evidence 来自 AgendaScope media read model，媒体 evidence 可追溯但未由本系统独立核验；
- 如引用 topic/article association，标记为 imported observation，不把它提升为因果结论。

### Assumptions

- `Northstar Mobility`、虚构劳资争议背景和两个回应均为 `synthetic demo data`；
- baseline 无 intervention，两个 alternatives 各注入一条合成品牌声明；
- Persona 角色是分析性映射，cohort 不代表真实员工、工会、车主或媒体总体；
- one seed/two rounds 只用于链路、时序、内容寻址和可审计性验证。

### Experiment

- experiment/trial IDs、scenario ID/hash、cohort/dataset/hash；
- Persona 成员顺序、model `qwen3.7-plus`、semantic config hash、prompt schema、seed、round 和 runtime/worker identity；
- readiness 状态和是否使用 semantic-only operational path。

### Observation

- 每个 trial 的 persisted events、actor kind、action kind、persona ID、sequence 和时间字段；
- scenario event 与 Persona event 分开计数；
- Persona authored content、comments、reactions、do-nothing 的原始汇总，不把文本自动解释成支持或反对。

### Comparison

列出 baseline / Alternative A / Alternative B 的原始 metrics 和相对 baseline 的 delta，并说明：

- paired comparison 来自同一 cohort 和同一 seed；
- 每个 variant 只有一次 trial，`n=1`；
- delta 仅描述本次运行中记录到的事件差异；
- 不因为某个 variant 的数量较高而给出“最佳回应”或策略排序。

### Analysis

只允许做证据边界内的解释，例如“本次运行中 Alternative A 的 Persona comment count 与 baseline 不同”。如果两个 alternatives 在某个指标上相同，只能写成“本次运行未观察到该指标差异”，不能写成两种沟通策略现实效果相同。

### Limitations

至少列出：5 个 development Persona、单/少量 seed、两个短 rounds、LLM/provider 非完全确定性、OASIS 网络边界、fictional brand 和 synthetic intervention、文章为媒体 evidence 而非独立事实核验、多个来源可能转载或评论、不能推断劳资关系/品牌/商业结果，以及 worker readiness 和 clock semantics 等运行限制。

## Success Criteria

第二条 Vertical Slice 的成功标准是下列资源和证据均可查询、可复核、可封存：

1. 5–6 条 Tesla labor-dispute media revisions 被复制进 sealed WorldSnapshot，并有 snapshot hash。
2. 一个 Scenario 包含 baseline + 两个 synthetic alternatives，并绑定 sealed snapshot。
3. 一个 5-persona sealed Cohort 来自现有 dataset，成员顺序和 hash 可验证。
4. 一个 Semantic Experiment 产生 3 个终态 trials，events 持久化，scenario/persona actor 可区分。
5. 一个 DecisionReport 能分别引用 Evidence、Assumptions、Experiment、Observation、Comparison 和 Limitations；如果当前 API 仍只有旧 sections，则明确标记为 V2 缺口。
6. 全部输出都没有把模拟结果包装为 Tesla、工会、员工、消费者或市场的真实预测、确定性结论或最佳方案。

## Non-goals

本案例不做：

- Tesla 或任何真实企业的责任认定、劳资法律意见、声誉评估或公关建议；
- 工会谈判结果、员工满意度、消费者信任、销量、股价或传播 reach 的预测；
- 自动判断文章真伪、立场、情绪、传播因果或影响力；
- 新的 AgendaScope collector、Persona 生成器、Agent Framework、LangChain/LangGraph 或通用 Agent 抽象；
- 为了该案例修改 SandOwl 的整体 Evidence → Experiment → Observation → Report 架构。

## Execution Result（2026-08-16）

第二条 Vertical Slice 已按设计真实执行完成，未新增采集器或模拟框架。执行前重新读取了 6 条 AgendaScope article；selection-time revision hash 与本设计表一致，随后创建并封存新资源。

| Resource | ID | Result |
| --- | --- | --- |
| WorldModel | `703cb7cb-0c97-4ec6-b107-3b7763d5b40f` | 6 条媒体 evidence |
| WorldSnapshot | `601b029d-32fb-452b-aa45-4dd8d32404c1` | SHA-256 `4846a0a4c52b839435974329faaf33f17af9bc17b6c83ab4988764884e7fd74d` |
| Scenario | `089b6b51-749b-4fea-bb82-fc55c821387d` | baseline + 2 synthetic alternatives |
| Cohort | `ebfbad03-3fbc-4280-8047-7565f4d999af` | 现有 dataset 的 5 个 Persona |
| Semantic Experiment | `107a357a-0f3a-4df2-810f-033f9934fecc` | 3/3 trials succeeded，seed `20260817`，2 rounds |
| DecisionReport V1 | `a7bd404a-50a9-49eb-9407-522cc8479b27` | sealed，四段兼容输出 |
| DecisionReport V2 | `8c9c938e-7c87-471d-9966-fc9200095ae7` | sealed，七段 typed output |

运行产生 32 个 persisted events：baseline 10、immediate 11、staged 11。Immediate intervention 是 round 1 的 sequence 1；Staged intervention 是 round 2 的 sequence 6，验证了 `offset_minutes=61` 的时序设计。

本次可复算的观测计数为：baseline authored content 6/reactions 2/do-nothing 2；immediate authored content 5/reactions 5/do-nothing 0；staged authored content 5/reactions 3/do-nothing 2。两个 alternative 的 observed action count 都比 baseline 多 1，但这 1 个事件就是各自的 scenario intervention；因此不能把它解释为参与度提升。每个 variant 仅 `n=1`，这些数值只描述本次 synthetic experiment，不支持真实品牌、员工、工会、消费者或市场结论。
