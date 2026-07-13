# AI Decision Center 文档索引

> SandOwl / ai-decision-center · 设计与工程文档入口

## 产品与架构

| 文档 | 内容 |
|------|------|
| [design.md](./design.md) | 定位、概念模型、五层架构、分层设计、引擎两档、场景模板、校准、演进路线、已定/待定 |
| [mirofish-integration.md](./mirofish-integration.md) | MiroFish 模块复用映射与 monorepo 集成约定 |

## 运行时（进度 / 恢复）

| 文档 | 内容 |
|------|------|
| [progress-sse.md](./progress-sse.md) | 一阶段一 SSE、Envelope、刷新契约、Task 持久化与 TTL |
| [crash-recovery.md](./crash-recovery.md) | Phase C 崩溃透明恢复、adopt、检查点、验收 |
| [interview-dual-track.md](./interview-dual-track.md) | Interview live / offline 双轨、回顾采访数据依赖 |
| [graph-snapshot.md](./graph-snapshot.md) | 图谱本地快照为展示 SoT、Refresh=同步 Zep |

## 规划中

| 文档 | 内容 |
|------|------|
| [platform-plugins.md](./platform-plugins.md) | 真·多平台插件（抖音/小红书等形态分型，未开工） |

## 阅读顺序建议

1. 新同学 / 评审方案 → `design.md`
2. 改进度条 / SSE / 前端 Step → `progress-sse.md`
3. 改启动恢复 / 子进程 / 建图断点 → `crash-recovery.md`
4. 改 Step5 采访 / 环境关闭后回顾 → `interview-dual-track.md`
5. 改图谱读路径 / 快照同步 → `graph-snapshot.md`
6. 动 MiroFish 遗留模块 → `mirofish-integration.md`
7. 扩社媒渠道 → `platform-plugins.md`
