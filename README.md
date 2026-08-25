# SandOwl Core Integration

> M16 工程基线（2026-08-24）：M11–M15 三方主链、Project-bound Harbor 不可变重试谱系和全量前端响应式加固均已通过工程验收；Alembic head 为 `20260820_core_0061`。Owner 选择不执行零提示中文复测，因此当前状态是 engineering pass，不是外部用户验证通过。仓库 CI 已覆盖前端、后端、OASIS Worker 与独立 PostgreSQL 集成套件。

SandOwl 整合 AgendaScope、MiroFish/OASIS 与 MatrAIx。历史上的 `ai-decision-center` 是基于 MiroFish 的研究性二开，是当前仓库的工程血缘而不是第四个产品来源；SandOwl 会保留其中属于三方整合和通用工程的能力，并逐步退出其多方案决策产品层。

当前分支只保留项目整合及其必要的工程能力，不包含后来单独扩展的企业业务。现有可运行链路是：

```text
AgendaScope 媒体文章
  → 人工选择并确认通用证据
  → 不可变 WorldSnapshot
  → Research Project

MatrAIx Persona Dataset
  → 严格导入与内容寻址
  → 不可变 Cohort

Research Project + Cohort + 单一模拟要求
  → 独立 Simulation Run
  → OASIS / CAMEL 合成模拟
  → 类型化观测事件
  → 单 Run 封存报告
  → ReportAgent / Agent Interaction

成功 Simulation Run + 该 Run 的冻结 Cohort
  → MatrAIx 单一上下文 Persona Survey
  → 清晰度 / 关注点 / 未解问题
```

当前真实能力包括：

