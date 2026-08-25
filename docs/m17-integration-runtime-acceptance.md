# M17 整合能力真实运行验收

日期：2026-08-25（Asia/Shanghai）

结论：**ENGINEERING PASS — REAL RUNTIME SAMPLES — INDEPENDENT ZERO-PROMPT UI AGENT PASS**

## 验收边界

- 所有资源均由开发者或独立 UI 验收代理通过 SandOwl 页面显式创建或重试；
- 每类模型任务只使用一个冻结 Persona，控制真实 provider 调用规模；
- 失败 attempt 保持不可变，没有删除、覆盖或改写成成功；
- 第二轮独立验收只操作产品页面，不读取源码、不直接调用应用 API 或数据库；
- 本记录不是外部真人研究、现实预测或 Owner 本人试用结论。

## 独立零提示 UI 修复复验

首次独立页面验收发现 Web 多工具调用、Trial Archive retry 哈希、Persona 引用规范化、无图快照创建 Project、Web screenshot 卷权限和移动端遮挡问题。修复部署后，独立代理于同日从 `#/overview` 重新操作完整主链，结论为通过。

- WorldModel `c6d33f46-9ce6-4f94-be3b-388c200bd41d`、Snapshot `837c27f8-019b-4355-8223-d356df5f275b`；
- Project 页面可直接为无图快照提交语义提取，Graph `9575ec2d-a08f-4957-9a39-20209e78483e` 成功后自动选中；
- Research Project `97def132-44a5-4b71-8945-35759d855a62`、Simulation Run `7bd2a17b-5e83-4103-82fa-7a90ed941b4e` 均通过页面创建并成功完成；
- 新 Persona 访谈成功，页面显示两条冻结运行引用；
- 新 Web Evaluation `229cea33-cec6-471f-bf8a-2c3be5126397`：1 / 1 Trial 成功、3 页、30 条引用，三张截图均可读取；
- Trial Archive 正常加载并完成新 Web Trial integrity verification；
- Batch Registry `9543513a-623b-4826-a950-bdbf968bdd73`：4 个父运行、6 个 Trial、6 成功、0 失败，Web 成员深链返回正确父运行；
- 1440、768、390 三档关键页面均无横向溢出；390 宽度下八个评测筛选按钮全部可见，产品导航不再遮挡控件；
- 总览 3D、平面热力、传播链切换后进入热点议题未再出现 Canvas 白屏，最终控制台无 error / warning。

非阻断残留：异步 Survey、Web、Chat 完成后，目录偶尔短暂保留 queued，手动刷新后恢复正确终态；评测 Worker 刚启动时 readiness 约需数秒完成真实探测。

## 原生媒体采集

- 页面新增并启用官方 NASA RSS 来源；
- `NASA Recent Content` 首轮成功发现 10 篇、插入 10 篇、已有 0 篇；
- 成功运行绑定 source `cf698c27-9f2e-4915-ac4d-4e750f605c69`、run `9017e559-eff2-4dcf-9722-df341ad861e4`；
- Docker Desktop 把公网域名解析到 `198.18.0.0/15` 合成代理地址，原 SSRF 防护因此拒绝真实外网。实现新增默认关闭、只允许该窄网段的显式兼容开关，localhost、私网与其他保留网段继续拒绝；
- 首轮后的标准 HTTP 304 曾被误记为失败。传输层现把 304 投影为成功、0 篇变化的有界批次。
- 修复后的定时条件请求于 2026-08-25 10:15 成功落库：0 篇发现、0 篇插入、0 篇已有；此前连接失败与误报的 `no_content` 告警均自动解除，页面活动告警归零。

## 最小冻结 Cohort

- Cohort：`M17 最小真实任务验收 · 1 Persona`；
- ID：`39cf5d82-93b9-4daf-aea2-9d2c11a722d2`；
- SHA-256：`98e9ec017c2b86e08ac45bd9d5298e7d76b2fbe82830d6f8f269f21d97dbedbe`；
- 成员：Tomas Horvat，冻结顺序 0。

## 固定 Chat Evaluation

