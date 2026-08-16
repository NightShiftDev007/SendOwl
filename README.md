# SandOwl · AI Decision Center V2 Core Integration

SandOwl 把 AgendaScope、原 AI Decision Center、MatrAIx 与 MiroFish/OASIS 重构到一个仓库、一套领域契约和一个运行拓扑中。

当前分支只保留项目整合及其必要的工程能力，不包含后来单独扩展的企业业务。现有可运行链路是：

```text
AgendaScope 媒体文章
  → 人工选择并确认通用证据
  → 不可变 WorldSnapshot
  → Baseline / Alternative Scenario

MatrAIx Persona Dataset
  → 严格导入与内容寻址
  → 不可变 Cohort

Scenario + Cohort
  → Baseline / 1～2 Alternatives × 1～2 Seeds
  → OASIS / CAMEL 语义实验
  → 类型化观测事件
  → 按 Seed 配对的观测计数比较

Scenario Alternative
  → OASIS Reddit platform smoke
```

当前真实能力包括：

- 媒体证据：将 AgendaScope PostgreSQL 的来源、文章、议题、快照和可逐字回指文章的正向首发观察幂等导入 V2 自有表，提供媒体统计、地域热点、议题、来源和文章检索。来源证据档案把每个来源严格关联到已导入、非重复的报道分页，并在同一只读快照中给出报道总量和时间边界；议题观察镜头只展示原文可核验的首发引用，不导入模型推理，也不把模型判断冒充权威的“最早表述”结论。首页地球复用 MatrAIx 的渲染原语，但只编码真实地域聚合，不生成虚构城市或传播关系。
- 通用世界快照：研究员可从任意已导入文章中选择 1～50 篇，阅读后显式确认，再创建 `WorldModel` 与不可变 `WorldSnapshot`。提交携带完整证据修订摘要；标题、正文、摘要、来源、URL、时间或地域变化时，后端返回 `409` 并要求重新阅读确认。
- 决策实验：在一个明确的封存快照上建立无干预基线与 1～5 个备选方案。每个方案包含有序的 Reddit 初始帖子；这些内容始终标记为实验假设，不会被呈现为现实事实。
- 人群上下文：从显式指定的 MatrAIx 数据集目录严格读取 manifest 与 Persona YAML，按数据集、档案和成员顺序计算内容摘要，再原子封存为可追溯 Dataset、Persona 与 Cohort。数据文件不打包进本仓库，导入时只读挂载，来源与授权责任保持可见。
- OASIS 平台验证：同仓库 Python 3.11 worker 从 PostgreSQL 持久队列领取任务，真实运行 OASIS 0.2.5 Reddit 平台、SQLite 持久化和手工 `CREATE_POST`。该 platform-smoke 模式固定使用 CAMEL `StubModel`，不读取 Cohort，仅验证平台接线。
- 有界语义实验：Persona World 将真实导入档案封存为 Cohort，并可带着 Cohort 或 Scenario 深链进入 Playground。Playground 把 Scenario baseline、1～2 个 alternatives 与 Cohort 组成持久实验矩阵；worker 在每个 seed 上使用真实 OpenAI-compatible LLM 执行 OASIS/CAMEL 受众动作，保存 SQLite 产物与类型化事件。决策报告页把真实 comparison 封存为固定四章节 Findings，展示实际观测计数、同 seed 配对差值、运行来源和限制，并提供 Markdown 下载；报告问答支持最多五轮的内容寻址追问链，历史只用于理解指代，每轮事实仍必须重新引用同一冻结图谱的精确原文。Persona 证据访谈进一步绑定 Report、Cohort、Persona profile 与模型配置，支持单人追问和 2～8 人原子访谈会话；每个回答只能引用固定报告章节，并明确是合成视角而非真人陈述。
- Task Gallery：统一展示 OASIS 与 MatrAIx 任务能力，可用性同时读取 `/api/v2/system/capabilities` 与各执行器的实时 readiness。Survey、Chatbot Evaluation、固定来源样例 Web Evaluation 与固定 Linux 产物任务已提供真实 Playground；尚未迁移的 OS App、通用 Computer Use 与 Harbor 会明确锁定。
- MatrAIx Chatbot Evaluation：固定接入 MatrAIx 仓库的 Acme Support REST 与 streamable-HTTP MCP 两个 source sample，把一个封存的 1～8 人 Cohort 展开为逐 Persona 多轮试验。隔离 sidecar 提供确定性支持回复；Worker 只允许固定 MCP 工具，真实千问生成 Persona 消息和严格 self-report，PostgreSQL 保存逐条 transcript、typed feedback、运行结果与内容哈希。样例不是生产客服系统，也不输出 benchmark reward。
- MatrAIx Web Evaluation：固定接入 MatrAIx `example-web-playwright_quote-choice` source sample，把封存的 1～4 人 Cohort 展开为逐 Persona 试验。独立、无 Docker socket 的 Chromium 容器只访问固定的 Quotes to Scrape 来源，读取三页真实 DOM、保存内容寻址截图和引文；Worker 只能从实际观察到的引文中提交选择。失败 Evaluation 可创建最多五次、保留旧记录的不可变 attempt 谱系。它不是任意网址浏览器、通用 Web Agent、Harbor trajectory 或生产任务。
- MatrAIx Linux Artifact Trial：固定接入 `matraix/linux-note-to-csv` source sample。用户显式选择封存 Cohort 与其中一个 Persona 后，千问只提交受约束解释和合成反馈；独立非特权 Runner 写入并校验固定 CSV、submission、feedback 与 verifier 产物，API 按允许清单和内容哈希读取。失败 Trial 可创建最多五次、保留旧产物身份的不可变 attempt 谱系，并为每次 attempt 封存独立 Evaluation。该任务不执行任意 shell、不接收任意路径，也不是桌面 Computer Use、OS App 或 Harbor runtime。
- MatrAIx Trial Archive：把已经持久化的 Survey、Chat、固定 Web 与固定 Linux trial 投影为同一份有界分页目录，统一展示执行状态、Persona、父任务或封存 Cohort、来源哈希，并从同一只读快照给出当前筛选的精确类型/状态计数，再深链回各自的 typed detail。Archive 只读取轻量身份与结果摘要，不读取 Survey 答案、Chat transcript、Web 截图或 Linux 文件内容，也不把回答、合成反馈或协议完成状态改写成 reward。Chat detail 仍可把真实 customer/support transcript 严格投影为内容寻址的 ATIF-v1.7 trajectory；该投影明确标注为 derived transcript projection，不虚构 reasoning、tool call、reward、截图、录屏或 Harbor 原生遥测。
- MatrAIx Batch Registry：可把 1～20 个已封存的 Survey、Chat、Web 或 Linux 父运行按显式顺序内容寻址并登记，也可通过一次原子请求创建 SendOwl-native Survey/Chat 父运行并立即封存 Registry；任一输入失败会整体回滚。Web 和 Linux 只进入 registry-only 候选和成员，不进入 native launch；Linux Evaluation 只封存一个真实固定 Linux Trial，不把 Cohort 冒充父运行。Registry 使用有界候选目录和同一只读快照展示底层 Trial 的观测状态。Survey、Chat、Web、Linux 的失败父运行均保留旧记录并创建最多五次的不可变 attempt 谱系；这些仍是 SendOwl-native 入队与恢复能力，不等于 Harbor job launch/retry，也不提供 verifier reward、Harbor 原生 trajectory、通用 artifacts 或授权导出。
- 运行目录与进度读取：Survey、Chat、Web 的父资源目录和 Linux Trial 目录使用统一严格、有界的 `page/page_size` 查询；Survey、Chat、Web、Linux sealed parent 另提供同语义的轻量 progress 投影，包含逐状态 Trial 计数、append-only 事件计数和稳定修订摘要。运行页仅在摘要变化时重读 typed detail，避免每次状态探测都重复传输 Survey answers、Chat transcript、Web 页面引用或 Linux 结果元数据。
- 运行互动图：借用 MiroFish 的关系图交互方式，把真实 Semantic Trial 事件投影为 Actor、Post、Comment 与 Reaction 关系，并支持节点核验；该图明确不是 Zep 世界图，也不表示现实社会关系。
- 证据世界图：把不可变 WorldSnapshot 直接投影为 Snapshot、Article、Source、Country 节点及其可证明关系；默认由 PostgreSQL 快照数据计算，前端 SVG 只负责交互展示，不需要 Zep Cloud。
- 千问语义世界图：对同一冻结快照异步提取组织、人物、地点、政策、事件和概念关系；每个节点与关系都必须携带可在冻结正文中逐字校验的引用，PostgreSQL 保存规范化图和内容哈希，Zep Cloud 不参与运行链路。

