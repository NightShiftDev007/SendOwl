# SandOwl 原生 Pilot Index

当前状态：M16 工程纵向验收及开发者页面自查已完成。M11–M15 的新主链、ReportAgent/Interaction、Persona 访谈、Survey、Rootless Harbor Evaluation 及失败重试均已通过页面真实运行；Owner 选择不执行 Session 004，因此仍不能记为真实用户验证通过。

## 当前材料

1. [`pilot-participant-guide.md`](pilot-participant-guide.md)：原生单次运行任务与主持规则；
2. [`pilot-data-authorization-checklist.md`](pilot-data-authorization-checklist.md)：自带问题前的数据、模型和费用授权；
3. [`pilot-observation-template.md`](pilot-observation-template.md)：完成率、分段时间、理解、摩擦和来源恢复记录；
4. [`pilot-session-002-native-chinese-readonly.md`](pilot-session-002-native-chinese-readonly.md)：M9 中文原生链只读 dry run；
5. [`pilot-session-004-owner-m16-zero-prompt-retest.md`](pilot-session-004-owner-m16-zero-prompt-retest.md)：Owner 选择不执行的 M16 中文零提示复测记录；
6. [`m16-developer-ui-self-check.md`](m16-developer-ui-self-check.md)：开发者通过页面完成的 M16 只读自查，不替代真人 Pilot；
7. [`chinese-guided-case-shared-power-bank.md`](chinese-guided-case-shared-power-bank.md)：中文案例的现实证据、合成边界和原生资源；
8. [`pilot-session-001-owner-guided-case.md`](pilot-session-001-owner-guided-case.md)：历史 Session 001，不追溯改写；
9. [`pilot-internal-dry-run-report.md`](pilot-internal-dry-run-report.md)：历史 ADC/DecisionReport dry run，只用于解释旧发现。

## Current Gate

判定：**ENGINEERING PASS — READY FOR OWNER ZERO-PROMPT RETEST — NOT YET HUMAN-VALIDATED**

- 原生阶段顺序已与真实资源链对齐；
- Report 可直接恢复精确 WorldSnapshot 和原始媒体来源；
- ReportAgent 与 Agent Interaction 的原始引用默认折叠，中文结论先于技术审计数据；
- Project、Cohort、Run、Report 与引用报告身份可在折叠审计区完整恢复；
- Project 同时提供冻结证据、人群准备和模拟运行入口；
- 不需要 Decision Thread、Scenario baseline、alternatives 或 DecisionReport V2；
- M16 开发者验收已真实创建 v3 Project、Run、Report、Interaction、Survey 与 Harbor Job，并验证失败 attempt 保留和成功 retry；这些记录不能替代真人 Pilot。

如果后续仍需要真人验证，应由 Owner 或目标用户重新开始一次零提示任务 A；开发者自查记录不得转换或补写为真人结果。
