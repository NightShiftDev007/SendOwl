# SandOwl 三方能力整合与 ADC 产品层退出计划

日期：2026-08-16  
目标：AgendaScope + MiroFish + MatrAIx  
工程原则：底座服从实现成本，不把 Git 血缘当作产品来源

## 已确认的来源关系

```text
MiroFish
  → ai-decision-center（研究性二开）
      → 当前 SandOwl 工程底座

AgendaScope ─┐
MiroFish ────┼→ SandOwl 产品能力
MatrAIx ─────┘
```

ADC 不是需要接入的第四个产品。它是 MiroFish 二开过程中形成的工程分支，其中同时包含两类内容：

1. MiroFish 派生或通用增强：图谱、模拟、OASIS 执行、报告、Agent 交互、运行稳定性；
2. ADC 独有产品层：决策任务、多候选方案、基线/备选、同 seed 配对比较和决策报告语义。

去 ADC 化只针对第二类。不能按仓库、提交或目录来源整体删除第一类。

## 最终用户流程

```text
AgendaScope 媒体发现与证据选择
  → MiroFish Project / Graph 上下文
  → MatrAIx Persona Dataset / Cohort
  → 一个 simulation requirement
  → 一次 MiroFish / OASIS Simulation Run
  → ReportAgent 报告
  → Agent Interaction
  → 可选 MatrAIx Evaluation
```

用户不需要理解三个上游仓库，也不需要进入三个独立产品。

## 当前能力处置

| 当前能力 | 目标来源 | 处置 |
| --- | --- | --- |
| `media`、AgendaScope import/sync、媒体态势 UI | AgendaScope | 保留 |
| `populations`、Persona/Cohort、Survey/Chat/Web/Linux tasks | MatrAIx | 保留 |
| `world_graphs`、OASIS worker、运行事件图 | MiroFish/OASIS + 工程增强 | 保留并补足来源映射 |
| bounded ReportAgent、Persona interview | MiroFish 能力的受控实现 | 保留，改为绑定单次 Simulation Run |
| `world_models`、evidence bundle、hash/audit/readiness | 三方整合胶水 | 保留，可按产品语言重命名 |
| `decision_threads` | ADC 产品层 | 从主流程退出；由 Project/Research Case 取代 |
| `scenarios` 的 baseline/alternatives/interventions | ADC 产品层 | 从新建流程退出；由单个 simulation requirement 取代 |
| `semantic_experiments` 的方案矩阵和 paired delta | ADC 产品层 | 从新建流程退出；改为独立 Simulation Run |
| DecisionReport V1/V2 的方案 Comparison | ADC 产品层 | 只读保留旧报告；新报告绑定单次 Run |
| Policy evidence | 额外扩展 | 不删除，但移出三方主导航 |

## 数据安全边界

- 不删除现有 Scenario、Experiment、Report 或 sealed 数据。
- 不改写现有哈希、UUID、迁移历史或数据库触发器。
- 旧对象继续提供只读深链，用于审计和导出。
- 新对象不再要求 baseline、alternative 或 paired comparison。
- 在单次运行替代链完整以前，不关闭旧 API 和 worker 消费能力。

## 实施顺序

### M0：停止扩大 ADC 产品层

- 不再为 Decision Thread、方案矩阵和 Comparison 增加新功能。
- UI 与文档明确旧报告属于历史兼容流程。

### M1：增加单次模拟主链

- 引入 Project/Research Case 投影，保存证据、研究问题和一个 simulation requirement。
- 复用现有 WorldSnapshot、Cohort、worker、event 与 artifact 能力。
- 新建独立 Simulation Run，不创建 baseline 或 alternatives。

### M2：恢复 MiroFish 报告与交互语义

- ReportAgent 直接绑定单次 Run 和冻结证据。
- Persona/Agent Interaction 绑定 Run/Report，不依赖 DecisionReport comparison。
- 旧 DecisionReport V1/V2 保持只读。

状态：ReportAgent 单次运行报告与原生 Agent Interaction 已接通；互动绑定成功报告、冻结运行原文和最多五轮上下文。默认“报告与交互”入口读取原生单次运行报告，旧 DecisionReport 只通过明确的只读历史入口与原有深链访问。

