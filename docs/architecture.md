# AI Decision Center V2 Core Integration 架构

## 范围

本分支的目标是把四个项目重构为一个产品，而不是增加新的企业业务：

| 来源 | 进入统一产品的能力 |
|---|---|
| AgendaScope | 媒体来源、文章、议题及导入适配 |
| 原 AI Decision Center | World、Scenario、Run 与报告方向的领域语义 |
| MatrAIx | 人群实验契约、工作台交互语言和地球渲染原语 |
| MiroFish / OASIS | 社会平台执行适配、运行约束和产物 |

为了让这些能力在同一个系统内可靠连接，V2 新增了严格 API 契约、内容摘要、数据库迁移、任务状态、不可变封存、运行队列、统一前端和 Compose。这些属于项目整合工程。

`Company` 主体、企业别名、企业报道 coverage、企业关系链和 GTV 不属于这条必需链路，本分支不包含它们。

## 目标数据流

```text
Media / Policy Reality
  → Article Evidence
  → Versioned World Snapshot
  → Decision Scenario
  → MatrAIx Population Trial + OASIS Social Evolution
  → Comparable Metrics / Explanation / Report
```

当前已接通七条模型/任务执行路径：不读取 Cohort 的 OASIS platform smoke、将封存 Cohort 与 Scenario baseline/alternatives 组成矩阵的有界语义实验、将封存 Scenario/Cohort 交给千问逐 Persona 完成固定三题的 MatrAIx Survey、让封存 Cohort 逐 Persona 与固定 Acme source sample 完成真实多轮 Chatbot Evaluation、让 1～4 人封存 Cohort 通过隔离 Playwright 执行固定 quote-choice Web source sample、让显式选择的冻结 Persona 通过非特权 Runner 完成固定 note-to-CSV Linux 产物任务，以及把封存 Report/Cohort/Persona 交给千问生成章节引用受限的合成 Persona 访谈。访谈支持单人任务和一次封存 2～8 个独立回答的原子会话。Persona World、Playground、Survey、Chat、Web、Linux 产物任务、Persona 访谈与持久章节式 Findings 共享这些真实资源；Trial Archive 提供有界只读目录，Batch Registry 可不可变登记 Survey/Chat/Web/Linux sealed parent，并可在单一数据库事务中创建既有 SendOwl-native Survey/Chat 父运行后立即登记，失败时整体回滚。Web/Linux 不进入 native launch；Linux Evaluation 仅内容寻址封存一个真实固定 Linux Trial，不把 Cohort 冒充父运行。固定 Web 执行器不是任意网址或 Harbor，Linux Runner 也不执行任意 shell、桌面或 Computer Use；Batch Registry 不引入 Harbor Docker/OS、verifier 或通用 artifact 执行语义。这些合成试验均不等于真人研究或决策推荐。Policy evidence 已提供人工确认的来源、稳定文档身份、不可变版本、效力日期、内容哈希、独立正文读取以及与 WorldSnapshot/Evidence Bundle 的精确版本冻结；含政策快照使用 `world-snapshot/v3`，无政策的历史快照继续按 `v2` 复算。完整 MatrAIx Harbor launch/verifier/artifact 执行面、桌面 OS/Computer Use、bounded/autonomous ReportAgent 与运行中 Agent IPC 仍未迁移。

现实观测、人工确认、实验假设和模拟输出是四种不同的事实类型。任何下游资源都必须保留来源、时间、版本和内容摘要，不能把实验输入或模拟产物回写成现实证据。

后续能力按三个互补层次依次建设：Policy evidence 扩展现实证据层；bounded ReportAgent 只编排有界 PostgreSQL evidence tools 并生成逐条引用的分析；Harbor-compatible executor 提供隔离任务、verifier 与 artifact 执行面。三者可以组合，但语义不可混用：政策文档是外部事实来源，Agent 叙事是分析，Harbor 结果是执行观测。实施顺序固定为 Policy evidence → bounded ReportAgent → Harbor executor，避免证据契约、Agent 工具与执行安全同时处于未封存状态。

## 运行拓扑

```text
React frontend
      │ /api/v2
      ▼
FastAPI backend ───── PostgreSQL
      │                    │
      ├──── Redis          └── durable simulation queue
      │                                  │
      └──────────────────── OASIS worker (Python 3.11)
                                           │
                                           └── SQLite artifact volume
```