本分支没有 `Company` 主体库、企业别名、企业报道 coverage、企业关系链、产业链、股权链或 GTV。媒体文章仍可包含企业内容，也可使用通用全文搜索检索企业名称，但系统不把它解释为已完成企业实体识别。

完整捕获文本和每个快照都使用 SHA-256 内容地址。世界快照、场景和运行输入使用 draft→sealed 状态与数据库触发器保护；封存后拒绝修改、删除、追加子记录和 `TRUNCATE`。这些机制属于跨项目整合所需的可追溯性与一致性，不是独立企业功能。

语义实验是 synthetic bounded observations：最多 8 个 Persona、3 轮，且整个矩阵不超过 96 persona-rounds。Persona prompt 只使用确定性的有界档案投影；记录的 seed 不能保证外部 provider 完全可复现。这些事件和计数不是 forecast、verdict、stance 或 reach，也不是现实因果结论。

持久 Decision Thread 已把 WorldSnapshot、Scenario、Cohort、SemanticExperiment 和报告入口组织成可恢复、可深链、只追加修订的任务上下文。章节式 Findings 已把配对观测、解释限制和来源哈希封存为可重复读取的报告，并支持 Markdown 下载。MatrAIx Survey 已接通封存 Scenario/Cohort、固定三题、逐 Persona 千问执行和精确聚合；MatrAIx Chat 已接通封存 Cohort、固定 source sample、真实多轮 Persona 对话、逐条 transcript 与 typed verifier result；固定 Web quote-choice source sample 已接通独立 Playwright 执行器、截图与逐字引文；固定 Linux note-to-CSV source sample 已接通独立非特权产物 Runner、typed verifier 与内容哈希下载；Trial Archive 和 Batch Registry 已接通有界统一目录与不可变父运行分组；Persona 证据访谈已接通单人追问和同问题 2～8 人原子会话；AgendaScope 默认关闭的周期快照刷新、并发锁和导入状态也已接通。语义图节点现在可以对冻结 Persona 的有信息属性执行有界精确词法匹配，人工选择 1～8 个候选后会把图谱、节点、数据集、成员顺序和内容哈希与 Cohort 一起封存，并可从 Cohort 详情分页恢复全部来源。仍未整合的主要范围包括完整自主 ReAct ReportAgent 与自动工具规划，更高级的 Population 排序、事实有效期和混合检索；MatrAIx 桌面 OS Task、通用 Computer Use、通用 Web/Harbor launch/verifier/artifact 执行面；AgendaScope 真正 CDC 与非文章对象删除对账；政策数据领域；以及 Decision Thread 协作权限、生产级认证/RBAC/审计、水平扩展和产物保留策略。World Slice 已支持从任意已校验实体出发，按双向/向外/向内查询 1～3 跳且有明确节点上限的邻域；Evidence Timeline 已按冻结文章发布时间组织图谱对象，并明确不把发布时间解释为事实生效时间。语义图默认使用 PostgreSQL、规模达到瓶颈后可增加阿里云 GDB Provider；Zep Cloud 不再是目标架构的必选依赖，ECharts/现有 SVG 只负责消费统一 nodes/edges API。当前数据也不是全国媒体、全国政策或全国企业主体的实时全量库。