### M3：重组产品导航

主流程改为：

1. 信息证据；
2. 世界与图谱；
3. 模拟人群；
4. 模拟运行；
5. 报告与交互。

MatrAIx Task Gallery 作为独立“评测”入口。Decision Workspace、决策任务、决策实验不再出现在主导航，但旧深链仍可读取。

状态：主导航和报告入口已按上述结构运行。原生报告页可进入独立评测中心，但会明确说明 Evaluation 不自动验证、排名或改写本次 Simulation Run 的结论。

### M4：兼容退出

- 观察新主链真实运行和报告验收。
- 确认没有新写入依赖后，再逐项关闭 ADC 新建 API。
- 数据表是否长期保留由归档、导出和合规要求决定，不以 UI 隐藏作为删除依据。

状态：首条原生 Research Run 已完成 Simulation Run、ReportAgent 和 Agent Interaction 验收。原生 MatrAIx Survey 已改为只绑定成功的单次 Run 和该 Run 的冻结 Cohort，固定观测清晰度、关注点和未解问题，不再依赖 Scenario 或 alternative。Decision Thread、DecisionReport、旧报告问答、旧 Persona Interview、Scenario、Semantic Experiment 与旧 Scenario Preference Survey 的写入口均返回 `410 Gone`，对应 UI 改为只读归档；历史 GET、Markdown 下载、UUID、SHA-256 和 Revision 顺序继续保留。

### M5：执行面与归档收口

- 关闭旧 `platform-smoke` 新建入口，只保留历史运行读取。
- Batch Launch 的 Survey 改为 `Research Project + succeeded Simulation Run`，不再接受 Scenario、Cohort 或 alternative 参数；Cohort 从 Run 继承。
- Batch Registry 与 Trial Archive 同时读取原生 Research Survey 和历史 ADC Survey，并在 UI 显式标出历史来源。
- capability inventory 增加 `legacy_readonly`，Scenario、旧报告、旧访谈和旧 OASIS/语义实验不再被声明为可新建运行。
- AgendaScope 同步状态把超过六小时仍为 `running` 的记录投影为 worker 心跳过期，避免孤儿运行长期显示为进行中；worker 身份统一为 `sandowl-compose-media-sync-worker`。

状态：代码与契约收口完成，未创建新的付费 Survey 或模型运行。M5 验收以旧写入 `410`、原生/历史双读、严格类型检查、数据库集成测试和浏览器只读核验为准。

### M6：原生模拟运行导航收口

- `#/runs` 默认进入 Research Project / Simulation Run 原生工作台，不再打开历史 Platform Smoke。
- 用户必须先明确选择 Research Project；运行继续从 Project 继承冻结证据，再显式绑定 Cohort、simulation requirement 和起始内容。
- 原生运行支持 `project_id + run_id` 严格深链，地址不允许混用历史 Scenario、Experiment 或 Trial 参数。
- 成功运行可直接进入原生“报告与交互”；旧 Platform Smoke 与多方案 Semantic Experiment 只通过显式历史深链读取。
- 历史页面继续保留原 UUID、哈希与产物，不迁移、不改写、不伪装成原生运行。

状态：完成。默认入口、严格原生深链、历史只读深链、中文流程提示、响应式布局、HTML/哈希资源缓存策略和浏览器无控制台错误均已验收；验收未触发模型调用。

### M7：主链阶段职责与上下文交接

- Research Project 页面只负责冻结证据与研究问题，不再同时展开运行创建、运行记录和报告生成。
- 每个 Project 提供明确的“进入模拟运行”动作，并通过 `project_id` 保留当前研究上下文。
- Simulation Run 成功后可深链进入对应报告；Report 页面可返回同一个 `project_id + run_id`，不要求用户复制 UUID。
- 报告工作区显示 Project → Run → 冻结报告 → 引用报告/追问的真实进度，并把正常流程中的状态和标签中文化。
- 历史 DecisionReport、Platform Smoke 和多方案实验继续走独立只读深链，不出现在原生流程进度中。