- PostgreSQL 是媒体副本、领域资源、任务状态和运行引用的事实源。
- Redis 只用于短期协调，不保存唯一业务事实。
- API 使用 Python 3.12；受 OASIS 0.2.5 约束的 worker 使用 Python 3.11。
- worker 是同仓库的执行角色，不是额外项目或代码仓库。
- Compose 先执行 Alembic migration，再启动 API、worker 和前端。
- Compose `test` profile 使用不映射端口、tmpfs 持久层的独立 PostgreSQL；测试镜像迁移该库后才注入 `TEST_POSTGRES_DATABASE_URL`，不复用应用数据库或数据卷。
- `/health` 表示进程存活；`/readyz` 检查必要数据库连接；platform readiness 还核验 worker 心跳及固定版本。
- semantic readiness 另外要求近期 worker 同时标记 platform/semantic runtime ready，且所有可用 worker 只暴露一个一致的 model/config/prompt 身份；配置冲突时禁止新实验入队。

## 后端领域边界

| 领域 | 当前职责 | 来源 |
|---|---|---|
| `media` | AgendaScope 数据导入、来源、文章、议题与地域聚合 | AgendaScope |
| `evidence` | 通用证据修订摘要、正文内容地址和证据契约 | V2 整合层 |
| `policy_evidence` | 人工确认的政策来源、稳定文档身份、不可变版本、效力日期与完整正文 | V2 整合层 |
| `world_models` | 通用、版本化、不可变的文章证据快照 | 原 ADC + V2 整合层 |
| `scenarios` | 基线、备选方案和有序干预规格 | 原 ADC |
| `populations` | MatrAIx 数据集、Persona 档案与有序不可变 Cohort | MatrAIx + V2 整合层 |
| `simulations` | MatrAIx/OASIS 契约、平台运行及统一结果边界 | MatrAIx + OASIS |
| `semantic_experiments` | Cohort/Scenario 矩阵、语义 trial、观测事件与配对计数 | MatrAIx + OASIS + V2 整合层 |
| `reports` | 固定四章节 Findings、真实 comparison、配对计数、限制、运行来源、Markdown 导出、证据追问链和 Persona 访谈 | 原 ADC + MatrAIx + MiroFish 交互模式 + V2 整合层 |

adapter 只负责将稳定领域契约转换为外部引擎协议。业务 API 不暴露四个来源项目各自的路由、进程状态或文件存储模型。

## 统一工作区

```text
态势
  ├── 真实地域媒体活动
  ├── 热点议题
  └── 最新证据

Decision Workspace
  ├── 媒体证据
  ├── 冻结现实
  └── 决策实验

Run Studio
  ├── Platform Smoke
  │   └── 单方案平台接线、产物与限制
  └── Semantic Experiment
      ├── Scenario / Alternatives / Cohort / Seeds
      ├── Readiness 与实验矩阵
      └── 事件时间线、溯源、结果与计数比较
```

界面围绕同一条决策任务组织，不复制四套前端菜单。Run Studio 保留 Persona World、capability 驱动的 Task Gallery、Playground 与决策报告四个连续任务面；Playground 在同一个主入口内切换 platform/semantic 模式。语义模式只显示真实任务状态、真实事件、由事件确定性生成的互动图和经过契约核验的计数，不使用演示数据伪装报告。

## 当前纵向切片

```text
AgendaScope PostgreSQL
  → REPEATABLE READ / READ ONLY 源事务
  → 幂等导入 V2 media_* 表
  → GET /api/v2/media/*
  → 用户选择 1～50 篇任意文章并阅读确认
  → POST /api/v2/world-models
  → immutable WorldSnapshot + snapshot_sha256
  → POST /api/v2/scenarios
  → baseline + alternatives + ordered initial posts
  → POST /api/v2/simulation-runs/platform-smoke
  → PostgreSQL durable queue
  → OASIS 0.2.5 Reddit + SQLite + manual CREATE_POST
  → run lifecycle + input/artifact hashes + explicit limitations

MatrAIx Persona dataset directory
  → strict manifest / YAML validation
  → immutable PersonaDataset + ordered Persona profiles
  → explicit 1～100 member selection
  → immutable content-addressed Cohort
  → select a 1～8 Persona Cohort for semantic execution

sealed Scenario + sealed Cohort
  → POST /api/v2/semantic-experiments
  → baseline + 1～2 alternatives × 1～2 seeds
  → PostgreSQL durable trial matrix
  → OASIS/CAMEL + configured OpenAI-compatible model
  → typed round events + verified SQLite artifact
  → paired observed-count comparison
```

