# Second Vertical Slice Execution Report

执行窗口：2026-08-16 11:02:35–11:07:29 UTC（Asia/Shanghai 19:02:35–19:07:29）

最终状态：**核心链路跑通。** 本次创建了全新的 WorldSnapshot、Scenario、Cohort、Semantic Experiment 和 DecisionReport V1/V2；三个 trials 全部成功，17 个 normalized events 已持久化，V2 七章节已在真实 Reports 页面验收。

# Case

案例名称：**电动车品牌劳资争议结束后的回应节奏实验**。

Scenario 主体是虚构品牌 `Northstar Mobility`。两个品牌声明及 baseline 都是 `synthetic demo data`。AgendaScope 中与 Tesla Sweden labor dispute / strike ending 相关的媒体记录只作为现实媒体背景 evidence；本报告不分析或预测真实 Tesla，不裁决媒体说法，也不提供企业回应建议。

# Runtime

| 项目 | 运行身份 |
| --- | --- |
| Backend / database | 本地 SandOwl；PostgreSQL；Alembic `20260816_core_0042 (head)` |
| Worker topology | 独立 `semantic`、`evaluation`、`report` worker；均有新鲜 heartbeat |
| Semantic readiness | `worker_online=true`；`semantic_runtime_ready=true`；无配置冲突 |
| Evaluation readiness | Survey / Chat / Web / Linux 全部 ready |
| Model | `qwen3.7-plus` |
| Semantic config SHA-256 | `4184bdb6cad7eebbb1836ae19f005ab926d93350b4705e5b0140fef79ac58741` |
| Prompt schema | `matraix-semantic-profile/v1` |
| Engine | OASIS `0.2.5` / CAMEL `0.2.78` |

没有使用 semantic-only workaround，没有 migration，没有改 worker topology，也没有创建新的 collector、Persona generator 或 Agent framework。

# Resources

| Resource | ID | Content identity / status |
| --- | --- | --- |
| WorldModel | `0a03bc0b-20c8-40c0-a3ac-8a6c58e0f8e0` | 2026-08-16 11:03:12.939843 UTC 创建 |
| WorldSnapshot | `214a681f-8b9d-4a2f-bce3-b816cdba43e7` | sealed；`a4e9c1407de43afe4f35418c7b083116e5826b200e23a1e634341af1611a7f37` |
| Scenario | `9ce88068-2a82-4239-a2db-15d4c9feacd9` | sealed；`0ebbf02860a9828e8de1945b5db78d1de3322836a1e7c23fa90b137524edeab2` |
| Cohort | `875df354-f2db-4236-86f1-9714670363b9` | sealed；`0d8b8804c752e2b77385b0f6e489b7628fac083647eaa0bfe9d56927fb9c571e` |
| Semantic Experiment | `b37534ab-970c-4ab3-9545-8483337355d0` | succeeded；`098520f7bd9769e79424c7693369ee9f466ea37207c63e626897028e1c77030b` |
| DecisionReport V1 | `ed5a01c8-e5d9-4bde-83ba-757b681df631` | sealed；`377cc61adc5ab9e8c4f7b270c8541132f8a084e474098b2c282ca45da0fceafd` |
| DecisionReport V2 | `d1387633-660e-4519-b315-0e98f11265bf` | sealed；`de0d553188bcccda1f0e6ad777f00f27656456e786e8a48d42c84e0d03970169` |

## Trials

配置为 3 variants × 1 seed × 1 round × 5 personas，seed `20260816`，每轮 60 分钟。

