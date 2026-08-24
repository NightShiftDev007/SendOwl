# DecisionReport V2 Design

状态：Phase 2 设计稿。本文只描述契约、兼容迁移和产品边界，不执行数据库迁移、不修改 API、不改变已有 sealed report。

## 设计目标

当前 `DecisionReport` 已经能够把一个终态 Semantic Experiment 的 paired comparison 封存为 deterministic findings，但它把现实证据、实验输入和实验观察压缩成了 provenance 文本。V2 的目标是让报告本身成为可核验的 Decision Intelligence 输出：读者可以分别回答“依据是什么”“做了什么假设”“实验配置是什么”“实际观察到了什么”“相对基线差了多少”“这些差异可以怎样解释”“哪里不能外推”。

V2 仍然遵循：

```text
Evidence -> Scenario/Assumptions -> Experiment -> Observation -> Comparison -> Analysis
```

这里的 `Analysis` 只解释已经封存的证据和观察，不预测未来、不声称因果、不选择最佳方案。

## 一、当前实现基线

### 1. DecisionReport 的持久化与生成

当前实现位于 `backend/app/decision_reports/`，数据库表由 migration `20260812_core_0013_decision_reports` 创建：

- `decision_reports` 保存 `experiment_id`、`experiment_sha256`、`scenario_id`、`scenario_sha256`、`cohort_id`、`cohort_sha256`、标题、`report_sha256`、固定的 `generator_version='deterministic-findings/v1'`、创建时间和 `sealed_at`。
- `decision_report_sections` 以 `(report_id, position)` 为主键，保存 `kind`、标题、Markdown 正文和 `metrics_json`。
- 数据库 trigger 要求报告先以 draft 插入，且关联的 experiment 已 input-sealed；封存前必须恰好存在四个连续章节：`scope`、`comparison`、`limitations`、`provenance`。
- 封存时数据库和 Python 都校验内容哈希。当前 canonical hash 包含 generator、experiment/scenario/cohort 三个 digest、标题，以及每个章节的 position、kind、title、body 和 metrics JSON。封存后父记录和章节均不可更新或删除。
- `POST /api/v2/decision-reports/from-experiment/{experiment_id}` 只接受可加载的终态 experiment，并要求至少一个成功的 baseline/alternative seed pair；`GET` 和 Markdown 下载路由只读已封存报告。

当前实现不是 LLM 报告生成器。`build_report_sections()` 使用确定性模板，把 scope、comparison、limitations、provenance 写入数据库；ReportAgent 的 bounded evidence run/cited draft 是另一个尚未接入 DecisionReport V2 的能力。

### 2. 当前四个章节的真实边界

| 当前章节 | 实际包含 | 缺口 |
| --- | --- | --- |
| `scope` | Scenario 标题、决策问题、variant/seed/trial 数和成功/失败数 | 没有冻结 WorldSnapshot、source、timestamp、证据 hash 的结构化字段 |
| `comparison` | 四个固定指标：observed action、authored content、reaction、do nothing；同 seed paired delta、标准差和 n | 没有独立的逐 trial 事件观察；没有明确列出配对 seed；对 intervention 造成的计数结构差异只能在正文中解释 |
| `limitations` | `compare_semantic_experiment()` 返回的两条限制 | 没有把 sample size、synthetic input、模型依赖、时钟和 evidence 边界按类型分层 |
| `provenance` | Scenario/Cohort/Dataset/Experiment、model、semantic config、prompt schema 的 hash | 没有直接绑定 `world_snapshot_id/snapshot_sha256`，也没有 source 行或冻结证据摘要 |

因此，Phase 1 报告 ID `37384e5e-798c-4b3c-8bda-e2502252e52a` 的确是 sealed、可校验的 V1 报告，但它不能被当作已经具备独立 Evidence/Observation 章节的 V2 报告。

### 3. 可复用的事实源

