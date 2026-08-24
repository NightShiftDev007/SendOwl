# End-to-End Demo Report

执行日期：`2026-08-16`

最终状态：**Run 2 核心链路已真实跑通。** AgendaScope → WorldSnapshot → Scenario → Persona/Cohort → Semantic Experiment → DecisionReport 均产生了可查询、可审计的系统资源。3 个 Semantic trials 全部成功，系统生成并 sealed 了一份 deterministic DecisionReport。

本文只描述一次小规模 synthetic experiment 的系统观察，不是未来预测、真实总体研究、政策建议或最佳方案判断。

# Demo Case

案例名称：**AI 生成内容水印规则变化的反应实验 [synthetic demo data]**

用户问题：在固定的 AI 内容水印相关新闻证据和固定 Persona cohort 下，与保持当前信息环境相比，“立即加强水印/披露要求”及“延迟并分阶段实施”两种假设性公告，在一次受限的语义实验中分别产生了哪些可观察行为差异？

数据边界：

- 四条 AgendaScope 文章是系统中真实存在、按 revision hash 选择并冻结的媒体 evidence；
- 两条规则公告是假设性 `synthetic demo data`；
- Persona 来自现有 sealed development dataset；
- events 和 comparison 是本次 `qwen3.7-plus` Semantic Experiment 的真实系统输出；
- 输出不能外推到真实公众、企业或监管机构。

# Execution Timeline

## Runtime preparation

| 时间（UTC） | 步骤 | 结果 |
| --- | --- | --- |
| 2026-08-16T09:48Z | 复用 `ai-decision-center` 配置 | 同名 Key/Base URL 可读取，但 `qwen-plus` provider probe 返回 HTTP 401 |
| 2026-08-16T09:53Z–09:57Z | 切换为 `qwen3.7-plus` 并逐项 probe | Semantic 与 Survey tool-call probe 成功 |
| 2026-08-16T09:57Z | 启动 semantic-only worker | Semantic readiness true；model `qwen3.7-plus`；config hash `4184bdb6cad7eebbb1836ae19f005ab926d93350b4705e5b0140fef79ac58741` |
| 2026-08-16T09:58Z–09:59Z | 处理数据库写锁等待 | 精确取消两个已超时的 Run 2 POST；等待 AgendaScope sync 正常完成并释放 advisory lock |

标准 worker 的组合启动失败在 Acme Chat SUT identity 漂移，不是 Semantic 或 LLM probe。本次未修改架构，使用同一镜像临时取消 Chat/Web/Linux 的无关 probe 后执行 Semantic Vertical Slice。

## Run 2 resources

| 时间（UTC） | 步骤 | ID | 结果 |
| --- | --- | --- | --- |
| 2026-08-16T10:00:04.284336Z | WorldSnapshot | World `4d8db56f-f9cb-4d1d-b5bb-b7ef82b6917b`; Snapshot `cf045f9d-7e42-4d5c-b8dd-895769e23e4c` | HTTP 201；4 条 frozen evidence；sealed |
| 2026-08-16T10:00:13.366116Z | Scenario | `49e186d8-3918-43d6-8b55-4e6ab62e0f73` | HTTP 201；baseline + 2 alternatives；sealed |
| 2026-08-16T10:00:21.563456Z | Persona Cohort | `a40434a6-74e1-4b68-90ed-bd61d8275675` | HTTP 201；5 个既有 Persona；sealed |
| 2026-08-16T10:00:28.361016Z | Semantic Experiment | `c2884f02-3475-45e7-83ee-5e584563bdaa` | HTTP 202；3 trials；seed `20260816`；input sealed |
| 2026-08-16T10:00:34.068186Z | Immediate trial | `1be9842f-fa3b-4272-b38d-eafa2e9e1882` | succeeded；6 events |
| 2026-08-16T10:02:09.527079Z | Baseline trial | `5c6a66b0-86c4-45a3-8650-f6bb7b763158` | succeeded；5 events |
| 2026-08-16T10:03:44.501772Z | Phased trial | `dfa62cfa-3fed-4877-81c2-96e730ac4468` | succeeded；6 events；experiment succeeded |
| 2026-08-16T10:04:07.350238Z | DecisionReport | `37384e5e-798c-4b3c-8bda-e2502252e52a` | HTTP 201；deterministic report；sealed |

# Evidence

## WorldSnapshot identity

- Snapshot version：`1`
- Snapshot SHA-256：`875845e88e63585a171f44ab22d214a04e989a8c8306cbcdec062c232d88ff68`
- `created_at` / `sealed_at`：`2026-08-16T10:00:04.284336Z`
- Verification：`human_confirmed`
- Evidence count：4

