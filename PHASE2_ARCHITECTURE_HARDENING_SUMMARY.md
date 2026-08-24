# Phase 2 Architecture Hardening Summary

状态：分析与设计完成。本阶段没有修改应用代码、数据库 schema、运行服务或既有 sealed 资源。

## 1. 当前 SandOwl 已经证明什么

第一个 Vertical Slice 已经证明核心链路不是文档概念，而是可以通过现有 API、PostgreSQL 队列和 OASIS worker 真实运行：

```text
AgendaScope evidence
  -> sealed WorldSnapshot
  -> sealed Scenario
  -> sealed Persona Cohort
  -> Semantic Experiment
  -> persisted Observation
  -> sealed DecisionReport
```

真实运行记录包括：

- Semantic Experiment `c2884f02-3475-45e7-83ee-5e584563bdaa`；
- `qwen3.7-plus` Semantic readiness 为 true；
- baseline + 2 alternatives 的 3/3 trials succeeded；
- 17 个 typed events 持久化；
- DecisionReport `37384e5e-798c-4b3c-8bda-e2502252e52a` 已生成并 sealed。

这证明 SandOwl 已经具备以下架构能力：现实媒体输入可以被冻结并内容寻址；Scenario、Cohort 和 Experiment 输入可以绑定精确 hash；worker 可以领取并执行 Semantic trials；Observation 可以与 trial/seed/Persona 对齐；报告可以基于成功配对结果生成且封存后不可变。

它没有证明模拟具有现实预测力、5 个 Persona 具有总体代表性、单 seed 结果稳定、LLM provider 完全可复现，或系统能够推荐最佳方案。当前被证明的是**链路完整性和审计能力**，不是商业结论有效性。

## 2. 当前最大架构风险

最大风险是 **worker 的故障域与业务领域边界不一致**。

当前一个 daemon 同时装载 Semantic、Survey、Chat、Web、Linux、World Graph、Report QA、ReportAgent draft 和 Persona Interview；启动时又在同一异常边界中依次探测 Semantic、Survey、Chat、Web、Linux。任何一个已配置 capability 失败都会使进程在完整 heartbeat 发布前退出。本次 Acme Chat SUT identity drift 已经实际证明：Chat 的契约问题可以让本来可运行的 Semantic runtime 无法按标准 Compose 上线。

这个风险同时表现为：

- readiness blast radius：一个 sidecar 或固定 SUT 漂移影响无关领域；
- head-of-line blocking：单进程一次只运行一个 job，长 Semantic/Web/Linux 任务可延迟 Report/QA；
- heartbeat 语义错位：Report job 也借用 OASIS simulation heartbeat；
- 运维边界混合：LLM、OASIS、浏览器、Linux runner 和 evidence/report 读取拥有不同依赖与安全边界，却共享进程生命周期。

第二个重要缺口是 **DecisionReport 的内容结构落后于已经存在的事实链路**。V1 的四章节和内容哈希是可靠的，但 Evidence 与 Experiment Observation 只通过 provenance 和 comparison 间接出现；调用方不能以 typed contract 独立读取“依据、假设、实验配置、观察、比较、解释、限制”。

其他已知边界包括：单 seed/小 Cohort、provider 非完全确定性、OASIS raw observation time 与 SandOwl recorded time 的时钟差异，以及 AgendaScope live revision 与 sealed snapshot content hash 必须严格区分。这些应进入报告限制，不应靠架构文案掩盖。

## 3. Phase 2 应优先做什么

### 第一优先：Worker M1 最小隔离

先复用现有 worker image、领域 queue 表和 engine，只增加：

- `semantic` / `evaluation` / `report` 三种明确进程 role 与 job-kind allowlist；
- heartbeat 的最小 domain 区分，防止不领取 Semantic job 的 report worker 造成 readiness false-positive；
- 只对本进程能力执行 probe、queue scan、claim 和 orphan 处理；
- 三个 Compose worker service，保留现有独立 `media-sync-worker`；
- 按 domain/capability 读取 readiness。