V2 不需要复制新的现实数据源，直接读取现有的 sealed 资源：

- `WorldSnapshot` 在 `world_snapshots`、`world_snapshot_evidence` 和 `world_snapshot_policy_evidence` 中保存冻结的 source、URL、title、published/captured time、excerpt、captured text digest，以及可选的人工确认 Policy 版本。`calculate_snapshot_sha256()` 对 canonical snapshot metadata 计算 hash；只有 `sealed_at` 非空的 snapshot 才能被读取为 `SnapshotDetail`。
- Evidence Bundle 是 WorldSnapshot 的只读投影，`bundle_sha256` 绑定 snapshot ID 和 snapshot hash；原文通过 content route 单独读取，并再次核对 content hash。因此报告可以引用 snapshot/bundle identity 和每个 item 的 hash，不需要把全部长文本复制进报告。
- `Scenario` 已绑定一个精确 `world_snapshot_id`、`snapshot_version`、`snapshot_sha256` 和 evidence count；baseline 没有 intervention，alternative 只能保存受限的 Reddit `initial_post` intervention。
- `SemanticExperiment` input-sealed 时冻结 Scenario/Cohort、dataset hash、variant、seed、round、时间预算、model、semantic config hash 和 prompt schema。每个 `SemanticTrial` 有 trial hash、状态、seed、时间、artifact hash、结果计数和明确失败信息。
- `semantic_trial_events` 是按 `(trial_id, sequence)` 排序的 append-only normalized OASIS actions。事件有 round、phase、actor kind、persona、action type、content/target IDs、OASIS 原始时间 `observed_at_raw` 和 SandOwl 记录时间 `recorded_at`。读取 experiment 时，系统会重新从事件核验 trial result counts；事件本身目前没有单独的 event digest。
- comparison 只使用成功 trial；每个 alternative 只与同一 seed 且成功的 baseline 配对。系统现有的限制明确声明 comparison 不推断 stance、reach、persuasion、business impact 或 decision verdict。

## 二、V2 报告契约

### 顶层身份

V2 建议保留一个不可变 `DecisionReport` 父对象，并增加以下明确字段：

```text
id
report_version = "decision-report/v2"
experiment_id / experiment_sha256
scenario_id / scenario_sha256
cohort_id / cohort_sha256
world_snapshot_id / world_snapshot_sha256
title
report_sha256
created_at / sealed_at
sections[7]
```

`world_snapshot_id` 和 `world_snapshot_sha256` 在 V2 父记录中直接保存，便于列表页、权限边界和完整性核验；它们仍必须与 Scenario 的冻结 snapshot identity 一致。V1 老记录保持现状，可以没有这两个字段。

实现上优先复用现有 `generator_version` 作为数据库中的版本 discriminator：V1 使用 `deterministic-findings/v1`，V2 使用 `decision-report/v2`；API 可以把该值映射为 `report_version`，不再新增一个内容重复的版本列。

每个 V2 section 同时保留两个层次：

1. `body_markdown`：给人阅读的确定性正文；
2. `data`：经过严格 Pydantic/Zod 校验的 typed payload，供 API、前端和后续 QA 使用。

`data` 不是随意的 `dict`。每个 `kind` 必须有固定 schema，拒绝未知字段；章节中的引用只允许指向当前报告绑定的 sealed resource、experiment、trial、event 或 section。

### Section 1：Evidence

Evidence 是现实输入的只读目录，不是观点总结，也不是“事实已经被证明”的数值置信度。

建议 payload：

```text
EvidenceSection {
  world_snapshot: {
    world_model_id, world_snapshot_id, version,
    snapshot_sha256, created_at, sealed_at,
    verification = "human_confirmed"
  },
  sources: [
    MediaEvidence {
      evidence_kind: "media_article",
      article_id, source_name, original_url,
      title, published_at, captured_at,
      captured_text_sha256, excerpt
    }
    | PolicyEvidence {
      evidence_kind: "policy_document",
      policy_version_id, authority_name, original_url,
      title, publication_date, captured_at,
      source_sha256, document_sha256, version_sha256, content_sha256
    }
  ],
  evidence_boundary: {
    status: "frozen_source_copy_not_independent_fact_check",
    statements: [...]
  }
}
```