状态：完成。Project 页面不再创建 Run，Project → Run → Report 上下文深链双向可逆；正常流程无退役品牌泄漏，固定事件枚举与运行限制已中文展示，响应式报告进度和浏览器控制台验收通过。验收未触发模型调用。

### M8：证据到研究项目的精确交接

- Media 中明确选择单篇报道后，继续通过 `evidence_id` 带入 World 版本室；系统不自动冻结证据。
- 已冻结 WorldSnapshot 提供“用此快照创建研究项目”的显式动作，同时传递 `world_model_id + snapshot_id`。
- Research Project 工作区只接受成对 UUID；缺失、重复或未知参数直接显示路由错误，不自动改选。
- 项目创建请求绑定用户实际选定的精确快照；即使 WorldModel 已有更新版本，也不会把历史移交悄悄替换成 latest。
- 页面显示上一步完成状态、当前冻结版本和下一步动作，仍不自动创建 Project、Run 或任何付费模型任务。

状态：完成。Media → World 的人工证据移交继续保留；World → Project 新增精确快照交接，项目创建请求绑定地址中的同一版本。严格路由、桌面与移动布局、返回核验深链和浏览器控制台均已验收；没有创建 Project、Run 或触发模型调用。

### M9：原生中文内部试用与 Reviewer 恢复

- 使用现有星桥充电原生资源执行 UI-only 只读 dry run，不创建资源或触发模型。
- Pilot 指南、观察模板和授权检查退出 Decision Thread、baseline/alternatives 与 DecisionReport V2 语义。
- 顶部阶段顺序与真实依赖统一为 Media → World → Project → Persona → Run → Report。
- 单次运行报告提供精确 WorldSnapshot 来源恢复入口。
- ReportAgent 与 Agent Interaction 的逐字引用默认折叠，保留原文、来源和字符区间。
- Project、Cohort、Run、Report 与 ReportAgent 草稿身份可在折叠审计区完整恢复。
- 项目目录明确区分“准备模拟人群”“查看冻结证据”和“使用已有 Cohort 进入运行”。

状态：完成。星桥充电原生链完成 UI-only Reviewer dry run；四个 P1 和旧 Pilot 脚本阻塞已收口。来源恢复、资源身份、折叠引用、阶段顺序、桌面与移动布局及浏览器控制台均已验收；没有创建资源或触发模型调用。下一 Gate 是 Owner 独立中文复测，不得把本轮自动化走查记为真实用户验证通过。

## 第一条实施切片

```text
从现有 AgendaScope 文章选择证据
→ 创建一个 Project/Research Case
→ 绑定现有 MatrAIx Cohort
→ 填写一个 simulation requirement
→ 复用现有 OASIS worker 运行一次
→ 保存事件和产物
→ 生成一份单 Run 报告
```

验收时不创建新的 Decision Thread、baseline、alternative、paired comparison 或 DecisionReport V2。

## 当前决定

继续使用现有 SandOwl 作为工程底座，因为它已经跑通 AgendaScope、MatrAIx 与 MiroFish/OASIS 的纵向链路。只有当具体模块无法安全解耦时，才从原版 MiroFish 迁移对应实现；不再进行空白重写。

## 2026-08-18 融合完整度复核

结论：**三方资源链已经接通，但三方语义能力尚未完整融合。** 当前系统可以从真实报道建立不可变快照，绑定 MatrAIx Cohort，运行一次 OASIS 合成模拟并生成可追溯报告；这证明了统一数据契约和运行链路。它还不能被描述为 AgendaScope、MiroFish 与 MatrAIx 的完整能力融合。