| Variant | Trial ID | Trial SHA-256 | 时间（UTC） | 结果 |
| --- | --- | --- | --- | --- |
| Baseline | `a4c34f75-5438-48df-bd09-33a0eb6a74be` | `7d2c8ccf9e4006ef8094fd99197c7710f6b7d3fc7d78cfff4c62249c142166bc` | 11:03:58.054937–11:04:00.303527 | succeeded |
| Alternative A | `c464b4f0-578a-44c6-be0c-a613426a5b60` | `02688bb143d0ed63376fea45630831ded8c2849379f1c6e73ddfe7e4510bf171` | 11:04:00.305987–11:04:14.073309 | succeeded |
| Alternative B | `e5af01d0-0c56-44ac-ad2f-123535884821` | `28f08ff6caffe131a89c8fd00c80c7e1ca7734b65a7058ef7baff9827691a907` | 11:04:14.076379–11:04:17.511755 | succeeded |

# Evidence

六条文章在创建 WorldModel 前重新通过 AgendaScope media read model 读取。selection-time revision 是并发校验身份；captured text SHA-256 是 sealed snapshot 内冻结正文身份。它们证明 SandOwl 冻结了这些媒体源副本，不表示 SandOwl 已独立核实文章中的全部主张。

| Article ID | Source / published at | URL | Selection revision SHA-256 | Frozen captured SHA-256 |
| --- | --- | --- | --- | --- |
| `0889fa6e-92b9-48d8-a8d7-de5fd1332cfe` | Dagens Nyheter / 2026-08-13 14:51:12 UTC | <https://www.dn.se/sverige/if-metall-avbryter-strejken-mot-tesla/> | `600fd9d8fe2a45ca29638ff5585595968f13bfbdbc4ff88c3e8636d20ce8e7b5` | `62a6c40ec3e963f003de1361e70c3f51d15724889c07a7010c546ac299e09372` |
| `9c552d01-4756-4d30-90ba-3fcebf78a772` | DR Nyheder / 2026-08-13 14:19:29 UTC | <https://www.dr.dk/nyheder/seneste/langvarig-tesla-strejke-i-sverige-slutter-ved-midnat> | `fe48ee68a3390e12c9a989914844570ded1fec28ff7a684b323b5122d0a5eac5` | `568379a33a286664369270ba2b5807181bd5ed5b2be7d90f947f3e3c0e0dbd97` |
| `88b6aed5-ded5-44e2-b983-bfb3ddfb3520` | Aftonbladet / 2026-08-13 13:13:28 UTC | <https://www.aftonbladet.se/nyheter/a/k0BKoL/if-metall-avbryter-strejken-mot-tesla?utm_medium=rss> | `c3b76e478d7fab0dbc9392125cd546a07278c166972e7427821f1a8bb0c5a09c` | `4ba8f32f411a33dacc011fd02abde66d1d0cc9828742f67ebcbb99174963fb7c` |
| `ee6d2868-8898-42c1-8375-3643ce5b91a7` | Politiken / 2026-08-13 18:19:51 UTC | <https://politiken.dk/internationalt/art10946384/Forsker-Afslutning-p%C3%A5-svensk-Tesla-strejke-er-ikke-set-f%C3%B8r> | `0474903aa3f8c65c156ce02d5f6cf831c0d231dff317b5bd62e1ebecea183c30` | `635a5b2b3768698995a978f763d6ae063b8f16beecad4551854984fa7ffe3596` |
| `d6889945-6f2e-485e-af62-5daf008c0643` | De Volkskrant (via GN) / 2026-08-14 06:53:08 UTC | AgendaScope 保存的 Google News RSS URL | `6727e740d1025e5d3be154e7def1015d5439628f0c118b02074f88e741768e19` | `50b77046b26828b24f542ef2df37ce7ce8fcf568274eb33238c356eceb58f8ac` |
| `75950a46-e45e-40df-b3a7-26c3619078ad` | Dagens Nyheter / 2026-08-14 09:50:35 UTC | <https://www.dn.se/debatt/detta-maste-vi-ta-med-oss-efter-teslastrejken/> | `51ecfde9c76a48646132ef1c8fd814bebcfe5bf754ffff447c8254484d16620d` | `8554531e0337c3f7cc7b6cadd15ddc0139a5cf1cf10578a0fe2107c91f70f21e` |

# Synthetic Assumptions

Scenario 中没有把任何 Northstar 内容写入 Evidence：

