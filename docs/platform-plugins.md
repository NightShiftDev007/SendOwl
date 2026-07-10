# 真·多平台插件计划

> 状态：规划稿（未开工）  
> 关联：[design.md](./design.md) §4.4 干预 DSL / §5 两档引擎 / §6 引擎契约 / §7 场景模板  
> 日期：2026-07-10

---

## 1. 背景与问题

当前推演渠道只有 OASIS 双轨硬编码：

| 内部 id | UI 名 | 形态 |
|---------|-------|------|
| `twitter` | Info Plaza | 短帖广场 |
| `reddit` | Topic Community | 话题社区 |

产品侧需要扩展到抖音、快手、微信公众号、微信视频号、小红书等。**不能**只做改名映射：短视频 / 图文社区 / 订阅号的内容单元与动作空间不同。

`design.md` 里的「引擎接口」解决的是 **LLM Agent 内核 vs 统计传播内核** 可替换，**不是**社媒平台可插拔。本计划单独定义 **Platform Plugin** 层。

---

## 2. 目标

1. 场景 / 决策可声明 `enabled_platforms: string[]`。
2. 新增平台 = 实现并注册插件，**不改** ScenarioRunner / 指标聚合壳 / 五步向导骨架。
3. 先把现有 twitter / reddit 收成两个插件（行为不变），再扩新族。

非目标（本阶段不做）：

- 假多平台（只改展示名、动作与推荐仍是双轨）。
- 一次实现全部国内 App。
- 改 OASIS 上游源码（优先自研 runtime / 包一层）。

---

## 3. 形态分型（比「再加 N 个名字」优先）

| 形态族 `family` | 候选平台 | 内容单元 | 核心动作 | 底座策略 |
|-----------------|----------|----------|----------|----------|
| `plaza` | 微博/X、部分视频号文案流 | 短文 | 发/转/评/赞/关 | 现有 twitter 轨 → 插件 |
| `community` | 小红书、贴吧式 | 图文帖+评论树 | 发/评/赞/藏/关 | 现有 reddit 轨 → 插件 |
| `short_video` | 抖音、快手、视频号 | 视频+话题 | 发/播/完播/赞/评/转/关 | **自研轻量 runtime** |
| `subscription` | 微信公众号 | 长文推送 | 发文/阅读/在看/转发 | **自研**；偏官方发布源 |

推荐落地顺序：**plaza + community 收口 → 小红书（community 扩展）→ 抖音（short_video）→ 公众号（subscription）**；快手/视频号复用短视频族。

---

## 4. 插件接口（草案）

```text
PlatformPlugin {
  id: str                         # douyin | xhs | wechat_oa | twitter | reddit
  display_name: str
  family: plaza | community | short_video | subscription

  # 人设
  serialize_profiles(agents) → list[path]
  # 动作
  action_set: list[str]
  to_taxonomy(action_type) → post|repost|comment|like|follow|view|share|…

  # 生命周期
  prepare(sim_dir, config, agents) -> None
  start(sim_dir, config) -> Handle
  poll(handle) -> { round, running, completed, actions_count }
  stop(handle) -> None

  # 产物约定（强制）
  actions_path = {sim_dir}/{id}/actions.jsonl
  db_path      = {sim_dir}/{id}_simulation.db   # 或插件声明的等价存储

  # 可选
  ranking_params_schema / apply()   # 现有 recency 等权重未接线：真接或从 UI 移除
  interview(agent_id, question)     # IPC
}
```

- 注册表：`PLATFORM_REGISTRY[id] = plugin`
- 编排层只认平台 id 列表，禁止 `if platform == "twitter"` 散落业务代码

与现有引擎契约的关系：

```text
输入：世界切片 + Agent 人口 + 网络 + 干预（含 channel）
  → ScenarioRunner
  → 对每个 enabled platform：PlatformPlugin.start(...)
输出：各平台 actions.jsonl + DB + 统一 status.platforms[id]
```

---

## 5. 架构关系

```text
产品层：五步 UI / 时间线 lane / 采访 tab / 干预 DSL(channel)
    ↓
编排层：ScenarioRunner → SimulationRunner → PlatformRegistry
    ↓
平台插件：plaza_twitter | community_reddit | short_video_* | subscription_*
    ↓
推演内核：OASIS/LLM（现有） | 自研 short_video/subscription runtime | 统计传播（远期）
```

说明：平台插件与「两档引擎（LLM vs 统计）」正交；统计层远期按渠道消费同一套 taxonomy 后的 actions。

---

