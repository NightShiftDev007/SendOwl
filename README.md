# SandOwl · AI Decision Center V2

SandOwl 的目标是把媒体与政策证据、企业世界模型、MatrAIx 人群实验和 OASIS 社会传播推演组织为一个可追溯的决策工作台。

当前可运行范围包含五个相连的真实纵向切片：

- 媒体证据：把 AgendaScope PostgreSQL 的来源、文章、议题和快照导入 V2 自有表，由 React 工作台展示媒体统计、地域热点、议题和文章检索；地域地球复用了 MatrAIx 的渲染原语。
- 企业名称命中候选：管理企业规范名称与别名，在已导入文章中查找字面命中，并返回来源、议题、上下文和字符位置供人工核验。字面命中不等于已确认企业报道，仍需实体识别和语义消歧。
- 企业世界快照：世界模型工作台从企业名称命中候选中选择 1～50 篇报道，要求用户显式声明已人工核验，再由一次原子请求创建 `WorldModel` 和版本 1 `WorldSnapshot`。界面把用户实际审阅的完整证据修订摘要随选择提交；正文、摘要、来源、URL、时间或地域已经变化时后端返回 `409`，要求刷新、重读和重新确认。新版本只追加、不覆盖；快照读取不再关联可变的企业或媒体记录。
- 决策实验：在任意一个已封存 `WorldSnapshot` 上建立无干预基线与 1～5 个备选方案，每个方案包含 1～20 条明确标注为实验假设的 Reddit 初始帖子。`Scenario` 在同一事务内 draft→sealed，并以 `scenario_sha256` 标识快照引用和有序实验语义；相同内容地址只保存一份，网络超时后的重提不会复制规格。
- OASIS 平台运行：从一个已封存 Scenario 备选方案复制有序初始帖，以 PostgreSQL 持久任务交给同仓库的 Python 3.11 worker，真实执行 OASIS 0.2.5 Reddit 平台、SQLite 持久化和手工 `CREATE_POST` 动作，并保存输入与产物摘要。该模式固定使用 CAMEL `StubModel`，只验收平台接线，不包含 LLM 受众行为、社会演化、预测或决策结论。

PostgreSQL 会在快照中复制企业名称与别名、报道来源与原始链接、标题与完整捕获文本、发布时间与捕获时间、国家、摘要，以及每次精确名称命中的别名、字符位置和上下文；完整捕获文本与快照分别具有 SHA-256 内容地址。Alembic `20260812_0002` 创建这组表，`20260812_0003` 建立基础不可变保护，`20260812_0004` 增加事务内 draft→sealed 封存，`20260812_0005` 在升级前重算并核验既有快照摘要，同时禁止直接插入 sealed 父行或封存空、不连续、无命中的 draft。封存后数据库拒绝父行修改或删除、子证据追加或修改，以及三张冻结表的 `TRUNCATE`。冻结正文可通过受控 API 读取并独立复算摘要。`snapshot_sha256` 标识冻结内容，`created_at` 是独立的审计元数据。

这些能力基于一次 AgendaScope 导入快照，不是全国企业主体库、全国政策库或全量实时采集系统。人工确认声明也不是自动实体消歧，当前单用户运行方式尚未把声明绑定到登录操作者。现有 `WorldSnapshot` 是可追溯证据基线，不是完整企业图谱或 Zep 世界模型；MatrAIx Persona/Trial 与需要真实 LLM/受权 Persona 的 OASIS 语义传播仍属于下一阶段。本地真实链路当前已保存 1 个华为模型、4 个封存版本和 1 个绑定版本 4 的封存实验；该实验内容地址为 `d11f119baddc9e3541ee277cdfb01456f60ddee64f09b312d3a70f28729e431b`。

## 结构

```text
frontend/       React + TypeScript + Vite
backend/        Python 3.12 FastAPI 控制面 + 隔离的 Python 3.11 OASIS worker
compose.yaml    frontend、backend、worker、PostgreSQL、Redis 的统一运行拓扑
backend/migrations/  Alembic 数据库迁移
docs/           V2 架构与设计系统
```

仓库只有一个前端和一个后端领域代码区，不创建 `services/` 或 `legacy/`。OASIS 0.2.5 要求 Python `<3.12`，因此 Compose 从同一 `backend` 目录构建独立的 Python 3.11 worker 镜像；这是同产品的执行进程角色，不是另一个仓库或需要单独启动的项目。

## 本地开发

```bash
pnpm install
pnpm setup
pnpm dev
```

- 前端：<http://127.0.0.1:3100>
- 后端：<http://127.0.0.1:8010>
- OpenAPI：<http://127.0.0.1:8010/api/v2/docs>

## 一条命令启动完整基础设施

```bash
pnpm stack
```

默认使用 `.env.example` 中仅供本机隔离开发的口令，前端位于 <http://127.0.0.1:3000>。非本机环境必须提供独立环境文件并更换全部凭据。

Compose 先运行一次 Alembic migration，再启动 API、OASIS worker 和前端。`/health` 用于 API 进程存活检查，`/readyz` 检查 API 所需的 PostgreSQL 连接；Runs 工作区另以数据库心跳核验 worker 与固定 OASIS/CAMEL 版本，worker 离线不会被伪装成平台已就绪。

```bash
ADC_ENV_FILE=/absolute/path/to/production.env pnpm stack
```

环境文件中的 `DATABASE_URL`、`REDIS_URL` 必须与容器初始化凭据一致；用户名或密码含 `/`、`?`、`#`、`@` 等保留字符时，需在 DSN 中进行 percent-encoding。`pnpm stack:down` 使用同一个 `ADC_ENV_FILE`。

## 验证

```bash
pnpm verify
```

## 导入现有 AgendaScope 媒体数据

目标 V2 栈启动后，显式提供 AgendaScope PostgreSQL 地址：

```bash
AGENDASCOPE_DATABASE_URL='postgresql://…' pnpm import:agendascope
```

导入器使用可重复读的只读源事务，按批次幂等 upsert 到 V2 自有 `media_*` 表，并输出每张表的读取、新增、更新和跳过数量；不会复制向量列，也不会在日志中打印数据库地址。它表达的是源库在导入时刻的增量快照，不是持续同步或删除镜像：源库后来删除的记录不会被导入命令自动从 V2 删除。导入完成后，V2 查询和界面不依赖 AgendaScope 服务常驻。

产品原则见 [PRODUCT.md](./PRODUCT.md)，工程边界与迁移顺序见 [架构文档](./docs/architecture.md)。
