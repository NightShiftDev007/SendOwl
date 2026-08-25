# SandOwl 项目交接与上下文

> M16 当前边界（优先于下文历史章节）：新工作走 `Native Media → WorldSnapshot + Semantic Graph → Research Project + AgendaContext → Cohort → SimulationContext / SimulationPlan → Simulation Run + Graph Memory → ReportAgent / Agent Interaction / Persona Interview → Project-bound Evaluation`。Scenario、Semantic Experiment、Decision Thread、DecisionReport、旧 Persona Interview、旧 Scenario Preference Survey 和 platform-smoke 均为显式历史只读。

> 状态基准：2026-08-25；分支 `main`；代码迁移 head `20260820_core_0061`。M11–M15 工程主链与 M16 发布收口均已完成；真实运行样本和独立零提示 UI 代理复验也已通过。该结论覆盖只经页面操作的产品主流程与 1440 / 768 / 390 响应式检查，不等同于外部真人研究或现实有效性验证。详见 [`m17-integration-runtime-acceptance.md`](./m17-integration-runtime-acceptance.md)。

本文是接手 SandOwl 开发时的首要上下文。它回答四个问题：项目为什么存在、当前真正完成了什么、运行环境现在有什么数据、下一阶段还需要整合什么。

产品原则见 [PRODUCT.md](../PRODUCT.md)，领域和运行架构见 [architecture.md](./architecture.md)，视觉规范见 [design.md](./design.md)。本文不复制各模块的字段级契约，字段与约束始终以代码、OpenAPI 和 Alembic 迁移为准。

## 1. 一句话定位

SandOwl 将 AgendaScope、原 `ai-decision-center`、MatrAIx 与 MiroFish/OASIS 的可复用能力整合为一个证据驱动的决策实验工作台：

```text
外部现实证据
  → SandOwl 自有媒体副本
  → 人工确认并冻结的 WorldSnapshot
  → Baseline / Alternative Scenario
  → 冻结 Persona Cohort
  → 有界合成实验与可核验 Trial
  → 比较、报告、证据问答与 Persona 访谈
```

系统的目标不是给出自动“最佳方案”，而是让用户能够回答：依据是什么、哪些是人工假设、实验实际观测到了什么、结果有哪些限制。

## 2. 项目边界与不可违反的隔离规则

### 2.1 唯一开发目标

- 所有新代码、迁移、服务、数据库表、数据卷和文档都只能位于 `/Users/ssyb/Workspace/web/SandOwl`。
- `ai-decision-center` 是正在运行的旧演示项目。不得在其中开发，不得重启、迁移、删除或修改其数据。
- AgendaScope、MatrAIx、MiroFish 和旧 SandOwl 可以作为只读来源，用于核对代码、契约和数据；不得修改其仓库、数据库或运行状态。

### 2.2 数据隔离

- PostgreSQL、Redis、OASIS artifacts、Web screenshots 和 Linux artifacts 都使用 `sandowl-*` 独立卷。
- Compose project 固定为 `sandowl`；默认入口为前端 `127.0.0.1:3200`、后端 `127.0.0.1:8210`。
- AgendaScope 媒体同步只能使用显式提供的只读源 DSN。源事务是 `REPEATABLE READ READ ONLY`，目标写入只发生在 SandOwl PostgreSQL。
- 不得复用旧项目的数据库卷、Compose project、镜像名、端口或迁移谱系。
- 任何跨项目导入必须先验证源/目标数据库身份不同；凭据不得进入日志、API 响应、业务表或 Git。

### 2.3 事实边界

系统严格区分四类内容：

1. 现实证据：导入的原始媒体内容，以及人工核对捕获的政策原文、来源、版本和效力日期。
2. 人工确认：用户选择并确认后冻结的证据快照。
3. 实验假设：Scenario baseline、alternative 和干预规格。
4. 合成输出：OASIS、Survey、Chat、Web、Linux 和 Persona Interview 的模型产物。