### MatrAIx 人群上下文

导入器只接受显式配置并只读挂载的数据集目录。manifest、文件清单、档案字段、来源元数据和有序 Persona 摘要共同决定 `dataset_sha256`；同一内容地址幂等返回同一个数据集。API 只读取已封存的数据集。

Cohort 由一个明确的数据集版本和 1～100 个有序 Persona 构成，`cohort_sha256` 覆盖数据集摘要、标题和每个成员的 Persona ID / profile 摘要。Dataset、Persona、Cohort 与成员均使用 draft→sealed 触发器保护，封存后拒绝修改、删除、追加和 `TRUNCATE`。

封存 Cohort 可以含 1～100 个 Persona，但当前语义实验只接受其中人数不超过 8 的完整 Cohort，不在入队时隐式抽样或改写成员。platform-smoke 请求仍不包含 `cohort_id`；它与语义实验是 Run Studio 中相互独立的运行模式。

### 通用证据修订

媒体 article response 提供 `evidence_revision_sha256`。摘要覆盖将被快照冻结、且可能在后续导入中变化的字段：标题、正文、摘要、URL、发布时间、抓取时间、地域、来源 ID 和来源名称。

创建快照时，前端提交用户实际阅读版本的摘要。后端先与 AgendaScope importer 获取同一事务级 advisory lock，再锁定文章和来源、重新计算摘要；不一致时返回 `409`。这防止用户确认后、提交前文章发生变化而被静默冻结。

### 不可变世界快照

快照复制来源名称、原始链接、标题、完整捕获文本、发布时间、捕获时间、国家、摘要和正文 SHA-256。读取世界模型只访问冻结表，不关联后来变化的 `media_*` 记录。

创建与追加版本均在一个事务中完成 draft→sealed。数据库要求证据数量为 1～50、位置连续、文章不重复，并在封存后拒绝父子记录修改、删除、追加和 `TRUNCATE`。冻结正文有独立只读 endpoint，可由客户端复算 `captured_text_sha256`。

### 决策实验

Scenario 引用一个明确的封存快照，不跟随 WorldModel 最新版本漂移。一个规格包含无动作 baseline、1～5 个 alternatives，以及每个方案 1～20 条 `initial_post`。actor 是中性的 `scenario_actor`，表示平台烟测使用的 synthetic actor，不代表企业或现实人物。

`scenario_sha256` 只覆盖有序实验语义及快照引用；相同内容地址通过唯一约束和事务级 advisory lock 去重。网络超时后重复提交不会创建另一份相同规格。

### OASIS platform smoke

控制面将选定方案复制成封存运行输入，worker 以 synthetic scenario actor 执行真实 OASIS Reddit 环境和 SQLite 持久化。输入哈希、运行生命周期、产物哈希、文件大小以及 user/post/trace 数量都会被核验。

该模式固定使用 CAMEL `StubModel`，`semantic_run_ready=false`。它不能输出受众演化、传播预测、方案优劣或商业结论。

### OASIS 有界语义实验

`SemanticExperiment` 始终包含 Scenario baseline，并要求显式选择 1～2 个 alternatives、1～2 个不重复的 uint32 seeds、1～3 轮和每轮 15～240 分钟。总预算按 `(1 + alternatives) × seeds × rounds × persona_count` 计算，不得超过 96 persona-rounds；干预的 `offset_minutes` 不得超过实验总时长。控制面将每个 variant/seed 展开为独立持久 trial，一次提交后不会随 Scenario、Cohort 或 worker 配置漂移。