- Baseline：`synthetic demo data` — `Northstar Mobility` 在本轮不发布新声明。
- Alternative A：`synthetic demo data` — 虚构品牌立即承认虚构争议结束、感谢相关方，并承诺 48 小时内发布后续说明。
- Alternative B：`synthetic demo data` — 虚构品牌表示正在核实并先沟通利益相关方，承诺七天内分阶段更新。

两个 alternative 的 initial post 均在本次唯一 simulation round 的 offset 0 注入。Alternative B 只模拟“现在发布一条承诺七天内更新的声明”，没有模拟七天后的后续传播。

# Persona Cohort

复用冻结 MatrAIx dataset `370c75f4-39d4-498b-922f-944d53df596b`，dataset SHA-256 `e5257c144450b65ffd6022408bdcb38b455539389846fd55d6fa9f716db03e79`。没有生成新 Persona。

成员顺序及 profile hash 与已验证 cohort 完全一致：

1. `1e059897-d1ad-439c-aa1f-ffd3b2da6be9` / source persona `0097` / `199b7e3ba3b653b9dd4fa27a500b4ff675949e5fc4e817ddb97f88fddef384cb`
2. `88a61011-0543-452d-b03d-e33cbc698415` / `0100` / `32e934a7c14546be13dc1986abc8c4857337602fe00e4a0ad3d026c8b476f235`
3. `1f84c65e-bf76-4016-88e4-d6cd89fde9a4` / `0172` / `35d7f955ec5fd8b66a00918c054e6561f3a6ebec8a28216cd90d5f85d6d267a7`
4. `072930b8-c68c-4acf-996b-a655ab34062c` / `0083` / `43c0bde0a4cd77895170827a5501a9e3e85e069e01486d5c85e8e8a411ba4f39`
5. `41b9e8d3-f5e7-4915-afdb-0b916623fe4d` / `0020` / `d8a40bd06513ae8f34e5c0d4147d76e6fa3f4481c3daccd78f88d19b6e5bccca`

这些 Persona 只是冻结 profile 的分析映射，不代表消费者、员工、工会或公众。

# Observation

PostgreSQL 复核得到 17 条 persisted events，三个 trial 的 sequence 均从 1 连续到末项：

| Variant | Total events | Scenario initial posts | Persona comments | Reactions | Do nothing |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 5 | 0 | 0 | 0 | 5 |
| Alternative A | 6 | 1 | 2 | 3 | 0 |
| Alternative B | 6 | 1 | 3 | 2 | 0 |

这里的“评论”“reaction”“do nothing”只描述本次 OASIS 记录的 synthetic actions。`observed_at_raw` 是 OASIS simulation clock，`recorded_at` 是 SandOwl 持久化时间，不能合并成现实时间线。

# Comparison

同 seed `20260816` 的配对计数如下；每个 variant 只有 `n=1`：

| Metric | Baseline | Alternative A | Alternative B | A − baseline | B − baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| observed action count | 5 | 6 | 6 | +1 | +1 |
| authored content count | 0 | 2 | 3 | +2 | +3 |
| reaction count | 0 | 3 | 2 | +3 | +2 |
| do nothing count | 5 | 0 | 0 | −5 | −5 |

两个 alternative 的 total event 均比 baseline 多 1，其中该 1 条就是各自的 scenario initial post；因此不能把 total event 的 `+1` 解释成参与度提升。其余差异也只是在单次合成运行中观察到的计数，不建立因果、不预测未来、不选“最佳方案”。

# DecisionReport V2

V2 已封存七个 typed sections：Evidence、Assumptions、Experiment、Observation、Comparison、Analysis、Limitations。Evidence 引用新 WorldSnapshot 及六条 frozen content hashes；Assumptions 保留 `synthetic demo data`；Experiment 固定 model/config/prompt/seed/cohort；Observation 引用三组 event endpoint 和 events SHA-256；Analysis 只做口径解释；Limitations 明确小样本、synthetic inputs、模型依赖、simulation/evidence/clock boundary 及 no-prediction/no-recommendation。

