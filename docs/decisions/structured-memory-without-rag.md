# ADR: Structured Memory Without RAG

- Status: Accepted
- Date: 2026-08-14

This decision applies to operational memory. It is complemented, not superseded,
by [Document Knowledge RAG](document-knowledge-rag.md) for maintained external
reports, regulations, and methodology documents.

## Context

Agent 需要记住最近对话、门店事实和历史经营指标。当前数据均有明确项目归属、字段定义、
时间顺序和权限边界，不是需要语义检索的大量非结构化知识文档。

## Decision

使用 SQLite/SQLAlchemy 保存公开会话、确认后的项目档案和同口径历史指标。最近消息按
conversation ID 与时间读取，项目事实按显式字段更新，历史比较按 canonical metric path
和 project ID 查询。历史消息进入提示词时标记为不可信上下文。

## Consequences

- 查询可解释、可测试，不需要 embedding 服务或额外数据库。
- 不会因相似度检索把其他门店或旧口径数据混入结论。
- 追踪可以只记录被选择的行 ID。
- 不能对大量合同、手册或行业文档做语义问答；出现该需求时再单独设计文档 RAG，不能
  复用经营指标记忆冒充知识库。