| Article ID | Source | Published at | Captured text SHA-256 |
| --- | --- | --- | --- |
| `d521ebfa-e188-4368-833b-134d6ca2e19e` | ARY News | 2026-08-15T15:42:26Z | `550d4ae33823a891c23435d80bd8590bf69cad0a46acad64fead52bec4893b75` |
| `5f6c48d8-1f9e-4ada-b1e4-9ee2296fade9` | Proto Thema | 2026-08-14T09:05:00Z | `ddb09111d268a210f51292876d0ba88c8c35b6bbd86987c7ec062c34a1b77760` |
| `10b2e2df-ed1a-4f77-964d-23878227672d` | Dawn | 2026-08-12T10:48:57Z | `42f2bae8da5462c6b8b783e62af5359ebd073b9e22a8074a4fe3b42c6488545b` |
| `4e917480-7109-4d7e-a2ba-194bc827ecff` | Times of India | 2026-08-13T05:53:46Z | `16b8f96400781bf2da5c278fbad96a4ae82d25a676a275a2a96b02b345c07cbf` |

这些记录证明媒体内容在系统中存在并被冻结，不证明文章陈述已被独立事实核验。

# Scenario

- Scenario SHA-256：`7f8a5d8bd617f698c5d1c8fcfad98ecb9b8b804fd0ce673fec683829db8df069`
- 绑定 snapshot SHA-256：`875845e88e63585a171f44ab22d214a04e989a8c8306cbcdec062c232d88ff68`
- `created_at` / `sealed_at`：`2026-08-16T10:00:13.366116Z`

| Role | Variant ID | 定义 |
| --- | --- | --- |
| Baseline | `40e8d1eb-6400-435b-a5d6-b691a4d483aa` | 不注入新公告 |
| Alternative | `e162a4e0-3ae1-4a2b-8d3a-28421aeeeded` | 立即水印与披露要求；1 条 synthetic intervention |
| Alternative | `ce87362e-790a-4dfa-8cb2-3c99942a3739` | 90 天试点后分阶段实施；1 条 synthetic intervention |

# Persona / Cohort

- Cohort SHA-256：`c4919a5a84863b5352ad111c2465dc89ed2eceff3cc9ca727b83a4c6044f8d8b`
- Dataset ID：`370c75f4-39d4-498b-922f-944d53df596b`
- Dataset SHA-256：`e5257c144450b65ffd6022408bdcb38b455539389846fd55d6fa9f716db03e79`
- `created_at` / `sealed_at`：`2026-08-16T10:00:21.563456Z`

冻结顺序：Ruby Taylor、Noah Williams、Jordan Lee、Casey Brooks、Ava Martinez。成员被分析性映射为 2 个普通用户视角、2 个行业参与者视角和 1 个观察者视角；该映射不是源数据标签，也不表示人口代表性。

# Experiment Observation

## Experiment identity

- Experiment ID：`c2884f02-3475-45e7-83ee-5e584563bdaa`
- Experiment SHA-256：`8af114dabfcbe47a12c698d612667fa909f9adbd0c63ec107c6a4f6041a1fec9`
- Model：`qwen3.7-plus`
- Semantic config SHA-256：`4184bdb6cad7eebbb1836ae19f005ab926d93350b4705e5b0140fef79ac58741`
- Prompt schema：`matraix-semantic-profile/v1`
- Seed：`20260816`
- Rounds：1
- Minutes per round：60
- Final status：`succeeded`

## Trial observations

| Variant | Trial ID | Persona actions | System result counts |
| --- | --- | --- | --- |
| Baseline | `5c6a66b0-86c4-45a3-8650-f6bb7b763158` | 3 `create_post`、2 `do_nothing` | observed 5；authored 3；reaction 0；do nothing 2 |
| Immediate | `1be9842f-fa3b-4272-b38d-eafa2e9e1882` | 4 `create_comment`、1 `dislike_post`，另有 1 synthetic scenario post | observed 6；authored 4；reaction 1；do nothing 0 |
| Phased | `dfa62cfa-3fed-4877-81c2-96e730ac4468` | 4 `create_comment`、1 `dislike_post`，另有 1 synthetic scenario post | observed 6；authored 4；reaction 1；do nothing 0 |

`observed_action_count` 包含 scenario intervention event；`authored_content_count` 使用系统的 Persona 内容计数口径。本文不把评论文本自动分类为支持或反对。

# Comparison

系统 comparison 状态：`complete`。所有 delta 都来自同一 seed 的成功 baseline/alternative pair，`n=1`。

| Metric | Baseline | Immediate | Immediate Δ | Phased | Phased Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| observed action count | 5 | 6 | +1 | 6 | +1 |
| authored content count | 3 | 4 | +1 | 4 | +1 |
| reaction count | 0 | 1 | +1 | 1 | +1 |
| do nothing count | 2 | 0 | -2 | 0 | -2 |

这只说明本次运行中两个带 initial post 的 alternatives 与没有初始帖的 baseline 产生了不同的动作构成。两个 alternatives 的聚合计数相同，系统没有据此判定其语义效果相同，更没有选择“最佳方案”。

# Decision Report