Persona 证据访谈已完成单人追问与 2～8 人原子会话、固定报告章节引用的真实纵向链路；报告页还提供基于同一证据问答队列的固定“证据脉络 / 对照与边界”叙事镜头。完整 MiroFish 自主 ReAct ReportAgent、运行中 Agent IPC 与自动工具规划仍未迁移。

## 结构

```text
frontend/             React + TypeScript + Vite
backend/              Python 3.12 FastAPI 控制面
backend/oasis_worker/ 隔离的 Python 3.11 OASIS 执行进程
backend/migrations/   Core 专属 Alembic 迁移谱系
compose.yaml          PostgreSQL、Redis、API、worker、frontend 统一拓扑
```

仓库不创建顶层 `services/` 或额外运行仓库。OASIS 0.2.5 要求 Python `<3.12`，所以 worker 使用独立镜像，但仍由同一个 Compose 命令管理。

## 本地开发

```bash
pnpm install
pnpm setup
pnpm dev
```

- 前端 Vite：<http://127.0.0.1:3300>
- 后端：<http://127.0.0.1:8310>
- OpenAPI：<http://127.0.0.1:8310/api/v2/docs>

开发时只使用 `3300`。下面的 Compose 前端是生产构建验收入口 `3200`，不要与本地 Vite 同时启动。SendOwl 不使用原 `ai-decision-center` 的端口、Compose project、镜像或数据卷。

## 一条命令启动完整栈

```bash
pnpm stack
```

Compose 会先运行 Alembic migration，再启动 API、OASIS worker 和 Nginx 前端。默认本机入口为 <http://127.0.0.1:3200>。

Core 分支使用独立的 Compose project 和数据卷，当前 Alembic head 为 `20260816_core_0035`，与企业版分支的 revision ID 分离。不要把已运行企业版迁移的外部数据库直接配置给本分支；版本不匹配会明确失败，而不会把两种 schema 视为相同版本。

非本机环境必须提供独立环境文件并替换所有凭据：