规则：

- `sources` 从 sealed WorldSnapshot 读取；不能从当前 AgendaScope live 数据重新查询后替换内容。
- media article 使用 `article_id + captured_text_sha256` 回到 Evidence Bundle item；当前 snapshot item 不持久化 AgendaScope `source_id` 或 selection-time `evidence_revision_sha256`，V2 不能从 live media 表补写这两个值。policy item 使用 `policy_version_id`，并同时保留 source/document/version/content digest。
- `published_at`、`captured_at` 都保留 timezone；这两个时间不能与模拟事件时间混用。
- `verification='human_confirmed'` 表示当前系统记录的核验状态，不等于对媒体叙述或政策效果的独立事实核验，也不产生 `confidence=0.8` 一类虚假的数字。
- 如果没有 policy evidence，payload 仍必须明确写出 `policy_sources=[]` 或使用统一 `sources` 数组，不能从 Scenario intervention 推导出政策事实。
- 长正文通过已有 Evidence Bundle content route 读取；V2 只封存必要 excerpt、identity 和 hash，避免报告表复制不可控的全文。

### Section 2：Assumptions

Assumptions 是 Scenario 和实验刺激的显式假设，与 Evidence 分开存放：

```text
AssumptionsSection {
  scenario: {
    id, scenario_sha256, title, decision_question,
    world_snapshot_id, snapshot_sha256
  },
  variants: [
    {
      id, position, role: "baseline" | "alternative",
      name, hypothesis,
      interventions: [
        { id, kind, actor, channel, content, offset_minutes,
          provenance = "scenario_assumption",
          synthetic_label = "synthetic demo data" }
      ]
    }
  ],
  assumption_boundary: [...]
}
```

baseline 和 alternatives 从 sealed Scenario 原样读取。对本 Vertical Slice，两个公告文本和其发布时间/强度都是 Scenario 假设，必须显示 `synthetic demo data`；它们不能进入 Evidence section，也不能被描述为 AgendaScope 文章或真实政策。现有 Scenario 表没有独立的 `synthetic_label` 列，V2 先在报告 payload 中记录 provenance 和标签；后续若允许更多 intervention origin，再考虑在 Scenario contract 中增加显式 origin，而不是在报告生成时猜测。

Assumptions 不应出现“预计会”“将导致”“最优”这类结论。`hypothesis` 是待观察的假设文本，不能在报告中升级为事实。

### Section 3：Experiment

Experiment 说明运行条件和样本边界，独立于观察结果：

```text
ExperimentSection {
  experiment: {
    id, experiment_sha256, status,
    scenario_id, scenario_sha256,
    cohort_id, cohort_sha256, dataset_sha256, persona_count,
    variants: [{ id, position, role, name, hypothesis, intervention_count }],
    seeds, rounds, minutes_per_round,
    model_name, semantic_config_sha256, prompt_schema_version,
    engine_version, camel_version
  },
  trials: [
    {
      id, variant_id, role, seed, trial_sha256, status,
      created_at, started_at, completed_at,
      artifact_sha256, rounds_completed,
      failure: { code, message } | null
    }
  ]
}
```

成功 trial 的 engine/model/config 必须与 experiment 的冻结配置一致；失败 trial 也作为实验事实保留，不用成功结果覆盖。`seed` 只标识 SandOwl 实验输入；它不保证外部 provider 每次返回相同 token 或相同行为。`engine_version`/`camel_version` 在不同 trial 必须一致，若历史数据存在差异，应把差异列入 Limitations，不隐去。

### Section 4：Observation

Observation 是本次 simulation 实际写入的事件与结果，不能和“为什么”或“未来会怎样”混在一起：

