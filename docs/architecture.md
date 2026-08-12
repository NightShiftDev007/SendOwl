# AI Decision Center V2 架构

## 目标产品数据流

```text
Media / Policy Reality
  → Article Evidence
  → Company & Entity Resolution
  → Versioned World Snapshot
  → Decision / Scenario
  → MatrAIx Population Trial + OASIS Social Evolution
  → Comparable Metrics / Explanation / Report
```

真实观测、模型假设、模拟结果和人工判断是四类不同的数据。V2 的契约必须保留来源、时间、版本和内容摘要，任何下游结果都能回溯到不可变的 Evidence Bundle 与 World Snapshot。

## 运行拓扑

```text
React frontend
      │ /api/v2
      ▼
FastAPI backend ───── PostgreSQL + pgvector
      │
      ├────────────── Redis queue / coordination
      │
      └── PostgreSQL durable run queue ── OASIS worker (Python 3.11)
                                             │
                                             └── SQLite artifact volume
```

- PostgreSQL 是业务实体、证据、任务和运行状态的事实源。
- Redis 只负责队列、短期协调和进度分发，不保存唯一业务事实。
- 大型正文快照、运行轨迹和报告附件进入可替换的 artifact storage，数据库保存内容摘要和引用。
- API、采集 worker、分析 worker 和模拟 worker 属于同一 `backend` 领域代码区，不形成新的代码仓库。OASIS 0.2.5 的 Python `<3.12` 约束要求模拟 worker 使用独立 Python 3.11 镜像，API 继续使用 Python 3.12；二者仍由同一个 Compose 命令管理。
- Compose 以一次性 Alembic migration 作为后端启动前置条件；`/health` 只表示进程存活，`/readyz` 检查必需的 PostgreSQL 依赖。

## 后端领域边界

| 领域 | 职责 | 主要来源 |
|---|---|---|
| `media` | 来源、采集任务、规范化文章快照 | AgendaScope |
| `evidence` | 内容寻址、证据包、来源与处理溯源 | AgendaScope + V2 |
| `companies` | 企业主体、别名、提及、关系与消歧 | V2 新模型 |
| `world` | 本体版本、不可变世界快照、切片与人口 | 原 AI Decision Center |
| `scenarios` | Decision、基线、干预和实验规格 | 原 AI Decision Center |
| `simulations` | MatrAIx / OASIS adapter 与统一结果契约 | MatrAIx + OASIS |
| `reports` | 方案比较、限制、证据引用和导出 | 原 AI Decision Center + MatrAIx |

adapter 只负责把稳定领域契约转换为外部引擎协议。业务 API 不暴露 AgendaScope、MatrAIx、MiroFish 的内部路由或存储模型。

## 统一产品工作区

V2 不复制四个项目各自的菜单，也不以任一项目的前端作为母版。用户围绕同一个决策对象工作，页面和稳定资源 ID 贯穿完整链路：

```text
态势总览 / 媒体证据
  → 企业与关系证据
  → 世界模型与不可变快照
  → 场景设计
  → 人群实验 / 社会模拟
  → 指标、解释与报告
```

| 工作区 | 稳定资源 | 融合能力 |
|---|---|---|
| 态势总览 | `MediaArticle`、`MediaTopic`、`MediaSource` | AgendaScope 真实媒体数据；MatrAIx 地球渲染原语改造成真实地域态势入口 |
| 企业证据 | `Company`、`CompanyAlias`、`MediaArticle` | 企业名单、别名、字面名称命中候选及上下文；人工核验入口已与世界快照连接，自动语义消歧和 Evidence Bundle 待迁移 |
| 世界模型 | `WorldModel`、`WorldSnapshot` | V2 不可变证据快照及追加版本已接通；原 Decision Center 本体、完整图谱、切片与人口语义以及 MiroFish Zep 实现待迁移 |
| 场景实验 | `Scenario`、`PopulationSpec`、`SimulationRun` | 原 Decision Center 场景矩阵；MatrAIx Persona/Survey/Trial；OASIS 传播演化 |
| 判断报告 | `MetricSet`、`Report` | 可复现指标、限制、证据引用、方案比较与访谈 |

界面只把已经接通真实数据和运行时的能力标为可用。尚未迁移的工作区保留明确的迁移状态，不使用静态演示数据伪装成已完成能力。

## 当前纵向切片

当前实现以 AgendaScope PostgreSQL 的导入快照为媒体输入，在同一前端、后端和 PostgreSQL 中提供四条相连链路：

