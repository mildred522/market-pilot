# Market Pilot 设计文档

这里保存面向产品和工程决策的长期文档。实现细节以当前代码、测试和 API 契约为准；已经完成
的逐步执行清单不再作为现行设计维护。

## 核心架构

- [电商迁移 M0：领域边界与平台层基线](commerce-migration-m0.md)：平台无关的电商域、Talk/Plan 模式和 M0 接口边界。
- [电商经营 Agent 转型规划](ecommerce-agent-transformation.md)：产品转型、Olist 数据、指标代号层与门禁、ToB 图记忆及验收路径；按阶段实施。
- [电商预期开发报告](commerce-expected-development-report.md)：基于当前商品经营链路，安排可信度、语义层、展示与有条件的 ToB 验证。
- [电商分析快照与 DuckDB Artifact](commerce-duckdb-artifacts.md)：SQLite 控制面、DuckDB 分析快照和 Olist 后续接入边界。
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
- [模型路由基准](model-routing-benchmark.md)：Flash/Pro 的真实延迟、tokens、质量对比与默认角色决策。
- [文档知识 RAG 落地方案](rag-implementation-plan.md)：来源版本、结构切分、中文混合检索、Agent 接入与分轮交付。
- [P0 Agent 面试强化计划](p0-agent-interview-strengthening.md)：Run 可观测性、执行预算、对抗评测与 CI 门禁。
- [领域工作流渐进式披露](progressive-workflow-disclosure.md)：用业务工作流卡片替代 Planner 全量 Tool 契约，并由策略层按需展开工具。
- [前端设计系统](frontend-design-system.md)：面向经营工作台的高密度布局、语义颜色、图表选择和响应式约束。
- [人工确认的经营事实更正](confirmed-correction-workflow.md)：白名单更正单、原子确认、增量重算、不可变报告版本与失败回滚。
- [文档知识导入手册](../knowledge-ingestion-operations.md)：审核清单、安全导入、Qdrant 启动和失败恢复。

## 产品定义与交付

- [经营分析指标体系](../restaurant-agent-analysis-indicators.md)
- [交付历史](delivery-history.md)
- [发布基线](../release-baseline.md)
- [面试评估证据](../interview-evidence.md)
- [五分钟演示](../demo-script.md)
- [电商 Benchmark 演示](../commerce-demo-script.md)

## 文档规则

1. 设计文档描述稳定边界、数据契约、关键决策和验收标准。
2. 已完成的逐步操作、临时命令和代理工作流不进入长期设计文档。
3. 新设计直接放入本目录，使用主题名称，不使用工具或工作流名称作为目录结构。
4. 产品级缺陷进入代码、测试和评测集，不依赖记忆规则掩盖。