- 媒体证据：将 AgendaScope PostgreSQL 的来源、文章、议题、快照和可逐字回指文章的正向首发观察幂等导入 V2 自有表，提供媒体统计、地域热点、议题、来源和文章检索。来源证据档案把每个来源严格关联到已导入、非重复的报道分页，并在同一只读快照中给出报道总量和时间边界；议题观察镜头只展示原文可核验的首发引用，不导入模型推理，也不把模型判断冒充权威的“最早表述”结论。首页地球复用 MatrAIx 的渲染原语，但只编码真实地域聚合，不生成虚构城市或传播关系。
- 政策证据：人工核对并捕获真实发布机构、辖区、规范文号、原文地址、发布日期、施行/失效日期与完整正文。稳定政策身份和最多 100 个不可变版本均使用内容地址，数据库会复算哈希并拒绝修改、删除或截断；目录、版本历史与完整正文分层读取。World 工作区可显式选择精确政策版本，把完整元数据、正文和哈希复制进不可变快照；含政策的新快照使用 `world-snapshot/v3`，纯媒体历史快照仍保持 `v2` 内容地址。当前不提供自动政策采集，也不把 Agent 输出当作政策事实。
- 受控 ReportAgent 证据运行：Evidence Bundle 工作台可把一个已封存 WorldSnapshot、分析目标、2～6 段有序大纲和 1～20 次工具预算冻结为内容寻址运行。`list_evidence`、`read_media`、`read_policy` 只能读取该快照内的媒体与政策，越界目标和预算耗尽会明确失败；每次调用按连续位置追加输入、结果和调用哈希，数据库拒绝修改、删除或截断。原生“报告与交互”目录以完成的 Simulation Run 为单位读取封存报告，并且只有用户明确点击后才生成引用报告或继续最多五轮 Agent Interaction。工作进程与 API 都会把回答引用反向校验到同一冻结原文的精确字符区间。旧 Decision Thread、DecisionReport、旧报告问答与旧 Persona Interview 已转为只读归档：读取、下载、UUID 和内容哈希保留，写入口返回 `410 Gone`。独立 MatrAIx Evaluation 不自动验证或排名模拟结论。当前切片不自动规划，也不冒充完整自主 ReAct ReportAgent。
- 通用世界快照：研究员可从任意已导入文章中选择 1～50 篇，阅读后显式确认，再创建 `WorldModel` 与不可变 `WorldSnapshot`。提交携带完整证据修订摘要；标题、正文、摘要、来源、URL、时间或地域变化时，后端返回 `409` 并要求重新阅读确认。
- 原生研究项目与单次运行：Research Project 只冻结证据快照和研究问题；每次 Simulation Run 再独立绑定 Cohort、模拟要求、seed、轮次和单一初始声明。运行与报告不创建 baseline、alternative、paired comparison 或推荐排序。
- 人群上下文：从显式指定的 MatrAIx 数据集目录严格读取 manifest 与 Persona YAML，按数据集、档案和成员顺序计算内容摘要，再原子封存为可追溯 Dataset、Persona 与 Cohort。数据文件不打包进本仓库，导入时只读挂载，来源与授权责任保持可见。
- 原生模拟运行入口：`#/runs` 直接进入 Research Project / Simulation Run 工作台，要求先明确选择项目，再定义单次运行；成功运行可深链进入原生报告与交互。
- 连续上下文交接：Research Project 只定义证据与问题，通过 `project_id` 进入模拟运行；报告通过 `project_id + run_id` 与对应 Run 双向跳转，用户不需要复制 UUID。
- OASIS 平台验证归档：旧 platform-smoke 运行、SQLite 产物和读取接口继续保留，但新建接口返回 `410 Gone`，仅通过显式历史深链访问，不再作为默认模拟运行入口。
- ADC 多方案语义实验归档：旧 Scenario、Semantic Experiment、Decision Thread、DecisionReport、旧报告问答、旧 Persona Interview 和 Scenario Preference Survey 保持可读、可下载和内容哈希可复算，但新建/追加入口返回 `410 Gone`，不再作为 SandOwl 原生工作流。
- 原生 MatrAIx Survey：只接受一个成功的 Simulation Run，自动继承该 Run 的冻结 Cohort，并逐 Persona 回答固定三题：上下文清晰度、下一关注点和一个未解问题。它不包含 baseline/alternative，不比较、排名或推荐方案，也不验证 Simulation Run 的现实有效性。旧 Survey trial 继续由 Trial Archive 只读展示。
- Task Gallery：统一展示 SandOwl 的研究 Survey、Chatbot Evaluation、固定来源样例 Web Evaluation、固定 Linux 产物任务、Trial Archive 与 Batch Registry；可用性同时读取 `/api/v2/system/capabilities` 与各执行器的实时 readiness。历史 ADC 能力只在能力目录标记为只读，不进入普通新建流程；尚未迁移的 OS App、通用 Computer Use 与 Harbor 不伪装成可运行能力。
- MatrAIx Chatbot Evaluation：固定接入 MatrAIx 仓库的 Acme Support REST 与 streamable-HTTP MCP 两个 source sample，把一个封存的 1～8 人 Cohort 展开为逐 Persona 多轮试验。隔离 sidecar 提供确定性支持回复；Worker 只允许固定 MCP 工具，真实千问生成 Persona 消息和严格 self-report，PostgreSQL 保存逐条 transcript、typed feedback、运行结果与内容哈希。样例不是生产客服系统，也不输出 benchmark reward。
- MatrAIx Web Evaluation：固定接入 MatrAIx `example-web-playwright_quote-choice` source sample，把封存的 1～4 人 Cohort 展开为逐 Persona 试验。独立、无 Docker socket 的 Chromium 容器只访问固定的 Quotes to Scrape 来源，读取三页真实 DOM、保存内容寻址截图和引文；Worker 只能从实际观察到的引文中提交选择。失败 Evaluation 可创建最多五次、保留旧记录的不可变 attempt 谱系。它不是任意网址浏览器、通用 Web Agent、Harbor trajectory 或生产任务。
- MatrAIx Linux Artifact Trial：固定接入 `matraix/linux-note-to-csv` source sample。用户显式选择封存 Cohort 与其中一个 Persona 后，千问只提交受约束解释和合成反馈；独立非特权 Runner 写入并校验固定 CSV、submission、feedback 与 verifier 产物，API 按允许清单和内容哈希读取。失败 Trial 可创建最多五次、保留旧产物身份的不可变 attempt 谱系，并为每次 attempt 封存独立 Evaluation。该任务不执行任意 shell、不接收任意路径，也不是桌面 Computer Use、OS App 或 Harbor runtime。
- Trial Archive：把原生 Research Survey、历史 ADC Survey、Chat、固定 Web 与固定 Linux trial 投影为同一份有界分页目录；历史 Survey 带有显式“历史 ADC”标记并深链到只读 API，原生 Survey 深链到研究 Survey 工作区。Archive 只读取轻量身份与结果摘要，不把回答、合成反馈或协议完成状态改写成 reward。
- Batch Registry：可把 1～20 个已封存的原生或历史 Survey、Chat、Web、Linux 父运行按显式顺序登记。原子创建中的 Survey 只接受 `Research Project + succeeded Simulation Run`，自动继承该 Run 的 Cohort，不接受 Scenario、baseline 或 alternative；Chat 保持固定任务契约。任一输入失败会整体回滚。Web 和 Linux 只进入登记候选，不进入原子创建；这不等于 Harbor job launch/retry，也不提供 verifier reward、通用 artifacts 或授权导出。
- 运行目录与进度读取：Survey、Chat、Web、Linux 四类 sealed parent 均提供统一严格、有界的 `page/page_size` 目录；Linux 仍保留 Trial 详情与产物深链，但运行页的历史选择以 Evaluation 父资源为准。四类 parent 另提供同语义的轻量 progress 投影，包含逐状态 Trial 计数、append-only 事件计数和稳定修订摘要。Chat 运行页使用数据库 identity 游标增量读取 append-only transcript，并仅在 Trial 状态变化或进入终态时重读 typed detail；该游标是传输元数据，不进入 transcript 内容哈希。Web pages/quotes 与终态在同一事务提交，Linux artifact 也只在终态封存后开放读取，因此两者在摘要变化后一次读取完整 typed detail，不暴露没有运行中可见数据的伪增量接口。
- 运行互动图：借用 MiroFish 的关系图交互方式，把真实 Semantic Trial 事件投影为 Actor、Post、Comment 与 Reaction 关系，并支持节点核验；该图明确不是 Zep 世界图，也不表示现实社会关系。
- 证据世界图：把不可变 WorldSnapshot 直接投影为 Snapshot、Article、Source、Country 节点及其可证明关系；默认由 PostgreSQL 快照数据计算，前端 SVG 只负责交互展示，不需要 Zep Cloud。
- 千问语义世界图：对同一冻结快照异步提取组织、人物、地点、政策、事件和概念关系；每个节点与关系都必须携带可在冻结正文中逐字校验的引用，PostgreSQL 保存规范化图和内容哈希，Zep Cloud 不参与运行链路。