```text
AgendaScope PostgreSQL
  → 只读、可重复读的幂等 upsert 导入
  → V2 PostgreSQL media_* 表
  ├→ /api/v2/media/* → 媒体总览、议题、来源、文章检索与地域地球
  └→ Company + CompanyAlias
       → 字面名称匹配
       → /api/v2/companies/* → 待核验文章、上下文与字符位置
       → 用户选择 1～50 篇并显式声明已人工确认
       → 将已审阅完整证据修订 SHA-256 随选择提交，变化时 409 要求重新核验
       → POST /api/v2/world-models
       → 原子创建 WorldModel + WorldSnapshot v1
       → /api/v2/world-models/* → 不可变详情与只追加的版本历史
       → 选择一个已封存 WorldSnapshot 版本
       → POST /api/v2/scenarios
       → 无干预基线 + 1～5 个备选方案 + 有序 Reddit 初始帖子
       → /api/v2/scenarios/* → 不可变实验档案与 scenario_sha256
       → 选择一个备选方案和固定 seed
       → POST /api/v2/simulation-runs/platform-smoke
       → PostgreSQL durable queue → Python 3.11 OASIS worker
       → OASIS 0.2.5 Reddit + SQLite + ordered manual CREATE_POST
       → /api/v2/simulation-runs/* → 输入哈希、生命周期、产物哈希与限制
```

导入器保存源库在执行时可见记录的 upsert snapshot，不是双向同步、CDC 或源库删除镜像；源库删除不会自动传播到 V2。导入结束后，查询链路不要求 AgendaScope 服务常驻。

企业链路输出的是名称字面命中候选，而不是完成语义消歧后的企业事件。它可能包含同名、词内包含或上下文不指向目标企业的结果。世界模型工作台因此要求用户逐篇阅读上下文，并显式提交 `human_confirmed` 声明；这是当前进入快照的信任边界，不代表系统已经完成自动实体消歧。当前是单用户运行方式，确认声明尚未绑定登录操作者身份，不能作为多用户审计记录使用。

创建世界模型时，后端在一个数据库事务内创建持久模型和版本 1。快照把当时的企业规范名称与别名，以及所选报道的 `article_id`、来源、原始链接、标题、完整 `captured_text`、发布时间、捕获时间、国家、摘要复制到 PostgreSQL；每次名称命中的别名、表面文本、字符起止位置和上下文也按顺序冻结。读取模型或快照只查询 `world_*` 冻结表，不关联后来可能变化的 `companies` 或 `media_*` 记录。

每篇捕获文本具有 `captured_text_sha256`，整个冻结版本具有 `snapshot_sha256`。coverage 还返回 `evidence_revision_sha256`，覆盖标题、正文、摘要、URL、发布时间、抓取时间、地域及来源身份；前端提交的是用户实际审阅的这一完整修订摘要。后端先与 AgendaScope 导入器取得同一事务级协调锁，再按稳定顺序锁定文章和来源行并复算；任一字段变化时返回 `409`，不会把未审阅的新证据版本标成 `human_confirmed`。正文超过 2 MiB、单篇超过 200 次精确别名命中或单快照超过 2,000 次命中时明确返回 `422`。冻结正文另有只读 endpoint，可独立复算其摘要。`snapshot_sha256` 是冻结内容地址；`created_at` 作为独立审计元数据保存，不宣称属于该内容地址。

向已有模型添加证据会创建下一个版本，不覆盖旧版本。Alembic `20260812_0002` 创建 `world_models`、`world_snapshots`、`world_snapshot_evidence` 和 `world_snapshot_mentions`；`20260812_0003` 建立基础不可变触发器；`20260812_0004` 增加 nullable draft 与原子 sealed 转换；`20260812_0005` 在升级前复算既有正文和快照摘要并拒绝损坏数据，同时要求父行只能以 draft 插入，且只有 1～50 篇连续证据、每篇至少一次连续命中时才能封存。后端只在同一事务写完父快照、证据和命中后封存；读取拒绝未封存 draft。封存后数据库拒绝父行修改或删除、子证据 `INSERT`/`UPDATE`/`DELETE`，以及三张冻结表的 `TRUNCATE`。

Scenario 只引用一个明确的已封存快照，不跟随模型的最新版本漂移。Alembic `20260812_0006` 创建规范化的 `scenarios`、`scenario_variants` 和 `scenario_interventions`，并在数据库中核验快照归属、内容摘要、版本、冻结企业名称及证据数量；父记录只能由完整 draft 封存，封存后父子表和 `TRUNCATE` 都受保护。读取 list/detail 时均从三表重建有序语义并复算 `scenario_sha256`。`20260812_0007` 在升级前拒绝重复内容地址，再建立唯一约束；API 使用同一内容摘要的事务级 advisory lock，使相同规格的重复 POST 返回同一资源。