- Report ID：`37384e5e-798c-4b3c-8bda-e2502252e52a`
- Report SHA-256：`843fc66bba09064cb4a329a52ae6fe0c23dd91391402977297b6b796ba9553a0`
- Generator：`deterministic-findings/v1`
- `created_at` / `sealed_at`：`2026-08-16T10:04:07.350238Z`
- Sections：范围与问题、配对观测差异、解释限制、来源与完整性

系统报告真实引用了 Scenario、Cohort、Dataset、Experiment、Model、Semantic config 和 prompt schema hashes，并输出上述 paired metrics。它没有预测未来、给出确定性结论或推荐最佳方案。

# Limitation

1. 5 个 development Personas、单 seed、单 round 只适合链路验证；
2. Provider 行为具有非确定性，记录 seed 不保证 provider-level reproducibility；
3. OASIS 环境没有真实社交网络，agents 只观察推荐内容；
4. alternative 比 baseline 多一个 synthetic initial post，`observed_action_count` 的 +1 不能直接解释为更高参与度；
5. 系统没有推断 stance、reach、persuasion、business impact 或 decision verdict；
6. 媒体 evidence 是可追溯来源，不是独立事实核验；
7. 当前 DecisionReport 没有独立的 Evidence 和 Experiment Observation 章节，只通过 provenance hashes 和 comparison metrics 间接表达；
8. OASIS `observed_at_raw` 使用模拟环境时间，与 SandOwl `recorded_at` / trial completion time 不在同一时钟语义，消费端必须区分。

# Architecture Validation

| 组件 | 状态 | 验证结果 |
| --- | --- | --- |
| AgendaScope | **通过** | 四条精确 media revisions 可查并冻结；同步正常完成 |
| WorldSnapshot | **通过** | sealed、content-addressed、完整 frozen content 可读 |
| Scenario | **通过** | baseline + 2 alternatives；绑定精确 snapshot hash |
| Persona | **通过** | 5 个既有 Persona；Cohort 成员顺序和 hash 冻结 |
| Simulation | **通过** | `qwen3.7-plus`；3/3 trials succeeded；17 events 持久化 |
| Report | **通过，存在内容缺口** | sealed DecisionReport 已生成；comparison/provenance 完整，但缺独立 Evidence/Observation sections |

核心技术链路已经真实运行。报告内容契约仍需补齐，才能完全满足目标中的四段式 DecisionReport。

# Problems Found

## Bugs / runtime defects

1. **组合 readiness 耦合：**标准 worker 要求 Semantic、Survey、Chat、Web、Linux 全部 probe 成功；Acme Chat SUT identity 漂移会连带阻止完全无关的 Semantic runtime 上线。
2. **辅助镜像/契约漂移：**当前 Acme Support service identity 与 worker 冻结 contract 不一致；本 Demo 需要 semantic-only operational workaround。
3. **写锁体验：**AgendaScope 周期同步持有全局 advisory lock 时，World create POST 会无响应等待；客户端超时后服务端会话仍排队，存在稍后重复创建风险。本轮精确取消了两个等待会话。
4. **时间语义不清：**部分 `observed_at_raw` 晚于 trial `completed_at`，而 `recorded_at` 正常；API 没有清楚解释两种时钟。

## Missing capability

1. 当前 DecisionReport 固定为 scope / comparison / limitations / provenance，没有独立 Evidence 与 Experiment Observation sections；
2. 新 ReportAgent 代码尚未进入运行态，数据库仍停在 migration `0032`，工作区 head 已到 `0040`；
3. WorldSnapshot `human_confirmed` 没有 verifier identity 或 `agent_prepared/human_approved` 两阶段审计状态；
4. SandOwl 不会自动、安全地从 sibling project 选择性加载 LLM 配置。

## Data issues

1. Proto Thema 冻结正文包含站点推广噪声；
2. Cohort 的角色分类是 Demo 映射，不是数据集原生标签；
3. 两个 alternatives 的 aggregate metrics 完全相同，单 seed 无法衡量差异稳定性；
4. 评论文本存在可读差异，但当前 comparison 不做 stance 或 theme extraction，这是刻意的能力边界。

## Manual steps

1. 从 `ai-decision-center/.env` 选择性复制 Key/Base URL，并人工选择可访问模型 `qwen3.7-plus`；
2. 因标准 worker 的 Acme contract drift，临时启动 semantic-only worker；
3. 在 AgendaScope sync 释放 advisory lock 后重提 World 创建。

# Next Recommended Step

优先修复 **worker readiness 域耦合 / Acme SUT identity 漂移**：让 Semantic worker 能在 Chat/Web/Linux 独立失败时仍按自己的已通过 probe 上线，或把不同执行域拆成明确的独立 worker 进程配置。修复后用标准 Compose worker 重跑现有 Experiment 的一个新 seed，确认不再需要 semantic-only 手工步骤。

随后再做一个最小的 DecisionReport 契约扩展，把 sealed evidence summary 和 trial observation summary 纳入系统报告，同时保留现有 comparison 与 limitations，禁止加入预测或最佳方案结论。
