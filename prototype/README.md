# AI 决策中心 · Demo 原型

用最小代价验证核心假设：**同一个 Agent 世界 + 不同干预方案 → 模拟结果是否可区分、符合直觉。**

不搭五层架构、不 vendor MiroFish；直接调用本地 MiroFish 引擎，本目录提供案例、编排、指标与对比页。

## 目录

```
prototype/
  case/                     # 「北京市丰台区电动自行车限行」种子材料（真实地名）
  scenarios.json            # 三方案干预定义（强硬 / 柔性 / Baseline）
  build_shared_world.py     # API：本体→图谱→prepare 共享世界
  run_scenarios.py          # 导出 / 物化 / 顺序跑三方案；或 synthesize 离线数据
  synthesize_demo_data.py   # 离线合成 actions（无 Zep 时用）
  metrics.py                # 指标提取 + 验收判据 + demo_data.json
  demo.html                 # 对比演示页（ECharts）
  outputs/                  # 运行产物
  shared/                   # 导出的共享世界快照
```

## 快速演示（离线，无需 Zep）

```bash
cd /Users/ssyb/Workspace/web/ai-decision-center
python3 prototype/run_scenarios.py synthesize
python3 prototype/metrics.py --synthetic

# 打开对比页（需本地 HTTP，避免 file:// 限制 fetch）
cd prototype && python3 -m http.server 8765
# 浏览器打开 http://localhost:8765/demo.html
```

## 真模拟流水线（需要 ZEP_API_KEY）

1. 配置 MiroFish：

```bash
# ~/Workspace/web/MiroFish/.env
LLM_API_KEY=...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
ZEP_API_KEY=...   # https://app.getzep.com/
```

2. 启动后端（改过 MiroFish 代码后需重启）：

```bash
cd ~/Workspace/web/MiroFish
# 若 5001 被占用：lsof -ti:5001 | xargs kill -9
pnpm run backend
```

3. 构建共享世界并跑三方案：

```bash
cd ~/Workspace/web/ai-decision-center
python3 prototype/build_shared_world.py
# 记下输出的 simulation_id，然后：
python3 prototype/run_scenarios.py export --simulation-id sim_xxxx
python3 prototype/run_scenarios.py run-all --base-simulation-id sim_xxxx
python3 prototype/metrics.py
cd prototype && python3 -m http.server 8765
```

### 已修复的卡死问题（2026-07）

根因：Twitter 模拟轮次结束后默认进入「采访等待模式」，`run-all` 一直等 `completed` 导致假死。

修复：
- MiroFish `/api/simulation/start` 支持 `no_wait: true`
- `run_scenarios.py` 默认传 `no_wait`，并检测 `env_status=alive` / 无进展超时后自动 `close-env`
- Twitter 脚本写入 `twitter/actions.jsonl` + `run_state` 进度心跳
- Demo 默认 `max_rounds` 降为 **10**

## 三方案

| ID | 名称 | 干预 |
|----|------|------|
| A_hard | 强硬发布 | 官方公告 + 罚则细节 |
| B_soft | 柔性发布 | 试点 + 换购补贴 + FAQ |
| Baseline | 不正式发布 | 仅市民传言帖 |

## 验收判据

`metrics.py` 自动检查：

- 传播规模可区分
- 强硬方案反对占比 ≥ 柔性方案（允许 2% 误差）
- Baseline 互动弱于两方案
- 级联深度存在差异

结果写入 `outputs/acceptance.json` 与对比页「验收判据」卡片。

## 与 MVP 的关系

- `run_scenarios.py` 的 initial_posts patch → 未来干预 DSL
- `metrics.py` → 决策层指标模块
- 验证通过后再执行 monorepo vendor 的 MVP 计划