本地真实验收状态为 1 个华为模型、4 个封存版本和 1 个绑定版本 4 的封存 Scenario；版本 4 通过完整证据修订摘要契约创建并完成正文摘要独立复算，Scenario 内容地址为 `d11f119baddc9e3541ee277cdfb01456f60ddee64f09b312d3a70f28729e431b`。0005 已在真实既有库上通过 preflight；0006 已实测拒绝父行修改、封存后子行追加及 `TRUNCATE`；0007 已应用，并实测 5 个并发相同 POST 全部返回同一个 Scenario ID 和内容摘要。OASIS 平台烟雾模式只验证真实引擎平台、SQLite 和手工动作执行，不产生受众代理行为、社会传播结果或方案判断。地域地球目前只迁入 MatrAIx 渲染原语并连接真实媒体聚合；MatrAIx Persona/Survey/Trial 与需要真实 LLM 和受权 Persona 的 OASIS 语义运行仍待接通。当前数据也不构成全国企业主体库、全国政策库或全量实时媒体库。

## 能力迁移边界

### AgendaScope

迁移采集流水线、来源治理、文章正文、去重、聚类、实体提取、议程检测和证据关系。其独立前端、用户系统、安装向导、许可管理与 Open API 不进入 V2。现有人物/机构枚举不能承载企业主体，企业、品牌、母子公司与别名消歧使用 V2 的新模型。现有 JSONB 与归一化 Topic 双轨也不会原样拼接迁移历史。

### 原 AI Decision Center

已落地 `WorldModel`、不可变 `WorldSnapshot` 证据基线，以及绑定精确快照版本的 baseline/alternative/initial-post Scenario；继续迁移 Ontology、完整关系图谱、World Slice、Population、Run、多样本比较、指标与报告的领域语义。Flask、SQLite registry、文件任务状态、进程内任务字典、daemon thread 和旧 Vue 界面不进入 V2。

### MatrAIx

迁移 Persona 数据协议、确定性抽样、Cohort、Survey/Trial、聚合结果，以及工作台、Persona 选择、运行与报告的交互语义。Harbor 和现有线程/文件执行设施不作为 V2 事实源；Persona 数据集必须逐项确认授权，不能因为代码使用 MIT 许可就默认数据可商用。

### MiroFish 与 OASIS

OASIS 保留为社会关系与传播演化引擎。当前已经先用其公开 API 接通 Reddit 平台、SQLite 和手工动作 smoke，并用隔离 worker 解决 Python 版本冲突；这不等于语义传播已经完成。MiroFish 是冻结的实现来源与参考基线，不作为运行中的第四个项目，也不进行双向整仓同步。后续上游修复只以经过许可、行为和测试审查的补丁进入 V2。

## 实现边界与后续顺序

| 范围 | 当前状态 |
|---|---|
| Foundation | React/FastAPI、严格领域契约、PostgreSQL/Redis 单栈、Alembic migration、存活与就绪检查已接通 |
| 媒体证据 | AgendaScope 导入快照、来源/文章/议题查询、媒体工作台和 MatrAIx 地球渲染原语已接通 |
| 企业解释 | 企业与别名、字面名称命中候选、人工核验入口已接通；自动实体消歧、事件、关系证据和 Evidence Bundle 待实现 |
| 世界快照 | 世界模型界面、模型与 v1 原子创建、冻结证据读取与摘要复算、修订冲突保护、追加版本、SHA-256 内容地址和数据库事务封存已接通；确认声明尚未绑定登录主体 |
| 决策实验 | 选择任意封存快照、无干预基线、1～5 个备选方案、初始帖子、Scenario 内容地址、重复 POST 去重和数据库封存已接通 |
| 世界与运行 | OASIS 0.2.5 平台/SQLite/手工动作 smoke、持久队列、worker 心跳与运行档案已接通；完整本体/图谱/Zep、Persona/Cohort、MatrAIx Trial 和 OASIS 语义 Run 待实现 |
| 判断闭环 | 可复现指标、证据化解释、方案比较、报告与历史回测待实现 |

后续仍以真实纵向切片验收；未迁移能力在 API 与界面中必须明确标记，不使用占位成功状态掩盖缺失。