本分支没有 `Company` 主体库、企业别名、企业报道 coverage、企业关系链、产业链、股权链或 GTV。媒体文章仍可包含企业内容，也可使用通用全文搜索检索企业名称，但系统不把它解释为已完成企业实体识别。

完整捕获文本和每个快照都使用 SHA-256 内容地址。世界快照、场景和运行输入使用 draft→sealed 状态与数据库触发器保护；封存后拒绝修改、删除、追加子记录和 `TRUNCATE`。这些机制属于跨项目整合所需的可追溯性与一致性，不是独立企业功能。

历史多方案 Semantic Experiment 是 synthetic bounded observations：最多 8 个 Persona、3 轮，且整个矩阵不超过 96 persona-rounds；该入口现已只读。原生单次 Simulation Run 最多 8 个 Persona、6 轮，可按最长 48 小时的确定性计划注入定时合成事件。两类运行的 Persona prompt 都只使用确定性的有界档案投影；记录的 seed 不能保证外部 provider 完全复现，事件和计数也不是 forecast、verdict、stance、reach 或现实因果结论。

当前原生主链是 WorldSnapshot → Research Project → 单次 Simulation Run → Research Report / ReportAgent → Agent Interaction，并可从成功 Run 派生单一上下文 Research Survey。旧 Decision Thread、Scenario、Semantic Experiment、DecisionReport 和 Scenario Preference Survey 仅保留历史读取。Trial Archive 与 Batch Registry 同时识别原生 Research Survey 和历史 ADC Survey，但所有新 Survey 写入只走原生 Research Run 契约。仍未整合的主要范围包括 ReportAgent 自动受控规划与完整自主 ReAct、更高级的 Population 排序与混合检索、桌面 OS / 通用 Computer Use、通用 Web/Harbor 执行面、AgendaScope 真正 CDC 与非文章对象删除对账，以及生产级认证/RBAC/审计、水平扩展和产物保留策略。

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

开发时只使用 `3300`。下面的 Compose 前端是生产构建验收入口 `3200`，不要与本地 Vite 同时启动。SandOwl 不使用原 `ai-decision-center` 的端口、Compose project、镜像或数据卷。

## 一条命令启动完整栈

```bash
pnpm stack
```

Compose 会先运行 Alembic migration，再启动 API、OASIS worker 和 Nginx 前端。默认本机入口为 <http://127.0.0.1:3200>。