合成输出不得回写为现实事实，不得表述为预测、因果结论、真人研究、benchmark reward 或决策推荐。

## 3. 来源项目能力如何进入 SandOwl

| 来源 | 已整合进 SandOwl | 明确没有直接搬入 |
|---|---|---|
| AgendaScope | 来源、文章、议题、快照、传播 follower、首发表述观察；只读周期刷新；媒体地图和议题/来源档案 | 原后台账号体系；对源库的写操作；真正 CDC；所有源对象删除同步 |
| 原 SandOwl | WorldSnapshot、Scenario、Run、Decision Thread、Decision Report 的领域语义 | 企业主体、企业别名、coverage、产业链、股权链、GTV 和旧企业数据库 |
| MatrAIx | Persona dataset/Cohort、Playground 信息架构、固定 Survey、REST/MCP Chat、Web、Linux source samples、Trial Archive、Batch Registry、地球渲染原语 | 通用 Harbor runtime、任意任务/网址/MCP、桌面 OS/Computer Use、完整 verifier/reward/artifact 平面 |
| MiroFish / OASIS | OASIS 执行、关系图交互、证据图、报告问答模式、Persona 访谈模式 | Zep Cloud 必选依赖、完整自主 ReAct ReportAgent、运行中 Agent IPC、双平台长期 Agent 状态 |

Zep 已从目标架构的必选项移除。千问负责受约束的语义理解，PostgreSQL 负责图、版本、引用、内容摘要和审计事实；前端 SVG/ECharts 只负责展示。

## 4. 当前产品工作区

前端是一套统一工作台，不暴露四个来源项目各自的菜单：

| 路由 | 工作区 | 当前职责 |
|---|---|---|
| `#/overview` | 决策工作台 | 媒体态势、真实地域地球、传播与最新证据入口 |
| `#/threads` | 决策任务 | 持久 Decision Thread 和只追加资源修订 |
| `#/media` | 媒体情报 | 报道、全量议题目录、议题时间线、来源健康与来源证据档案 |
| `#/world` | 世界模型 | 证据选择、人工确认、快照版本、直接证据图和语义图 |
| `#/decisions` | 决策实验 | baseline、alternative、帖子和干预规格 |
| `#/personas` | Persona World | Dataset、Persona、Cohort 选择与封存 |
| `#/tasks` | Task Gallery | Survey、Chat、Web、Linux、Trial Archive 和 Batch Registry |
| `#/runs` | Playground | OASIS platform smoke 与有界语义实验矩阵 |
| `#/reports` | 报告 | 固定 Findings、Markdown、证据问答链和 Persona 访谈 |

## 5. 已完成整合清单

### 5.1 基础设施与工程契约

- React + TypeScript + Vite 前端、FastAPI Python 3.12 控制面、Python 3.11 OASIS worker。
- PostgreSQL 事实源、Redis 短期协调、Alembic 独立迁移谱系、Docker Compose 单栈。
- 前后端严格类型和运行时校验；外部响应不使用松散字典。
- 内容寻址、幂等创建、draft→sealed、不可变父子资源和数据库触发器守卫。
- `/health`、`/readyz`、系统 capability 目录和每种执行器独立 readiness。

### 5.2 AgendaScope 媒体整合

- 只读幂等导入到 SandOwl 自有 `media_*` 表。
- 默认关闭、显式启用的周期快照刷新，带并发锁、逐表计数、失败保留上次成功结果和脱敏错误。
- 来源、文章、议题、议题时间线、地域聚合、传播边、首发观察和来源证据档案 API/UI。
- 首页 3D 地球包含真实大陆纹理、真实国家节点和真实传播线；2D 地图使用同一 API 数据。
- 完整扫描中消失的文章只在当前媒体 API 隐藏，不删除已经冻结到证据快照的正文。

### 5.3 World / Evidence / Graph

