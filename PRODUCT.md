# SandOwl

三方整合目标、来源边界与去 ADC 产品层顺序以 [`TRIAD_INTEGRATION_REFACTOR_PLAN.md`](TRIAD_INTEGRATION_REFACTOR_PLAN.md) 为当前基线；原 V1 文档只保留为历史设计记录。

## Register

product

## Users

面向持续跟踪政策、媒体与现实环境的研究员、分析师和研究团队。用户通常在信息密集、时间有限的工作场景中，需要把外部证据转化为可复核的世界状态，再运行有边界的合成人群模拟，而不是浏览一个展示型网站。

## Product Purpose

SandOwl 把媒体发现、世界与图谱、合成人群、群体模拟、报告生成、Agent 交互和任务评测收敛为一条原生研究工作流。成功标准是用户能够从一条媒体线索建立可追溯的研究上下文，运行一次有边界的合成人群模拟，并继续追问或按需评测，而不需要理解三个上游项目。

最终用户流程是：媒体发现与证据选择 → Project / Graph 上下文 → Persona Dataset / Cohort → 一个 simulation requirement → 一次 Simulation Run → ReportAgent 报告 → Agent Interaction → 可选 Evaluation。WorldSnapshot、事件记录、内容哈希和审计字段是支撑这条流程的技术数据链路，不是另一套面向用户的工作流。

一次 Simulation Run 只绑定一个 requirement、一组合成人群和一组初始动作，不要求基线或备选方案；跨运行比较只有在未来成为独立、明确授权的研究能力后才出现。

旧 Decision Thread、Scenario、Semantic Experiment、Decision Report、Survey、Chat、Web、Linux、Trial Archive 与 Batch Registry 仍作为兼容能力保留。它们可以复用同一证据、合成人群和执行基础设施，但不得反向规定 SandOwl 原生项目的数据模型、导航或产品语言。来源项目名称只保留在代码契约、迁移记录和工程溯源中，不出现在普通用户工作流里。

媒体观察只保存成功的正向判断、精确文章引用、实体投影与模型版本；不保存模型推理，不声称证明全网不存在更早表述，缺失或非法发生日期不会被猜测补齐。世界快照、运行输入、事件和报告均以不可变哈希建立追溯关系。模拟结果始终标注为合成观察，不冒充现实预测、真人研究或商业建议。

## Brand Personality

冷静、可信、前瞻。以清晰的证据层级、研究边界和运行状态形成 SandOwl 自己的视觉语言；所有视觉表达都服务于理解与判断，不制造虚假的确定性。

## Anti-references

- 不做传统 BI 的组件堆叠和无差别指标墙。
- 不做营销站式的大字、渐变、玻璃卡片和装饰性动效。
- 不把 AgendaScope、MatrAIx、MiroFish 暴露成三个需要用户理解或分别进入的产品。
- 不沿用旧版线性五步向导作为全局信息架构；步骤只用于确实有先后依赖的单次任务。

## Design Principles

1. 证据先于结论：每项判断都能回到来源、时间和处理状态。
2. 一个工作台、一条任务主线：采集、建模、实验与报告共享上下文。
3. 单次运行保持独立：每次模拟只描述自身输入、事件与限制；跨运行比较只有在未来形成独立、明确授权的研究能力后才出现。
4. 渐进披露复杂度：先给出当前决策所需内容，再允许专家下钻。
5. 能力边界透明：明确区分真实数据、推断、模拟结果和人工判断。

## Accessibility & Inclusion

以 WCAG 2.2 AA 为基线；正文和状态信息满足对比度要求，所有交互支持键盘与清晰焦点，状态不只依赖颜色，数据图表提供文本等价信息，并尊重减少动态效果的系统设置。