worker 仅加载被选 Cohort 的封存 Persona，按 `matraix-semantic-profile/v1` 从档案中确定性投影最多 40 个有信息属性。场景干预由 synthetic scenario actor 在对应轮次发布；每个 Persona 每轮执行一次真实 LLMAction。公开事件只有 `create_post`、`create_comment`、`like_post`、`dislike_post` 和 `do_nothing`；每轮事件先追加到 PostgreSQL，再推进 `current_round`。成功结果另外绑定 OASIS/CAMEL/model/config/prompt 身份、SQLite 产物摘要和经核验的计数。

对比固定输出 `observed_action_count`、`authored_content_count`、`reaction_count` 和 `do_nothing_count`。alternative 只与同一 seed 下成功的 baseline 配对，并报告观测值与差值的 mean、标准差和样本数。该结果是 synthetic bounded observations，不推断 stance、reach、persuasion、forecast、商业影响或 decision verdict；外部 provider 的非确定性也意味着 seed 不能保证 provider-level reproducibility。

Run Studio 使用以下 API：

- `POST/GET /api/v2/semantic-experiments`：入队或列出实验；
- `GET /api/v2/semantic-experiments/{experiment_id}`：读取矩阵与 trial 状态；
- `GET /api/v2/semantic-experiments/{experiment_id}/comparison`：读取观测计数和按 seed 配对的差值；
- `GET /api/v2/semantic-trials/{trial_id}/events`：按 sequence 增量读取类型化事件；
- `GET /api/v2/simulations/oasis/semantic-readiness`：读取 worker、版本和不含密钥的配置身份。

Survey、Chat、Web、Linux 四类 sealed parent 目录共享严格、有界的 `page/page_size` 查询语义；未知、重复、越界或超出总数的页码都会明确失败。Linux 的目录项封存一个真实 Trial，Trial 详情与产物路径继续独立存在。四类 parent 另提供各自的 `/{id}/progress` 轻量读取，并共享严格的 `ParentProgress` 语义：父 attempt、queued/running/succeeded/failed Trial 计数、append-only 事件计数和不包含观测时间的稳定 `progress_sha256`。Chat 额外提供 `/{id}/transcript-delta`，以全局单调 identity 序号读取一个 Evaluation 内的新消息；序号只用于传输，不进入 transcript 哈希。Chat 前端在状态变化和终态重读完整详情，其余轮询只合并严格校验的消息增量。Web pages/quotes 与终态在同一事务提交，Linux artifact 也只在终态封存后开放读取，因此它们在修订变化后读取完整 typed detail，不定义无法表达真实中间状态的 artifact 游标。

