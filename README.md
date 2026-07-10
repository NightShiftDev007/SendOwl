# AI 决策中心（AI Decision Center）

> 本体层（持续同步的现实世界模型）× 群体智能推演引擎（MiroFish/OASIS）× 决策对比闭环
>
> **Palantir/Ontology 回答「现在世界是什么样」，MiroFish 回答「如果我做 X，世界会变成什么样」。**

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

### 1. 环境

```bash
# 根目录
pnpm install
pnpm run setup:backend   # uv sync

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

或分别：

```bash
pnpm run backend
pnpm run frontend
```

### 3. 离线验收（不依赖 Zep/OASIS）

```bash
cd backend
uv run python scripts/smoke_offline_mvp.py   # 快速 smoke
uv run python scripts/e2e_mvp_demo.py        # 2 方案 + Baseline × 3 采样
```

成功输出 `SMOKE_OK` / `E2E_OK`。随后可在前端「对比面板」打开对应 `decision_id`（见脚本打印）。

### 4. 产品路径（舆情模板）

1. **本体管理**：创建舆情模板本体 → 上传种子材料 → 建图 → 快照  
2. **创建决策**：选本体 → 配置强硬 / 柔性 / Baseline → `M=3` 采样 → 启动  
3. **运行监控**：查看 Scenario × Run 矩阵  
4. **对比面板**：传播规模、观点结构、叙事报告  

真推演需要可用的 `LLM_*` 与 `ZEP_API_KEY`，耗时较长；离线路径用合成 actions 验证闭环。

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
