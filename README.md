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

- 媒体证据：将 AgendaScope PostgreSQL 的来源、文章、议题和快照幂等导入 V2 自有表，提供媒体统计、地域热点、议题、来源和文章检索。首页地球复用 MatrAIx 的渲染原语，但只编码真实地域聚合，不生成虚构城市或传播关系。
- 通用世界快照：研究员可从任意已导入文章中选择 1～50 篇，阅读后显式确认，再创建 `WorldModel` 与不可变 `WorldSnapshot`。提交携带完整证据修订摘要；标题、正文、摘要、来源、URL、时间或地域变化时，后端返回 `409` 并要求重新阅读确认。
- 决策实验：在一个明确的封存快照上建立无干预基线与 1～5 个备选方案。每个方案包含有序的 Reddit 初始帖子；这些内容始终标记为实验假设，不会被呈现为现实事实。
- 人群上下文：从显式指定的 MatrAIx 数据集目录严格读取 manifest 与 Persona YAML，按数据集、档案和成员顺序计算内容摘要，再原子封存为可追溯 Dataset、Persona 与 Cohort。数据文件不打包进本仓库，导入时只读挂载，来源与授权责任保持可见。
- OASIS 平台验证：同仓库 Python 3.11 worker 从 PostgreSQL 持久队列领取任务，真实运行 OASIS 0.2.5 Reddit 平台、SQLite 持久化和手工 `CREATE_POST`。该 platform-smoke 模式固定使用 CAMEL `StubModel`，不读取 Cohort，仅验证平台接线。
- 有界语义实验：Persona World 将真实导入档案封存为 Cohort，并可带着 Cohort 或 Scenario 深链进入 Playground。Playground 把 Scenario baseline、1～2 个 alternatives 与 Cohort 组成持久实验矩阵；worker 在每个 seed 上使用真实 OpenAI-compatible LLM 执行 OASIS/CAMEL 受众动作，保存 SQLite 产物与类型化事件。决策报告页把真实 comparison 封存为固定四章节 Findings，展示实际观测计数、同 seed 配对差值、运行来源和限制，并提供 Markdown 下载；报告追问只使用同一快照的 PostgreSQL 语义图候选，回答必须保存精确文章引用与内容哈希。
- Task Gallery：统一展示 OASIS 与 MatrAIx 任务能力，可用性直接读取 `/api/v2/system/capabilities`。Survey 已提供真实 Playground；尚未迁移的 Chat、Web、OS App、Harbor 会明确锁定。
- 运行互动图：借用 MiroFish 的关系图交互方式，把真实 Semantic Trial 事件投影为 Actor、Post、Comment 与 Reaction 关系，并支持节点核验；该图明确不是 Zep 世界图，也不表示现实社会关系。
- 证据世界图：把不可变 WorldSnapshot 直接投影为 Snapshot、Article、Source、Country 节点及其可证明关系；默认由 PostgreSQL 快照数据计算，前端 SVG 只负责交互展示，不需要 Zep Cloud。
- 千问语义世界图：对同一冻结快照异步提取组织、人物、地点、政策、事件和概念关系；每个节点与关系都必须携带可在冻结正文中逐字校验的引用，PostgreSQL 保存规范化图和内容哈希，Zep Cloud 不参与运行链路。

本分支没有 `Company` 主体库、企业别名、企业报道 coverage、企业关系链、产业链、股权链或 GTV。媒体文章仍可包含企业内容，也可使用通用全文搜索检索企业名称，但系统不把它解释为已完成企业实体识别。

完整捕获文本和每个快照都使用 SHA-256 内容地址。世界快照、场景和运行输入使用 draft→sealed 状态与数据库触发器保护；封存后拒绝修改、删除、追加子记录和 `TRUNCATE`。这些机制属于跨项目整合所需的可追溯性与一致性，不是独立企业功能。

语义实验是 synthetic bounded observations：最多 8 个 Persona、3 轮，且整个矩阵不超过 96 persona-rounds。Persona prompt 只使用确定性的有界档案投影；记录的 seed 不能保证外部 provider 完全可复现。这些事件和计数不是 forecast、verdict、stance 或 reach，也不是现实因果结论。

持久 Decision Thread 已把 WorldSnapshot、Scenario、Cohort、SemanticExperiment 和报告入口组织成可恢复、可深链、只追加修订的任务上下文。章节式 Findings 已把配对观测、解释限制和来源哈希封存为可重复读取的报告，并支持 Markdown 下载。MatrAIx Survey 已接通封存 Scenario/Cohort、固定三题、逐 Persona 千问执行和精确聚合；仍未整合的主要范围包括完整 ReportAgent 工具链与角色访谈，语义图之上的 Population 映射、事实有效期和混合检索；MatrAIx Chat/Web/OS Task、通用 Trial 和 Harbor 执行能力；AgendaScope 持续同步、CDC、删除传播与导入任务档案；政策数据领域；以及 Decision Thread 协作权限、生产级认证/RBAC/审计、取消重试、水平扩展和产物保留策略。World Slice 已支持从任意已校验实体出发，按双向/向外/向内查询 1～3 跳且有明确节点上限的邻域；Evidence Timeline 已按冻结文章发布时间组织图谱对象，并明确不把发布时间解释为事实生效时间。语义图默认使用 PostgreSQL、规模达到瓶颈后可增加阿里云 GDB Provider；Zep Cloud 不再是目标架构的必选依赖，ECharts/现有 SVG 只负责消费统一 nodes/edges API。当前数据也不是全国媒体、全国政策或全国企业主体的实时全量库。

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

- 前端 Vite：<http://127.0.0.1:3100>
- 后端：<http://127.0.0.1:8010>
- OpenAPI：<http://127.0.0.1:8010/api/v2/docs>

开发时只使用 `3100`。下面的 Compose 前端是生产构建验收入口 `3000`，不要与本地 Vite 同时启动。

## 一条命令启动完整栈

```bash
pnpm stack
```

Compose 会先运行 Alembic migration，再启动 API、OASIS worker 和 Nginx 前端。默认本机入口为 <http://127.0.0.1:3000>。

Core 分支使用独立的 Compose project 和数据卷，当前 Alembic head 为 `20260813_core_0016`，与企业版分支的 revision ID 分离。不要把已运行企业版迁移的外部数据库直接配置给本分支；版本不匹配会明确失败，而不会把两种 schema 视为相同版本。

非本机环境必须提供独立环境文件并替换所有凭据：

```bash
ADC_ENV_FILE=/absolute/path/to/production.env pnpm stack
```

## 导入 AgendaScope 媒体数据

先启动目标栈，再显式提供 AgendaScope PostgreSQL 地址：

```bash
AGENDASCOPE_DATABASE_URL='postgresql://…' pnpm import:agendascope
```

导入器使用可重复读的只读源事务，按批次幂等 upsert 到 V2 `media_*` 表，不复制向量列，也不在日志中打印数据库地址。它表达导入时刻的增量快照，不是 CDC 或双向同步；源库删除不会自动传播。导入完成后，V2 查询不要求 AgendaScope 服务常驻。

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

产品原则见 [PRODUCT.md](./PRODUCT.md)，当前领域边界见 [架构文档](./docs/architecture.md)。