```text
ObservationSection {
  trials: [
    {
      trial_id, variant_id, seed, status,
      event_count, events_sha256,
      event_endpoint,
      normalized_counts: {
        scenario_initial_posts,
        generated_posts, comments, reactions,
        do_nothing, observed_actions, authored_content
      },
      event_clock_boundary: {
        observed_at_raw_semantics,
        recorded_at_semantics
      }
    }
  ],
  behavior_changes: [
    {
      basis: [trial_id | event sequence | metric],
      statement: "只描述已经发生的 action/count 变化",
      interpretation_status: "observation"
    }
  ]
}
```

设计选择：不把可能很长的 event content 再复制成第二份事实表。`event_endpoint` 指向现有 `/api/v2/semantic-trials/{trial_id}/events`；`events_sha256` 由报告生成器按稳定 `(trial_id, sequence, ...)` canonical rows 计算，用来证明读取的是生成报告时的那批事件。V2 generator 必须在同一事务/一致性读取中先取得全部事件、核对现有 `_trial_from_record()` 的计数，再计算 digest。若未来需要离线单文件报告，可在 Markdown 导出中附带事件摘要或提供单独的 verified event export，而不改变核心事件表。

`behavior_changes` 只能陈述例如“alternative trial 有 4 个 create_comment、1 个 dislike_post”，不能把文本自动判为支持/反对，不能推断 reach、persuasion、态度或业务结果。事件中的 `observed_at_raw` 是 OASIS 模拟时钟字符串；`recorded_at` 是 SandOwl 写入时钟，UI 必须分别标注。

### Section 5：Comparison

Comparison 复用当前四项 deterministic metrics，但把它们提升为独立 typed payload：

```text
ComparisonSection {
  metrics: [
    {
      metric,
      baseline: { variant_id, mean, stddev, n },
      alternatives: [
        {
          variant_id, name,
          mean, stddev, n,
          mean_delta, stddev_delta,
          paired_seeds, paired_seed_count
        }
      ]
    }
  ],
  pairing_rule: "successful baseline/alternative trials with the same recorded seed",
  comparison_state,
  comparison_boundary: [...]
}
```

四个 metric 的顺序和含义沿用 `compare_semantic_experiment()`。V2 应补充 `paired_seeds`，因为仅有 n=1/2 不足以复核具体配对范围；如果第一版 API 暂时只得到 n，则必须在 payload 明确写出“seed list unavailable”，不能猜测。Comparison 仍然是描述性差异，不是显著性检验、因果效应或方案排序。

对于 Phase 1 的结果，alternative 比 baseline 多一条 synthetic `initial_post`，因此 `observed_action_count` 的 +1 至少包含输入结构差异。V2 的 Comparison 应把这种可由 Assumptions/Observation 直接核对的计数边界写出来，而不是把 +1 解释成“参与度提高”。

### Section 6：Analysis

Analysis 是解释层，不是预测层。V2 第一版建议继续使用确定性模板，不让 LLM 直接生成可封存的结论。每一条解释应带依据引用：

```text
AnalysisSection {
  statements: [
    {
      statement_id,
      text,
      basis: ["evidence:...", "assumptions:...", "observation:...", "comparison:..."],
      allowed_type: "accounting_explanation" | "scope_explanation" | "boundary_explanation"
    }
  ],
  prohibited_claims: [
    "future prediction", "causal claim", "best option", "population estimate"
  ]
}
```

允许的表达：

- “两个 alternative 都含有一条 scenario initial post，所以 observed action count 与 baseline 的差异包含 intervention 事件。”
- “本次只有一个共同 seed；两个 alternative 的 aggregate counts 相同，但这不能证明它们在更多 seed、更多 Persona 或现实平台中等效。”
- “comparison 只统计 normalized actions，不能从评论文本推出 stance。”

禁止的表达：

