# Second Vertical Slice Runtime Check

检查时间：2026-08-16 11:02:35 UTC（2026-08-16 19:02:35 Asia/Shanghai）

本检查只确认本地 SandOwl 运行态是否能执行“电动车品牌劳资争议结束后的回应节奏实验”。案例主体固定为虚构品牌 `Northstar Mobility`；AgendaScope 媒体记录只是现实背景 evidence，不是事实裁决。

## Worker

| Domain | Worker ID | 运行态 | 能力身份 |
| --- | --- | --- | --- |
| semantic | `sandowl-compose-semantic-worker` | 在线；`semantic_runtime_ready=true` | `qwen3.7-plus` / `matraix-semantic-profile/v1` |
| report | `sandowl-compose-report-worker` | 在线；Report/QA 所需 semantic provider probe 已通过 | `qwen3.7-plus` / `matraix-semantic-profile/v1` |
| evaluation | `sandowl-compose-evaluation-worker` | 在线；Survey/Chat/Web/Linux 均 ready | domain-specific evaluation runtimes |

三个 worker 是独立 Compose 服务，heartbeat 的 `worker_domain` 分别为 `semantic`、`report`、`evaluation`。本次 Semantic Experiment 可由标准 `semantic-worker` 直接消费，不需要 semantic-only workaround，也不受 Chat SUT readiness 影响。

## Database

- Alembic workspace head：`20260816_core_0042`。
- 当前 PostgreSQL revision：`20260816_core_0042 (head)`。
- V2 持久层已存在：`decision_reports` 与 `decision_report_sections`。
- 当前报告数据包含 `decision-report/v2` 两条及兼容的 `deterministic-findings/v1` 两条。
- 本次不需要 migration，也不修改 schema。

## Existing resources

已有且将复用的唯一输入资源是冻结 MatrAIx dataset：

- dataset ID：`370c75f4-39d4-498b-922f-944d53df596b`
- dataset slug：`matraix-persona-dev-sample`
- dataset SHA-256：`e5257c144450b65ffd6022408bdcb38b455539389846fd55d6fa9f716db03e79`
- persona count：200

数据库中已存在上一次设计验证产生的同类资源：WorldModel `703cb7cb-0c97-4ec6-b107-3b7763d5b40f`、WorldSnapshot `601b029d-32fb-452b-aa45-4dd8d32404c1`、Scenario `089b6b51-749b-4fea-bb82-fc55c821387d`、Cohort `ebfbad03-3fbc-4280-8047-7565f4d999af`、Experiment `107a357a-0f3a-4df2-810f-033f9934fecc`、DecisionReport V2 `8c9c938e-7c87-471d-9966-fc9200095ae7`。这些资源只用于确认“已存在”，本次执行不会引用旧 WorldSnapshot、Scenario、Cohort、Experiment 或 Report。

本次会创建一个全新 Cohort，但严格复用旧 cohort 已验证的五个 Persona、同 dataset、同成员顺序。不会生成 Persona，也不会赋予这些 Persona 消费者、员工、工会或公众代表性。

## AgendaScope evidence revision

执行前已重新读取六条 `/api/v2/media/articles/{article_id}`。六条记录当前均可读取，selection-time `evidence_revision_sha256` 与旧设计记录一致。创建新 WorldModel 时仍以这次读取结果作为并发校验；sealed snapshot 将保存新的 snapshot identity 和 frozen captured hashes，不复用旧 snapshot hash。

## LLM

- model name：`qwen3.7-plus`
- semantic config SHA-256：`4184bdb6cad7eebbb1836ae19f005ab926d93350b4705e5b0140fef79ac58741`
- prompt schema：`matraix-semantic-profile/v1`
- engine：`camel-oasis 0.2.5`
- CAMEL：`0.2.78`
- readiness：`worker_online=true`、`live_worker_count=1`、`configuration_conflict=false`

API key 未读取、未输出，也不会写入报告。创建 Semantic Experiment 会触发本任务明确要求的 provider 调用；若 trial 失败，将保留真实失败状态，不人工补结果、不自动创建替代 experiment。

## Execution decision

所有前置条件满足，可直接执行现有链路：重新冻结 AgendaScope evidence → 创建 Scenario → 创建同序 Persona Cohort → 运行三 variants、单 seed、单 round 的 Semantic Experiment → 核对 persisted events → 生成 DecisionReport V2 → 浏览器验收。