重复调用 V2 生成接口返回相同 Report ID 和 report SHA-256，验证了版本内幂等性。

# Browser Validation

真实打开：`http://127.0.0.1:3200/#/reports?experiment_id=b37534ab-970c-4ab3-9545-8483337355d0`。

- 七个 section heading 全部显示且顺序正确；
- Evidence 显示 WorldSnapshot `214a681f-8b9d-4a2f-bce3-b816cdba43e7`、snapshot hash 和六条 source content hash；
- Assumptions 页面中 `synthetic demo data` 标签可见；
- Observation 显示三条可访问的 trial event links；
- Comparison 显示 baseline 与两个 alternatives 的同 seed 计数；
- Limitations 显示 sample size、synthetic inputs、model dependency 和 simulation boundary；
- 页面无可见 error alert；浏览器开发日志为 `[]`。

# Validation

| Layer | Result | Evidence |
| --- | --- | --- |
| AgendaScope | 通过 | 六条 article detail 在执行前重新读取，revision guard 全部有效 |
| WorldSnapshot | 通过 | 新 snapshot 6 条 frozen evidence；`sealed_at=created_at`；snapshot hash 可复核 |
| Scenario | 通过 | 新 scenario sealed；baseline + 2 alternatives；synthetic 内容未进入 Evidence |
| Persona | 通过 | 新 cohort sealed；同 dataset、同五个 profile hashes、同顺序；未生成 Persona |
| Simulation | 通过 | 新 experiment input sealed；3/3 trials succeeded；17 events 持久化且 sequence 连续 |
| Report | 通过 | V1/V2 均 sealed；V2 七章节、hash、API 幂等性和浏览器显示通过 |
| Traceability | 通过 | snapshot → scenario → cohort → experiment → trials/events → report IDs 与 hashes 均可查询 |

# Problems

1. **Observation UI 的 post 口径容易误读。** V2 structured payload 正确保存 `scenario_initial_posts=1`，但 Observation 的摘要文字/UI 对 alternatives 显示 `posts 0`，这里实际展示的是 `generated_posts`。因此摘要中的 `0 posts + 2/3 comments + 3/2 reactions` 与 6 个 total events 表面上少 1；缺少的就是 scenario initial post。底层 events 与结构化计数正确，展示标签需要后续澄清。
2. **“新 Cohort”与“同 cohort hash”不能同时满足。** 当前 cohort hash 包含 title。使用原 title + 同成员会被内容寻址幂等地返回旧 cohort；为了满足本次必须创建新资源，使用了新 title，因此 cohort hash 必然变化。dataset hash、五个 profile hashes 与顺序保持不变。
3. **单 round 不覆盖七天后的阶段更新。** Alternative B 只观察“承诺七天内更新”的初始声明；本实验没有跨七天运行，也没有后续声明事件。
4. **Provider seed 不是完全复现保证。** `qwen3.7-plus` provider 行为仍可能非确定；seed 只用于本次矩阵身份和配对。
5. **UI 主要展示 report hash，未直接显示 Report UUID。** UUID 可由 API 和本执行记录追溯，但 Reports 主视图的 provenance 对人工抄录 ID 不够直接。

这些问题没有造成资源不一致或 trial 失败；其中第 1 项是最值得优先修正的产品表达问题。

# Product Evaluation

**有限度地证明了泛化能力。** 第二个案例在不改架构、不新增 collector/persona generator/framework 的前提下，把同一条 `Evidence → Scenario → Persona → Simulation → Observation → DecisionReport V2` 链路从政策/规则议题复用到企业沟通/舆情类议题，并真实产生了新的、相互绑定且可审计的资源。

它证明的是“产品链路和数据契约可以承载第二类问题”，不是“模拟结果具有现实商业效度”。单 seed、五个合成 Persona、虚构品牌和虚构声明不足以支持真实企业判断、现实人群推断、因果结论、未来预测或方案推荐。
