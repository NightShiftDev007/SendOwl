# 实时进度（一阶段一 SSE）

> Phase A / B · 关联总设计 [design.md](./design.md)、崩溃恢复 [crash-recovery.md](./crash-recovery.md)

## 模型

一阶段一 SSE：同连接推进度 + 结果增量，终态 `done` 后关闭。

主 URL（按 scope，正常路径同时只开一条）：

- Step1 建图 / Step2(N=1 prepare) / Step4 报告 → `GET /api/tasks/<task_id>/events`
- Step2(N>1 prepare) / Step3 推演 → `GET /api/decision/<decision_id>/events`（可带 `?sim_id=&actions_from=`）

事件：

- `progress`：必有 `envelope`；**同帧**可带结果增量（`profiles_digest` / `graph` / `actions` / `agent_logs`…）
- `done`：终态快照后关闭连接
- GET 仅用于：连上瞬间补快照、刷新恢复、`EventSource.CLOSED` 后的唯一降级 interval

**废弃作为正常路径的第二连接**（端点可保留作降级，前端默认不订）：

- `/api/simulation/.../prepare/preview/events`
- `/api/simulation/.../actions/events`
- `/api/report/.../logs/events`
- `/api/ontology/.../graph/events`

一次性拉图仍可用 `GET /api/ontology/<ontology_id>/graph`。

- **部署约束**：进度 pub/sub 默认进程内内存（`PROGRESS_BUS=memory`）。多 worker 可设 `PROGRESS_BUS=redis`（配置位已留）。Flask debug 热重载会断 SSE，属预期。

### 刷新 / force 契约（Phase A）

- **进行中 = attach**：刷新页面只重新订阅 SSE / 拉快照，不自动 `force` 重开任务。
- **显式 force**：仅用户点击「重新推演 / 确认方案并准备环境（强制）」时清产物重跑。
- **权威状态在服务端**：`decision.status` + 磁盘 `run_state` / 产物；前端 `phase` 只是投影。N=1 启动也会回写 registry；`get_status` 惰性用 `run_state` 校正。
- **双轨纪律**：正常路径只开一条主 SSE；`onOpen` 拉一次 HTTP 快照；`EventSource.CLOSED` 后才开唯一降级 interval；禁止 SSE 存活时并行 2s 轮询。
- **N>1 prepare 细进度**：`decisions/<id>/prepare_progress.json`，经 decision SSE `envelope` 下发（含 `profiles_digest`）。

### ProgressEnvelope 与一阶段一 SSE（Phase B → 单通道定稿）

```text
ProgressEnvelope {
  scope: "ontology" | "decision" | "run" | "task"
  id: string
  status: pending|running|completed|failed|...
  raw_status?: string
  stage: string
  progress: 0..100
  message?: string
  artifacts?: {
    profile_count?: number
    profiles_digest?: object[]  // name/username/entity_type/bio/topics，上限 20
    topics_count?: number
    config_ready?: boolean
    prepare_task_id?: string
    report_task_id?: string
    // Step3
    twitter_current_round?: number
    reddit_current_round?: number
    *_actions_count?: number
    actions_watermark?: number
    // Step1 / Step4
    node_count?: number
    edge_count?: number
    agent_log_line?: number
    console_log_line?: number
  }
  updated_at: iso
}
```

- **实现**：`backend/app/progress/envelope.py`；task/decision SSE 帧附带 `envelope` **并同帧推结果增量**。
- **Step2**：N=1 订 task SSE；N>1 订 decision SSE；人设直接用帧内 digest 渲染，**禁止**与 preview SSE 并行。
- **Step3**：只订 decision SSE；同帧平台 ROUND/ACTS + actions；完成态以 `runner_status` / 平台 completed / matrix 为准，不单看 `prepared`。
- **Step1 / Step4**：只订 task SSE；同帧 graph / logs+章节。
- **`resolveSimContext`**：simId 缓存 TTL 30s。
- **前端**：`useProgress.js` + 各 Step 主通道订阅。

### Task 持久化与 TTL（Phase B）

- **tasks 表**（`meta.db`，`app/models/store.py::init_tasks_schema`）：TaskManager create/update 写库；`get_task` 内存未命中回源 DB。
- **句柄**：`prepare_task_id`（sim state）/ `build_task_id`（ontology）/ `reports/<id>/generate_task.json`（report_task_id）；刷新后可恢复 SSE。
- **TTL 与回收**（`progress_janitor`，惰性 + 每 5min 定时扫；debug reloader 仅 `WERKZEUG_RUN_MAIN` 启动）：

| 状态 | TTL | 超时动作 |
|---|---|---|
| `building` / graph task | 2h（`PROGRESS_TTL_BUILDING_SEC`） | `failed` + `task_lost` |
| `preparing` | 1h 无 progress 更新（`PROGRESS_TTL_PREPARING_SEC`） | `prepare_failed` |
| `running` 且 env 不存活 | 定时检测 | `failed` / run `env_not_alive` |

- **Redis**：`PROGRESS_BUS=memory|redis`；默认 memory。接口见 `app/progress/bus.py`。

