# SandOwl Vertical Slice Demo Runtime Check

检查时间：`2026-08-16T09:36:49Z`

检查对象：当前 `compose.yaml` 运行态（Backend `127.0.0.1:8210`、Frontend `127.0.0.1:3200`）以及同一时刻的 SandOwl 工作区代码。所有结论均来自只读 API、数据库查询、容器状态和源码检查；本阶段未创建 Demo 资源。

## 总结

当前系统可以直接完成：

- 从现有 AgendaScope import 中选择精确 article revisions；
- 创建并 seal WorldModel / WorldSnapshot；
- 创建并 seal baseline + 2 alternatives 的 Scenario；
- 从现有 sealed Persona dataset 创建 5-persona Cohort；
- 在实验完成后从 Semantic Experiment 生成传统 DecisionReport。

当前系统不能直接完成：

- Semantic Experiment 实际运行。OASIS worker 在线，但 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_NAME` 均未配置，API 明确返回 `semantic_runtime_ready=false`；
- 新 ReportAgent evidence/draft 流程。相关代码和 migration 已存在于工作区，但当前数据库和运行镜像未升级到该版本。

核心阻塞是运行配置，不是缺少 Demo 证据或 Persona 数据。不能用手工结果、平台 smoke 结果或伪造事件替代 Semantic Experiment。

## 1. 当前数据库状态

PostgreSQL 容器正在运行且健康，Backend readiness 显示 database `connected`。检查时主要表计数如下：

| 表 | 行数 |
| --- | ---: |
| `media_articles` | 47,261 |
| `persona_datasets` | 1 |
| `personas` | 200 |
| `world_models` | 0 |
| `world_snapshots` | 0 |
| `scenarios` | 0 |
| `cohorts` | 0 |
| `semantic_experiments` | 0 |
| `semantic_trials` | 0 |
| `decision_reports` | 0 |

因此数据库不是空库，但 Vertical Slice 的 World → Scenario → Cohort → Experiment → Report 资源尚未创建。

## 2. Migration 最新状态

- 数据库 `alembic_version`：`20260815_core_0032`；
- 当前工作区 migration 链的最新文件：`20260816_core_0040_report_agent_cited_drafts.py`；
- `0033`–`0040` 尚未应用到当前数据库；
- 当前 Backend OpenAPI 与 `0032` 运行态一致：WorldSnapshot create 仍只接受 media `evidence`，不接受工作区新增的 `policy_evidence` 字段；
- 当前运行态已有本 Demo 必需的 world/scenario/population/semantic/decision-report 表和 API，所以不需要为了本 Demo 先升级 migration；
- 新 ReportAgent 依赖 `0039`–`0040`，不能在这个数据库上运行。

工作区在 `main`、HEAD `152b932`，且已有大量用户未提交修改。为避免污染或覆盖正在开发的 ReportAgent 工作，本 Demo 不重建镜像、不执行 migration upgrade，也不修改这些现有改动。

## 3. 是否已有 Demo 数据

有一部分可复用的开发数据：

- Persona dataset：`matraix-persona-dev-sample`；
- Dataset ID：`370c75f4-39d4-498b-922f-944d53df596b`；
- Persona 数：200；
- Dataset SHA-256：`e5257c144450b65ffd6022408bdcb38b455539389846fd55d6fa9f716db03e79`；
- 数据集已 sealed，可直接创建 Cohort；
- 系统另有 MatrAIx Acme support、Linux、Web 等确定性样例任务，但它们不属于本案例的 Semantic Simulation 链路。

没有已有的 WorldModel、Scenario、Cohort、Semantic Experiment 或 DecisionReport。

## 4. 是否已有 AgendaScope import 数据

有，而且同步 worker 正在运行。

检查时：

- source 数：409；
- `media_articles` 实际行数：47,261；
- Media overview 的活跃聚合 article count：8,565；
- topic 数：约 29,738（overview 口径）；
- 最新成功同步 run：`6c3e1b55-8f7a-4807-9f97-6a2cc1a232ab`；
- 最新成功同步完成时间：`2026-08-16T09:29:58.199937Z`；
- 检查时下一轮同步 run `cb0898b2-1a80-4761-8a6a-860f5031649a` 正在运行。

本案例需要的四条 watermark evidence 均存在，且各自具有 `original_url`、`published_at`、captured `excerpt` 和 `evidence_revision_sha256`。不需要新增采集，也不需要创建 synthetic evidence fixture。

注意：AgendaScope 持续同步可能更新可变 media 记录。因此创建 WorldSnapshot 时必须使用本设计中列出的精确 revision hash；一旦 seal，后续只使用冻结内容。

## 5. 是否已有 Persona 数据

有。为保持规模最小并覆盖三类视角，计划从同一 dataset 选择以下 5 个既有 Persona：

| 分析性角色映射 | Persona | Persona ID | 选择依据（冻结属性） |
| --- | --- | --- | --- |
| 普通用户 | Ruby Taylor | `1e059897-d1ad-439c-aa1f-ffd3b2da6be9` | cautious adopter、AI positive、English |
| 普通用户 | Noah Williams | `88a61011-0543-452d-b03d-e33cbc698415` | cautious adopter、AI neutral、English |
| 行业参与者 | Jordan Lee | `072930b8-c68c-4acf-996b-a655ab34062c` | Software & AI、Engineering、technology veteran |
| 行业参与者 | Casey Brooks | `1f84c65e-bf76-4016-88e4-d6cd89fde9a4` | Software & AI、technology experienced、AI opposed |
| 观察者 | Ava Martinez | `41b9e8d3-f5e7-4915-afdb-0b916623fe4d` | Media & Journalism、media veteran、technology exposure |

“普通用户 / 行业参与者 / 观察者”是 Demo 的分析性映射，不会写回或修改 Persona 属性，也不表示真实人口代表性。Persona 本身来自现有数据体系，不需要新 fixture。

## 6. 是否可以配置 LLM

代码和 Compose 支持通过以下三个必填环境变量配置现有 OpenAI-compatible provider：

- `LLM_API_KEY`；
- `LLM_BASE_URL`；
- `LLM_MODEL_NAME`。

当前情况：

- `.env.example` 中三项均为空；
- 工作区根目录没有其他 `.env*` 文件；
- 当前 `oasis-worker` 容器中三项均为 unset；
- semantic readiness：worker online，但 `semantic_runtime_ready=false`、`model_name=null`、`semantic_config_sha256=null`；
- readiness 说明要求 worker 在成功完成 provider tool-call startup probe 后才会对外宣告 ready。

因此“可以配置”，但“目前没有可用配置”。需要人工提供有效的 provider base URL、model name 和 secret API key，并重启/重建 worker 使其完成 startup probe。API key 不应写入仓库或 Demo 文档。真实模型调用可能产生费用。

### 后续跨项目复用复核

用户指出 `ai-decision-center` 可能已有可复用配置后，进一步确认：

- `/Users/ssyb/Workspace/web/ai-decision-center/.env` 中三个同名变量均已设置；
- 只将这三个变量注入 SandOwl `oasis-worker` 后，配置契约可以正常解析；
- Provider 的真实 tool-call startup probe 返回 HTTP 401；
- Provider 错误码为 `invalid_api_key`，说明 access token 无效或已过期；
- 因此配置来源可以复用，但当前凭据不可用；
- 为避免 worker 持续重试过期凭据，验证后已恢复 SandOwl worker 的未配置状态。

这修正了初始结论：不是完全没有候选配置，而是 SandOwl 未自动加载 sibling project 配置，且该候选配置中的 key 已失效。

### Run 2 修正：模型访问范围与组合 readiness

进一步分别验证模型后，上述“key 已失效”结论需要再次收窄：

- 同一 `LLM_API_KEY` 和 `LLM_BASE_URL` 使用 `qwen-plus` 时返回 HTTP 401；
- 改用 `qwen3.7-plus` 后，SandOwl Semantic tool-call probe 成功；
- Survey tool-call probe 也成功；
- 因此 key 并非全局失效，而是 `qwen-plus` 路由不可用或不在该凭据的访问范围内；
- 标准 `oasis-worker` 仍无法完成组合启动，因为无关的 Acme Chat SUT identity 与 worker 中冻结的 task/SUT contract 不一致；
- 本次 Vertical Slice 使用同一 worker 镜像启动 semantic-only 进程，只取消 Chat/Web/Linux 的无关 readiness probes，Semantic 与 Survey readiness 均为 true；
- 当前 `.env` 已设置 `LLM_MODEL_NAME=qwen3.7-plus`，且被 Git 忽略、文件权限为 `0600`。

Run 2 证明 LLM 配置可用；剩余运行态问题是多个执行域共享一个全有或全无的 worker readiness，以及辅助 SUT 镜像/契约漂移。

## 7. ReportAgent 当前状态

需要区分两个报告能力：

### 传统 DecisionReport

- 当前运行态已有 `/api/v2/decision-reports/from-experiment/{experiment_id}`；
- 当前数据库已有 `decision_reports` 表；
- 能在 comparable Semantic trials 完成后生成 sealed DecisionReport；
- 这是本 Demo 目标中的 Report 步骤。

### 新 ReportAgent

- 工作区中已有 ReportAgent API、repository、contracts、前端面板、worker draft engine，以及 `0039`/`0040` migrations；
- 当前数据库只到 `0032`；
- 当前运行 Backend OpenAPI 没有 ReportAgent routes；
- 当前 capability list 没有 `report_agent.evidence_tools`；
- 当前 worker 镜像也未承载这组工作区增量。

结论：新 ReportAgent 是“代码开发中、运行态不可用”。本 Demo 不依赖它，也不会为了 Demo 干扰这批未提交改动。

## 8. Semantic Experiment 当前状态

Semantic Experiment 的 API、表结构、队列和 worker 心跳都存在，创建契约支持：

- 1 个 sealed Scenario；
- 1 个 sealed Cohort（1–8 Personas）；
- baseline + 1–2 alternatives；
- 1–2 seeds；
- 1–3 rounds；
- 每轮 15–240 分钟。

但当前 runtime readiness 是：

- engine：`camel-oasis`；
- OASIS：`0.2.5`；
- CAMEL：`0.2.78`；
- worker online：true；
- live worker count：1；
- semantic runtime ready：false；
- 原因：没有完整、经过 provider probe 的 LLM configuration。

`reddit_manual_smoke` 虽然 ready，但它只验证一个 synthetic scenario actor 的手工 `CREATE_POST`，不运行 Persona audience agents、不产生 semantic comparison，也不能替代本 Demo 的 Simulation。

## 可直接运行、需准备、需补代码、需人工输入

| 步骤 | 当前状态 | 动作 |
| --- | --- | --- |
| AgendaScope evidence selection | 可直接运行 | 选择四条现有精确 revision |
| WorldSnapshot | 可直接运行 | 创建 WorldModel 和 sealed snapshot |
| Scenario | 可直接运行 | 创建 baseline + 2 synthetic alternatives |
| Persona/Cohort | 可直接运行 | 从现有 dataset 创建 5-persona sealed cohort |
| Semantic Experiment | API 可创建，worker 不可执行 | 需要有效 LLM 配置并通过 startup probe |
| DecisionReport | 条件可运行 | 必须等待 comparable Semantic trials 完成 |
| 新 ReportAgent | 当前不可运行，且非本 Demo 必需 | 若未来要验证，需先审阅现有改动、升级 migration、重建运行态 |

### 需要准备的数据

- 不需要新增 evidence 或 Persona fixture；
- 只需要创建本 Demo 的 WorldModel、Scenario 和 Cohort 资源；
- synthetic 内容仅限两个 alternative 的 intervention 文本，并明确写入 `synthetic demo data`。

### 需要补充的代码

- 当前没有证据表明完成传统 Vertical Slice 需要补代码；
- 在没有 LLM 配置前，不应增加 fake semantic engine 或手工结果 fallback；
- 如果提供有效 LLM 后出现实际代码错误，再做最小、针对性的修复。

### 需要人工输入

- 刷新或替换 `ai-decision-center/.env` 中已失效的 `LLM_API_KEY`；
- 现有 `LLM_BASE_URL` 和 `LLM_MODEL_NAME` 可以继续作为候选配置；
- 如需执行可能计费的真实 provider 调用，需确认该凭据可用于本 Demo。