Core 分支使用独立的 Compose project 和数据卷，当前 Alembic head 为 `20260820_core_0061`，与企业版分支的 revision ID 分离。不要把已运行企业版迁移的外部数据库直接配置给本分支；版本不匹配会明确失败，而不会把两种 schema 视为相同版本。

非本机环境必须提供独立环境文件并替换所有凭据：

```bash
SANDOWL_ENV_FILE=/absolute/path/to/production.env pnpm stack
```

## SandOwl 原生媒体采集

默认栈包含 `media-collector-worker`。它只抓取用户在媒体工作台明确新增并启用的公开 RSS/Atom 或网页来源，直接写入 SandOwl PostgreSQL，同时维护正文提取、URL 去重、源健康、告警、议题生命周期和传播观察。未配置来源时 worker 只发布心跳，不访问外网。

## 历史 AgendaScope 数据迁移

先启动目标栈，再创建一个独立、不会提交到 Git 的环境文件。源地址必须使用 AgendaScope 专用只读账号，并显式声明预期数据库名和 Alembic revision；程序会在连接后核对，且不会把地址或凭据写入日志：

```bash
cp .env.example .env.media-sync
# 编辑 .env.media-sync：填写 AGENDASCOPE_DATABASE_URL、
# AGENDASCOPE_EXPECTED_DATABASE_NAME 与 AGENDASCOPE_EXPECTED_SCHEMA_REVISION。
SANDOWL_ENV_FILE="$PWD/.env.media-sync" pnpm import:agendascope
```

导入器使用可重复读的只读源事务，按批次幂等 upsert 到 SandOwl `media_*` 表，不复制向量列，也不在日志中打印数据库地址。每次运行会全量扫描受支持的源表、只更新目标中的差异行；它不是 CDC 或双向同步。完整扫描中已不再出现的文章会在 SandOwl 标记为源端缺失并从当前媒体 API 隐藏，但不会删除已冻结证据行；来源、议题、议题关系等其他源对象的删除仍不传播。传播数据优先读取 AgendaScope 的规范 `agenda_event_followers` 关系，并保留 follower/source/article/sequence/time 身份；尚未回填规范关系的历史事件会明确标记为 `legacy_projection`，继续从 `agenda_events.follower_sequence` 展开为 origin→followers 星型链路。媒体写入、文章存在性对账、逐表计数和成功状态在同一 SandOwl 目标事务提交，失败或取消时保留上次成功快照。

仅在迁移旧 AgendaScope 数据库时，才显式启用默认关闭的兼容 profile：

```bash
SANDOWL_ENV_FILE="$PWD/.env.media-sync" pnpm stack:media-sync
```

`media-sync-worker` 没有端口、Docker socket、宿主项目挂载或旧项目数据卷，只连接显式 AgendaScope 源与 SandOwl 目标。重叠运行不会排队：第二次尝试记录为 `skipped_concurrent`。同步状态通过 `GET /api/v2/media/sync-status` 的单个只读一致快照读取；失败不会发布虚假的下次调度时间。不可重试的配置或源 schema 错误以状态码 2 停止且不会自动重启，操作员修正环境后再显式启动。AgendaScope 暂时不可用不会让 SandOwl `/readyz` 失败，API 会继续服务最后一次成功快照。

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

该命令启动不暴露宿主机端口的 `postgres-test`，数据目录使用 tmpfs；测试镜像先把该库迁移到当前 Alembic head，再将仅在 Compose 网络内可见的 `TEST_POSTGRES_DATABASE_URL` 传给 pytest。它不会连接 `postgres` 应用服务或 `sandowl-postgres-data` 数据卷。

仓库 CI 位于 [`.github/workflows/ci.yml`](./.github/workflows/ci.yml)。向 `main` 推送或创建 Pull Request 时会并行执行前端测试、类型检查与生产构建，后端测试与 Ruff，Python 3.11 OASIS Worker 测试与 Ruff，以及独立 PostgreSQL 16.8 迁移/触发器集成套件。CI 只授予 `contents: read`，不读取本地 `.env`，也不连接 SandOwl 开发数据卷。

接手开发前先阅读 [项目交接与上下文](./docs/handoff.md)。产品原则见 [PRODUCT.md](./PRODUCT.md)，当前领域边界见 [架构文档](./docs/architecture.md)。