| 能力边界 | 当前状态 | 复核结论 |
| --- | --- | --- |
| AgendaScope 来源、文章、议题、传播与首发观察导入 | 已接通 | 属于真实整合；但当前是周期全量读取模型，不是 AgendaScope 的采集、聚类、议程演化、告警与人工修订工作台 |
| 媒体证据 → WorldSnapshot → Research Project | 已接通 | 精确快照、原文、修订与哈希可以恢复 |
| MiroFish Project / Graph 上下文 | 已接通 | Project 不可变绑定精确 `graph_id + graph_sha256`；历史无图项目保持只读 |
| 冻结证据 / 图谱 → Simulation 输入 | 已接通 | 冻结媒体、政策、图谱实体与关系被编译为可读 `SimulationContext`，其摘要进入 Run 哈希；人工 synthetic post 保持独立 |
| MatrAIx Dataset / Persona / Cohort | 已接通 | 严格导入、成员顺序、内容寻址和 OASIS profile 投影已进入原生运行 |
| MatrAIx Persona 生成、检索、grounding 与质量流水线 | 未接通 | 当前使用已有数据集与 Cohort；没有接入 1,290 维 schema 的生成、依赖感知抽样、质量过滤和大规模检索 |
| MiroFish Simulation Config Agent | 部分接通 | 已有不调用模型的可审核自动编排，生成观察时长、活动强度、轮次与定时事件；平台仍限 Reddit，尚未恢复模型规划器 |
| MiroFish 社会演化运行 | 部分接通 | 真实使用 OASIS/CAMEL、类型化事件、最多 8 人 / 6 轮、定时事件和逐轮图记忆；尚未恢复双平台或运行中 IPC |
| MiroFish ReportAgent | 部分接通 | v2 报告联合读取冻结媒体、语义图、运行事件和授权访谈，保存审计工具调用并默认提供读者报告；仍是受控大纲与检索循环，不宣称等同上游全部 GraphRAG/ReAct 能力 |
| MiroFish Agent Interview / Interaction | 部分接通 | 已可对冻结 Run 中单人/多人 Persona 做有界访谈并用于授权报告；不连接正在运行的模拟进程，不伪装为实时 IPC |
| MatrAIx Evaluation | 部分接通 | 原生 Survey 已绑定 Project / Run / Cohort；研究级能力矩阵与 Persona 质量报告已接通。Chat、Web、Linux 仍明确标为固定 source sample，App、Harbor、统一 verifier/reward 尚未接入 |
| 面向研究用户的报告阅读层 | 已完成第一轮修复 | 默认先展示本轮观察、可说/不可说、现实证据与合成输入、可读计数；哈希、配置、英文 JSON 和历史报告降到技术审计区 |

### 下一阶段顺序

#### M10：原生报告阅读与试用阻塞修复

- 报告默认展示研究结论层级，不再以哈希、JSON、模型配置和限制清单主导页面；
- 明确区分现实背景、人工设定的合成输入、Persona 生成内容与无动作；
- 把引用解释成“这条依据支持报告中的哪句话”，技术原文继续可审计但默认折叠；
- 当前运行详情在窄屏展开后自动定位，历史入口退出主任务路径；
- 六步工作台导航在 320px 以上宽度完整可见。

状态：代码完成，前端 320 项测试、生产构建与 320 / 390 / 768 / 900 / 1440 宽度浏览器验收通过；未触发模型调用。仍需 Owner 使用同一 Task A 重新独立复测，不能把开发者验收当成用户验证。

#### M11：证据、图谱与模拟上下文真正融合

1. 为 Research Project 增加不可变 `GraphBinding`，保存精确 `graph_id + graph_sha256`，不再只在页面上称为 Graph；
2. 从冻结媒体、图谱实体/关系、研究问题和 simulation requirement 编译一份可读、可审计的 `SimulationContext`；
3. 把 `SimulationContext` 的内容摘要纳入 Run 哈希，并明确记录哪些现实内容进入 Persona 上下文；
4. 保持人工设定的 synthetic initial post 独立，不把它混进现实证据；
5. 用现有中文案例回归，证明 Persona 的上下文确实来自 AgendaScope / Graph，而不只是验证快照 ID 存在。

状态：完成。Project v3 不可变绑定语义图；Run v3/v4 保存内容寻址的 `SimulationContext`，明确列出进入 Persona 上下文的媒体、政策、实体与关系；synthetic 起始内容保持独立。旧项目和旧 Run 保持只读兼容。

#### M12：恢复 MiroFish 的运行与互动深度