- 1～50 篇文章的人工阅读确认和证据修订冲突保护。
- 不可变 WorldModel / WorldSnapshot，多版本读取和冻结正文哈希。
- Evidence Bundle 是 sealed WorldSnapshot 的一等只读投影，不复制第二份事实。
- bounded ReportAgent evidence run 把一个 sealed WorldSnapshot、分析目标、2～6 段有序大纲和 1～20 次工具预算内容寻址；三种只读工具只能列举该快照证据或读取其中的媒体/政策正文，每次调用追加不可变输入、结果和调用哈希。
- PostgreSQL 直接证据图：Snapshot、Article、Source、Country 及可证明关系。
- 千问 evidence-backed 语义图：实体和关系必须附带冻结正文中的精确引用。
- 有向 1～3 跳 World Slice、证据发布时间线、图搜索、关系历史、Persona 匹配和图谱来源 Cohort。

### 5.4 Scenario / Decision / Report

- 一个无动作 baseline、1～5 个 alternatives、有序帖子和干预。
- Scenario 与明确的 snapshot version 绑定，不跟随“最新版本”漂移。
- Decision Thread 将 Snapshot、Scenario、Cohort、Experiment 和 Report 组织为可恢复的只追加上下文。
- Decision Report 固定四章节，封存真实配对计数、来源哈希和限制，可导出 Markdown。
- 报告证据问答支持最多五轮父问题链；历史只用于指代理解，每轮事实仍需引用本轮冻结图谱证据。
- Persona 证据访谈支持单人追问和 2～8 人原子会话，回答只引用固定报告章节。

### 5.5 MatrAIx Population 与执行任务

- Persona dataset 严格导入、manifest/文件/档案校验、内容寻址和有序 Cohort 封存。
- OASIS platform smoke：真实 OASIS Reddit + SQLite + 手工 `CREATE_POST`，不调用 LLM。
- OASIS semantic experiment：Scenario × Cohort × Variant × Seed 有界矩阵、类型化事件和同 seed 配对观测计数。
- Survey：固定三题、逐 Persona 严格回答和精确聚合。
- Chat：固定 Acme REST/MCP source samples、真实多轮 transcript、typed self-report、内容哈希和最多五次不可变 retry lineage。
- Web：固定 Quotes to Scrape Playwright source sample、真实 DOM、三页 screenshot、引用约束选择和最多五次不可变 retry lineage。
- Linux：固定 note-to-CSV source sample、隔离非特权 runner、允许清单 artifacts、typed verifier 结果和最多五次不可变 retry lineage。
- Trial Archive：Survey、Chat、Web、Linux 四类 Trial 的统一有界目录、状态统计和 typed detail 深链。
- Batch Registry：Survey/Chat/Web/Linux sealed parent 的不可变登记，以及 SandOwl-native Survey/Chat 原子入队并立即登记；Web/Linux 不进入 native launch。Linux parent 只封存一个真实固定 Trial，不复用 Cohort 充当运行。

## 6. 当前运行环境快照

以下数据来自 2026-08-25 对 `127.0.0.1:8210` 与 SandOwl PostgreSQL 的只读核验，不是代码能力上限。

### 6.1 服务与迁移

- 后端 `/health` 和 `/readyz` 正常；数据库已连接。
- 代码与实际 PostgreSQL 均位于唯一迁移 head `20260820_core_0061`。
- Semantic、Research Survey、Chat、Web、Linux Worker 均在线并通过真实 provider/执行器身份探测；模型为 `qwen3.7-plus`。
- Compose 包含 Nginx frontend、Acme REST/MCP、固定 Chromium executor、Linux artifact runner、Rootless DinD Harbor runner、Evaluation Job Worker、Report Worker 与原生媒体采集 Worker。
- Git `main` 与 `origin/main` 一致；GitHub Actions 的 Frontend、Backend、OASIS Worker、PostgreSQL Integration 四个作业全部通过。

### 6.2 SandOwl 自有数据

