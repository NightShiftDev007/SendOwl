# M16 开发者页面自查

日期：2026-08-20，响应式复验与加固完成于 2026-08-24（Asia/Shanghai）
执行者：Codex，开发侧只读验收  
案例：`UI 巡检 · 共享充电宝说明观察`  
结论：**ENGINEERING PASS — NOT HUMAN-VALIDATED**

## Boundary

- 从 SandOwl 页面进入并操作，不直接调用业务 API；
- 使用已封存案例，不创建新的 Project、Run、报告、访谈或 Evaluation，不触发模型费用；
- 本记录是开发者自查，不能替代 Owner 或真实用户的零提示 Pilot。

## Walkthrough

1. 从态势页进入模拟工作台，核对 Project、WorldSnapshot、现实媒体原文、语义图和 AgendaContext；
2. 进入已封存 Run，核对 Seed `20260818`、4 轮、5 人、2 条预置内容、22 条事件和 4 份图记忆；
3. 打开报告，核对读者摘要、现实证据/合成输入边界、逐章引用、Agent Interaction 与 Persona Interview；
4. 从报告进入当前研究评测中心，核对 Survey、Web 和 App 的原生上下文；
5. 展开 App 尝试谱系，核对 attempt 1 失败、attempt 2 成功，以及 trajectory、artifact、verifier 哈希和 reward；
6. 打开试验档案，选择 Survey Trial，复算父任务、Trial、生命周期和答案哈希，再进入所属 Survey 详情；
7. 在 Survey 详情核对 5/5 完成、0 失败以及选中 Persona 的结构化回答。

## Findings And Fixes

- 旧 Run 的冻结限制仍写“三轮上限”，与实际 4 轮和当前 6 轮能力冲突。页面现在明确标注这是旧版文案，当前最多六轮，实际轮数以运行配置为准；引用解释同时区分旧三轮和当前六轮记录。
- Trial Archive 的“打开所属 Trial”链接曾丢失当前 `project_id` / `run_id`。链接现在保留完整研究上下文，并已通过页面进入正确 Survey Trial 复验。
- 已封存 ReportAgent 草稿可能早于后续 Persona Interview，正文会保留生成时的“没有访谈”结论。报告页现在明确说明后续访谈不会回写已封存草稿，避免被误读为当前页面没有访谈。

## Verified Page State

- WorldSnapshot：1 篇冻结媒体，语义图 12 个实体、10 条关系；
- Run：5 Persona，4 轮，2 条预置内容，10 条评论，10 次反应；
- Report：逐章引用可展开，成功 Interaction 显示 6 条依据，成功 Persona Interview 显示 3 条依据；
- Survey：5/5 succeeded，0 failed；
- App Harbor：attempt 1 failed，attempt 2 succeeded；trajectory `009869df55…c16e9bad`，artifact `b70300c539…c3b89471`，verifier `66b4376cc3…7ee852ab`，reward `0`；
- Web Harbor：保留 attempt 1 失败及可重试入口，未在本次只读自查中再次执行。

## Validation

- 先在 1440、1024、768、390、320px 五档宽度检查 22 个页面状态及无效地址恢复页；
- 修复嵌套主地标、缺失一级标题、小触控目标、低对比文字、政策表单窄屏溢出和布局属性动画后，再次复验桌面与 320px 手机宽度；
- 最终每页恰好一个可见 `h1` 和一个 `<main>`，嵌套 `<main>`、整页横向溢出、小于 24px 的有效交互目标和控制台错误均为 0；
- 前端测试：331 passed；
- 前端 typecheck：passed；
- 前端 production build：passed；
- 本地前端容器完成重建并健康启动；
- M16 主链与响应式修复均再次通过页面可见状态复验。

## Remaining Gate

Owner 已选择不执行 Session 004，因此当前仍是工程验收通过、真人零提示验证未执行。后续如需要真人 Pilot，必须新开一次明确的 Owner/用户操作记录，不能把本文件改写成真人结果。
