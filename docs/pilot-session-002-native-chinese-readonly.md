# SandOwl Pilot Session 002 — 原生中文链只读 Dry Run

日期：2026-08-17（Asia/Shanghai）  
执行者：Codex，模拟 Reviewer 走查  
案例：原生中文案例 — 星桥充电单次回应观察  
付费操作：无

## Outcome

本轮只通过 SandOwl UI 读取现有资源，完整恢复了：

```text
WorldSnapshot
→ Research Project
→ Simulation Run
→ 冻结单次运行报告
→ ReportAgent 引用报告
→ Agent Interaction
```

未创建 Project、Cohort、Run、ReportAgent 草稿、Interaction 或 Evaluation。

## 已验证资源

| 资源 | 身份 / 内容地址 |
| --- | --- |
| WorldSnapshot | `b1353579-a59a-46c7-84cf-9b5dcc6986ee` / `83fd49ca…d625880c` |
| Research Project | `748de69e-3192-496d-9b2c-6ca72ac85575` / `d113987a…52208050` |
| Simulation Run | `32f4e1ed-985e-4786-b965-4e37436bda9f` / `34d73032…3d73a11` |
| Single-run Report | `fd81c881-345d-4bab-9ca2-97b82affd1a2` / `e2c36ca8…5d5dfdec` |
| ReportAgent draft | `aac8ac30-5085-4b7a-acc2-a629043731fe` / `430bd2d3…baddb61` |

## Findings 与修复

### RESOLVED P1 — 报告无法恢复冻结来源

报告只显示 WorldSnapshot 短哈希，没有产品内入口。Reviewer 无法从报告确认精确快照或打开原始来源。

修复：证据边界增加“打开冻结证据与原始来源”，使用报告自身封存的 `world_model_id + world_snapshot_id`，不查询或替换为最新版本。

### RESOLVED P1 — 技术引用压过中文报告

ReportAgent 五个章节默认展开最长 500 字符的 JSON 原文，页面视觉层级被审计数据占据，中文分析难以连续阅读。

修复：每节改为“查看 N 条冻结引用原文”的折叠审计区；保留逐字引用、来源标签和字符区间，不删除审计信息。Agent Interaction 使用同一呈现。

### RESOLVED P1 — 阶段顺序与资源依赖不一致

顶部原顺序是 World → Persona → Project，但原生数据链和创建约束是 World → Project → Cohort / Run。

修复：改为媒体证据 → 世界与图谱 → 研究项目 → 模拟人群 → 模拟运行 → 报告与交互。Project 对已有 Cohort 与新建 Cohort 提供不同的显式下一步。

### RESOLVED P1 — 原生资源身份恢复不完整

运行与报告能显示人物数和短哈希，但 Reviewer 不能从同一报告恢复 Project、Cohort、Run 与 Report 的完整 UUID 和内容地址。

修复：来源与完整性章节增加默认折叠的完整资源身份区；ReportAgent 页脚同时展示草稿 UUID 与 SHA-256。普通阅读仍优先显示中文结论。

### RESOLVED DOC BLOCKER — Pilot 脚本仍要求 ADC 多方案任务

旧指南要求 Decision Thread、Scenario、baseline、alternatives 和 DecisionReport V2，与当前产品主链相反。

修复：Participant Guide、Observation Template、Data Authorization 与 Pilot Index 全部改为原生单次 Run 语义；历史 Session 001 与旧 dry run 保持不可变记录。

## 本轮不能证明的内容

- 没有真实参与者，不能记录人类完成时间和复用意愿；
- 没有验证自带问题的数据授权、费用确认或模型运行体验；
- 没有证明合成观察对现实业务具有有效性；
- 没有证明折叠引用能满足所有专业 Reviewer。

## Gate

**PASS FOR OWNER RETEST。** 下一步必须由 Owner 独立完成中文任务 A；本 dry run 不得冒充真实用户验证通过。