## 6. 分阶段路线

### P0 — 收口现有双平台（优先 spike）

**做什么**

- 抽出 `PlatformPlugin` + `PLATFORM_REGISTRY`
- `twitter` / `reddit` 各一个实现，包装现有 `run_*_simulation` / parallel 逻辑
- `run_state` / API 状态改为 `platforms: { [id]: { round, running, completed, actions_count } }`
- 前端 Step2/3/4 改为按 `enabled_platforms` 动态渲染（默认仍开两个）
- 统一产物路径与 `action_taxonomy`

**验收**

- 端到端行为与现网一致（双平台并行、时间线左右、采访）
- 业务代码无 `enable_twitter` / `enable_reddit` 布尔分叉（可保留兼容别名一层）

**关键改动面（现状锚点）**

- `backend/app/engine/simulation_manager.py` / `simulation_runner.py` / `scenario_runner.py`
- `backend/scripts/run_parallel_simulation.py` 及单平台脚本
- `backend/app/api/simulation.py`
- `frontend/src/components/Step2EnvSetup.vue` / `Step3Simulation.vue` / `Step4Report.vue`
- `frontend/src/api/simulation.js`

### P1 — 渠道化干预 + 场景默认平台集

- 干预 DSL：`{ content, actor, channel, time, intensity }`（对齐 design §4.4）
- 场景模板声明默认 `enabled_platforms`
- 时间线 UI：由「twitter 左 / reddit 右」改为可配置 **lane**（最多 3 列）或「单列 + 平台色标」

### P2 — 第一类新平台：小红书（community 族）

- Fork/扩展 community 插件：字段、动作文案、UI 标签贴近小红书
- 再逐步替换推荐/互动规则（避免长期「reddit 换皮」）

### P3 — 短视频族（抖音 → 快手 / 视频号）

- 内容模型：`video`（时长、完播、话题）
- 动作：`publish_video` / `view` / `complete_view` / `like` / `comment` / `share`
- **不依赖 OASIS 上游**；自研轻量状态机 + LLM 决策

### P4 — 订阅号族（微信公众号）

- 主路径：关注集 + 阅读/在看 + 向其他渠道转发事件
- 定位：官方发布源插件，可向 plaza/community/short_video 注入跨渠道内容

### P5 — 对接统计传播层（design 方案 B）

- 用各渠道 actions 校准传播参数
- 大规模触达走统计层；LLM 只跑关键节点

---

## 7. 前端约定（多平台后）

| 区域 | 现状 | 目标 |
|------|------|------|
| Step2 平台卡 | 写死两张 | `v-for="p in enabled_platforms"` |
| Step3 进度 | `twitter_*` / `reddit_*` | `platforms[id].*` |
| Step3 时间线 | 按 platform 类名左右 | `lane` 配置或色标单列 |
| Step4 采访 | twitter/reddit tab | 按启用平台生成 tab |
| 推荐权重 UI | 有字段、脚本未读 | P0/P1：接线或隐藏，禁止假参数 |

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| 低估短视频工程量 | P3 单独立项；P0–P2 不阻塞 |
| 假多平台伤害可信度 | 验收以动作/产物/指标为准，不只看名字 |
| Token 成本随平台线性涨 | 配合代表性 Agent / 统计层；场景默认少开平台 |
| OASIS 改不动 | 新族自研 runtime；旧族继续包 OASIS |
| 配置权重未接线 | 插件化时显式处理，不继续展示空参 |

---

## 9. 待拍板

1. **第一批真做清单**：是否确认 `P0 → 小红书 → 抖音`，公众号/快手/视频号跟族复用？
2. **短视频是否进近期里程碑**：若演示以帖文舆情为主，可暂缓 P3。
3. **时间线形态**：3 列 lane vs 单列色标？
4. **P0 是否立刻开 spike**：先接口 + 双平台收口，不上新 App。

---

## 10. 建议的下一步（执行顺序）

1. 评审本计划，确认 §9 待拍板。
2. 开 **P0 spike**：`backend/app/engine/platforms/`（`base.py` + `twitter.py` + `reddit.py` + `registry.py`），跑通一次双平台 prepare/start。
3. 状态与前端改为列表驱动后，再开 P2 小红书。

---

## 11. 与 design.md 的衔接

- 本文件细化 **社媒渠道插件**；不替代 §5 两档引擎、§7 场景模板。
- 场景模板后续增加字段：`default_platforms` / `allowed_platform_families`。
- 干预 DSL 的 `channel` 以本文件 §4 / §6.P1 为准落地。
