# 中文引导案例：共享充电宝误还扣费争议

## 目的

本案例用于验证 SandOwl 能否以中文呈现一条新的、可追溯的决策链。它验证的是数据契约、资源边界和用户理解，不预测现实舆情，也不提供法律、经营或公关建议。

## 案例边界

- 现实证据：中新网关于共享充电宝外观相似、误还后扣费争议的报道。
- 合成主体：虚构共享充电平台“星桥充电”。
- 原生合成情境：虚构平台发布一则关于误还扣费复核流程的说明；不创建 baseline、alternatives 或方案排名。
- Persona：复用现有开发数据集中的 5 个 Persona，保持成员与顺序不变；新 Cohort 的标题不同，因此 Cohort hash 也不同。
- 当前状态：历史 ADC 三方案实验只读保留；SandOwl 原生单次 Simulation Run、引用报告和一次 Agent Interaction 已封存。

## 已冻结资源

| 资源 | ID | SHA-256 / 状态 |
| --- | --- | --- |
| Evidence article | `411897e1-7883-430e-be82-9e5d467b4248` | revision `3f955c0c877107943140401acf74f6750726db2ef9cd8344f3497598e90e90eb` |
| WorldModel | `3d493c23-3603-4ec9-8096-d8af17d98b21` | 已创建 |
| WorldSnapshot | `b1353579-a59a-46c7-84cf-9b5dcc6986ee` | `83fd49ca7808eb02e7cb62689ef2b676be149457057fc49851f837c2d625880c` |
| Scenario | `2374c08e-3b5e-45f2-a980-9a534cdabaa2` | `284409c9e5650e0cdd7592f5fde051df3bdf716f15368ae300f60615ba36afa6` |
| Cohort | `415caf8a-1ce0-4d75-a699-7d5a402fcb79` | `8dbdcb40ab68b0f4fdf610768ae6f3de9156e6851d32027b2126bbbe8f4b69fc` |
| Decision Thread | `453a5a59-d51c-4965-a5b8-6099b69162ca` | Revision 1 |
| Decision Thread Revision 1 | `bd058c5a-9781-40e4-81d9-d9f3c8bcfb81` | Experiment 未绑定 |
| Semantic Experiment | `20b05cdf-526b-4be8-bd9e-b1e429ebf662` | `1a4ab32ed59c45f25083575c11f1d0ae774f2dee9cd6b0d187ea7cfc799a544a` |
| DecisionReport V2 | `becfe677-16d1-46ab-9cff-2b135f94315b` | `ecd3c60f095c42977310ee4cb79b26e231e4b273dcf1af92d4bd2f784d7e1d3c` |
| Decision Thread Revision 2 | `c0885403-f0bf-42b2-9ede-c3248cebd8e1` | Experiment 已绑定 |

上表中 Scenario、Decision Thread、Semantic Experiment 与 DecisionReport V2 是历史兼容资源，不属于当前原生主流程。

## 原生 SandOwl 资源

| 资源 | ID | SHA-256 / 状态 |
| --- | --- | --- |
| Research Project | `748de69e-3192-496d-9b2c-6ca72ac85575` | `d113987abe205b79b0506967bf2d43a351e05090370fad2445678e7952208050` |
| Simulation Run | `32f4e1ed-985e-4786-b965-4e37436bda9f` | `34d730320316fc79c836365c4d659f9efd08fcfeeb1bc8fcaaf8a08533d73a11` |
| Single-run report | `fd81c881-345d-4bab-9ca2-97b82affd1a2` | `e2c36ca8d99fb7e95799093fad5e28a2d504039065f043e49334f6cf5d5dfdec` |
| ReportAgent draft | `aac8ac30-5085-4b7a-acc2-a629043731fe` | `430bd2d3dd439027ba556c8a66f1678a7e705cf6ed654281af43dbf29baddb61` |
| Agent Interaction | `c702c54f-3d6c-4f11-a287-e7f8152fd222` | succeeded |

原生链使用同一个 WorldSnapshot 与 Cohort，但不读取或比较历史三方案实验结果。

Evidence 原始来源：<https://www.chinanews.com.cn/sh/2026/08-15/10678214.shtml>

## 历史已确认并执行的付费实验

建议使用与上一条成功链路相同的最小矩阵：

- 模型：`qwen3.7-plus`
- 配置 hash：`4184bdb6cad7eebbb1836ae19f005ab926d93350b4705e5b0140fef79ac58741`
- Prompt schema：`matraix-semantic-profile/v1`
- 变体：3 个（1 个 baseline + 2 个 alternatives）
- Persona：5 个
- Seed：1 个
- Round：1 轮，每轮 60 分钟的合成时钟
- Trial：3 个，3/3 succeeded
- 总预算维度：15 persona-rounds

本次用户已明确确认运行。实验调用了当前配置的模型供应商，共持久化 17 个事件。

## 本次合成观察

### 原生单次 Run

- 场景起始帖子：1；这是合成情境，不是 Persona 生成内容。
- Persona 生成帖子：0。
- 评论：1。
- reaction：3，均为点赞。
- `do_nothing`：1。
- 共 6 个类型化事件，只描述 seed `20260817` 的单轮合成运行。

### 历史三方案实验（只读兼容）

- 基线：5 次 `do_nothing`，没有场景初始帖、评论或 reaction。
- 备选 A：1 条场景初始帖、1 条评论、4 次 reaction。
- 备选 B：1 条场景初始帖、3 条评论、2 次 reaction。
- 两个备选方案比基线多出的 1 个总事件均来自 Scenario 初始帖，不能解释为总体参与度提升。
- 本次结果只描述单 seed、单轮、5 个开发 Persona 的合成观察；现有 Persona 不是中国消费者代表样本。