M1 不需要统一 job 表、通用 payload、消息总线或全面 job lease。验收只需复现 Chat identity drift，并证明标准 `semantic-worker` 仍能 ready 且成功运行一个 Semantic trial；Chat 自身应准确显示 unavailable。

### 第二优先：DecisionReport V2

保持 V1 原样可读、hash 不变、sealed 记录不可覆盖，新增七个 typed sections：

1. Evidence
2. Assumptions
3. Experiment
4. Observation
5. Comparison
6. Analysis
7. Limitations

V2 第一版应继续由 deterministic projector 生成。Evidence 绑定 sealed WorldSnapshot 和 frozen content hash；Assumptions 显式标记 synthetic inputs；Observation 绑定 persisted events 及其 canonical digest；Analysis 只能解释可核对差异，禁止预测、因果断言和最佳方案。

最小兼容迁移允许同一 Experiment 按 `generator_version` 同时拥有 V1/V2 报告，扩展现有 section kind/position 和 typed `data_json`，并让 V2 hash 覆盖 WorldSnapshot identity、七个 typed payload 和展示正文。API 与前端采用 additive contract，不把四章节数组强行升级为七章节。

### 第三优先：第二个 Vertical Slice

第二案例选择“电动车品牌劳资争议结束后的回应节奏实验”。当前 AgendaScope 投影已有瑞典 Tesla 长期罢工结束的 5–6 条多来源候选文章，不需要新增采集。执行时应重新确认精确 revision，再冻结为新的 WorldSnapshot。

现实 evidence 只作为媒体语境；Scenario 使用虚构品牌 `Northstar Mobility`，并把“立即承认并承诺更新”和“核实后分阶段更新”两条声明标成 `synthetic demo data`。运行仍使用现有 5-persona Cohort 和 Semantic Experiment，观察帖子、评论、reaction、do-nothing、actor/sequence 等 persisted events，不输出 Tesla、工会、员工、消费者、声誉、销量或市场的真实预测。

## 4. 哪些事情不要做

- 不引入 LangChain、LangGraph、AutoGPT、通用 Agent OS、planner 或通用 Agent 基类；
- 不把 domain separation 变成一次性重写所有 queue、engine、heartbeat 和 artifact 模型；
- 不为了名字统一把所有领域任务塞进松散 JSON `jobs` 表；现有强类型领域表是资产；
- 不立即按每个 engine 拆一个服务；先用 semantic/evaluation/report/media 四个故障域验证收益；
- 不在 M1 同时实现自动重派、checkpoint resume、复杂 priority、autoscaling 或新消息基础设施；
- 不修改或覆盖已有 sealed V1 DecisionReport，也不改变它的 hash 算法；
- 不让 ReportAgent 草稿绕过 typed Evidence/Observation 和人工确认后直接成为 sealed Analysis；
- 不从 AgendaScope live 表补写 sealed snapshot 中不存在的字段，也不把 selection-time revision hash 与 frozen `captured_text_sha256` 混为一谈；
- 不把 synthetic intervention、Persona 输出或 paired delta 包装成现实事实、因果效应、未来预测或最佳方案。

## 5. 下一阶段推荐顺序

| 顺序 | 工作 | 完成判据 |
| --- | --- | --- |
| 0 | 保护当前未提交 ReportAgent 工作，并在实施前核对 workspace migration head 与运行库 revision | 不覆盖现有改动；明确目标 migration 基线 |
| 1 | 实现 Worker M1 的 role/allowlist、domain heartbeat 和三组 Compose service | Chat probe 失败时 Semantic 仍 ready；一个标准 Semantic trial 成功 |
| 2 | 修复 Acme Chat SUT identity drift，并单独验收 evaluation readiness | Chat 恢复不影响 Semantic；四个 evaluation capability 可独立报告状态 |
| 3 | 定义 DecisionReport V2 typed contracts、canonical hash 和 V1/V2 compatibility tests | 已有 V1 hash 不变；七章节纯投影可从首案资源生成 |
| 4 | 增加 V2 migration、deterministic repository/API 和前端只读展示 | 同一 Experiment 的 V1/V2 并存且均可校验；Analysis 无预测/推荐 |
| 5 | 执行第二个 Vertical Slice | 新 snapshot/scenario/cohort/experiment/report 全部可追溯；事件与 scenario input 分开计数 |
| 6 | 根据等待时间、orphan、配置冲突和资源指标评估 M2 | 只有真实运行数据证明需要时才设计 job lease、routing envelope 或进一步拆分 |

