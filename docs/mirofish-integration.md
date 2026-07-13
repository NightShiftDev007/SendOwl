# MiroFish 复用与集成

> 来源：从 [design.md](./design.md) §6 拆出 · 关联产品总设计

## MiroFish 复用映射

| MiroFish 模块 | 决策中心去向 | 改造程度 |
|---|---|---|
| `ontology_generator.py` | 本体层 Schema 冷启动 + 场景模板生成 | 小改：输出接受人工审阅/锁定 |
| `graph_builder.py` / `text_processor.py` | 数据接入层文档管道 | 小改：支持增量 episode 追加 |
| `zep_entity_reader.py` / `zep_tools.py` / `zep_paging.py` | 本体层图检索服务 | 基本复用 |
| `zep_graph_memory_updater.py` | 推演结果回写（标记 simulated 来源） | 小改 |
| `oasis_profile_generator.py` | 人口合成的具名 Agent 部分 | 中改：增加 cohort 代言人生成分支 |
| `simulation_config_generator.py` | Scenario 配置生成 | 中改：干预 DSL 化 |
| `simulation_manager/runner/ipc.py` | Run 级执行器 + Interview | 基本复用，上面套 Scenario Runner |
| `run_*_simulation.py`（OASIS 脚本） | LLM Agent 内核 | 中改：初始网络注入、环境变量干预 |
| `action_logger.py` | 动作日志 | 复用 |
| `report_agent.py` | 决策层叙事报告 | 中改：输入改为指标层 + 多 Run |
| 前端五步向导 / `GraphPanel.vue`（D3） | 五步向导接入决策 API 复用；另保留多方案决策创建/监控/对比 | 中改 |
| **完全新建** | 实体消歧、版本快照、世界切片器、网络合成、Scenario Runner、统计传播内核、指标计算、对比面板 | — |

结论：**后端 services 六成以上可复用或小改**，新增集中在镜像世界生成层和决策层的量化部分——这正是"决策中心"区别于"模拟工具"的增量所在。

### 集成方式：整库集成进 monorepo（已定）

> 许可背景：MiroFish 原为 AGPL-3.0，**我方已取得商业授权/双许可**，代码可直接并入本仓，无开源传染问题。

**决定：方式 A —— 把 MiroFish 后端代码 vendor 进本仓，在单一代码库内改造。** 这是工程上最顺的路线：§6 映射表中的"小改/中改"模块（profile 生成、模拟配置、OASIS 脚本等）都需要动内部实现，同仓改造避免跨仓接口协调和双份 CI/部署。

**前端改造原则（已定，必须遵守）：**

> **MiroFish 已有功能全部保留、全部可用。** 允许美化、修改、重构、换 API 适配层；**禁止以「决策中心不需要」为由删减五步向导或其中能力**（schema 浏览、建图进度/刷图、环境搭建/人设与配置、推演时间线、报告生成、Agent 互动等）。决策中心的增量（常驻本体、多方案 × 多采样、对比面板）是**叠加**，不是替换。

**落地形态：**

- 目录规划：MiroFish 的 `backend/app/services` 按五层架构归位重组，而非整体平移——图谱/检索/回写类（`ontology_generator`、`graph_builder`、`zep_*`）并入本体层模块；模拟执行类（`simulation_*`、`run_*_simulation`、`action_logger`）并入推演引擎模块；`report_agent` 并入决策层。
- **前端主路径 = MiroFish 五步向导**（`/` → `/process` → `/simulation` → `/start` → `/report` → `/interaction`），壳用 SandOwl（AppHeader / tokens），底层接 ontology/decision/run API。
- **前端次路径 = 多方案决策**（`/decision/new` → monitor → compare），作为叠加能力，不替代五步。
- **引擎接口契约保留，降级为内部模块边界**：推演引擎模块对外只暴露一个接口——输入 = 世界切片 + Agent 人口（profiles）+ 初始网络 + 干预配置；输出 = actions 流（jsonl）+ 平台 DB + 运行状态回调。该边界与 §5"两档引擎"设计重合：未来统计传播内核作为第二个引擎实现同一接口接入，不动上下游。
- 与上游的关系：vendor 后即分叉，不追求与 MiroFish 上游保持同步（改造深度决定了合并成本高于收益）；OASIS/CAMEL、Zep SDK 仍作为 pip 依赖正常升级。
- 授权文件与来源声明（NOTICE：代码源自 MiroFish、商业授权依据）随代码入仓存档，避免日后审计说不清来源。

---