| 数据 | 当前数量/状态 |
|---|---|
| 媒体来源 | 412；原生采集启用 1，两个失败验收来源已停用 |
| 媒体文章 | 48,091 |
| 议题目录 | 30,886 |
| Persona dataset | 1 个 `matraix-persona-dev-sample` |
| Persona | 200 |
| Cohort | 6；新增 1 人最小真实任务验收 Cohort |
| WorldModel / WorldSnapshot / Semantic Graph | 6 / 6 / 1 |
| Research Project / Simulation Run / Run Report | 3 / 3 / 3；3 个 Run 均成功 |
| Research Survey | 1 个父任务；5 / 5 Trial 成功 |
| Project-bound Evaluation | 3 个 Target；5 个 Job，其中 3 成功、2 失败；App 与 Web 均由失败根 attempt 重试成功 |
| 固定 Chat / Web / Linux / Batch | Chat 1 个成功；Web attempt 4 成功并保留 3 个失败 attempt；Linux 1 个成功；Batch 1 个，4 个父运行、8 / 8 Trial 成功 |

ReportAgent、Agent Interaction 与 Persona Interview 都保留开发期间失败 attempt；当前分别已有 2、2、1 个成功终态。失败记录是不可变审计事实，不应删除或改写成成功。

### 6.3 媒体同步

- 历史 AgendaScope 只读迁移已形成 409 个来源、48,081 篇文章与 30,877 个议题；该 profile 不是 SandOwl 启动前提。
- 原生采集 Worker 心跳新鲜；已启用 NASA 官方 RSS，首轮成功发现并插入 10 篇。Docker Desktop `198.18.0.0/15` 合成 DNS 代理兼容和 HTTP 304 无变化处理均使用显式、默认关闭或严格类型化的边界。
- 历史导入实现仍是“全表扫描 + changed-row upsert”，不是 CDC；除文章存在性外，其他源对象删除不传播。

### 6.4 LLM readiness

当前 OpenAI-compatible provider 配置完整，Semantic、Research Survey、Chat、Web、Linux readiness 均为 `true`，每项都有一个近期 Worker heartbeat，模型为 `qwen3.7-plus`。真实成功已覆盖原生 Simulation Run、ReportAgent、Agent Interaction、Persona Interview、Research Survey、固定 Chat/Web/Linux、四类 Batch Registry，以及 Project-bound App/Web Harbor。具体资源与失败修复见 [`m17-integration-runtime-acceptance.md`](./m17-integration-runtime-acceptance.md)。

## 7. 架构与实现原则

### 7.1 PostgreSQL 是业务事实源

- 媒体副本、冻结证据、图、任务、队列、状态、内容摘要和 provenance 都保存在 PostgreSQL。
- Redis 不是唯一事实源。
- Screenshot、SQLite 和 Linux artifacts 进入独立内容卷，数据库保存允许读取的元数据、大小和哈希。

### 7.2 不可变与可复算优先

- 外部数据先校验，再投影到严格模型。
- 每个跨阶段资源都绑定上游 ID、版本和 SHA-256。
- sealed 数据拒绝更新、删除、追加和 `TRUNCATE`。
- 网络结果不明时不自动重试创建；客户端刷新目录核对内容地址。

### 7.3 Readiness 必须反映真实执行能力

- capability 表示代码/契约已存在，runtime readiness 表示近期 worker 已通过真实身份与 provider probe。
- LLM 配置全空会禁用相关任务；配置一部分会明确启动失败。
- 固定 Web/Linux/Chat 执行器只允许固定目标和固定任务，不暴露任意网络、shell、路径或工具。

### 7.4 纵向切片验收

新增能力必须一次贯通：迁移/模型 → repository → API → worker/connector → UI → strict contract test → 真实运行边界。不得只搬页面、只写契约或用静态成功状态冒充接通。

## 8. 代码地图

