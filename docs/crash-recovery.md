# 崩溃透明恢复（Phase C）

> 关联：[progress-sse.md](./progress-sse.md)（进度 / Task TTL）、[design.md](./design.md)

## 目标

后端进程崩溃/重启后，在途工作自动从断点续跑；janitor TTL 降为最后兜底。

## 启动扫描与恢复矩阵

启动扫描实现：`app/progress/recovery.py`（与 janitor 同块调度，延迟数秒后台执行）。

| 在途状态 | 恢复动作 |
|---|---|
| decision `preparing` | 重入 `prepare_decision`（N>1 shared 按产物跳过；N=1 按 profiles/config 跳过） |
| decision `running` | 先 `reconcile_runs_with_run_state` → `try_adopt` 子进程 → `start_decision(revive_worker=True)` |
| ontology `building` | 有检查点则同 graph 续传；无检查点立即 `failed` |
| report task `processing` | **复用原 task_id**，`generate_report(resume=True)` 跳过已完成章节 |
| sim `preparing` + `prepare_task_id` | 复用原 task_id 重开 prepare worker |

## 模拟子进程 adopt

实现：`SimulationRunner.try_adopt`。

- 校验 `process_pid` 存活 + `env_status` 心跳新鲜
- 登记 `PidProcess` shim（`poll` / `terminate` / `kill`），重建 monitor；收养后 `stop_simulation` 仍可用
- `SIM_DETACH_ON_EXIT`（默认 `false`）：仅影响**优雅退出**（SIGTERM/Ctrl+C）；`kill -9` 本就不跑 atexit，子进程总是存活可被 adopt

## 建图检查点

写入 task `progress_detail`：

```text
{graph_id, phase: appending|waiting, next_chunk_index, total_chunks, episode_uuids}
```

`waiting` 阶段 resume 只续等、不重发 episodes。

## 验收要点

- 报告 / prepare / 建图 `kill -9` → 重启后续跑
- 推演 `kill -9` → adopt 且可 stop
- `SIGTERM` + `SIM_DETACH_ON_EXIT=true` → 子进程不被杀，重启后 adopt
- 无法恢复 → 启动后数秒内标 failed（非等 1h TTL）