- 在 M11 上增加可审核的自动 simulation config：时间、事件、活动强度和平台配置；
- 支持定时事件与更长时间跨度，是否恢复双平台由真实产品需求决定；
- 增加运行中图记忆更新和合成人物单人/批量访谈；
- 所有扩展继续保持合成观察边界，不恢复 ADC 多方案比较。

状态：完成当前产品范围。已增加可预览的确定性自动编排、最长 48 小时/6 轮、定时合成事件、逐轮图记忆，以及绑定冻结 Run/Cohort 的单人或多人 Persona 访谈。双平台和运行中进程 IPC 未因缺少真实需求而恢复。

#### M13：恢复面向用户的 ReportAgent

- 让报告同时使用冻结媒体、语义图谱、运行事件和经授权的 Persona 访谈；
- 恢复自动大纲、逐章节多轮检索与反思，但只保存可审计工具调用，不暴露隐藏推理；
- 默认输出读者报告，技术审计作为第二层；
- 每个结论直接显示可读来源关系，原始字符区间仅在下钻时出现。

状态：完成受控 v2。报告联合读取冻结快照、语义图、运行事件和经授权访谈，读者层与技术审计层分离，并保留 v1/v2 不可变归档。实现是可审计的有界多源读取器，不宣称复制上游所有开放式 ReAct/GraphRAG 行为。

#### M14：把 MatrAIx Evaluation 变成主链能力

- Survey、Chat、Web、App 统一绑定 Research Project / Run / Cohort；
- 逐步接入通用 task bundle、Harbor job、verifier、trajectory、artifact 与 reward 边界；
- 接入 Persona 检索、抽样、grounding 和质量报告，而不只读取现成 Cohort。

状态：完成。Survey 使用不可变 Task Bundle；Chat/Web/App 使用 Project-bound Evaluation Target。统一 Evaluation Job 保存 Persona grounding、trajectory、artifact、task-owned verifier 和 reward 哈希，并由 PostgreSQL worker 调度至固定 MatrAIx commit 的 Harbor runner。Web/App 容器运行在独立 Rootless DinD，不挂宿主 Docker socket；官方无 API key Harbor smoke 已真实成功。旧 Acme/Quotes/Linux 样例继续作为历史验证，不再冒充当前研究执行。

#### M15：补足 AgendaScope 研究能力

- 将议题生命周期、传播链、首发修订、监控对象和告警以原生研究上下文接入 Project；
- 明确哪些采集和治理能力继续由 AgendaScope 独立服务负责，SandOwl 通过稳定契约消费，避免复制两个采集系统；
- 从周期全量导入升级到可观测的增量同步与非文章对象删除对账。

状态：完成。SandOwl 原生拥有 Source 配置、RSS/Atom 与网页列表发现、受限公开网络 Fetcher、正文提取、URL 去重、调度、运行档案、源健康、告警、确定性议题生命周期、小时快照与跨国传播链。默认 collector worker 直接写 SandOwl PostgreSQL；只有用户显式启用的来源会联网。外部 AgendaScope 数据库同步降为历史迁移 profile，不再是产品运行前提。

#### M16：发布收口与真实用户 Gate

- 修复真实 UI 纵向运行发现的 worker domain、Harbor 卷权限、runner 路径、孤儿任务、AgendaContext 复用、引用窗口和导航上下文问题；
- 为 Project-bound Harbor Job 增加最多五次、旧失败不可变的 retry lineage；
- 在 UI 显示失败原因、attempt、父任务哈希、trajectory、artifact、verifier 与 reward；
- 从空 PostgreSQL 完整迁移到 `20260820_core_0061`，执行本地、Worker、前端、生产构建和独立 PostgreSQL 集成验证；
- 只把工程走查记为 engineering pass，Owner 零提示复测和外部参与者继续作为独立 Gate。

状态：M16 第一阶段完成。根 Harbor Job 与重试 attempt 的内容身份和父子关系已由契约与数据库约束固定；真实失败 attempt 1 已通过页面创建 attempt 2 并成功封存产物。当前不继续扩展三方功能面，下一步是 Owner 零提示中文复测，再根据真实观察决定性能、来源治理和任务模板优先级。
