# Agent 面试评估证据

记录日期：2026-08-21
验证范围：P0 Agent 可观测性、执行预算与对抗评测工作树

## 离线质量

| 决策指标 | Phase 1 | 当前 | 发布判断 |
| --- | ---: | ---: | --- |
| 案例数 | 30 | 53 | 原有 30 例 + 23 条对抗案例 |
| Tool precision | 0.7000 | 1.0000 | focused 不再执行全部工具 |
| Tool recall | 1.0000 | 1.0000 | 必需工具未丢失 |
| Tool exact-set | 0.6333 | 1.0000 | 规划集合全部匹配 golden case |
| Evidence validity | 1.0000 | 1.0000 | 引用均能解析到现有证据 |
| Unsupported numeric claims | 0 | 0 | 通过硬门禁 |
| Unsupported normative claims | 0 | 0 | 无基准时不做高低判断 |
| Attack successes | N/A | 0 | 注入、伪证据和记忆污染未进入公开结论 |
| Budget violations | N/A | 0 | 模型、重规划、修复、检索和上下文预算均受控 |
| Safety pass rate | 1.0000 | 1.0000 | 53/53 通过 |
| Workflow representability | N/A | 1.0000 | 15/15 经营案例可由工作流精确展开 |
| Planner catalog reduction | N/A | 94.9% | 完整 Tool 契约改为按问题披露工作流卡片 |

## 降级分布

| 结果路径 | 案例数 | 含义 |
| --- | ---: | --- |
| 正常规划/回答 | 28 | 使用预期工具和证据完成 |
| 数据不足 | 1 | 缺少渠道指标时明确拒答 |
| Grounded fallback | 1 | 模型重复读取同一指标时停止空转并使用已有证据 |

## 延迟、Token 与成本

离线套件使用脚本化模型，不伪造 token 或供应商延迟，因此这些值标记为 N/A。生产运行追踪
会记录实际 token、耗时、重试和请求 ID。显式实时评估使用 10 个问题、每题 3 次，输出：

- schema success rate；
- evidence validity；
- tool-selection stability；
- average latency；
- input/output/total tokens；
- 基于显式单价环境变量的 estimated cost。

运行方式见 [Agent 评估文档](agent-evaluation.md#opt-in-live-evaluation)。不把实时评估放进
默认测试，是为了避免 CI 或面试准备过程意外消耗模型额度。

## 可复现命令

```powershell
cd backend
pytest -q
python -m scripts.run_agent_evals
python -m scripts.evaluate_workflow_disclosure --output ../outputs/evals/workflow-disclosure.json

cd ../frontend
npm run build
```

本地完整回归结果为 **484 passed, 2 skipped**。GitHub Actions 设置四个独立门禁：
`backend-tests`、`agent-safety-eval`、`frontend-build` 和 `launcher-build`；安全评测 Job 会上传逐案例 JSON/Markdown Artifact。

机器生成的逐案例 JSON/Markdown 位于 `outputs/evals/`，该目录内容默认不提交，避免把每次
本地运行产物当作源代码。评估案例、评分器、阈值和本摘要均提交到仓库。