推荐的总体方向保持不变：

```text
Evidence -> Scenario -> Simulation -> Observation -> Decision
```

Worker separation 是为了让这条链路可靠运行；DecisionReport V2 是为了让这条链路的输出可核验；第二案例是为了验证它能跨议题泛化。三者都不需要、也不应把 SandOwl 改造成 Agent Framework。

## 6. Phase 2 执行结果（2026-08-16）

推荐顺序中的 1–5 已完成：

- Worker M1 已落地并运行，Semantic/Evaluation/Report 三个 domain heartbeat 与 dispatch 已隔离；
- Acme REST/MCP stale image identity 已通过 contract-hash image tag 和 rebuild 修复；
- DecisionReport V2 已以 migration `0042`、additive API、deterministic projector、strict frontend contract 和 Reports 工作区展示落地；
- 首案 V1 ID/hash 保持不变，并为同一 Experiment 生成独立 V2 `2b214688-d350-4eb1-8550-1d210c6b75b2`；
- 第二案例 Experiment `107a357a-0f3a-4df2-810f-033f9934fecc` 的 3/3 trials succeeded，V2 `8c9c938e-7c87-471d-9966-fc9200095ae7` 已 sealed。

当前所有 runtime readiness 均为 true：Semantic 使用 `qwen3.7-plus`，evaluation 的 Survey/Chat/Web/Linux 也分别通过 probe。第二案例真实验证了同一核心链路可以从 AI 监管/水印议题迁移到品牌劳资争议沟通议题，并验证了 intervention 的 round 1/round 2 时序。

下一步不应自动进入 M2。应先观察实际 queue wait、orphan、资源竞争和 capability 配置冲突；只有这些数据表明三域仍过粗时，才设计 job lease/fencing、routing companion metadata 或进一步拆分。近期更有价值的工作是增加 V2 工作区的小范围交互测试、把第二案例纳入可重复但显式付费的 smoke runbook，并补充 worker/domain 运维指标。

## 7. 运行基线与 UI 验收（2026-08-16）

当前数据库只有 Semantic 队列产生过样本：6/6 trials succeeded，平均排队约 21.54 秒、最大约 101.17 秒、平均运行约 36.33 秒；当前 running jobs 为 0，heartbeat 超过 30 秒的 orphan candidate 为 0。该样本足以证明 M1 没有破坏 Semantic dispatch，但还不能评估 evaluation/report 域吞吐或跨域 head-of-line 改善。

三个空闲 worker 的一次 `docker stats --no-stream` 基线约为：semantic 531 MiB、evaluation 487 MiB、report 525 MiB。故障隔离带来了约三个常驻 Python runtime 的内存成本。当前不因此回退 M1，也不直接推进 M2；应先在更长窗口观察实际并发、worker restart、queue wait 和资源上限，再决定是否需要缩减 image/runtime 依赖或调整部署拓扑。

真实浏览器验收发现并修复了 V2 目录的 async projection bug：单报告 detail 可读，但多报告 list 因 async generator 用法返回 500。修复后 `/api/v2/decision-reports/v2` 返回两份 V2，Reports 工作区能直接显示七段报告，且右侧 provenance 同时列出 V1/V2 identity 与下载入口。回归测试覆盖目录逐报告 await；前端 contract、routing、typecheck 和生产构建均通过。

可重复 smoke 流程已写入 `docs/vertical-slice-smoke-runbook.md`。它把 LLM startup probe 和 Semantic Experiment POST 标为显式付费边界，并要求保留 synthetic input、event clock、selection revision 与 frozen content hash 的区分。