```text
frontend/src/                    统一 React 工作台、严格 Zod 契约与 hooks
backend/app/api/                 /api/v2 路由
backend/app/media/               AgendaScope 导入、副本、同步与媒体查询
backend/app/policy_evidence/     政策来源、稳定文档身份与不可变版本
backend/app/world_models/        WorldModel / WorldSnapshot
backend/app/world_graphs/        直接证据图、语义图、Slice、检索和来源链
backend/app/scenarios/           baseline / alternative 规格
backend/app/populations/         Dataset / Persona / Cohort
backend/app/semantic_experiments/ OASIS 语义实验控制面
backend/app/decision_threads/    持久决策上下文
backend/app/decision_reports/    固定 Findings 与导出
backend/app/report_questions/    证据问答与追问链
backend/app/report_agents/       单快照受控证据运行与工具审计
backend/app/persona_interviews/  合成 Persona 报告访谈
backend/app/matraix_*            Survey、Chat、Web、Linux、Trial Archive、Batch Registry
backend/oasis_worker/            Python 3.11 OASIS 与各 LLM 任务执行器
backend/migrations/versions/     0001～0039 独立 Core 迁移链
compose.yaml                     sandowl 独立运行拓扑
```

前端真实一级工作区以 `frontend/src/domain.ts` 为准；后端实际路由注册以 `backend/app/main.py` 为准；能力目录以 `backend/app/system/service.py` 为准。

## 9. 尚未完整整合的范围

### 9.1 高优先级断链

1. **当前计划内整合链没有已知高优先级工程断链**：原生媒体采集、Project → Run → ReportAgent → Interaction / Persona Interview → Survey、固定 Chat/Web/Linux、四类 Batch Registry，以及 Project-bound App/Web Harbor 都已有真实成功记录。剩余 Gate 是真人零提示验证和生产治理，不得用开发者验收替代。
2. **品牌已确定，技术标识保留**：对外产品名确定为 `SandOwl`。仓库目录、Compose project、镜像、数据卷和环境变量中的 `SandOwl` / `sandowl` 继续作为内部技术标识，避免破坏运行环境；后端 health/product 中残留的 `SandOwl` 应在独立的小范围兼容改动中统一，不做零散替换。

### 9.2 MatrAIx 未完成范围

- Project-bound Harbor Job、Worker plane、最多五次不可变 retry lineage、task-owned verifier、trajectory、artifact 与 reward 已接通。尚未完成的是通用 cancel、任意任务包、通用 artifact 浏览与受权导出。
- 桌面 OS App、真实 Computer Use、录屏、通用 trajectory 和 macOS/iOS runner。
- 用户自定义 Chat/MCP/Web/OS 任务；当前所有 connector 都是固定、允许清单化的 source sample。

### 9.3 MiroFish 未完成范围

- bounded ReportAgent 的单快照作用域、冻结大纲、显式预算、媒体/政策只读工具、不可变调用审计，以及基于冻结正文读取前缀的异步逐条引用章节草稿已接通；自动受控规划尚未接通。
- 完整自主 ReAct ReportAgent 与开放式工具循环。
- Zep insight/panorama/quick-search 等上游工具的同等 PostgreSQL 实现仍不完整。
- 运行中 Agent IPC、长期记忆、Twitter/Reddit 双平台状态和对活跃 Agent 的真实访谈。
- 当前 Report QA 和 Persona Interview 是有证据边界的安全子集，不能标成完整 ReportAgent。

### 9.4 World / Graph / Policy 未完成范围

- 事实有效期与证据发布时间仍是不同语义；当前 timeline 只表示文章发布时间。
- PostgreSQL 图的混合全文/向量检索、规模基准和可选阿里云 GDB Provider 尚未实现。
- 政策来源、稳定文档身份、不可变版本、发布/施行/失效日期、完整正文、内容哈希及与 WorldSnapshot/Evidence Bundle 的精确版本冻结已建立；效力层级和自动摄取尚未建立。
- 企业实体、企业关系链和 GTV 是明确非目标，不应作为“遗漏”重新加回。

### 9.5 生产治理未完成范围