语义 worker 的 OpenAI-compatible 连接只由 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_NAME` 三项显式配置。三项全空会禁用语义执行但保留 platform smoke；部分配置会让 worker 明确启动失败。完整配置不会立即被视为 ready：worker 先对真实 provider 发起一次有界的 `do_nothing` tool-call 启动探测，严格核验响应只有一个预期工具调用；探测成功后才更新为 semantic-ready heartbeat，探测失败则在有界 provider 重试后使 worker 启动失败。API key 不进入 heartbeat、内容摘要或业务表。

## 数据库谱系

Core 分支使用 `20260812_core_0001` 至 `20260816_core_0038` 的独立 Alembic revision 链，并使用独立 Compose project/volume。`20260812_core_0010` 增加 semantic experiment/variant/trial/event 表和 worker 语义配置心跳字段；`20260812_core_0011` 增加 evidence-backed semantic world graph 队列、节点、关系与引用表；`20260812_core_0012` 增加只追加的 Decision Thread 与资源修订绑定；`20260812_core_0013` 增加内容寻址、固定四章节且封存后不可修改的 Decision Report；`20260813_core_0014` 增加证据约束的报告问答队列，`20260813_core_0015` 无损加固问题内容寻址、快照/图配置绑定和回答长度边界，`20260813_core_0016` 增加 Survey 实验、逐 Persona trial、typed answers 与独立 worker readiness，`20260813_core_0017` 增加绑定 Report/Cohort/Persona 哈希的合成 Persona 访谈队列，`20260813_core_0018` 增加封存 2～8 个有序子访谈的原子多人会话，`20260813_core_0019` 增加首页传播链投影，`20260813_core_0020` 增加周期媒体快照刷新状态与逐表计数，`20260813_core_0021` 增加固定 MatrAIx Chat task、逐 Persona 多轮 trial、append-only transcript、typed feedback/result 与独立 worker readiness，`20260813_core_0022` 增加把已封存 Survey/Chat 父运行按有序成员内容寻址的不可变 Batch Registry，`20260813_core_0023` 增加最多五轮、父问题与父回答摘要绑定的报告追问链，`20260813_core_0024` 在保留 REST 内容地址的同时增加固定 Acme MCP source sample 与双通道运行时身份，`20260813_core_0025` 保留规范化传播 follower 身份，`20260813_core_0026` 和 `0027` 增加 Chat/Survey 不可变重试谱系，`20260813_core_0028` 增加首发证据观察，`20260814_core_0029` 增加图谱节点人工筛选 Persona 后与 Cohort 一起封存的不可变来源链，`20260815_core_0030` 增加固定 Playwright Web Evaluation，`20260815_core_0031` 增加媒体文章源端存在性对账，`20260815_core_0032` 增加固定 Linux artifact trial 与隔离 runner provenance，`20260816_core_0033` 将 sealed Web Evaluation 纳入 registry-only 候选和不可变成员，`20260816_core_0034` 增加单 Trial Linux Evaluation 父资源并将其纳入 registry-only 候选和不可变成员，同时保持 native launch 仅限 Survey/Chat，`20260816_core_0035` 为 Web Evaluation 和 Linux Trial 增加最多五次、保留旧失败记录的不可变 attempt 谱系，`20260816_core_0036` 为 append-only Chat 消息增加不参与内容寻址的全局单调传输游标，`20260816_core_0037` 增加内容寻址、数据库防篡改的政策来源、稳定文档身份与不可变版本，`20260816_core_0038` 将显式选择的政策版本完整复制进 WorldSnapshot，以 `v3` 哈希封存并保持纯媒体 `v2` 内容地址不变。这样已运行企业版 `20260812_0008` 的数据库不会被误认为符合 Core schema。

此分支不提供企业版数据到 Core schema 的无损迁移；两者是并行产品边界。需要导入媒体数据时，应建立 Core 数据库并重新运行 AgendaScope importer。

## 明确不包含的企业扩展

- `companies` / `company_aliases` 表与 API；
- 企业规范名称、别名冲突和名称命中算法；
- `/api/v2/companies/{id}/coverage`；
- 企业身份、命中别名或命中字符位置在 WorldSnapshot 中的冻结；
- Scenario/Run 中的 `company_name` 或 `snapshot_company` actor；
- 股权、母子公司、供应链、产业链、人物任职、风险事件和 GTV。

文章中出现企业名称只是原始媒体内容。通用全文搜索不会将其提升为已消歧企业实体。

## 世界图谱 Provider 决策

Zep Cloud 不再是目标架构的必选依赖。默认实现使用现有 PostgreSQL 保存版本化的图空间、节点、关系和证据引用；每个事实必须回指 WorldSnapshot 与冻结文章，图版本封存后保持不可变。邻居查询和证据过滤先使用 SQL，确有语义召回需求时再增加向量索引。

当前最小切片已经提供 `GET /api/v2/world-models/{model_id}/snapshots/{snapshot_id}/evidence-graph`：它直接从已封存快照确定性生成 `evidence-world-graph/v1`，只包含 Snapshot、Article、Source、Country 与 `contains_evidence`、`published_by`、`located_in` 直接关系，并返回 `graph_sha256`。这是零额外服务的 PostgreSQL projection，不进行实体推断；MiroFish 本体与语义关系进入后续持久 GraphStore 版本。

存储与展示保持解耦：`GraphStore` 业务接口面向节点、关系、版本和 evidence reference，默认由 PostgreSQL 实现；阿里云部署可以继续使用托管 PostgreSQL，图规模或在线多跳查询达到明确瓶颈后，可增加兼容 Apache TinkerPop Gremlin 的阿里云 GDB 实现。ECharts Graph 或现有 SVG Canvas 只消费统一 API 的 nodes/edges，不承担实体抽取、持久化、检索或版本管理。Lindorm 只作为海量全文/向量融合检索的后续可选 Provider，不进入第一阶段必需拓扑。

当前实现由通过真实 tool-call 启动探测的千问 Worker 消费 `semantic_world_graphs` 队列，从冻结正文提取实体与有向关系；模型输出必须引用快照内文章的逐字文本，Worker 与数据库触发器共同校验 article identity、字符偏移、结构完整性和 canonical graph hash。`GET /api/v2/world-graphs/{graph_id}/slice` 在已封存图上提供确定性的有向 1～3 跳邻域，支持双向、向外、向内和 2～100 节点上限；响应保留原节点/关系位置、证据和 graph hash，截断必须显式返回。`GET /api/v2/world-graphs/{graph_id}/evidence-timeline` 按 WorldSnapshot 中冻结的 `published_at` 组织被引用节点与关系，契约固定声明 `evidence_publication_time_not_fact_validity`，不能当作事实有效期。原 Zep adapter 仅保留为可选兼容层，不允许其 Cloud ID 成为 WorldModel、Scenario、Run 或 Report 的业务主键。事实有效期与混合检索仍需后续在统一 GraphStore 契约上实现。

## 后续整合顺序

| 范围 | 状态 |
|---|---|
| Foundation | React/FastAPI、严格契约、PostgreSQL/Redis、Alembic、健康检查与单栈已接通 |
| AgendaScope | 媒体导入、来源/文章/议题查询、来源证据档案、原文可核验的首发观察和真实地域地球已接通 |
| World | 通用证据选择、修订冲突保护、不可变快照、版本与正文读取已接通 |
| Scenario | 基线/备选、内容寻址、去重和封存已接通 |
| MatrAIx Population | Dataset / Persona 严格导入、内容寻址、Cohort 选择与封存已接通 |
| OASIS Platform | Reddit 平台、SQLite、手工动作、队列、worker 心跳和运行档案已接通 |
| Semantic Experiment | 有界 Cohort/Scenario 矩阵、真实 LLM 动作、类型化事件和观测计数配对比较已接通 |
| MiroFish World Graph | PostgreSQL 直接证据图、千问 evidence-backed 语义实体关系、有向 World Slice 与证据发布时间线已接通；事实有效期、混合检索待实现，Zep 仅为可选 Provider |
| MatrAIx Trial / Harbor | Survey、固定 Acme REST/MCP Chatbot Evaluation、固定 Playwright Web quote-choice、固定 note-to-CSV Linux artifact runner、Chat 最多五次且保留父失败记录的不可变 attempt 谱系、四类 Trial 共用且不读取重型产物的只读 Trial Archive，以及可登记 Survey/Chat/Web/Linux sealed parent、仅对 Survey/Chat 提供原子 native 入队的 `registry_only` 不可变 Batch Registry 已接通；Linux parent 是单个真实 Trial 的不可变封存，不是 Cohort 或 Harbor Job；Harbor job launch/verifier/通用 artifacts/受权导出、桌面 OS/Computer Use trajectory 与更多执行器仍待迁移 |
| Decision / Thread | 持久任务、只追加修订以及 World→Scenario→Cohort→Run→Report 跨资源深链已接通；协作权限与审计待实现 |
| 判断闭环 | 持久章节式 Findings、Markdown 导出、来源哈希、最多五轮的证据约束报告追问链、固定证据叙事镜头、单人及 2～8 人原子合成访谈已接通；完整自主 ReAct ReportAgent、运行中 Agent IPC、历史回测与人工判断待迁移 |
| AgendaScope 持续摄取 | 默认关闭的周期快照刷新、并发锁、导入任务状态、规范化 follower 传播关系及文章源端缺失标记已接通；缺失文章只从当前 API 隐藏并保留冻结证据，未回填关系的历史事件显式使用 legacy projection；真正 CDC 与非文章对象删除对账待实现 |
| Policy | 人工确认的政策来源、稳定文档身份、不可变版本、发布/施行/失效日期、内容哈希、目录、正文读取及 WorldSnapshot/Evidence Bundle 精确版本冻结已接通；效力层级和自动摄取待实现 |
| 生产运行治理 | 认证/RBAC/审计、取消与重试、水平扩展、产物下载与保留策略待实现 |

后续仍以真实纵向切片验收；未接通能力必须在 API 和界面中明确标记，不能用静态成功状态掩盖缺失。