- Evaluation ID：`21f4f59f-3376-4848-845b-871c16948355`；
- Evaluation SHA-256：`152f1730b2586ff8ffb8e8e210c63687a0c1fe05a83e126b6488d23db028ed12`；
- 结果：1 / 1 Trial 成功，8 条真实 transcript 消息；
- ATIF-v1.7 trajectory、Persona self-report 和 verifier 枚举均在页面恢复；
- 固定 Acme Support 样例出现上下文循环，Persona 评分 1 / 10；这是被测样例结果，不是 SandOwl 运行失败。

## 固定 Web Evaluation

- attempt 1：外部 JSON 数组被严格 Python tuple 契约拒绝；
- attempt 2：Worker 未纳入 Web retry lineage，内容地址复算失败；
- attempt 3：执行器按每页 20 条预留位置，实际每页 10 条，导致引用位置不连续；
- attempt 4 成功，前三次失败均保留；
- 成功 Evaluation ID：`ec4931ce-0600-4de4-93b2-0b2add4ab7a7`；
- Evaluation SHA-256：`a2659405a52bfd4ac4fae9c31e8eee4a61571632e9b3b22b2777c1997a27cda9`；
- 结果：3 个真实页面、30 条连续引用、3 张截图；
- Trace SHA-256：`ad9ad17bf56468b9dc3ed1ee809c0aef94f69922de1b3c08883b2887f300e137`；
- Result SHA-256：`9f94eb08963f201ce41276ddf4fb4c62257da3b15fb5f7061c43972f97212924`。

## 固定 Linux Evaluation

- Evaluation ID：`493ac928-e347-4886-b27a-91e592317e0f`；
- Evaluation SHA-256：`75e852676783834d0a8753a9ca9ae8717596eb0cdc6a2840259c959d4475a3e3`；
- 结果：1 / 1 Trial 成功，`cleaned_list.csv` 3 行，verifier passed；
- Artifact SHA-256：`f6e4d9848194ce6abd845326b4bde4acff1d7af2b38e204d0c0ab9ec55de4c1d`；
- CSV、submission、feedback 与 verifier 四个允许清单产物均可从页面打开。

## Batch Registry

- 标题：`M17 全类型真实成功父运行登记`；
- Registry ID：`99531aa0-6d21-4cae-b162-a77263b990e4`；
- Registry SHA-256：`c49eb676026ced28858b235a4a8cf4ef727ffd837b6da6806c682e1723a63d01`；
- 成员：Linux、Web、Chat、Research Survey 四个成功父运行；
- 观测：4 个父运行、8 个 Trial、8 成功、0 失败。

## Project-bound Web Harbor

- 原失败 attempt 1 保留；
- attempt 2 成功；Job ID `96c05c16-5605-4723-a45f-69b17ea9c169`；
- Job SHA-256：`392b5ce1a5b24d2b004d3756cca72cd1e091aac4ed0540c3079cbce001a93194`；
- Trajectory SHA-256：`d4aeb87b0a27fb936b58fa929f8ce775b0c0aa99c209c36a142d969171f1f5d2`；
- Artifact SHA-256：`cf2ad58984d681f206d9b1475b78643dc19ccf448cdc5d652a052ed0908b8321`；
- Verifier SHA-256：`66b4376cc32462a38928e129bfc3e506e62b461f4e4c5ef5d37c8d437ee852ab`；
- Reward：0；该值来自任务 verifier，不评价 Simulation Run 现实有效性。

## 验证

- Backend：324 passed，21 skipped；
- OASIS Worker：92 passed，2 skipped，另一个真实 OASIS/SQLite 测试因沙箱共享内存限制失败后在沙箱外单独通过；
- 独立 PostgreSQL 迁移、触发器与 repository 集成：21 passed；
- Frontend：331 passed；typecheck 与 production build 通过；
- 原生采集定向测试：7 passed；
- Web Worker 与 Persona Interview 新增有界纠正回归测试并通过；
- Ruff 与格式检查：通过；
- Compose 配置：通过。
- 页面控制台 error / warning：0。
