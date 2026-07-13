# SandOwl · AI 决策中心

> 本体层（持续同步的现实世界模型）× 群体智能推演引擎（OASIS）× 决策对比闭环
>
> **在沙盘里推演，再做决定。** Palantir/Ontology 回答「现在世界是什么样」，SandOwl 回答「如果我做 X，世界会变成什么样」。

## 项目状态

| 阶段 | 说明 |
|------|------|
| 方案设计 | [docs/](./docs/)（入口 [README](./docs/README.md)） |
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
frontend/     # Vue 3 + Vite：五步向导（本体 → 准备 → 推演 → 报告 → 采访）
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

### 3. 产品路径（五步）

1. **首页**（`/`）：上传种子文档 → 构建本体  
2. **环境准备**（`/process` → `/simulation/:id`）：切片 / 人设 / 平台与事件配置；多方案时在此应用 N×M 并自动补 Baseline  
3. **推演监控**（`/simulation/:id/start`）：Scenario 矩阵 + 动作流时间线  
4. **对比报告**（`/report/:id`）：verdict / 立场结构 / 传播曲线 / markdown 报告  
5. **Agent 采访**（`/interaction/:id`）：对模拟世界中的 Agent 提问  

旧路径 `/decision/new|monitor|compare` 仍保留 redirect，进入上述五步。

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
| [docs/README.md](./docs/README.md) | 文档索引（产品 / 运行时 / 规划） |
| [docs/design.md](./docs/design.md) | 产品与架构总览 |
| [prototype/README.md](./prototype/README.md) | Demo 原型用法 |
| [NOTICE](./NOTICE) | MiroFish 来源与商业授权 |

## 相关项目

- [MiroFish](https://github.com/666ghj/MiroFish) — 多智能体群体智能推演引擎  
- [OASIS](https://github.com/camel-ai/oasis) — CAMEL-AI 社媒 Agent 模拟框架  