```bash
SENDOWL_ENV_FILE=/absolute/path/to/production.env pnpm stack
```

## 导入 AgendaScope 媒体数据

先启动目标栈，再创建一个独立、不会提交到 Git 的环境文件。源地址必须使用 AgendaScope 专用只读账号，并显式声明预期数据库名和 Alembic revision；程序会在连接后核对，且不会把地址或凭据写入日志：

```bash
cp .env.example .env.media-sync
# 编辑 .env.media-sync：填写 AGENDASCOPE_DATABASE_URL、
# AGENDASCOPE_EXPECTED_DATABASE_NAME 与 AGENDASCOPE_EXPECTED_SCHEMA_REVISION。
SENDOWL_ENV_FILE="$PWD/.env.media-sync" pnpm import:agendascope
```

导入器使用可重复读的只读源事务，按批次幂等 upsert 到 SendOwl `media_*` 表，不复制向量列，也不在日志中打印数据库地址。每次运行会全量扫描受支持的源表、只更新目标中的差异行；它不是 CDC 或双向同步。完整扫描中已不再出现的文章会在 SendOwl 标记为源端缺失并从当前媒体 API 隐藏，但不会删除已冻结证据行；来源、议题、议题关系等其他源对象的删除仍不传播。传播数据优先读取 AgendaScope 的规范 `agenda_event_followers` 关系，并保留 follower/source/article/sequence/time 身份；尚未回填规范关系的历史事件会明确标记为 `legacy_projection`，继续从 `agenda_events.follower_sequence` 展开为 origin→followers 星型链路。媒体写入、文章存在性对账、逐表计数和成功状态在同一 SendOwl 目标事务提交，失败或取消时保留上次成功快照。

需要周期刷新时，必须显式启用默认关闭的 Compose profile：

```bash
SENDOWL_ENV_FILE="$PWD/.env.media-sync" pnpm stack:media-sync
```

`media-sync-worker` 没有端口、Docker socket、宿主项目挂载或旧项目数据卷，只连接显式 AgendaScope 源与 SendOwl 目标。重叠运行不会排队：第二次尝试记录为 `skipped_concurrent`。同步状态通过 `GET /api/v2/media/sync-status` 的单个只读一致快照读取；失败不会发布虚假的下次调度时间。不可重试的配置或源 schema 错误以状态码 2 停止且不会自动重启，操作员修正环境后再显式启动。AgendaScope 暂时不可用不会让 SendOwl `/readyz` 失败，API 会继续服务最后一次成功快照。

## 导入 MatrAIx Persona 数据集

先启动目标栈，再显式指定一个本机 MatrAIx Persona 数据集目录：

```bash
MATRAIX_PERSONA_DATASET_PATH='/absolute/path/to/persona/datasets/example' \
  pnpm import:matraix-personas
```

命令只把该目录挂载为容器内只读路径，严格核对 manifest、文件清单、Persona 档案和内容摘要；同一内容重复导入返回原 dataset ID。仓库不会复制或重新发布 Persona 数据文件，使用者仍需自行确认数据集许可。

## 配置 OASIS 语义实验

worker 只从显式环境变量创建 OpenAI-compatible 连接器：

```dotenv
LLM_API_KEY=…
LLM_BASE_URL=https://provider.example/v1
LLM_MODEL_NAME=…
```

三项全空时只禁用语义实验，platform smoke 仍可用；只配置其中一部分时 worker 会明确启动失败。配置完整时，worker 会先对真实 provider 发起一次有界、无业务副作用的 `do_nothing` tool-call 启动探测；只有返回符合严格契约的单个工具调用后才发布 semantic-ready 心跳，失败会在有界重试后使 worker 启动失败。`GET /api/v2/simulations/oasis/semantic-readiness` 再基于近期 worker 心跳、固定 OASIS/CAMEL 版本和唯一一致的不含密钥配置摘要决定是否允许提交；API 和数据库不保存 API key。

## 验证

```bash
pnpm verify
```

需要执行真实 PostgreSQL 迁移、触发器和 repository 行为测试时，使用隔离的 Compose test profile：

```bash
pnpm test:backend:postgres
```

该命令启动不暴露宿主机端口的 `postgres-test`，数据目录使用 tmpfs；测试镜像先把该库迁移到当前 Alembic head，再将仅在 Compose 网络内可见的 `TEST_POSTGRES_DATABASE_URL` 传给 pytest。它不会连接 `postgres` 应用服务或 `sendowl-postgres-data` 数据卷。

接手开发前先阅读 [项目交接与上下文](./docs/handoff.md)。产品原则见 [PRODUCT.md](./PRODUCT.md)，当前领域边界见 [架构文档](./docs/architecture.md)。
