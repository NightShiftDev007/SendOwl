# Interview 双轨（live / offline）

> 关联：[crash-recovery.md](./crash-recovery.md)（进程 adopt ≠ Interview 内存态）、[progress-sse.md](./progress-sse.md)

## 模型

深度互动 / Agent 采访统一走 `interview_with_fallback`：

| mode | 条件 | 行为 |
|------|------|------|
| `live` | `env_status.json` 为 `alive` 且 IPC 成功 | OASIS 当场 Interview |
| `offline` | 环境关闭，或 live 失败/超时 | LLM 基于人设 + `actions.jsonl`（+ 可选历史 interview）回顾作答 |

响应一律带 `mode`；offline **不是**固定 stub，也**不**伪装成 live。

## 调用方

- `POST /api/simulation/interview` / `batch` / `all`
- `POST /api/run/<run_id>/interview`
- Report 工具 `zep_tools.interview_agents`

实现：[`backend/app/engine/offline_interview.py`](../backend/app/engine/offline_interview.py)

## 离线数据依赖

目录：`uploads/runs/<simulation_id>/`

- 人设：`reddit_profiles.json` 或 `twitter_profiles.csv`
- 动作：`twitter|reddit/actions.jsonl`（或根级 `actions.jsonl`）
- 可选：`*_simulation.db` 中 `trace.action=interview`

无人设且无动作时：仍返回 `mode=offline`，文案说明无法回顾，不 500。

## 与崩溃恢复的关系

Phase C adopt 可找回**还在跑**的子进程；Interview 依赖进程内 Agent 状态。环境已关或不存在时，双轨走 offline，**不**依赖 adopt 复活采访。

## UI

Step5 展示「实时采访 / 回顾模式」；offline 气泡带「回顾」标签。历史库 hint：Step3 仍需运行中启动；Step5 支持回顾采访。