- “该方案将导致真实用户……”“预计市场会……”等未来预测；
- “政策造成了……”等超出当前受限模拟的因果结论；
- “A 是最佳/推荐方案”；
- “5 个 Persona 代表公众中 X%”；
- 把 synthetic intervention、provider 输出或媒体报道改写成现实事实。

前端必须把 Analysis 标记为“解释，不是预测/推荐”。如果未来启用 bounded ReportAgent，其 cited draft 只能作为待审稿材料，只有通过 Evidence citations、schema 和禁止词校验后才可人工确认；不能让 ReportAgent 绕过 V2 的 typed payload 和封存规则。

### Section 7：Limitations

Limitations 是结构化边界清单，不只是 Comparison 的两行字符串：

```text
LimitationsSection {
  items: [
    { code: "sample_size", text, severity: "material" | "context" },
    { code: "synthetic_inputs", text, severity },
    { code: "model_dependency", text, severity },
    { code: "simulation_boundary", text, severity },
    { code: "evidence_boundary", text, severity },
    { code: "clock_semantics", text, severity },
    { code: "no_prediction_or_recommendation", text, severity }
  ]
}
```

最低限必须覆盖：Persona/Cohort 数量、成功/失败 trial 数、seed/round 数、synthetic Scenario 输入、模型/provider/config 依赖、OASIS 的平台边界、媒体/Policy evidence 只是冻结且可追溯的来源而非独立事实核验、`observed_at_raw` 与 `recorded_at` 的时间语义、没有真实总体估计/预测/最佳方案。

## 三、Hash 与封存规则

V2 仍是 content-addressed、draft-then-seal、sealed immutable：

```text
decision-report/v2
 + experiment/scenario/cohort/world-snapshot identity digests
 + title
 + each section: position, kind, title,
   canonical(data JSON), body_markdown, metrics JSON
 -> report_sha256
```

要求：

1. `data JSON` 使用 UTF-8、sorted keys、无空白和禁止 NaN/Infinity 的 canonical serialization；数组顺序由 schema 定义，不能按数据库随机顺序输出。
2. V2 report 必须绑定 Scenario 的 sealed WorldSnapshot hash；V2 Evidence payload 中每个 source hash 必须能从该 snapshot 重算/核对。
3. V2 Observation 读取全部成功/失败 trial 的事件。失败 trial 没有 events 时明确记录 `event_count=0` 和失败原因；不能用空数组掩盖 failure。
4. 计算 report hash 前先通过 Pydantic 验证七个位置连续且 kind 唯一；DB trigger 在 seal 时执行同等的版本/章节完整性检查。
5. 现有 V1 report 的 hash 算法不能被改写。数据库 trigger 和 Python projector 必须按 `generator_version` 分支验证 V1/V2，保留已封存的 `37384e5e-...` 原样可读。

## 四、从当前 Report 到 V2 的最小兼容迁移

### 1. 是否需要数据库变更

需要，但可以限制在现有报告表：

推荐新增一条后续 migration（实际执行前先以 `alembic current` 核对运行库，工作区目前可见 migration 文件已到 `0040`，Demo 运行记录曾停在 `0032`）：

- 在 `decision_reports` 增加 `world_snapshot_id`、`world_snapshot_sha256`，V2 必填，V1 老行允许 NULL；增加与 `world_snapshots` 的 `RESTRICT` 外键和 digest check。
- 在 `decision_report_sections` 增加 `data_json TEXT NOT NULL DEFAULT '{}'`。V1 行保留空 object；V2 每行保存对应 typed payload 的 canonical JSON。`metrics_json` 暂时保留，Comparison 可以继续使用现有 metrics serialization，其他章节保持空 tuple/空数组以降低迁移风险。
- 将 section position 上限从 3 扩到 6，把 kind allowlist 扩展为七种 V2 kind；不要删除 V1 kind，因为老报告仍需投影。
- 将 `generator_version` check 从单值改成 `deterministic-findings/v1` 或 `decision-report/v2`。
- 当前 `UNIQUE(experiment_id)` 会阻止同一 Phase 1 experiment 生成一份不可变 V2。应改为 `UNIQUE(experiment_id, generator_version)`：原 V1 继续存在，V2 可以针对同一 experiment 产生新的 report ID；不能 update/overwrite 现有 sealed report。
- 替换 report parent/section seal trigger：V1 分支严格要求原四章节并使用原 hash；V2 分支严格要求七章节、snapshot identity、`data_json` 和 V2 hash。迁移完成后仍应保留 truncate/delete protection。

