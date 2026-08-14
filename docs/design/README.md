# Market Pilot 设计文档

这里保存面向产品和工程决策的长期文档。实现细节以当前代码、测试和 API 契约为准；已经完成
的逐步执行清单不再作为现行设计维护。

## 核心架构

- [系统架构](../restaurant-agent-architecture.md)：业务模块、服务边界、数据流和部署结构。
- [MVP 架构](../restaurant-agent-mvp-architecture-plan.md)：前后端职责和初始模块划分。
- [Agent 核心](../agent-core-design.md)：LLM、Plan、Tool、Memory 和可观测性边界。
- [Agent 记忆](../agent-memory.md)：会话、项目事实和历史指标的结构化记忆规则。
- [Agent 评测](../agent-evaluation.md)：离线门禁和显式实时评测。
- [API 契约](../api-contract.md)：主要接口和响应结构。

## 专项设计

- [外部上下文存储](external-context-storage.md)：参考数据、快照、供应商边界和 RAG 决策。
- [双模式选址与商圈推荐](location-recommendation.md)：手动点位分析和行政区候选推荐。
- [自适应证据追问](adaptive-evidence-followups.md)：Evidence-first、Plan-and-Execute、回答版本和反馈记忆。

## 产品定义与交付

- [经营分析指标体系](../restaurant-agent-analysis-indicators.md)
- [交付历史](delivery-history.md)
- [发布基线](../release-baseline.md)
- [面试评估证据](../interview-evidence.md)
- [五分钟演示](../demo-script.md)

## 文档规则

1. 设计文档描述稳定边界、数据契约、关键决策和验收标准。
2. 已完成的逐步操作、临时命令和代理工作流不进入长期设计文档。
3. 新设计直接放入本目录，使用主题名称，不使用工具或工作流名称作为目录结构。
4. 产品级缺陷进入代码、测试和评测集，不依赖记忆规则掩盖。
