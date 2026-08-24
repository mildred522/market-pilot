# 人工确认的经营事实更正闭环

> 实施状态（2026-08-24）：经营假设字段的提取、提案、确认/拒绝、幂等领取、陈旧版本保护、增量重算、新报告版本、指标差异和 Trace 已完成。CSV 行级修改不在当前范围。

## 目标

把回答修订中的 `recompute_metrics` 从提示状态补成安全执行链路，同时保持三个约束：LLM 不直接写数据库，未确认事实不生效，旧报告永不覆盖。

```text
用户反馈
  -> RevisionPlanner / 窄范围 fallback parser
  -> CorrectionCandidate（8 个白名单字段）
  -> CorrectionProposal(pending)
  -> 用户确认或拒绝
  -> 原子领取 pending -> applying
  -> 版本与输入快照校验
  -> 仅执行受影响工具
  -> 新 AnalysisResult + InputSnapshot + Trace
  -> applied
```

## 支持字段与依赖

| 字段 | 增量工具 |
| --- | --- |
| 月租、人工、水电、营销、其他固定成本、现金余额 | `analyze_survival_line` |
| 外卖佣金率、单均包材成本 | `analyze_channel_profitability` |

更正候选只包含字段、新值和用户原始理由。旧值来自源报告的不可变 `AnalysisInputSnapshot`，不能由模型提供。佣金率必须位于 0–1，其他字段必须非负。

## 状态与一致性

```text
pending -> applying -> applied
   |                    |
   +------> rejected    +-> repeated confirm returns same analysis
```

- 确认请求必须携带更正单的幂等键。
- `pending -> applying` 使用条件更新原子领取，避免并发双执行。
- 源报告不再是项目最新经营报告时返回 `409`。
- 工具、输入或写入失败时事务回滚，更正单恢复为 `pending`。
- 成功后创建新报告和新输入快照，源报告与上传文件保持不变。
- Project Profile 仅在同一事务成功后写入已确认假设。

## 当前边界

- 不允许自然语言生成 SQL、JSON Path 或任意字段名。
- 不修改 CSV 中的订单、菜品和评论行。
- 一张更正单当前只应用一个字段；同一反馈最多生成三张独立更正单。
- 增量重算后使用更新后的完整指标重新生成确定性摘要，避免保留旧数值结论。

## 验收证据

- 相同幂等键重复确认只生成一个报告。
- 错误幂等键、拒绝状态和陈旧源报告均不会修改数据。
- 工具失败后无部分写入，并可使用同一更正单安全重试。
- 月租更正只执行一次 `analyze_survival_line`，运行记录可从 Agent Run API 查询。
