# 图谱快照为展示 Source of Truth

> 关联：[design.md](./design.md)、[crash-recovery.md](./crash-recovery.md)

## 模型

日常打开图谱面板 **只读本地最新快照**（`ontology_versions` + `SNAPSHOT_DIR/.../vN.json`），不再每次打 Zep live。

| 场景 | 行为 |
|------|------|
| 本体 ready，有快照 | `GET /api/ontology/<id>/graph` → `source=snapshot` |
| 本体 building | 读 Zep live（**不 heal**），供 Step1 SSE 增量刷图 |
| ready 无快照 | bootstrap：`export_snapshot` 一次后再读 |
| 用户点刷新 | 先 `POST .../snapshot`（从 Zep 同步），再 GET |
| 建图完成 / 追加文档完成 / recovery | 自动 `export_snapshot` |

## 端点补全（heal）放在哪

Zep 列表分页常漏边端点节点。补全只在 **`export_snapshot` 写快照时做一次**，不在读热路径上串行 `node.get`。

读路径 `get_graph_data(..., heal=False)` 默认关闭 heal。

## 去重

同 `graph_id` 且 node/edge 计数与最新快照一致时，`export_snapshot` 不升版（避免 watcher + 前端 finalize 连写两版）。

## 与推演的关系

决策路径默认关闭 graph memory 回写；推演不自动升展示快照。需要新图时靠用户刷新或追加文档触发导出。