不建议在第一版 V2 复制 `world_snapshot_evidence`、`semantic_trial_events` 或 ReportAgent citations 到新的报告子表。它们已经是不可变事实源；V2 payload 存 typed identity、summary 和 digest，原文/事件通过现有只读 API 查回。只有当产品需要按 source/metric 做跨报告 SQL 筛选时，再评估拆出专用 normalized child tables。

### 2. 后端 contract/repository 变化

新增 `DecisionReportV2`、七个 section payload model 和 `build_report_v2_sections()`，不改写 V1 models：

- V2 generator 先加载 sealed Scenario、WorldSnapshot、Cohort、SemanticExperiment detail、全部 trial events 和 comparison；对每个来源做 hash/identity 校验。
- 由确定性 projector 生成七个 payload/body，不调用 LLM，不从 live AgendaScope 重新采集，不把 ReportAgent draft 自动写入 Analysis。
- V2 `report_sha256` 使用新版本 canonicalizer；所有 response projector 在读取时重新计算并拒绝 hash mismatch。
- 既有 `get_decision_report()` 保持 V1 行为；新增 `get_decision_report_v2()` 按 discriminator 返回 V2。列表可以增加 `report_version` 和 `world_snapshot_sha256` summary，或提供 V2 专用列表，避免旧前端被迫理解七章节。
- Report generation 要求同一 experiment 的 `(experiment_id, generator_version)` 幂等；重复 POST 返回现有对应版本的 sealed report，而不是再建一份。

### 3. API 变化

采取 additive API，保持当前客户端不破坏：

```text
POST /api/v2/decision-reports/from-experiment/{id}
    -> 继续生成/读取 deterministic-findings/v1

POST /api/v2/decision-reports/v2/from-experiment/{id}
    -> 生成/读取 decision-report/v2

GET  /api/v2/decision-reports/v2
GET  /api/v2/decision-reports/v2/{report_id}
GET  /api/v2/decision-reports/v2/{report_id}/markdown
    -> V2 typed response / 七章节导出
```

FastAPI 中静态 `/v2/...` 路由必须在 `/{report_id}` 之前注册，或改用独立 `/api/v3/decision-reports`；不要让字符串 `v2` 被 UUID route 当成 report ID。错误状态、sealed/integrity 语义和 Markdown 下载保持现有习惯。若最终决定使用 query discriminator，也必须显式 `report_version=v2`，不能按“最新报告”隐式切换。

### 4. 前端变化

不重写现有 Report workspace：

- 保留 `frontend/src/decisionReportContracts.ts` 的 V1 Zod schema，继续渲染四章节旧报告。
- 新增 `decisionReportV2Contracts.ts`，为七种 section 写 strict Zod payload；所有 article/policy item identity、trial/event reference、hash、timestamp、enum 都在边界验证。
- V2 页面复用现有 comparison ledger 和 Markdown inline renderer，但新增 Evidence source table、Assumptions synthetic label、Experiment trial ledger、Observation event/clock panel、Analysis boundary banner、Limitations code list。
- Report header 显示 `decision-report/v2`、WorldSnapshot hash、Experiment hash 和 Report hash；Evidence item 提供现有 Evidence Bundle content link，Observation item 提供 Semantic Trial events link。
- V1 与 V2 的 route/缓存 key 分开，避免用同一 `DecisionReport` TypeScript 类型把四章节数组强行解释成七章节数组。
- 现有 Report Questions、Persona Interview 和 ReportAgent cited draft 保持独立入口。它们可以读取 V2 的 Evidence/Observation refs，但不能在没有人工确认的情况下修改 sealed DecisionReport。

