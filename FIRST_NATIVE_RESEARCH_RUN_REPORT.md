# SandOwl 首条原生 Research Run 验收记录

日期：2026-08-17  
案例：原生中文案例 — 星桥充电单次回应观察

## 验收结论

首条不依赖 ADC 多方案语义的 SandOwl 原生链路已真实运行并封存：

```text
AgendaScope Evidence / WorldSnapshot
→ Research Project
→ MatrAIx Cohort
→ one simulation requirement
→ one OASIS Simulation Run
→ sealed single-run report
→ ReportAgent 引证报告
→ Agent Interaction
```

本次没有创建 Decision Thread、Scenario baseline、alternatives、paired comparison 或 DecisionReport V1/V2。

## 冻结资源

| 资源 | UUID / SHA-256 |
| --- | --- |
| WorldModel | `3d493c23-3603-4ec9-8096-d8af17d98b21` |
| WorldSnapshot | `b1353579-a59a-46c7-84cf-9b5dcc6986ee` |
| WorldSnapshot SHA-256 | `83fd49ca7808eb02e7cb62689ef2b676be149457057fc49851f837c2d625880c` |
| Cohort | `415caf8a-1ce0-4d75-a699-7d5a402fcb79` |
| Cohort SHA-256 | `8dbdcb40ab68b0f4fdf610768ae6f3de9156e6851d32027b2126bbbe8f4b69fc` |
| Research Project | `748de69e-3192-496d-9b2c-6ca72ac85575` |
| Project SHA-256 | `d113987abe205b79b0506967bf2d43a351e05090370fad2445678e7952208050` |
| Simulation Run | `32f4e1ed-985e-4786-b965-4e37436bda9f` |
| Run spec SHA-256 | `34d730320316fc79c836365c4d659f9efd08fcfeeb1bc8fcaaf8a08533d73a11` |
| Artifact SHA-256 | `b0ff5cf76a00b87f7764912bcc85d229a3d92349cf70c29b58faa56662311264` |
| Single-run report | `fd81c881-345d-4bab-9ca2-97b82affd1a2` |
| Report SHA-256 | `e2c36ca8d99fb7e95799093fad5e28a2d504039065f043e49334f6cf5d5dfdec` |
| ReportAgent scope | `9e7968a6-862a-42d8-af79-f0684e38d828` |
| ReportAgent draft | `aac8ac30-5085-4b7a-acc2-a629043731fe` |
| ReportAgent draft SHA-256 | `430bd2d3dd439027ba556c8a66f1678a7e705cf6ed654281af43dbf29baddb61` |
| Agent Interaction | `c702c54f-3d6c-4f11-a287-e7f8152fd222` |
| Interaction SHA-256 | `4f81b952af8e077b392ae5a66d06c6bc31c3e18fda97060db01250e1406b5702` |
| Interaction answer SHA-256 | `412f7abf0e1868468407798d6464e89b6846914566acec6296645a2d87fd3613` |

## 运行配置

- 模型：`qwen3.7-plus`
- 语义配置 SHA-256：`01e176e98d64a53059954cddbf53996c0c54ce40c5ed9784ce7b4fbb75e7c901`
- Prompt schema：`matraix-semantic-profile/v1`
- Persona：5
- Seed：`20260817`
- 轮数：1
- 每轮时间：60 分钟
- 状态：`succeeded`

ReportAgent 使用独立的 report domain 配置，输出预算为 2048 tokens；Semantic Simulation 仍保持 512 tokens。成功草稿的 config SHA-256 为 `655f14e27e0c41cd33fb39c3bc736aae1f464ac0a51424d506b10e414073a453`，输入 SHA-256 为 `6b79ffa0a06a156d7ba882a7e558a4b3e15c3bc5abb0b79a236133b2971553a1`。

## 合成观察

共封存 6 个类型化事件：

- scenario 起始帖子：1
- Persona 生成帖子：0
- Persona 评论：1
- Persona reaction：3，均为 `like_post`
- Persona `do_nothing`：1

唯一评论认为 48 小时处理窗口偏长，并追问柜机记录的具体技术指标与异常订单自动检测能力。该文本只属于本次合成 Persona 动作，不代表现实用户意见、市场结论或经营建议。

## 产品验收

- 原生报告目录从 0 增加为 1。
- 原生深链可以直接打开对应 Project / Simulation Run 报告。
- 页面完整显示证据边界、研究上下文、模拟配置、观测计数、事件记录、限制和来源完整性。
- 页面读取不会自动创建 ReportAgent scope 或模型任务。
- ReportAgent 入口明确标记为“调用模型”。
- ReportAgent 已生成五章节中文引证报告《星桥充电单次合成观察报告》，每条引用均绑定到冻结证据中的精确字符区间。
- Agent Interaction 已回答“这次合成运行记录了哪些主要动作？这些记录不能说明什么？”，并附带两条精确引用。
- MatrAIx Evaluation 明确标记为独立评测，不对本次模拟结论打分。
- 浏览器已确认报告标题、成功状态、中文问题、回答和独立评测入口均真实显示。一次部署后的旧资源缓存错误通过版本化重载清除；当前页面加载正常。

验收期间发现并修复：报告页保持打开时，新完成的报告不会随原生深链变化重新读取目录。当前路由变化会重新加载目录，空状态也提供显式刷新按钮。

## 失败保留与重试

ReportAgent 在成功前暴露了 JSON 截断、引用重复、引用超过 500 字符和引用无法在证据中定位等失败。所有失败草稿均保持不可变，没有覆盖或伪装为成功：

- 相同输入的重试通过 `retry_of_draft_id`、`retry_of_input_sha256` 和 `attempt_number` 记录谱系，最多 5 次。
- 输出相关配置变化会产生新的 input/config SHA-256 和新的根草稿，不冒充同一次输入的重试。
- worker 只接受 report-domain heartbeat；不会再把 ReportAgent 工作错误路由给 semantic worker。
- 引用改为从冻结证据预先生成的编号候选窗口中选择，worker 再填充原文和偏移并校验。

## 未执行范围

未执行 MatrAIx 独立 Evaluation。它仍是可选、显式触发的独立评测能力，不属于本条原生 Research Run 的成功条件。页面读取不会自动触发 ReportAgent、Agent Interaction 或 Evaluation。

## M4 兼容退出

原生链验收后核对了旧 ADC 资源的最后写入时间。Decision Thread、DecisionReport、旧报告问答和旧 Persona Interview 在本条原生运行期间均没有新增写入，因此第一批兼容退出已执行：

- 对应新建和追加 API 返回 `410 Gone`；
- 历史目录、详情、Markdown 下载、UUID、SHA-256 和 Revision 顺序继续可读；
- 历史页面移除新建、生成、追问和访谈控件，并明确标记为只读归档；
- 后续已完成 Survey 解耦：新 Survey 绑定 Research Project、成功的单次 Simulation Run 与该 Run 的冻结 Cohort，不含 baseline/alternative。Scenario、Semantic Experiment 与旧 Scenario Preference Survey 的写入口现已关闭，历史数据继续只读保留。