- 登录、认证、RBAC、团队协作权限和细粒度审计。
- Secret manager、生产环境配置、备份恢复、数据库高可用和灾备演练。
- 多 worker 水平扩展、通用取消/重试、队列配额、速率限制和成本预算。
- Artifact 保留/删除策略、授权下载、隐私最小化和数据许可治理。
- 全链路可观测性、告警、SLO、安全扫描和生产发布流程。

## 10. 推荐后续路线

### 阶段 A：先把现有能力真实跑通

1. 已确定对外品牌名为 SandOwl；UI、README 和 package metadata 已主要使用该名称，后续只需在保持 API 兼容的前提下清理残余 product/service 文案。
2. 已完成。独立千问/OpenAI-compatible provider 已配置，Semantic、Survey、Chat、Web、Linux readiness 均为 `true`。
3. 已完成。当前有 200 个 Persona 与 5 个不可变 Cohort。
4. 已完成当前原生产品路径。真实媒体已形成 WorldSnapshot → Semantic Graph → Research Project → 单次 Simulation Run → Run Report；旧 Scenario / Decision Report 不再作为新链路。
5. 已完成。Research Survey、固定 Chat/Web/Linux、四类 Batch Registry，以及 Project-bound App/Web Harbor 均已有成功资源；失败 attempt 保持不可变。
6. 已保存脱敏中文案例和 M16 开发者验收记录；后续新增任务只记录资源 ID、内容哈希和边界，不保存 API key 或复制 Persona 原文件。

### 阶段 B：补齐当前内部断链

1. 已完成。Survey、Chat、Web、Linux 四类 sealed parent 的有界分页、轻量 progress 和修订驱动轮询已接通；Chat transcript 使用不进入内容哈希的数据库 identity 游标实现真正增量读取。Web pages/quotes 与成功状态在同一事务提交，Linux artifact 也只在终态结果封存后开放读取，因此两者不存在可观察的运行中详情增量，不增加伪游标接口。

### 阶段 C：按证据、分析、执行三层依次扩展

三个方向互补且都纳入目标路线，但禁止同时铺开；每一层必须形成通过真实 PostgreSQL 验证的纵向切片后再进入下一层：

1. **Policy evidence（证据层，基础闭环已完成）**：政策来源、稳定文档身份、不可变版本、发布/施行/失效时间、内容哈希、人工确认工作区，以及显式政策版本与 WorldSnapshot/Evidence Bundle 的冻结绑定已接通，并通过真实 PostgreSQL 验证。政策是外部现实证据，不能被 Agent 输出或执行结果替代；自动摄取和效力层级属于后续增强。
2. **PostgreSQL evidence tools + bounded ReportAgent（分析编排层，受控 v2 已完成）**：已完成单 Run 多来源作用域、冻结大纲与预算、媒体/政策/图谱/事件/获授权访谈读取、不可变调用审计，以及异步生成并逐字校验引用的章节草稿。开放式自主 ReAct 和隐藏推理不在当前产品声明内；Agent 输出仍是分析，不自动成为事实。
3. **隔离 Harbor-compatible executor（执行层，Project-bound 子集已完成）**：固定 MatrAIx commit、Rootless DinD、PostgreSQL Job Worker、不可变 retry、task-owned verifier、trajectory、artifact 与 reward 已接通。通用 cancel、任意任务包、授权下载和资源治理仍是后续生产化范围；执行结果不自动升级为现实证据。

跨层连接必须保留来源、版本、时间、内容哈希和运行身份；ReportAgent 可以读取 Policy evidence 并提交 Harbor 任务，但任何下游结果进入 World 或 Report 前仍需显式、类型化引用。

### 阶段 D：生产化

完成 auth/RBAC/audit、secret 管理、备份、artifact retention、监控告警、资源配额、发布回滚和安全评审后，才能把当前开发栈定义为生产系统。

## 11. 开发与运行手册

### 11.1 本地开发

```bash
pnpm install
pnpm setup
pnpm dev
```

