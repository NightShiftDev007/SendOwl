# SandOwl · AI 决策中心

> 本体层（持续同步的现实世界模型）× 群体智能推演引擎（OASIS）× 决策对比闭环
>
> **在沙盘里推演，再做决定。** Palantir/Ontology 回答「现在世界是什么样」，SandOwl 回答「如果我做 X，世界会变成什么样」。

## 项目状态

| 阶段 | 说明 |
|------|------|
| 方案设计 | [docs/design.md](./docs/design.md) |
| Demo 原型 | [prototype/](./prototype/) — 已跑通「同世界多方案对比」 |
| **P1 MVP** | `backend/` + `frontend/` — 常驻本体、世界切片、Scenario Runner、指标对比面板 |

MiroFish 商业授权说明见 [NOTICE](./NOTICE)。

## 仓库结构

```
backend/app/
  ontology/   # 常驻本体、文档管道、快照
  world/      # 世界切片、人口、初始网络
  engine/     # 干预 DSL、Scenario Runner、OASIS 执行
  decision/   # 指标计算、ReportAgent
  api/        # /api/ontology /api/decision /api/run
frontend/     # Vue 3 + Vite：本体 / 创建决策 / 监控 / 对比
prototype/    # 早期 Demo（仍可用）
```

## 快速开始（MVP）

前端品牌为 **SandOwl**：自有设计 token + AppHeader，决策指挥台式首页与对比结论条；API 接到本仓 `/api/ontology` `/api/decision` `/api/run`。

### 1. 环境

```bash
# 根目录
pnpm install
pnpm run setup:backend   # uv sync
cd frontend && pnpm install && cd ..

# 配置密钥（与 MiroFish 相同变量名）
cp .env.example .env
# 填写 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME / ZEP_API_KEY
```

### 2. 启动

```bash
pnpm run dev
# 后端 http://localhost:5001
# 前端 http://localhost:3000
```

### 3. 产品路径（舆情模板）

1. **首页**：上传种子文档 →「构建本体」进入本体工作台  
2. **本体工作台**（`/ontology/:id`）：建图 → 快照 → 创建决策  
3. **创建决策**（`/decision/new`）：强硬 / 柔性 / Baseline，`M=3` 采样  
4. **运行监控**（`/decision/:id/monitor`）：Scenario 卡 + 动作流时间线  
5. **对比面板**（`/decision/:id/compare`）：量化对比 + 报告 + Agent 采访  

### 4. 离线验收

```bash
pnpm run smoke
pnpm run e2e
```

真推演需要可用的 `LLM_*` 与 `ZEP_API_KEY`；离线路径用合成 actions 验证闭环。

## 旧 Demo（prototype）

```bash
cd prototype
python3 run_scenarios.py synthesize
python3 metrics.py --synthetic
python3 -m http.server 8765
# http://localhost:8765/demo.html
```

## 文档

| 文档 | 内容 |
|------|------|
| [docs/design.md](./docs/design.md) | 完整方案设计 |
| [prototype/README.md](./prototype/README.md) | Demo 原型用法 |
| [NOTICE](./NOTICE) | MiroFish 来源与商业授权 |

## 相关项目

- [MiroFish](https://github.com/666ghj/MiroFish) — 多智能体群体智能推演引擎  
- [OASIS](https://github.com/camel-ai/oasis) — CAMEL-AI 社媒 Agent 模拟框架  
