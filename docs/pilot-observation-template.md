# SandOwl 原生 Pilot Observation Template

状态：每个研究员 / Reviewer session 单独填写

## 1. Session Metadata

- Session ID：
- 日期与时区：
- 参与者角色与工作环境：
- 是否符合第一目标用户假设：是 / 部分 / 否
- 任务：中文只读案例 / 自带问题 / Reviewer
- 使用的 Research Project：
- 使用的 Simulation Run / Report：
- 主持人：

## 2. Outcome

| 指标 | 结果 |
| --- | --- |
| 无数据库、脚本或 API 操作完成 | 是 / 否 |
| 无手工提供 UUID 完成 | 是 / 否 |
| 找到或生成单次运行报告 | 是 / 否 |
| 正确区分现实 Evidence 与合成起始情境 | 是 / 否 / 部分 |
| 正确解释 Observation | 是 / 否 / 部分 |
| Reviewer 恢复冻结来源 | 是 / 否 / 部分 |
| 未做预测、因果、总体或最佳方案误读 | 是 / 否 / 部分 |
| 出现明确重复使用意愿 | 是 / 否 / 不确定 |

任务未完成时的最后可用状态：

## 3. Time to First Reviewed Report

| 阶段 | 开始 | 结束 | 用时 | 备注 |
| --- | --- | --- | --- | --- |
| 明确研究问题 |  |  |  |  |
| Evidence 选择与确认 |  |  |  |  |
| WorldSnapshot / Graph |  |  |  |  |
| Research Project |  |  |  |  |
| Cohort / Simulation Run |  |  |  |  |
| 事件与计数核对 |  |  |  |  |
| 报告与引用复核 |  |  |  |  |
| Reviewer 来源恢复 |  |  |  |  |

总用时：

## 4. Friction Log

| 时间 | 当前页面 / 对象 | 参与者目标 | 实际行为与原话 | 等待秒数 | 是否需要提示 | 最小提示 | 严重度 |
| --- | --- | --- | --- | ---: | --- | --- | --- |
|  |  |  |  |  |  |  | blocker / major / minor |

提示总次数：  
错误入口次数：  
返回次数：  
手工寻找或抄录 ID 次数：

## 5. Boundary Comprehension

| 问题 | 参与者原话 | 正确 / 部分 / 错误 |
| --- | --- | --- |
| 什么是现实 Evidence？ |  |  |
| 什么是合成起始情境？ |  |  |
| Observation 记录了什么？ |  |  |
| 起始帖子与生成帖子有什么不同？ |  |  |
| Persona 是否代表真实人群？ |  |  |
| 单 seed 是否代表稳定结论？ |  |  |
| Analysis 可以解释到哪里？ |  |  |
| 报告能否预测现实或选择最佳方案？ |  |  |

## 6. Provenance Recovery

| 目标 | 是否从 UI 找到 | 用时 | 路径 / 阻塞 |
| --- | --- | ---: | --- |
| WorldSnapshot 与 hash |  |  |  |
| 原始媒体来源 |  |  |  |
| Research Project 与 hash |  |  |  |
| Cohort 人数与身份 |  |  |  |
| Simulation Run 配置与 hash |  |  |  |
| 类型化事件记录 |  |  |  |
| 单次运行报告与 hash |  |  |  |
| ReportAgent 草稿与冻结引用 |  |  |  |

## 7. Interpretation Errors

- [ ] 把媒体副本当作 SandOwl 已核实的事实
- [ ] 把合成起始内容当作现实声明
- [ ] 把 Persona 当作真人或总体样本
- [ ] 把场景起始帖当作 Persona 生成内容
- [ ] 把事件计数当作参与度或现实效果
- [ ] 把单 seed 当作稳定结论
- [ ] 把 Analysis 当作因果解释
- [ ] 把报告当作预测或最佳方案推荐

其他误读与触发它的界面文案：

## 8. Reuse Intent

- 参与者愿意再次使用吗？为什么？
- 下一项问题是什么？
- 他愿意邀请谁作为 Reviewer？
- 哪个环节若不改善会阻止再次使用？
- 他当前会用什么替代方法？

## 9. Observer Assessment

主要失败类别只能选择一个：目标用户不匹配 / Job 不成立 / 导航与工作流 / 报告不可理解 / Simulation 价值不足 / 数据或费用 / Runtime。

最小可验证修复：

明确不应因此扩大的系统边界：

## 10. Pilot Gate Roll-up

- 本 session 是否满足完成条件：是 / 否
- 产品价值信号：强 / 弱 / 无
- 是否允许进入下一名参与者：是 / 修复后再继续 / 停止
- 需要进入产品 backlog 的证据化问题：