- Vite 开发入口：`127.0.0.1:3300`。
- 本地 FastAPI：`127.0.0.1:8310`。
- Compose 验收入口：`127.0.0.1:3200` / `127.0.0.1:8210`。
- 不要同时把 Vite 和 Compose frontend 绑定到同一端口。

### 11.2 Compose

```bash
pnpm stack
```

非本机环境必须使用独立、gitignored 的环境文件：

```bash
SANDOWL_ENV_FILE=/absolute/path/to/sandowl.env pnpm stack
```

媒体同步是显式 profile，默认栈不会自动连接 AgendaScope：

```bash
SANDOWL_ENV_FILE=/absolute/path/to/media-sync.env pnpm stack:media-sync
```

### 11.3 变更验证

遵循最小相关验证：

- 后端领域变更：对应测试文件 + Ruff check/format。
- Worker 变更：对应 worker test + Ruff。
- 前端契约/UI：对应 Vitest + typecheck；跨构建边界时再 build。
- 迁移/数据库触发器：临时或 SandOwl 专属 PostgreSQL 真实升级和行为测试。
- 跨服务能力：重建受影响的 SandOwl 服务，核验 readiness/API/桌面与 390px；不得重启旧项目。

真实 PostgreSQL 集成测试使用 `pnpm test:backend:postgres`。该命令只启动 Compose `test` profile 中不映射端口、使用 tmpfs 的 `postgres-test`，测试容器先升级到当前 head，再通过内部 `TEST_POSTGRES_DATABASE_URL` 运行 pytest；禁止把应用数据库 `DATABASE_URL` 改作测试 DSN。

完整验证入口仍为 `pnpm verify`，但日常小改动不要无差别运行全仓测试。

## 12. 接手检查清单

开始任何新开发前：

- [ ] 当前目录是 `/Users/ssyb/Workspace/web/SandOwl`。
- [ ] 没有计划修改或重启 `ai-decision-center`、AgendaScope、MatrAIx 或 MiroFish。
- [ ] `git status` 已阅读；当前工作树包含大量未提交整合改动，不得覆盖或 reset。
- [ ] 需求被归类为“补断链”还是“新增大能力”，并有清晰验收边界。
- [ ] 外部数据只读，所有新持久化都进入 SandOwl。
- [ ] API 使用严格类型和运行时验证，没有 `Any`/松散字典/假数据 fallback。
- [ ] sealed 内容、哈希、provenance 和数据库守卫在同一切片内完成。
- [ ] UI 明确显示 runtime readiness、synthetic 边界和未接能力。
- [ ] 只运行与变更范围相称的测试和服务重建。
- [ ] 未经明确要求不 commit、不建分支、不 push。

## 13. 已知交接风险

- 当前 `main` 已提交到 `84239b1`；其后的 Chat transcript 增量游标是已通过聚焦验证的未提交切片，禁止整体 reset。
- 系统 capability 的 `runtime_ready` 表示能力代码已存在；真正是否允许执行仍要读取对应实时 readiness。当前需要 LLM 的五类执行均未就绪。
- 媒体同步当前处于显式启用状态；任何调整源 DSN、schema revision 或同步周期的操作都必须保持源只读并只影响 SandOwl。
- 固定 source sample 的成功只证明该受约束纵向链路，不代表通用 Chat/Web/Linux/Harbor 能力。
- Trial `succeeded` 表示协议与产物封存成功，不等于任务效果优秀、Persona 满意或 verifier reward 为正。

## 14. 交接完成标准

新的维护者能够在不接触旧项目的前提下：

1. 启动 SandOwl 独立栈并确认 migration、health 和 readiness。
2. 解释现实证据、人工确认、实验假设和合成输出的区别。
3. 从 Media → World → Scenario → Cohort → Run → Report 追踪全部 ID、版本和内容哈希。
4. 说明当前代码已接通但 LLM 环境未就绪的任务。
5. 从第 9、10 节选择下一条纵向切片，而不是新增静态页面或冒充完整上游能力。