## 五、迁移步骤与验收条件（设计，不执行）

建议顺序：

1. 先在 contract 层定义 V2 payload 和 canonical serializer，使用已经存在的 Phase 1 资源做纯内存 projection；确认 V1 hash 不变。
2. 增加 migration，扩展列/check/trigger，并在隔离 PostgreSQL 上先验证 V1 老行可读、V2 draft 可插入、错误章节/hash 无法 seal、sealed rows 不能修改。
3. 实现 deterministic V2 repository/API，先对已有 Experiment 生成一份新 V2 report；不要更新或删除 report `37384e5e-...`。
4. 增加前端 V2 contract/render，再用同一 report 的 GET/Markdown 与数据库 projector 交叉核对 hash。
5. 运行一个新 seed 或第二 Vertical Slice，确认七章节中每项都能追溯到真实 sealed resource；手工检查 Analysis 无预测、因果和最佳方案语言。

验收必须能证明：

- Evidence 的 snapshot/source/hash 与 Scenario 绑定一致；
- Assumptions 与 Evidence 分离，所有 synthetic input 有显式标签；
- Experiment 的每个 trial 状态、seed、model/config 和失败原因均可复核；
- Observation 的 event count/digest 与 `/semantic-trials/{id}/events` 一致；
- Comparison 的 paired seed 和 delta 可由同一成功 trial 重算；
- Analysis 每条解释有 basis refs，且没有预测/推荐；
- Limitations 明确样本、模型、模拟、来源和时钟边界；
- V1 报告仍能用旧 API/旧 hash 正常读取，V2 不覆盖旧记录。

## 结论

DecisionReport V2 的关键不是把 Markdown 写得更长，而是把“证据、假设、实验、观察、比较、解释、限制”变成七个可验证的 typed sections，并让 content hash 覆盖这些结构化内容。最小安全路径是扩展现有不可变报告表和 trigger、为同一 experiment 允许按 report version 并存、用确定性 projector 生成 V2，再以 additive API 和前端 schema 逐步接入。这样可以修复当前报告缺少独立 Evidence/Observation 的产品缺口，同时保持 Evidence → Experiment → Observation → Report 的核心设计和既有 V1 数据完整性。

## 六、实施与运行验收（2026-08-16）

V2 已按上述 additive 方案实现：migration `20260816_core_0042`、七类 strict payload、V2 canonical hash、seal trigger、repository、API、Markdown 导出和前端只读展示均已落地。现有 Reports 工作区优先显示同一 experiment 的 V2；若只有 V1，则仍显示 V1 并提供显式 V2 生成操作。

首案 Experiment `c2884f02-3475-45e7-83ee-5e584563bdaa` 的原 V1 仍是 `37384e5e-798c-4b3c-8bda-e2502252e52a`，report hash 仍是 `843fc66bba09064cb4a329a52ae6fe0c23dd91391402977297b6b796ba9553a0`。同一 Experiment 新生成 V2 `2b214688-d350-4eb1-8550-1d210c6b75b2`，七章节齐全且绑定 WorldSnapshot `cf045f9d-7e42-4d5c-b8dd-895769e23e4c`。

第二案例也生成了并存报告：V1 `a7bd404a-50a9-49eb-9407-522cc8479b27` 与 V2 `8c9c938e-7c87-471d-9966-fc9200095ae7`。V2 的 Evidence 使用冻结 source copy/hash，Assumptions 保留 `synthetic demo data`，Observation 记录三个 trial 的 event digest，Analysis 只解释计数边界，没有预测、因果结论或最佳方案。
